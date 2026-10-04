"""Red Team reviewing (Story 6.5): the `assessments.red_team_review` job and
`assessments.accept_red_team_review`.

**Queueing.** `estimates.accept_draft` calls `enqueue_review` (through
`assessments.application.public`) in its Unit of Work: it inserts a `queued`
`assessments_red_team_runs` row and its job (background priority), unless one of the
Opportunity's runs is still `queued` (its job not yet started), in which case nothing is
added. `start_review` (the Retry API) does the same, but refuses (409) while one is `queued`
or `running`. Both hold the Opportunity's Red Team lock until commit.

**The handler.**

1. Short Unit of Work: reads the Opportunity's active Requirements at their current versions
   (`intake.active_requirement_snapshots`), labelled `R<n>`, its open Gaps
   (`gaps.open_gap_summaries`), labelled `G<n>`, and its current draft Estimate Version's
   lines (`estimates.current_version_lines`), labelled `L<n>`, and marks the run `running`.
2. No active Requirements: no model call, no Review; the run `succeeded`.
3. No Unit of Work open: `red_team_agent` proposes Findings through the ModelGateway.
4. `accept_red_team_review`, one Unit of Work: validates every Finding (its Requirement
   labels must resolve to Requirements still active at the version read; line labels that
   don't resolve to a line of the version reviewed are ignored), supersedes the Opportunity's
   `current` Red Team Review, stores the new `current` one (numbered one past the latest)
   with its Findings and their Requirement and line links, marks the run `succeeded` and
   traces `assessments.red_team_review.completed`.

When no Finding is valid, acceptance writes nothing and raises `ModelOutputInvalidError`, so
the queue runs the job once more (`max_attempts` 2); on the final attempt the handler marks
the run `failed` / `output_invalid`. A gateway error is handled the same way:
`model_unavailable`, `model_timeout` or `output_invalid`. Idempotent: only a run still
`queued` or `running` is worked on, and only a `running` one accepted.

Logs, trace and `last_error` carry ids, codes and counts only, never Requirement, Gap or
Finding text.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID

from app.agents.contract import AgentResult
from app.agents.red_team_agent.agent import (
    AGENT_ID,
    GapBlock,
    LineBlock,
    RedTeamAgent,
    RedTeamTask,
    RequirementBlock,
)
from app.agents.red_team_agent.agent import config as agent_config
from app.agents.red_team_agent.schema import RedTeamOutput
from app.modules.assessments.adapters import repository as repo
from app.modules.assessments.domain.reviews import (
    IN_PROGRESS,
    REVIEW_SUBJECT_TYPE,
    FindingCandidate,
    FindingValidation,
    ReviewKind,
    RunErrorCode,
    RunStatus,
    Severity,
    severity_counts,
    validate_findings,
)
from app.modules.estimates.application import public as estimates
from app.modules.gaps.application import public as gaps
from app.modules.intake.application import public as intake
from app.platform import trace
from app.platform.actor import Actor
from app.platform.config import Settings, get_settings
from app.platform.ids import new_id
from app.platform.jobs import JobContext, JobPayload, JobType, enqueue, register
from app.platform.logging import get_logger
from app.platform.model_gateway import provider
from app.platform.model_gateway.port import ModelOutputInvalidError, ModelTimeoutError
from app.platform.trace.catalogue import AssessmentsRedTeamReviewCompleted
from app.platform.uow import UnitOfWork, unit_of_work

RED_TEAM_REVIEW = "assessments.red_team_review"
_KIND = ReviewKind.RED_TEAM.value
_IN_PROGRESS = tuple(sorted(s.value for s in IN_PROGRESS))
_QUEUED = (RunStatus.QUEUED.value,)
_RUNNING = (RunStatus.RUNNING.value,)
_log = get_logger(__name__)


class RedTeamReview(JobPayload):
    run_id: UUID


def review_settings() -> Settings:
    """Settings for the handler (the chat profile). Tests replace this."""
    return get_settings()


# --- queueing -------------------------------------------------------------------------------


async def queue_review(uow: UnitOfWork, opportunity_id: UUID) -> UUID:
    """Insert a `queued` run and its job. The caller holds the Opportunity's Red Team lock."""
    run_id = new_id()
    await repo.insert_run(uow, run_id=run_id, opportunity_id=opportunity_id)
    await enqueue(uow, RedTeamReview(run_id=run_id), opportunity_id=opportunity_id)
    return run_id


async def enqueue_review(uow: UnitOfWork, opportunity_id: UUID) -> UUID:
    """Queue a Red Team Review of the Opportunity in the caller's Unit of Work, unless one is
    already queued and not yet started: then that one's id is returned and nothing added."""
    await repo.lock_opportunity(uow, opportunity_id)
    await fail_stale(uow, opportunity_id)
    waiting = await repo.run_in(uow, opportunity_id, _QUEUED)
    ids = {"opportunity_id": str(opportunity_id)}
    if waiting is not None:
        _log.info("assessments.red_team_coalesced", extra={**ids, "run_id": str(waiting)})
        return waiting
    run_id = await queue_review(uow, opportunity_id)
    _log.info("assessments.red_team_queued", extra={**ids, "run_id": str(run_id)})
    return run_id


def stale_after() -> timedelta:
    """How long a run may stay `queued` or `running` before it is taken as lost (its job died
    without recording it): every attempt's timeout and the longest backoff before it, plus
    five minutes of queue slack."""
    spec = RED_TEAM_REVIEW_JOB
    return timedelta(seconds=(spec.timeout_s + spec.backoff_cap_s) * spec.max_attempts + 300)


async def fail_stale(uow: UnitOfWork, opportunity_id: UUID) -> None:
    """Mark the Opportunity's lost runs `failed` / `model_timeout`. The caller holds its Red
    Team lock."""
    failed = await repo.fail_stale_runs(
        uow,
        opportunity_id,
        older_than=stale_after(),
        error_code=RunErrorCode.MODEL_TIMEOUT.value,
    )
    if failed:
        _log.info(
            "assessments.red_team_stale_failed",
            extra={"opportunity_id": str(opportunity_id), "count": failed},
        )


# --- accepting ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReviewRequirement:
    """A Requirement the run read, with its prompt label `R<n>`."""

    label: str
    requirement_id: UUID
    version: int
    classification: str
    text: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ReviewLine:
    """A line of the reviewed Estimate Version the run read, with its prompt label `L<n>`."""

    label: str
    line_id: UUID
    section: str
    effort_hours: str
    title: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ReviewInputs:
    """What the run read: the Requirements, the number of open Gaps, and the Estimate Version
    reviewed (null when there was none) with its lines."""

    requirements: Sequence[ReviewRequirement]
    estimate_version_id: UUID | None = None
    lines: Sequence[ReviewLine] = ()
    gap_count: int = 0


def proposal(result: AgentResult) -> RedTeamOutput:
    """The agent's proposed Findings, re-validated (AD-4). Raises `ModelOutputInvalidError`
    when the extension is missing or malformed."""
    raw = result.extensions.get(AGENT_ID)
    try:
        return RedTeamOutput.model_validate(raw)
    except ValueError:
        raise ModelOutputInvalidError("The red_team_agent extension is not valid.") from None


def candidates(output: RedTeamOutput) -> list[FindingCandidate]:
    return [
        FindingCandidate(
            category=f.category,
            severity=f.severity,
            title=f.title,
            argument=f.argument,
            requirements=tuple(f.requirements),
            lines=tuple(f.lines),
        )
        for f in output.findings
    ]


async def accept_red_team_review(
    uow: UnitOfWork,
    *,
    run_id: UUID,
    result: AgentResult,
    inputs: ReviewInputs,
    actor: Actor,
) -> FindingValidation[tuple[UUID, int], UUID] | None:
    """`assessments.accept_red_team_review`: validate the agent's Findings and store them as a
    new `current` Red Team Review, superseding the Opportunity's earlier one; mark the run
    `succeeded` and trace it. Returns None (and writes nothing) unless the run is still
    `running`.

    When a newer run of the Opportunity has already succeeded, nothing is stored and the
    reply isn't even parsed (this one is `succeeded` with an empty validation: its results
    are out of date). When no Finding is valid, nothing is written and
    `ModelOutputInvalidError` is raised, so the job runs again."""
    record = await repo.get_run(uow, run_id)
    if record is None:
        return None
    await repo.lock_opportunity(uow, record.opportunity_id)
    record = await repo.get_run(uow, run_id, for_update=True)
    if record is None or record.status != RunStatus.RUNNING:
        return None
    ids = {"run_id": str(run_id), "opportunity_id": str(record.opportunity_id)}
    if await repo.newer_succeeded(uow, record):
        await _succeed(uow, record.id)
        _log.info("assessments.red_team_outdated", extra=ids)
        return FindingValidation((), 0)
    proposed = candidates(proposal(result))
    current = {
        (s.id, s.version)
        for s in await intake.active_requirement_snapshots(uow, record.opportunity_id)
    }
    requirement_labels = {
        r.label: (r.requirement_id, r.version)
        for r in inputs.requirements
        if (r.requirement_id, r.version) in current
    }
    line_labels = {line.label: line.line_id for line in inputs.lines}
    validation = validate_findings(proposed, requirement_labels, line_labels)
    if not validation.findings:
        _log.info(
            "assessments.red_team_all_invalid",
            extra={**ids, "dropped_count": validation.dropped},
        )
        raise ModelOutputInvalidError("No proposed Red Team Finding was valid.")

    superseded = await repo.supersede_reviews(uow, record.opportunity_id, _KIND)
    number = await repo.latest_review_number(uow, record.opportunity_id, _KIND) + 1
    review_id = new_id()
    await repo.insert_review(
        uow,
        review_id=review_id,
        opportunity_id=record.opportunity_id,
        kind=_KIND,
        version=number,
        estimate_version_id=inputs.estimate_version_id,
        dropped_count=validation.dropped,
        findings=[
            repo.NewFinding(
                finding_id=new_id(),
                position=position,
                category=f.category.value,
                severity=f.severity.value,
                title=f.title,
                argument=f.argument,
                requirements=list(f.requirements),
                lines=list(f.lines),
            )
            for position, f in enumerate(validation.findings, start=1)
        ],
    )
    counts = severity_counts(f.severity for f in validation.findings)
    completed = AssessmentsRedTeamReviewCompleted(
        version=number,
        finding_count=len(validation.findings),
        critical_count=counts[Severity.CRITICAL],
        high_count=counts[Severity.HIGH],
        medium_count=counts[Severity.MEDIUM],
        low_count=counts[Severity.LOW],
        dropped_count=validation.dropped,
        requirement_count=len(inputs.requirements),
        gap_count=inputs.gap_count,
        line_count=len(inputs.lines),
        superseded_count=superseded,
    )
    await trace.append(
        uow,
        actor=actor,
        payload=completed,
        subject_type=REVIEW_SUBJECT_TYPE,
        subject_id=review_id,
        opportunity_id=record.opportunity_id,
    )
    await _succeed(uow, record.id)
    _log.info(
        "assessments.red_team_accepted",
        extra={**ids, "review_id": str(review_id), **completed.model_dump()},
    )
    return validation


async def _succeed(uow: UnitOfWork, run_id: UUID) -> None:
    await repo.update_run(
        uow,
        run_id,
        from_statuses=_RUNNING,
        status=RunStatus.SUCCEEDED.value,
        finished=True,
    )


# --- the handler ----------------------------------------------------------------------------


def error_code(exc: BaseException) -> RunErrorCode:
    """The run's `error_code` for the error that killed its job."""
    if isinstance(exc, ModelTimeoutError):
        return RunErrorCode.MODEL_TIMEOUT
    if isinstance(exc, ModelOutputInvalidError):
        return RunErrorCode.OUTPUT_INVALID
    # The gateway unreachable or missing, or anything else that kept the model from
    # answering.
    return RunErrorCode.MODEL_UNAVAILABLE


async def _mark_failed(ctx: JobContext, run_id: UUID, code: RunErrorCode) -> bool:
    async with unit_of_work(ctx.engine) as uow:
        return await repo.update_run(
            uow,
            run_id,
            from_statuses=_IN_PROGRESS,
            status=RunStatus.FAILED.value,
            error_code=code.value,
            finished=True,
        )


async def red_team_review(ctx: JobContext, payload: RedTeamReview) -> None:
    """The handler. On the job's final attempt any error first marks the run `failed` (best
    effort), so none is left `running` once its job is dead; then it re-raises."""
    ids = {"run_id": str(payload.run_id), "job_id": str(ctx.job_id)}
    try:
        await _review(ctx, payload)
    except asyncio.CancelledError:
        # The job's timeout (or a stopping worker) cancelled the run. On the final attempt
        # nothing will run it again, so record it as timed out, shielded from the
        # cancellation, then let the cancellation through.
        if ctx.attempt >= ctx.max_attempts:
            await _mark_failed_shielded(ctx, payload.run_id, ids)
        raise
    except Exception as exc:
        code = error_code(exc)
        if ctx.attempt >= ctx.max_attempts:
            try:
                recorded = await _mark_failed(ctx, payload.run_id, code)
            except Exception as mark_exc:  # e.g. the database is down: the job still dies
                _log.warning(
                    "assessments.red_team_fail_unrecorded",
                    extra={**ids, "exc_type": type(mark_exc).__name__},
                )
            else:
                _log.info(
                    "assessments.red_team_failed",
                    extra={**ids, "error_code": code.value, "recorded": recorded},
                )
        else:
            _log.warning(
                "assessments.red_team_retrying",
                extra={**ids, "exc_type": type(exc).__name__, "error_code": code.value},
            )
        raise


async def _mark_failed_shielded(ctx: JobContext, run_id: UUID, ids: dict[str, str]) -> None:
    write = asyncio.ensure_future(_mark_failed(ctx, run_id, RunErrorCode.MODEL_TIMEOUT))
    try:
        recorded = await asyncio.shield(write)
    except asyncio.CancelledError:  # cancelled again: still let the write land
        await asyncio.wait({write})
        recorded = not write.cancelled() and write.exception() is None and write.result()
    except Exception as exc:
        _log.warning(
            "assessments.red_team_fail_unrecorded", extra={**ids, "exc_type": type(exc).__name__}
        )
        return
    _log.info(
        "assessments.red_team_failed",
        extra={**ids, "error_code": RunErrorCode.MODEL_TIMEOUT.value, "recorded": recorded},
    )


@dataclass(frozen=True, slots=True)
class _Started:
    opportunity_id: UUID
    inputs: ReviewInputs
    gaps: list[GapBlock] = field(repr=False)


async def _start(ctx: JobContext, run_id: UUID) -> _Started | None:
    """Read the Opportunity's active Requirements, open Gaps and current Estimate lines and
    mark the run `running`; None if it is no longer queued or running (a duplicate or late
    run)."""
    async with unit_of_work(ctx.engine) as uow:
        record = await repo.get_run(uow, run_id)
        if record is None:
            return None
        await repo.lock_opportunity(uow, record.opportunity_id)
        record = await repo.get_run(uow, run_id, for_update=True)
        if record is None or record.status not in _IN_PROGRESS:
            return None
        snapshots = await intake.active_requirement_snapshots(uow, record.opportunity_id)
        open_gaps = await gaps.open_gap_summaries(uow, record.opportunity_id)
        estimate = await estimates.current_version_lines(uow, record.opportunity_id)
        await repo.update_run(
            uow,
            run_id,
            from_statuses=_IN_PROGRESS,
            status=RunStatus.RUNNING.value,
        )
        return _Started(
            opportunity_id=record.opportunity_id,
            inputs=ReviewInputs(
                requirements=[
                    ReviewRequirement(
                        label=f"R{s.number}",
                        requirement_id=s.id,
                        version=s.version,
                        classification=s.classification,
                        text=s.text,
                    )
                    for s in snapshots
                ],
                estimate_version_id=None if estimate is None else estimate.version_id,
                lines=[]
                if estimate is None
                else [
                    ReviewLine(
                        label=f"L{n}",
                        line_id=line.id,
                        section=line.section,
                        effort_hours=f"{line.effort_hours:.1f}",
                        title=line.title,
                    )
                    for n, line in enumerate(estimate.lines, start=1)
                ],
                gap_count=len(open_gaps),
            ),
            gaps=[
                GapBlock(
                    label=f"G{n}",
                    category=g.category,
                    impact=g.impact,
                    title=g.title,
                    why_it_matters=g.why_it_matters,
                )
                for n, g in enumerate(open_gaps, start=1)
            ],
        )


async def _review(ctx: JobContext, payload: RedTeamReview) -> None:
    settings = review_settings()
    run_id = payload.run_id
    ids: dict[str, object] = {"run_id": str(run_id)}
    started = await _start(ctx, run_id)
    if started is None:
        _log.info("assessments.red_team_skipped", extra=ids)
        return
    ids["opportunity_id"] = str(started.opportunity_id)

    inputs = started.inputs
    if not inputs.requirements:  # nothing to challenge: no model call, no Review
        async with unit_of_work(ctx.engine) as uow:
            await _succeed(uow, run_id)
        _log.info("assessments.red_team_empty", extra=ids)
        return

    agent = RedTeamAgent(provider.current(), profile=settings.model_profile_chat)
    result = await agent.run(
        RedTeamTask(
            opportunity_id=started.opportunity_id,
            run_id=run_id,
            requirements=[
                RequirementBlock(r.label, r.classification, r.text) for r in inputs.requirements
            ],
            gaps=started.gaps,
            lines=[
                LineBlock(line.label, line.section, line.effort_hours, line.title)
                for line in inputs.lines
            ],
        )
    )
    actor = Actor(type="agent", id=agent_config(settings.model_profile_chat).actor_id)
    async with unit_of_work(ctx.engine) as uow:
        accepted = await accept_red_team_review(
            uow, run_id=run_id, result=result, inputs=inputs, actor=actor
        )
    if accepted is None:
        _log.info("assessments.red_team_skipped", extra=ids)


RED_TEAM_REVIEW_JOB = register(
    JobType(
        name=RED_TEAM_REVIEW,
        payload=RedTeamReview,
        handler=red_team_review,
        priority="background",
        # Above the worst case: (1 + PSA_MODEL_MAX_RETRIES) attempts of PSA_MODEL_TIMEOUT_S
        # (3 x 120 s) for the call, plus the wait for a model slot.
        timeout_s=900.0,
        max_attempts=2,
        backoff_base_s=15.0,
        backoff_cap_s=120.0,
    )
)
