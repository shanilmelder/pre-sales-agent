"""Human edits of Clarification Questions (Story 4.5, demo slice): edit, approve, and approve
all.

Every command follows the AD-3 path: `identity.authorize` (`gaps.clarification_question.edit`:
the Opportunity's owner and collaborators except sales representatives; other readers 403,
everyone else the Opportunity's 404), validate, write, then trace, in the caller's Unit of
Work. Each takes the Opportunity's detection lock, so a detection accepted at the same time
sees the question either before or after the change, never half-way: a Gap whose question a
person edited or approved is kept by the next detection instead of superseded. Only questions
of `open` Gaps change (409 `gap_not_open` otherwise).

- `edit_question`: new text and/or topic with `If-Match` (428 without, 412 when stale). A
  change sets `edited_by_human`, returns an approved question to `drafted` (clearing its
  approval) and appends `gaps.clarification_question.edited` naming the changed fields.
  Nothing changed: nothing written, 200 (a stale `If-Match` is still 412).
- `approve_question`: with `If-Match`; sets `approved`, `approved_by` and `approved_at` and
  appends `gaps.clarification_question.approved`. Already approved: 200 with nothing written,
  whatever version `If-Match` names (it is idempotent).
- `approve_all`: approves exactly the drafted questions the client lists (id and row
  version), one event each, all or nothing; 412 when the list differs from the drafted
  questions of open Gaps (one changed, approved meanwhile, or not listed).
- `approve_selected` (Story 4.4): approves exactly the listed questions (1 to 200), one event
  each, all or nothing; 412 when one is stale, not drafted, or not on an open Gap.
- `mark_sent` (Story 4.6, `gaps.clarification_question.send`: the owner and every
  collaborator, sales representatives included): marks exactly the listed approved questions
  (1 to 200) sent on a date that is not in the future (422), one
  `gaps.clarification_question.sent` event each, all or nothing; 412 when one is stale, not
  approved, or not on an open Gap.
- `mark_unanswered` (Story 4.6, same action): "No answer" on a sent question with
  `If-Match`; 409 `question_not_sent` when it isn't sent. Appends
  `gaps.clarification_question.marked_unanswered`. The Gap stays open.

- `answer_question` (Story 4.7, same action): **Record answer** on a sent or unanswered
  question with `If-Match`: the text becomes a `clarification_answer` Source
  (`intake.add_answer_source`, parsed as usual, which then queues the extraction and the
  answer matching), the question becomes `answered` with the passage spanning the text as
  its Evidence and, when the answer settles the Gap, the Gap `answered` too; the question's
  open suggestions are `superseded`. 409 `question_not_sent` for any other status. Traces
  `gaps.clarification_question.answered` (and `gaps.gap.answered`).

A sent, unanswered or answered question can't be edited or approved (409
`question_not_editable`). Every write notifies the Opportunity's event stream
(`gaps.changed`).

Trace and logs carry ids, versions and field names only, never the text.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from functools import partial
from uuid import UUID

from app.modules.gaps.adapters import repository as repo
from app.modules.gaps.adapters.repository import GapRecord, QuestionRecord
from app.modules.gaps.application.gaps import (
    gap_views,
    question_names,
    question_view,
    sees_only_approved_questions,
)
from app.modules.gaps.application.models import (
    AnswerRequest,
    ApproveAllResult,
    ApproveSelectedResult,
    ClarificationQuestion,
    Gap,
    MarkSentRequest,
    MarkSentResult,
    QuestionChanges,
    QuestionVersion,
)
from app.modules.gaps.domain import gaps as rules
from app.modules.gaps.domain.gaps import (
    GAP_SUBJECT_TYPE,
    QUESTION_SUBJECT_TYPE,
    SENT_STATUSES,
    DismissReasonKind,
    GapHistoryKind,
    GapState,
    GapStatus,
    Impact,
    QuestionState,
    QuestionStatus,
    question_text,
    question_topic,
    sent_date,
)
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.intake.application import public as intake
from app.modules.opportunities.application import public as opportunities
from app.platform import trace
from app.platform.concurrency import parse_if_match
from app.platform.errors import (
    ForbiddenError,
    GapNotOpenError,
    NotFoundError,
    QuestionNotApprovedError,
    QuestionNotEditableError,
    QuestionNotSentError,
    RowVersionMismatchError,
    UnprocessableError,
)
from app.platform.ids import new_id
from app.platform.logging import get_logger
from app.platform.storage import BlobStore
from app.platform.trace.catalogue import (
    GapsClarificationQuestionAnswered,
    GapsClarificationQuestionApproved,
    GapsClarificationQuestionEdited,
    GapsClarificationQuestionMarkedUnanswered,
    GapsClarificationQuestionSent,
    GapsGapAnswered,
)
from app.platform.uow import UnitOfWork

MAX_ROW_VERSION = 2**31 - 1
NOT_FOUND_DETAIL = "No Clarification Question with this id."
NOT_OPEN_DETAIL = (
    "The Gap of this Clarification Question is no longer open: it was dismissed, converted "
    "or replaced by a newer Gap detection."
)
SENT_DETAIL = "This Clarification Question was sent: it can no longer be edited or approved."
NOT_APPROVED_DETAIL = "Only an approved Clarification Question can be marked sent."
NOT_SENT_DETAIL = 'Only a sent Clarification Question can be marked "No answer".'
NOT_OPEN_TO_ANSWER_DETAIL = (
    'Only a sent Clarification Question, or one marked "No answer", can be answered.'
)
_log = get_logger(__name__)


def _stale() -> RowVersionMismatchError:
    return RowVersionMismatchError(
        "The Clarification Question was changed by someone else since you opened it. "
        "Reload and try again."
    )


async def _authorized(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    action: Action = Action.GAP_QUESTION_EDIT,
) -> UUID:
    """Authorize `action` (by default `gaps.clarification_question.edit`) on the Opportunity,
    then take its detection lock; the acting user's id."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, action, resource)
    user_id = actor.user_id
    if user_id is None:  # pragma: no cover - the policy grants these actions to users only
        raise ForbiddenError("Only people can change Clarification Questions.")
    await repo.lock_opportunity(uow, opportunity_id)
    return user_id


async def _load(
    uow: UnitOfWork, opportunity_id: UUID, question_id: UUID
) -> tuple[QuestionRecord, GapRecord]:
    found = await repo.get_question(uow, opportunity_id, question_id)
    if found is None:
        raise NotFoundError(NOT_FOUND_DETAIL)
    return found


def _expected(if_match: str | None) -> int:
    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION:
        # The stored version can't be this large, or bumping it would overflow int4.
        raise _stale()
    return expected


def _open(gap: GapRecord) -> None:
    if gap.status != GapStatus.OPEN:
        raise GapNotOpenError(NOT_OPEN_DETAIL)


def _state(record: QuestionRecord) -> QuestionState:
    return QuestionState(
        text=record.text,
        topic=record.topic,
        status=QuestionStatus(record.status),
        approved_by=record.approved_by,
        approved_at=record.approved_at,
        edited_by_human=record.edited_by_human,
        sent_on=record.sent_on,
        sent_by=record.sent_by,
        answered_on=record.answered_on,
        answered_by=record.answered_by,
        answer_passage_id=record.answer_passage_id,
    )


async def _write(
    uow: UnitOfWork,
    record: QuestionRecord,
    state: QuestionState,
    *,
    expected: int,
    user_id: UUID,
    at: datetime,
    opportunity_id: UUID,
) -> QuestionRecord:
    """Write the question's new state (412 when stale, 409 when its Gap is no longer open)
    and notify the Opportunity's event stream."""
    updated = await repo.update_question(
        uow,
        record.id,
        expected_row_version=expected,
        text_=state.text,
        topic=state.topic,
        status=state.status.value,
        approved_by=state.approved_by,
        approved_at=state.approved_at,
        edited_by_human=state.edited_by_human,
        changed_by=user_id,
        status_changed_at=at if state.status != record.status else None,
        sent_on=state.sent_on,
        sent_by=state.sent_by,
        answered_on=state.answered_on,
        answered_by=state.answered_by,
        answer_passage_id=state.answer_passage_id,
    )
    if updated is None:
        gap = await repo.get_gap(uow, record.gap_id)
        if gap is None or gap.status != GapStatus.OPEN:
            raise GapNotOpenError(NOT_OPEN_DETAIL)
        raise _stale()
    await repo.notify_gaps_changed(uow, opportunity_id)
    return updated


def _transition[T](change: Callable[[], T]) -> T:
    """Run a domain transition; a superseded question (inconsistent with an open Gap) is 409
    `gap_not_open`, never a 500. A sent or unanswered one is 409 `question_not_editable`, one
    not approved (to mark sent) `question_not_approved`, and one not sent (to mark "No
    answer") `question_not_sent`."""
    try:
        return change()
    except rules.QuestionNotEditableError:
        raise GapNotOpenError(NOT_OPEN_DETAIL) from None
    except rules.QuestionSentError:
        raise QuestionNotEditableError(SENT_DETAIL) from None
    except rules.QuestionNotApprovedTransitionError:
        raise QuestionNotApprovedError(NOT_APPROVED_DETAIL) from None
    except rules.QuestionNotSentTransitionError:
        raise QuestionNotSentError(NOT_SENT_DETAIL) from None


async def _view(uow: UnitOfWork, record: QuestionRecord) -> ClarificationQuestion:
    return question_view(record, await question_names(uow, [record]))


async def edit_question(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    question_id: UUID,
    changes: QuestionChanges,
    if_match: str | None,
) -> ClarificationQuestion:
    """Change the question's text and/or topic. `if_match` is the raw `If-Match` header
    (428/412)."""
    user_id = await _authorized(uow, actor, opportunity_id)
    record, gap = await _load(uow, opportunity_id, question_id)
    try:
        text = None if changes.text is None else question_text(changes.text)
        topic = None if changes.topic is None else question_topic(changes.topic)
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from None
    expected = _expected(if_match)
    _open(gap)
    state, changed = _transition(
        lambda: rules.edit_question(_state(record), text=text, topic=topic)
    )
    if record.row_version != expected:
        raise _stale()
    if not changed:
        return await _view(uow, record)
    updated = await _write(
        uow,
        record,
        state,
        expected=expected,
        user_id=user_id,
        at=datetime.now(UTC),
        opportunity_id=opportunity_id,
    )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=GapsClarificationQuestionEdited(
            gap_id=str(gap.id),
            fields=list(changed),
            row_version=updated.row_version,
            approval_revoked=record.status == QuestionStatus.APPROVED,
        ),
        subject_type=QUESTION_SUBJECT_TYPE,
        subject_id=question_id,
        opportunity_id=opportunity_id,
    )
    _log.info(
        "gaps.clarification_question_edited",
        extra={
            "opportunity_id": str(opportunity_id),
            "question_id": str(question_id),
            "actor_id": str(user_id),
            "fields": list(changed),
            "row_version": updated.row_version,
        },
    )
    return await _view(uow, updated)


async def _approve(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    record: QuestionRecord,
    gap: GapRecord,
    *,
    expected: int,
    user_id: UUID,
) -> QuestionRecord:
    at = datetime.now(UTC)
    state = _transition(lambda: rules.approve_question(_state(record), user_id=user_id, at=at))
    updated = await _write(
        uow,
        record,
        state,
        expected=expected,
        user_id=user_id,
        at=at,
        opportunity_id=opportunity_id,
    )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=GapsClarificationQuestionApproved(
            gap_id=str(gap.id), approved_by=str(user_id), row_version=updated.row_version
        ),
        subject_type=QUESTION_SUBJECT_TYPE,
        subject_id=record.id,
        opportunity_id=opportunity_id,
    )
    return updated


async def approve_question(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    question_id: UUID,
    if_match: str | None,
) -> ClarificationQuestion:
    """Approve the question as the caller. `if_match` is the raw `If-Match` header
    (428/412)."""
    user_id = await _authorized(uow, actor, opportunity_id)
    record, gap = await _load(uow, opportunity_id, question_id)
    expected = _expected(if_match)
    _open(gap)
    if record.status in SENT_STATUSES:
        raise QuestionNotEditableError(SENT_DETAIL)
    if record.status == QuestionStatus.APPROVED:
        return await _view(uow, record)
    if record.row_version != expected:
        raise _stale()
    approved = await _approve(
        uow, actor, opportunity_id, record, gap, expected=expected, user_id=user_id
    )
    _log.info(
        "gaps.clarification_question_approved",
        extra={
            "opportunity_id": str(opportunity_id),
            "question_id": str(question_id),
            "actor_id": str(user_id),
            "row_version": approved.row_version,
        },
    )
    return await _view(uow, approved)


async def _approve_listed(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    drafted: Sequence[QuestionRecord],
    *,
    user_id: UUID,
) -> None:
    """Approve these drafted questions of open Gaps, already checked against what the client
    listed."""
    gaps = await repo.gaps_by_id(uow, opportunity_id, [q.gap_id for q in drafted])
    for record in drafted:
        await _approve(
            uow,
            actor,
            opportunity_id,
            record,
            gaps[record.gap_id],
            expected=record.row_version,
            user_id=user_id,
        )


async def approve_selected(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    selected: Sequence[QuestionVersion],
) -> ApproveSelectedResult:
    """Approve exactly the questions the client selected (`selected`: id and row version) as
    the caller; how many. All or nothing: if one changed, is not drafted, is not on an open
    Gap of this Opportunity, or is listed twice with different versions, 412 and nothing is
    approved."""
    user_id = await _authorized(uow, actor, opportunity_id)
    drafted = {q.id: q for q in await repo.drafted_questions_of_open_gaps(uow, opportunity_id)}
    listed: dict[UUID, int] = {}
    for q in selected:
        if listed.setdefault(q.id, q.row_version) != q.row_version:
            raise _selection_changed()
    chosen = [drafted.get(qid) for qid in listed]
    records = [q for q in chosen if q is not None]
    if len(records) != len(listed) or any(q.row_version != listed[q.id] for q in records):
        raise _selection_changed()
    await _approve_listed(uow, actor, opportunity_id, records, user_id=user_id)
    _log.info(
        "gaps.clarification_questions_approved_selected",
        extra={
            "opportunity_id": str(opportunity_id),
            "actor_id": str(user_id),
            "count": len(records),
        },
    )
    return ApproveSelectedResult(count=len(records))


def _selection_changed() -> RowVersionMismatchError:
    return RowVersionMismatchError(
        "The selected Clarification Questions changed since you opened them. Reload and try again."
    )


async def approve_all(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    shown: Sequence[QuestionVersion],
) -> ApproveAllResult:
    """Approve exactly the drafted questions the client shows (`shown`: id and row version)
    as the caller; how many. All or nothing: if a listed question changed or is no longer
    drafted (of an open Gap), or a drafted question of an open Gap isn't listed, 412 and
    nothing is approved."""
    user_id = await _authorized(uow, actor, opportunity_id)
    drafted = await repo.drafted_questions_of_open_gaps(uow, opportunity_id)
    current = {q.id: q.row_version for q in drafted}
    listed = {q.id: q.row_version for q in shown}
    if listed != current:
        raise RowVersionMismatchError(
            "The Clarification Questions changed since you opened them. Reload and try again."
        )
    await _approve_listed(uow, actor, opportunity_id, drafted, user_id=user_id)
    _log.info(
        "gaps.clarification_questions_approved",
        extra={
            "opportunity_id": str(opportunity_id),
            "actor_id": str(user_id),
            "count": len(drafted),
        },
    )
    return ApproveAllResult(count=len(drafted))


# --- sending (Story 4.6) --------------------------------------------------------------------


def _today() -> date:
    """The latest date that is "today" somewhere: the API's UTC date plus one day, so a user
    ahead of UTC can always mark questions sent on their own today."""
    return datetime.now(UTC).date() + timedelta(days=1)


async def mark_sent(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    request: MarkSentRequest,
    *,
    today: date | None = None,
) -> MarkSentResult:
    """Record that exactly the listed approved questions (`id` and row version, 1 to 200)
    were sent on `request.sent_on`, as the caller; how many. All or nothing: a date in the
    future is 422; if one changed, is not approved, is not on an open Gap of this
    Opportunity, or is listed twice with different versions, 412 and nothing is marked."""
    user_id = await _authorized(uow, actor, opportunity_id, Action.GAP_QUESTION_SEND)
    try:
        sent_on = sent_date(request.sent_on, today=today or _today())
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from None
    approved = {
        q.id: (q, gap)
        for q, gap in await repo.questions_of_open_gaps(
            uow, opportunity_id, QuestionStatus.APPROVED.value
        )
    }
    listed: dict[UUID, int] = {}
    for q in request.questions:
        if listed.setdefault(q.id, q.row_version) != q.row_version:
            raise _selection_changed()
    chosen = [approved.get(qid) for qid in listed]
    pairs = [pair for pair in chosen if pair is not None]
    if len(pairs) != len(listed) or any(q.row_version != listed[q.id] for q, _ in pairs):
        raise _selection_changed()
    at = datetime.now(UTC)
    for record, gap in pairs:
        state = _transition(partial(rules.mark_sent, _state(record), user_id=user_id, on=sent_on))
        updated = await _write(
            uow,
            record,
            state,
            expected=record.row_version,
            user_id=user_id,
            at=at,
            opportunity_id=opportunity_id,
        )
        await trace.append(
            uow,
            actor=actor.actor,
            payload=GapsClarificationQuestionSent(
                gap_id=str(gap.id), sent_on=sent_on.isoformat(), row_version=updated.row_version
            ),
            subject_type=QUESTION_SUBJECT_TYPE,
            subject_id=record.id,
            opportunity_id=opportunity_id,
        )
    _log.info(
        "gaps.clarification_questions_sent",
        extra={
            "opportunity_id": str(opportunity_id),
            "actor_id": str(user_id),
            "count": len(pairs),
            "sent_on": sent_on.isoformat(),
        },
    )
    return MarkSentResult(count=len(pairs))


async def mark_unanswered(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    question_id: UUID,
    if_match: str | None,
) -> ClarificationQuestion:
    """Record that the customer won't answer the sent question ("No answer"). `if_match` is
    the raw `If-Match` header (428/412). The Gap stays open."""
    user_id = await _authorized(uow, actor, opportunity_id, Action.GAP_QUESTION_SEND)
    record, gap = await _load(uow, opportunity_id, question_id)
    expected = _expected(if_match)
    _open(gap)
    state = _transition(lambda: rules.mark_unanswered(_state(record)))
    if record.row_version != expected:
        raise _stale()
    updated = await _write(
        uow,
        record,
        state,
        expected=expected,
        user_id=user_id,
        at=datetime.now(UTC),
        opportunity_id=opportunity_id,
    )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=GapsClarificationQuestionMarkedUnanswered(
            gap_id=str(gap.id), row_version=updated.row_version
        ),
        subject_type=QUESTION_SUBJECT_TYPE,
        subject_id=question_id,
        opportunity_id=opportunity_id,
    )
    _log.info(
        "gaps.clarification_question_marked_unanswered",
        extra={
            "opportunity_id": str(opportunity_id),
            "question_id": str(question_id),
            "actor_id": str(user_id),
            "row_version": updated.row_version,
        },
    )
    return await _view(uow, updated)


# --- answering (Story 4.7) ------------------------------------------------------------------


def _gap_state(record: GapRecord) -> GapState:
    return GapState(
        status=GapStatus(record.status),
        impact=Impact(record.impact),
        dismiss_reason_kind=None
        if record.dismiss_reason_kind is None
        else DismissReasonKind(record.dismiss_reason_kind),
        dismiss_note=record.dismiss_note,
        dismissed_by=record.dismissed_by,
        dismissed_at=record.dismissed_at,
        touched_by_human=record.touched_by_human,
        answered_on=record.answered_on,
        answered_by=record.answered_by,
        answer_passage_id=record.answer_passage_id,
    )


def check_answerable(record: QuestionRecord, gap: GapRecord) -> None:
    """409 `gap_not_open` unless the Gap is open, then 409 `question_not_sent` unless the
    question is `sent` or `unanswered`."""
    _open(gap)
    if record.status not in rules.OPEN_TO_ANSWER:
        raise QuestionNotSentError(NOT_OPEN_TO_ANSWER_DETAIL)


async def settle_answer(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    record: QuestionRecord,
    gap: GapRecord,
    *,
    expected: int,
    user_id: UUID,
    on: date,
    passage_id: UUID,
    source_id: UUID,
    settles_gap: bool,
) -> GapRecord:
    """Answer the question (and, when `settles_gap`, its open Gap) with the passage as
    Evidence, supersede the question's open suggestions, trace and notify; the Gap as it is
    now. The caller holds the Opportunity's lock and checked the transition."""
    at = datetime.now(UTC)
    state = _transition(
        lambda: rules.answer_question(_state(record), user_id=user_id, on=on, passage_id=passage_id)
    )
    updated = await _write(
        uow,
        record,
        state,
        expected=expected,
        user_id=user_id,
        at=at,
        opportunity_id=opportunity_id,
    )
    await repo.supersede_matches(uow, record.id)
    await trace.append(
        uow,
        actor=actor.actor,
        payload=GapsClarificationQuestionAnswered(
            gap_id=str(gap.id),
            source_id=str(source_id),
            passage_id=str(passage_id),
            row_version=updated.row_version,
        ),
        subject_type=QUESTION_SUBJECT_TYPE,
        subject_id=record.id,
        opportunity_id=opportunity_id,
    )
    if not settles_gap:
        return gap
    try:
        gap_state = rules.answer_gap(_gap_state(gap), user_id=user_id, on=on, passage_id=passage_id)
    except rules.GapNotOpenTransitionError:
        raise GapNotOpenError(NOT_OPEN_DETAIL) from None
    answered = await repo.update_gap(
        uow,
        gap.id,
        expected_row_version=gap.row_version,
        from_status=gap.status,
        status=gap_state.status.value,
        impact=gap_state.impact.value,
        dismiss_reason_kind=None,
        dismiss_note=None,
        dismissed_by=None,
        dismissed_at=None,
        touched_by_human=gap_state.touched_by_human,
        changed_by=user_id,
        answered_on=gap_state.answered_on,
        answered_by=gap_state.answered_by,
        answer_passage_id=gap_state.answer_passage_id,
    )
    if answered is None:  # changed since it was read, though the lock is held: conflict
        raise GapNotOpenError(NOT_OPEN_DETAIL)
    await repo.insert_history(
        uow,
        history_id=new_id(),
        gap_id=gap.id,
        kind=GapHistoryKind.ANSWERED.value,
        actor_id=user_id,
        at=at,
    )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=GapsGapAnswered(
            question_id=str(record.id),
            passage_id=str(passage_id),
            row_version=answered.row_version,
        ),
        subject_type=GAP_SUBJECT_TYPE,
        subject_id=gap.id,
        opportunity_id=opportunity_id,
    )
    return answered


async def answer_question(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    question_id: UUID,
    body: AnswerRequest,
    if_match: str | None,
    *,
    store: BlobStore,
    today: date | None = None,
) -> Gap:
    """**Record answer**: store the customer's answer as a Source and answer the sent (or
    "No answer") question with it, settling its Gap when `body.settles_gap`. `if_match` is
    the question's raw `If-Match` header (428/412). Order of checks: authorize → 404 → 422
    → 428 → 409 → 412."""
    user_id = await _authorized(uow, actor, opportunity_id, Action.GAP_QUESTION_SEND)
    record, gap = await _load(uow, opportunity_id, question_id)
    try:
        text = rules.answer_text(body.text)
        on = rules.answered_date(body.answered_on, today=today or _today())
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from None
    expected = _expected(if_match)
    check_answerable(record, gap)
    if record.row_version != expected:
        raise _stale()
    source = await intake.add_answer_source(
        uow, actor, opportunity_id, text, answered_on=on, store=store
    )
    answered = await settle_answer(
        uow,
        actor,
        opportunity_id,
        record,
        gap,
        expected=expected,
        user_id=user_id,
        on=on,
        passage_id=source.passage_id,
        source_id=source.source_id,
        settles_gap=body.settles_gap,
    )
    _log.info(
        "gaps.clarification_question_answered",
        extra={
            "opportunity_id": str(opportunity_id),
            "question_id": str(question_id),
            "gap_id": str(gap.id),
            "source_id": str(source.source_id),
            "actor_id": str(user_id),
            "settles_gap": body.settles_gap,
        },
    )
    (view,) = await gap_views(
        uow,
        opportunity_id,
        [answered],
        approved_only=sees_only_approved_questions(actor),
        store=store,
    )
    return view
