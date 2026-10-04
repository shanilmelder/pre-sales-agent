"""Estimate drafting (Story 8.1): the `estimates.draft_estimate` job and
`estimates.accept_draft`.

**Queueing.** `gaps.accept_gap_detection` calls `enqueue_draft` (through
`estimates.application.public`) in its Unit of Work: it inserts a `queued` `estimates_drafts`
row and its job (background priority), unless one of the Opportunity's drafts is still
`queued` (its job not yet started), in which case nothing is added. `start_draft` (the Retry
API) does the same, but refuses (409) while one is `queued` or `running`. Both hold the
Opportunity's draft lock until commit.

**The handler.**

1. Short Unit of Work: reads the Opportunity's active Requirements at their current versions
   (`intake.active_requirement_snapshots`), labelled `R<n>`, and its open Gaps
   (`gaps.open_gap_summaries`), labelled `G<n>`, and marks the draft `running`.
2. No active Requirements: no model call, no version; the draft `succeeded`.
3. No Unit of Work open: `estimating_agent` proposes work items through the ModelGateway.
4. `accept_draft`, one Unit of Work: validates every line (its covers labels must resolve to
   Requirements still active at the version read), supersedes the Opportunity's `draft`
   Estimate Version, stores the new `draft` version (numbered one past the latest, template
   `demo-1`) with its lines and their Requirement links, carries the superseded draft's
   accepted Assumptions into it (Story 8.7), marks the draft `succeeded`,
   traces `estimates.estimate_version.created`, queues the version's Assumption
   proposals (`estimates.propose_assumptions`, Story 8.4) and the Opportunity's Red Team
   Review (`assessments.red_team_review`, Story 6.5).

When no line is valid, acceptance writes nothing and raises `ModelOutputInvalidError`, so
the queue runs the job once more (`max_attempts` 2); on the final attempt the handler marks
the draft `failed` / `output_invalid`. A gateway error is handled the same way:
`model_unavailable`, `model_timeout` or `output_invalid`. Idempotent: only a draft still
`queued` or `running` is worked on, and only a `running` one accepted.

Logs, trace and `last_error` carry ids, codes and counts only, never Requirement, Gap or line
text.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID

from app.agents.contract import AgentResult
from app.agents.estimating_agent.agent import (
    AGENT_ID,
    EstimatingAgent,
    EstimatingTask,
    GapBlock,
    RequirementBlock,
)
from app.agents.estimating_agent.agent import config as agent_config
from app.agents.estimating_agent.schema import EstimatingOutput
from app.modules.estimates.adapters import repository as repo
from app.modules.estimates.application.assumptions import carry_accepted, enqueue_proposals
from app.modules.estimates.domain.assumptions import ProposalStatus
from app.modules.estimates.domain.estimates import (
    IN_PROGRESS,
    TEMPLATE_VERSION,
    VERSION_SUBJECT_TYPE,
    DraftErrorCode,
    DraftStatus,
    LineCandidate,
    Validation,
    uncovered,
    validate_lines,
)
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
from app.platform.trace.catalogue import EstimatesEstimateVersionCreated
from app.platform.uow import UnitOfWork, unit_of_work

DRAFT_ESTIMATE = "estimates.draft_estimate"
_IN_PROGRESS = tuple(sorted(s.value for s in IN_PROGRESS))
_QUEUED = (DraftStatus.QUEUED.value,)
_RUNNING = (DraftStatus.RUNNING.value,)
_log = get_logger(__name__)


class DraftEstimate(JobPayload):
    draft_id: UUID


def draft_settings() -> Settings:
    """Settings for the handler (the chat profile). Tests replace this."""
    return get_settings()


# --- queueing -------------------------------------------------------------------------------


async def queue_draft(uow: UnitOfWork, opportunity_id: UUID) -> UUID:
    """Insert a `queued` draft and its job. The caller holds the Opportunity's draft lock."""
    draft_id = new_id()
    await repo.insert_draft(uow, draft_id=draft_id, opportunity_id=opportunity_id)
    await enqueue(uow, DraftEstimate(draft_id=draft_id), opportunity_id=opportunity_id)
    return draft_id


async def enqueue_draft(uow: UnitOfWork, opportunity_id: UUID) -> UUID:
    """Queue an Estimate draft of the Opportunity in the caller's Unit of Work, unless one is
    already queued and not yet started: then that one's id is returned and nothing added."""
    await repo.lock_opportunity(uow, opportunity_id)
    await fail_stale(uow, opportunity_id)
    waiting = await repo.draft_in(uow, opportunity_id, _QUEUED)
    ids = {"opportunity_id": str(opportunity_id)}
    if waiting is not None:
        _log.info("estimates.draft_coalesced", extra={**ids, "draft_id": str(waiting)})
        return waiting
    draft_id = await queue_draft(uow, opportunity_id)
    _log.info("estimates.draft_queued", extra={**ids, "draft_id": str(draft_id)})
    return draft_id


def stale_after() -> timedelta:
    """How long a draft may stay `queued` or `running` before it is taken as lost (its job
    died without recording it): every attempt's timeout and the longest backoff before it,
    plus five minutes of queue slack."""
    spec = DRAFT_ESTIMATE_JOB
    return timedelta(seconds=(spec.timeout_s + spec.backoff_cap_s) * spec.max_attempts + 300)


async def fail_stale(uow: UnitOfWork, opportunity_id: UUID) -> None:
    """Mark the Opportunity's lost drafts `failed` / `model_timeout`. The caller holds its
    draft lock."""
    failed = await repo.fail_stale_drafts(
        uow,
        opportunity_id,
        older_than=stale_after(),
        error_code=DraftErrorCode.MODEL_TIMEOUT.value,
    )
    if failed:
        _log.info(
            "estimates.draft_stale_failed",
            extra={"opportunity_id": str(opportunity_id), "count": failed},
        )


# --- accepting ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DraftRequirement:
    """A Requirement the draft read, with its prompt label `R<n>`."""

    label: str
    requirement_id: UUID
    version: int
    classification: str
    text: str = field(repr=False)


def proposal(result: AgentResult) -> EstimatingOutput:
    """The agent's proposed lines, re-validated (AD-4). Raises `ModelOutputInvalidError` when
    the extension is missing or malformed."""
    raw = result.extensions.get(AGENT_ID)
    try:
        return EstimatingOutput.model_validate(raw)
    except ValueError:
        raise ModelOutputInvalidError("The estimating_agent extension is not valid.") from None


def candidates(output: EstimatingOutput) -> list[LineCandidate]:
    return [
        LineCandidate(
            section=line.section,
            title=line.title,
            covers=tuple(line.covers),
            effort_hours=line.effort_hours,
            role_mix=line.role_mix.model_dump(),
            basis=line.basis,
        )
        for line in output.lines
    ]


async def accept_draft(
    uow: UnitOfWork,
    *,
    draft_id: UUID,
    result: AgentResult,
    requirements: Sequence[DraftRequirement],
    actor: Actor,
) -> Validation[tuple[UUID, int]] | None:
    """`estimates.accept_draft`: validate the agent's lines and store them as a new `draft`
    Estimate Version, superseding the Opportunity's earlier `draft`; mark the draft
    `succeeded` and trace it. Returns None (and writes nothing) unless the draft is still
    `running`.

    When a newer draft of the Opportunity has already succeeded, nothing is stored and the
    reply isn't even parsed (this one is `succeeded` with an empty validation: its results
    are out of date). When no line is valid, nothing is written
    and `ModelOutputInvalidError` is raised, so the job runs again."""
    record = await repo.get_draft(uow, draft_id)
    if record is None:
        return None
    await repo.lock_opportunity(uow, record.opportunity_id)
    record = await repo.get_draft(uow, draft_id, for_update=True)
    if record is None or record.status != DraftStatus.RUNNING:
        return None
    ids = {"draft_id": str(draft_id), "opportunity_id": str(record.opportunity_id)}
    if await repo.newer_succeeded(uow, record):
        # Out of date: nothing is stored, whatever the reply was.
        await _succeed(uow, record.id)
        _log.info("estimates.draft_outdated", extra=ids)
        return Validation((), 0)
    proposed = candidates(proposal(result))
    active = [
        (s.id, s.version)
        for s in await intake.active_requirement_snapshots(uow, record.opportunity_id)
    ]
    current = set(active)
    labels = {
        r.label: (r.requirement_id, r.version)
        for r in requirements
        if (r.requirement_id, r.version) in current
    }
    validation = validate_lines(proposed, labels)
    if not validation.lines:
        _log.info(
            "estimates.draft_all_invalid",
            extra={**ids, "dropped_count": validation.dropped},
        )
        raise ModelOutputInvalidError("No proposed Estimate line was valid.")

    # Story 8.7: the draft version being superseded, whose accepted Assumptions are carried.
    previous = await repo.current_version(uow, record.opportunity_id)
    superseded = await repo.supersede_drafts(uow, record.opportunity_id)
    number = await repo.latest_version_number(uow, record.opportunity_id) + 1
    version_id = new_id()
    missing = uncovered(validation.lines, active)
    await repo.insert_version(
        uow,
        version_id=version_id,
        opportunity_id=record.opportunity_id,
        version=number,
        template_version=TEMPLATE_VERSION,
        uncovered_count=missing,
        dropped_count=validation.dropped,
        proposal_status=ProposalStatus.QUEUED.value,
        lines=[
            repo.NewLine(
                line_id=new_id(),
                position=position,
                section=line.section.value,
                title=line.title,
                effort_hours=line.effort_hours,
                role_mix={role.value: share for role, share in line.role_mix.items()},
                basis=line.basis,
                requirements=list(line.covers),
            )
            for position, line in enumerate(validation.lines, start=1)
        ],
    )
    carried = (
        0
        if previous is None
        else await carry_accepted(uow, source_version_id=previous.id, target_version_id=version_id)
    )
    created = EstimatesEstimateVersionCreated(
        version=number,
        template_version=TEMPLATE_VERSION,
        line_count=len(validation.lines),
        dropped_count=validation.dropped,
        uncovered_count=missing,
        requirement_count=len(requirements),
        superseded_count=superseded,
        carried_assumption_count=carried,
    )
    await trace.append(
        uow,
        actor=actor,
        payload=created,
        subject_type=VERSION_SUBJECT_TYPE,
        subject_id=version_id,
        opportunity_id=record.opportunity_id,
    )
    await enqueue_proposals(uow, version_id=version_id, opportunity_id=record.opportunity_id)
    # Story 6.5: every accepted draft is reviewed by the Red Team, queued in this Unit of
    # Work. Imported here, not at the top: assessments reads Estimate lines through
    # `estimates.application.public`, which imports this module, so a top-level import would
    # be circular.
    from app.modules.assessments.application import public as assessments

    await assessments.enqueue_review(uow, record.opportunity_id)
    await _succeed(uow, record.id)
    _log.info(
        "estimates.draft_accepted",
        extra={**ids, "version_id": str(version_id), **created.model_dump()},
    )
    return validation


async def _succeed(uow: UnitOfWork, draft_id: UUID) -> None:
    await repo.update_draft(
        uow,
        draft_id,
        from_statuses=_RUNNING,
        status=DraftStatus.SUCCEEDED.value,
        finished=True,
    )


# --- the handler ----------------------------------------------------------------------------


def error_code(exc: BaseException) -> DraftErrorCode:
    """The draft's `error_code` for the error that killed its job."""
    if isinstance(exc, ModelTimeoutError):
        return DraftErrorCode.MODEL_TIMEOUT
    if isinstance(exc, ModelOutputInvalidError):
        return DraftErrorCode.OUTPUT_INVALID
    # The gateway unreachable or missing, or anything else that kept the model from
    # answering.
    return DraftErrorCode.MODEL_UNAVAILABLE


async def _mark_failed(ctx: JobContext, draft_id: UUID, code: DraftErrorCode) -> bool:
    async with unit_of_work(ctx.engine) as uow:
        return await repo.update_draft(
            uow,
            draft_id,
            from_statuses=_IN_PROGRESS,
            status=DraftStatus.FAILED.value,
            error_code=code.value,
            finished=True,
        )


async def draft_estimate(ctx: JobContext, payload: DraftEstimate) -> None:
    """The handler. On the job's final attempt any error first marks the draft `failed`
    (best effort), so none is left `running` once its job is dead; then it re-raises."""
    ids = {"draft_id": str(payload.draft_id), "job_id": str(ctx.job_id)}
    try:
        await _draft(ctx, payload)
    except asyncio.CancelledError:
        # The job's timeout (or a stopping worker) cancelled the run. On the final attempt
        # nothing will run it again, so record it as timed out, shielded from the
        # cancellation, then let the cancellation through.
        if ctx.attempt >= ctx.max_attempts:
            await _mark_failed_shielded(ctx, payload.draft_id, ids)
        raise
    except Exception as exc:
        code = error_code(exc)
        if ctx.attempt >= ctx.max_attempts:
            try:
                recorded = await _mark_failed(ctx, payload.draft_id, code)
            except Exception as mark_exc:  # e.g. the database is down: the job still dies
                _log.warning(
                    "estimates.draft_fail_unrecorded",
                    extra={**ids, "exc_type": type(mark_exc).__name__},
                )
            else:
                _log.info(
                    "estimates.draft_failed",
                    extra={**ids, "error_code": code.value, "recorded": recorded},
                )
        else:
            _log.warning(
                "estimates.draft_retrying",
                extra={**ids, "exc_type": type(exc).__name__, "error_code": code.value},
            )
        raise


async def _mark_failed_shielded(ctx: JobContext, draft_id: UUID, ids: dict[str, str]) -> None:
    write = asyncio.ensure_future(_mark_failed(ctx, draft_id, DraftErrorCode.MODEL_TIMEOUT))
    try:
        recorded = await asyncio.shield(write)
    except asyncio.CancelledError:  # cancelled again: still let the write land
        await asyncio.wait({write})
        recorded = not write.cancelled() and write.exception() is None and write.result()
    except Exception as exc:
        _log.warning(
            "estimates.draft_fail_unrecorded", extra={**ids, "exc_type": type(exc).__name__}
        )
        return
    _log.info(
        "estimates.draft_failed",
        extra={**ids, "error_code": DraftErrorCode.MODEL_TIMEOUT.value, "recorded": recorded},
    )


@dataclass(frozen=True, slots=True)
class _Started:
    opportunity_id: UUID
    requirements: list[DraftRequirement]
    gaps: list[GapBlock] = field(repr=False)


async def _start(ctx: JobContext, draft_id: UUID) -> _Started | None:
    """Read the Opportunity's active Requirements and open Gaps and mark the draft
    `running`; None if it is no longer queued or running (a duplicate or late run)."""
    async with unit_of_work(ctx.engine) as uow:
        record = await repo.get_draft(uow, draft_id)
        if record is None:
            return None
        await repo.lock_opportunity(uow, record.opportunity_id)
        record = await repo.get_draft(uow, draft_id, for_update=True)
        if record is None or record.status not in _IN_PROGRESS:
            return None
        snapshots = await intake.active_requirement_snapshots(uow, record.opportunity_id)
        open_gaps = await gaps.open_gap_summaries(uow, record.opportunity_id)
        await repo.update_draft(
            uow,
            draft_id,
            from_statuses=_IN_PROGRESS,
            status=DraftStatus.RUNNING.value,
        )
        return _Started(
            opportunity_id=record.opportunity_id,
            requirements=[
                DraftRequirement(
                    label=f"R{s.number}",
                    requirement_id=s.id,
                    version=s.version,
                    classification=s.classification,
                    text=s.text,
                )
                for s in snapshots
            ],
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


async def _draft(ctx: JobContext, payload: DraftEstimate) -> None:
    settings = draft_settings()
    draft_id = payload.draft_id
    ids: dict[str, object] = {"draft_id": str(draft_id)}
    started = await _start(ctx, draft_id)
    if started is None:
        _log.info("estimates.draft_skipped", extra=ids)
        return
    ids["opportunity_id"] = str(started.opportunity_id)

    if not started.requirements:  # nothing to estimate: no model call, no version
        async with unit_of_work(ctx.engine) as uow:
            await _succeed(uow, draft_id)
        _log.info("estimates.draft_empty", extra=ids)
        return

    agent = EstimatingAgent(provider.current(), profile=settings.model_profile_chat)
    result = await agent.run(
        EstimatingTask(
            opportunity_id=started.opportunity_id,
            run_id=draft_id,
            requirements=[
                RequirementBlock(r.label, r.classification, r.text) for r in started.requirements
            ],
            gaps=started.gaps,
        )
    )
    actor = Actor(type="agent", id=agent_config(settings.model_profile_chat).actor_id)
    async with unit_of_work(ctx.engine) as uow:
        accepted = await accept_draft(
            uow,
            draft_id=draft_id,
            result=result,
            requirements=started.requirements,
            actor=actor,
        )
    if accepted is None:
        _log.info("estimates.draft_skipped", extra=ids)


DRAFT_ESTIMATE_JOB = register(
    JobType(
        name=DRAFT_ESTIMATE,
        payload=DraftEstimate,
        handler=draft_estimate,
        priority="background",
        # Above the worst case: (1 + PSA_MODEL_MAX_RETRIES) attempts of PSA_MODEL_TIMEOUT_S
        # (3 x 120 s) for the call, plus the wait for a model slot.
        timeout_s=900.0,
        max_attempts=2,
        backoff_base_s=15.0,
        backoff_cap_s=120.0,
    )
)
