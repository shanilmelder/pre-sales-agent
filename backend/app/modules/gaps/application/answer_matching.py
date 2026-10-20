"""Answer matching (Story 4.7): the `gaps.match_answers` job, `gaps.accept_answer_matches`,
and a person's **Confirm** and **Not an answer**.

**Queueing.** After each successful parse, `intake`'s parse job calls
`enqueue_answer_matching` (through `gaps.application.public`) in its Unit of Work: it queues
one `gaps.match_answers` job for that Source version, unless no question of an open Gap is
`sent` or `unanswered`.

**The handler.**

1. Short Unit of Work: while `clarification_agent` runs tasks (Agent Registry), reads the
   questions waiting for an answer (`Q1…Qn`) and the Source version's extracted text.
2. Over the profile's input budget (`matching_budget`): skipped and logged
   (`input_too_large`), no model call.
3. No Unit of Work open: `clarification_agent.match_answers` suggests which passages answer
   which questions, through the ModelGateway.
4. `accept_answer_matches`, one Unit of Work: keeps a suggestion only when its question is
   still `sent` or `unanswered` (of an open Gap) and its quote resolves in that Source
   version (`intake.resolve_passage`, which stores the passage). A (question, passage) pair
   already known (suggested, confirmed or rejected) is skipped, so a rejected pair never
   returns. Each new suggestion is stored `suggested`, with `injection_suspected` from the
   cited passage, and traced `gaps.answer_match.suggested` (actor
   `clarification_agent@<semver>`). When the agent suggested something and every suggestion
   is invalid, nothing is written and `ModelOutputInvalidError` is raised, so the queue runs
   the job once more (`max_attempts` 2). Failures are logged only.

No question or Gap status ever changes here: only a person's Confirm (or Record answer)
answers a question.

**Confirm / Not an answer** (`gaps.clarification_question.send`: the owner and every
collaborator, sales representatives included): with the suggestion's `If-Match`. Confirm
answers the question through the same transition as Record answer (`answered_on` today, the
matched passage as Evidence) and settles its Gap; 409 when the question is no longer `sent`
or `unanswered` (or its Gap no longer open), 412 when the suggestion is stale or already
decided. Not an answer marks it `rejected`. Traces `gaps.answer_match.confirmed` /
`.rejected`.

Logs, trace and `last_error` carry ids and counts only, never question or Source text.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from uuid import UUID

from app.agents.clarification_agent.agent import AnswersTask, ClarificationAgent, QuestionBlock
from app.agents.clarification_agent.schema import AnswerMatchOutput
from app.agents.contract import AgentResult
from app.modules.gaps.adapters import repository as repo
from app.modules.gaps.adapters.repository import AnswerMatchRecord
from app.modules.gaps.application.detection import CLARIFICATION_AGENT
from app.modules.gaps.application.gaps import gap_views, sees_only_approved_questions
from app.modules.gaps.application.models import Gap
from app.modules.gaps.application.questions import (
    _authorized,
    _expected,
    check_answerable,
    settle_answer,
)
from app.modules.gaps.domain.gaps import (
    ANSWER_MATCH_SUBJECT_TYPE,
    AnswerMatchStatus,
    injection_suspected,
)
from app.modules.identity.application.public import Action, Principal
from app.modules.intake.application import public as intake
from app.modules.registry.application import public as registry
from app.platform import trace
from app.platform.actor import Actor
from app.platform.config import Settings, get_settings
from app.platform.errors import NotFoundError, RowVersionMismatchError
from app.platform.ids import new_id
from app.platform.jobs import JobContext, JobPayload, JobType, enqueue, register
from app.platform.logging import get_logger
from app.platform.model_gateway import provider
from app.platform.model_gateway.port import ModelOutputInvalidError
from app.platform.model_gateway.profiles import get_profile
from app.platform.storage import BlobStore
from app.platform.trace.catalogue import (
    GapsAnswerMatchConfirmed,
    GapsAnswerMatchRejected,
    GapsAnswerMatchSuggested,
)
from app.platform.uow import UnitOfWork, unit_of_work

MATCH_ANSWERS = "gaps.match_answers"
SOURCE_LABEL = "S1"
NOT_FOUND_DETAIL = "No answer suggestion with this id."
_log = get_logger(__name__)


class MatchAnswers(JobPayload):
    source_id: UUID
    version: int


def matching_budget(profile: str) -> int:
    """The most characters (code points) of Source and question text one match call may
    carry for this profile, measured as intake's extraction does. Tests replace this."""
    return intake.input_budget_chars(get_profile(profile).num_ctx)


def matching_settings() -> Settings:
    """Settings for the handler (the chat profile, the storage root). Tests replace this."""
    return get_settings()


# --- queueing -------------------------------------------------------------------------------


async def enqueue_answer_matching(
    uow: UnitOfWork, *, opportunity_id: UUID, source_id: UUID, version: int
) -> UUID | None:
    """Queue `gaps.match_answers` for a newly parsed Source version in the caller's Unit of
    Work; None (nothing queued) when no question is waiting for an answer."""
    if not await repo.questions_open_to_answer(uow, opportunity_id):
        return None
    job_id = await enqueue(
        uow, MatchAnswers(source_id=source_id, version=version), opportunity_id=opportunity_id
    )
    _log.info(
        "gaps.answer_matching_queued",
        extra={
            "opportunity_id": str(opportunity_id),
            "source_id": str(source_id),
            "version": version,
            "job_id": str(job_id),
        },
    )
    return job_id


# --- accepting ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MatchQuestion:
    """A question the job read, with its prompt label `Q<n>`."""

    label: str
    question_id: UUID
    topic: str = field(repr=False)
    text: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class MatchOutcome:
    suggested: int
    dropped: int
    known: int


def proposal(result: AgentResult) -> AnswerMatchOutput:
    """The agent's suggestions, re-validated (AD-4). Raises `ModelOutputInvalidError` when
    the extension is missing or malformed."""
    raw = result.extensions.get(CLARIFICATION_AGENT)
    try:
        return AnswerMatchOutput.model_validate(raw)
    except ValueError:
        raise ModelOutputInvalidError("The clarification_agent extension is not valid.") from None


async def accept_answer_matches(
    uow: UnitOfWork,
    *,
    opportunity_id: UUID,
    source_id: UUID,
    version: int,
    result: AgentResult,
    questions: Sequence[MatchQuestion],
    actor: Actor,
    store: BlobStore | None = None,
) -> MatchOutcome:
    """`gaps.accept_answer_matches`: store each valid, new suggestion `suggested` and trace
    it (see the module docstring). Raises `ModelOutputInvalidError` (writing nothing) when
    there were suggestions and none is valid. A suggestion for a question the job read that
    is no longer waiting for an answer (answered or its Gap closed during the model call) is
    stale: skipped, never invalid."""
    output = proposal(result)
    await repo.lock_opportunity(uow, opportunity_id)
    waiting = {q.id for q, _ in await repo.questions_open_to_answer(uow, opportunity_id)}
    labels = {q.label: q.question_id for q in questions}
    known = await repo.known_match_pairs(uow, [qid for qid in labels.values() if qid in waiting])
    ids = {"opportunity_id": str(opportunity_id), "source_id": str(source_id), "version": version}
    valid: list[tuple[UUID, intake.ResolvedPassage]] = []
    dropped = stale = 0
    for match in output.matches:
        question_id = labels.get(match.question.strip())
        if question_id is not None and question_id not in waiting:
            stale += 1
            continue
        resolved = (
            None
            if question_id is None
            else await intake.resolve_passage(uow, source_id, version, match.quote, store=store)
        )
        if question_id is None or resolved is None:
            dropped += 1
            continue
        valid.append((question_id, resolved))
    if output.matches and not valid and not stale:
        _log.info("gaps.answer_matching_all_invalid", extra={**ids, "dropped_count": dropped})
        raise ModelOutputInvalidError("Every suggested answer was invalid.")
    suggested = repeated = 0
    for question_id, resolved in valid:
        if (question_id, resolved.passage_id) in known:
            repeated += 1
            continue
        known.add((question_id, resolved.passage_id))
        match_id = new_id()
        suspected = injection_suspected(resolved.text)
        await repo.insert_match(
            uow,
            match_id=match_id,
            opportunity_id=opportunity_id,
            question_id=question_id,
            passage_id=resolved.passage_id,
            injection_suspected=suspected,
        )
        await trace.append(
            uow,
            actor=actor,
            payload=GapsAnswerMatchSuggested(
                question_id=str(question_id),
                passage_id=str(resolved.passage_id),
                injection_suspected=suspected,
            ),
            subject_type=ANSWER_MATCH_SUBJECT_TYPE,
            subject_id=match_id,
            opportunity_id=opportunity_id,
        )
        suggested += 1
    if suggested:
        await repo.notify_gaps_changed(uow, opportunity_id)
    outcome = MatchOutcome(suggested=suggested, dropped=dropped, known=repeated)
    _log.info(
        "gaps.answer_matching_accepted",
        extra={
            **ids,
            "suggested_count": suggested,
            "dropped_count": dropped,
            "known_count": repeated,
            "stale_count": stale,
        },
    )
    return outcome


# --- the handler ----------------------------------------------------------------------------


async def _start(
    ctx: JobContext, payload: MatchAnswers, store: BlobStore
) -> tuple[UUID, list[MatchQuestion], str, registry.ConfigVersion] | None:
    async with unit_of_work(ctx.engine) as uow:
        agent = await registry.current_config(uow, CLARIFICATION_AGENT)
        if not agent.runs_tasks:
            return None
        opportunity_id = ctx.opportunity_id
        if opportunity_id is None:  # pragma: no cover - always queued with the Opportunity
            return None
        waiting = await repo.questions_open_to_answer(uow, opportunity_id)
        if not waiting:
            return None
        text = await intake.extracted_text(uow, payload.source_id, payload.version, store=store)
        if text is None:
            return None
        read = [
            MatchQuestion(label=f"Q{n}", question_id=q.id, topic=q.topic, text=q.text)
            for n, (q, _) in enumerate(waiting, start=1)
        ]
        return opportunity_id, read, text, agent.current


async def match_answers(ctx: JobContext, payload: MatchAnswers) -> None:
    """The handler. Errors are logged (ids and the error type only) and re-raised, so the
    queue retries the job once."""
    ids = {
        "job_id": str(ctx.job_id),
        "source_id": str(payload.source_id),
        "version": payload.version,
    }
    try:
        await _match(ctx, payload)
    except Exception as exc:
        _log.warning(
            "gaps.answer_matching_failed",
            extra={
                **ids,
                "exc_type": type(exc).__name__,
                "attempt": ctx.attempt,
                "final": ctx.attempt >= ctx.max_attempts,
            },
        )
        raise


async def _match(ctx: JobContext, payload: MatchAnswers) -> None:
    settings = matching_settings()
    store = BlobStore(settings.storage_dir)
    started = await _start(ctx, payload, store)
    if started is None:
        _log.info(
            "gaps.answer_matching_skipped",
            extra={"job_id": str(ctx.job_id), "source_id": str(payload.source_id)},
        )
        return
    opportunity_id, questions, text, version = started
    config = registry.agent_config(version, settings)
    chars = len(text) + sum(len(q.text) + len(q.topic) for q in questions)
    budget = matching_budget(config.profile)
    if chars > budget:
        _log.info(
            "gaps.answer_matching_skipped",
            extra={
                "job_id": str(ctx.job_id),
                "source_id": str(payload.source_id),
                "reason": "input_too_large",
                "char_count": chars,
                "budget_chars": budget,
                "question_count": len(questions),
            },
        )
        return
    agent = ClarificationAgent(provider.current(), config=config)
    result = await agent.match_answers(
        AnswersTask(
            opportunity_id=opportunity_id,
            run_id=ctx.job_id,
            questions=[QuestionBlock(q.label, q.topic, q.text) for q in questions],
            source_label=SOURCE_LABEL,
            source_text=text,
        )
    )
    async with unit_of_work(ctx.engine) as uow:
        await accept_answer_matches(
            uow,
            opportunity_id=opportunity_id,
            source_id=payload.source_id,
            version=payload.version,
            result=result,
            questions=questions,
            actor=Actor(type="agent", id=config.actor_id),
            store=store,
        )


MATCH_ANSWERS_JOB = register(
    JobType(
        name=MATCH_ANSWERS,
        payload=MatchAnswers,
        handler=match_answers,
        priority="background",
        # As `gaps.detect_gaps`: above the worst case of one model call with its retries.
        timeout_s=900.0,
        max_attempts=2,
        backoff_base_s=15.0,
        backoff_cap_s=120.0,
    )
)


# --- Confirm / Not an answer ----------------------------------------------------------------


def _stale() -> RowVersionMismatchError:
    return RowVersionMismatchError(
        "The answer suggestion was changed by someone else since you opened it. Reload and "
        "try again."
    )


async def _load_match(uow: UnitOfWork, opportunity_id: UUID, match_id: UUID) -> AnswerMatchRecord:
    found = await repo.get_match(uow, opportunity_id, match_id)
    if found is None:
        raise NotFoundError(NOT_FOUND_DETAIL)
    return found


async def _view(uow: UnitOfWork, actor: Principal, opportunity_id: UUID, gap_id: UUID) -> Gap:
    gap = await repo.get_gap(uow, gap_id)
    if gap is None:  # pragma: no cover - Gaps are never deleted
        raise NotFoundError(NOT_FOUND_DETAIL)
    (view,) = await gap_views(
        uow, opportunity_id, [gap], approved_only=sees_only_approved_questions(actor)
    )
    return view


def _today() -> date:
    return datetime.now(UTC).date()


async def confirm_match(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    match_id: UUID,
    if_match: str | None,
) -> Gap:
    """**Confirm**: the suggested passage answers the question (today), which settles its
    Gap. `if_match` is the suggestion's raw `If-Match` header (428/412)."""
    user_id = await _authorized(uow, actor, opportunity_id, Action.GAP_QUESTION_SEND)
    match = await _load_match(uow, opportunity_id, match_id)
    expected = _expected(if_match)
    found = await repo.get_question(uow, opportunity_id, match.question_id)
    if found is None:  # pragma: no cover - questions are never deleted
        raise NotFoundError(NOT_FOUND_DETAIL)
    question, gap = found
    check_answerable(question, gap)
    if match.row_version != expected or match.status != AnswerMatchStatus.SUGGESTED:
        raise _stale()
    refs = await intake.passage_refs(uow, opportunity_id, [match.passage_id])
    ref = refs.get(match.passage_id)
    if ref is None:  # pragma: no cover - passages are immutable
        raise NotFoundError(NOT_FOUND_DETAIL)
    if not await repo.decide_match(
        uow,
        match.id,
        expected_row_version=expected,
        status=AnswerMatchStatus.CONFIRMED.value,
        decided_by=user_id,
    ):
        raise _stale()
    await settle_answer(
        uow,
        actor,
        opportunity_id,
        question,
        gap,
        expected=question.row_version,
        user_id=user_id,
        on=_today(),
        passage_id=match.passage_id,
        source_id=ref.source_id,
        settles_gap=True,
    )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=GapsAnswerMatchConfirmed(
            question_id=str(question.id), passage_id=str(match.passage_id)
        ),
        subject_type=ANSWER_MATCH_SUBJECT_TYPE,
        subject_id=match.id,
        opportunity_id=opportunity_id,
    )
    _log.info(
        "gaps.answer_match_confirmed",
        extra={
            "opportunity_id": str(opportunity_id),
            "match_id": str(match.id),
            "question_id": str(question.id),
            "actor_id": str(user_id),
        },
    )
    return await _view(uow, actor, opportunity_id, gap.id)


async def reject_match(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    match_id: UUID,
    if_match: str | None,
) -> Gap:
    """**Not an answer**: the suggestion is `rejected`, and the pair never suggested again.
    `if_match` is the suggestion's raw `If-Match` header (428/412)."""
    user_id = await _authorized(uow, actor, opportunity_id, Action.GAP_QUESTION_SEND)
    match = await _load_match(uow, opportunity_id, match_id)
    expected = _expected(if_match)
    if match.row_version != expected or match.status != AnswerMatchStatus.SUGGESTED:
        raise _stale()
    if not await repo.decide_match(
        uow,
        match.id,
        expected_row_version=expected,
        status=AnswerMatchStatus.REJECTED.value,
        decided_by=user_id,
    ):
        raise _stale()
    await trace.append(
        uow,
        actor=actor.actor,
        payload=GapsAnswerMatchRejected(
            question_id=str(match.question_id), passage_id=str(match.passage_id)
        ),
        subject_type=ANSWER_MATCH_SUBJECT_TYPE,
        subject_id=match.id,
        opportunity_id=opportunity_id,
    )
    await repo.notify_gaps_changed(uow, opportunity_id)
    _log.info(
        "gaps.answer_match_rejected",
        extra={
            "opportunity_id": str(opportunity_id),
            "match_id": str(match.id),
            "question_id": str(match.question_id),
            "actor_id": str(user_id),
        },
    )
    found = await repo.get_question(uow, opportunity_id, match.question_id)
    if found is None:  # pragma: no cover - questions are never deleted
        raise NotFoundError(NOT_FOUND_DETAIL)
    return await _view(uow, actor, opportunity_id, found[1].id)
