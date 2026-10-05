"""Gap detection (Story 4.3): the `gaps.detect_gaps` job and `gaps.accept_gap_detection`.

**Queueing.** `intake.accept_extraction` calls `enqueue_detection` (through
`gaps.application.public`) in its Unit of Work: it inserts a `queued` `gaps_detections` row
and its job (background priority), unless one of the Opportunity's detections is still
`queued` (its job not yet started), in which case nothing is added. `start_detection` (the
Retry API) does the same, but refuses (409) while one is `queued` or `running`. Both hold the
Opportunity's detection lock until commit.

**The handler.**

1. Short Unit of Work: reads the Opportunity's active Requirements at their current versions
   (`intake.active_requirement_snapshots`), labelled `R<n>`, and marks the detection
   `running`.
2. No active Requirements: no model call; accepted as an empty result (0 Gaps).
3. No Unit of Work open: `clarification_agent` proposes Gaps through the ModelGateway.
4. `accept_gap_detection`, one Unit of Work: validates every candidate (the related labels
   must resolve to Requirements still active at the version read), supersedes the earlier
   open, detected Gaps with their questions (except those whose question a person edited or
   approved, Story 4.5: they are kept as they are), stores the new Gaps, their Requirement links and
   their drafted questions, marks the detection `succeeded` with its counts, and traces
   `gaps.gap.raised` and `gaps.clarification_question.drafted` per Gap and
   `gaps.detection.completed`; and queues the Opportunity's Estimate draft
   (`estimates.enqueue_draft`, Story 8.1) and its specialist assessment run
   (`assessments.enqueue_run`, Story 5.1; coalesced with a run already queued or running).

When the agent proposed candidates and every one is invalid, acceptance writes nothing and
raises `ModelOutputInvalidError`, so the queue runs the job once more (`max_attempts` 2); on
the final attempt the handler marks the detection `failed` / `output_invalid`. A gateway
error is handled the same way: `model_unavailable`, `model_timeout` or `output_invalid`.
Idempotent: only a detection still `queued` or `running` is worked on, and only a `running`
one accepted.

Logs, trace and `last_error` carry ids, codes and counts only, never Requirement, Gap or
question text.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID

from app.agents.clarification_agent.agent import (
    AGENT_ID,
    ClarificationAgent,
    ClarificationTask,
    RequirementBlock,
)
from app.agents.clarification_agent.agent import config as agent_config
from app.agents.clarification_agent.schema import ClarificationOutput
from app.agents.contract import AgentResult
from app.modules.gaps.adapters import repository as repo
from app.modules.gaps.domain.gaps import (
    DETECTION_SUBJECT_TYPE,
    GAP_SUBJECT_TYPE,
    IN_PROGRESS,
    QUESTION_SUBJECT_TYPE,
    Candidate,
    DetectionErrorCode,
    DetectionStatus,
    Validation,
    trigger,
    validate_candidates,
)
from app.modules.intake.application import public as intake
from app.platform import trace
from app.platform.actor import Actor
from app.platform.config import Settings, get_settings
from app.platform.ids import new_id
from app.platform.jobs import JobContext, JobPayload, JobType, enqueue, register
from app.platform.logging import get_logger
from app.platform.model_gateway import provider
from app.platform.model_gateway.port import ModelOutputInvalidError, ModelTimeoutError
from app.platform.trace.catalogue import (
    GapsClarificationQuestionDrafted,
    GapsDetectionCompleted,
    GapsGapRaised,
)
from app.platform.uow import UnitOfWork, unit_of_work

DETECT_GAPS = "gaps.detect_gaps"
_IN_PROGRESS = tuple(sorted(s.value for s in IN_PROGRESS))
_QUEUED = (DetectionStatus.QUEUED.value,)
_RUNNING = (DetectionStatus.RUNNING.value,)
_log = get_logger(__name__)


class DetectGaps(JobPayload):
    detection_id: UUID


def detection_settings() -> Settings:
    """Settings for the handler (the chat profile). Tests replace this."""
    return get_settings()


# --- queueing -------------------------------------------------------------------------------


async def queue_detection(uow: UnitOfWork, opportunity_id: UUID) -> UUID:
    """Insert a `queued` detection and its job. The caller holds the Opportunity's
    detection lock."""
    detection_id = new_id()
    await repo.insert_detection(uow, detection_id=detection_id, opportunity_id=opportunity_id)
    await enqueue(uow, DetectGaps(detection_id=detection_id), opportunity_id=opportunity_id)
    return detection_id


async def enqueue_detection(uow: UnitOfWork, opportunity_id: UUID) -> UUID:
    """Queue a Gap detection of the Opportunity in the caller's Unit of Work, unless one is
    already queued and not yet started: then that one's id is returned and nothing added."""
    await repo.lock_opportunity(uow, opportunity_id)
    await fail_stale(uow, opportunity_id)
    waiting = await repo.detection_in(uow, opportunity_id, _QUEUED)
    ids = {"opportunity_id": str(opportunity_id)}
    if waiting is not None:
        _log.info("gaps.detection_coalesced", extra={**ids, "detection_id": str(waiting)})
        return waiting
    detection_id = await queue_detection(uow, opportunity_id)
    _log.info("gaps.detection_queued", extra={**ids, "detection_id": str(detection_id)})
    return detection_id


def stale_after() -> timedelta:
    """How long a detection may stay `queued` or `running` before it is taken as lost (its
    job died without recording it): every attempt's timeout, plus a minute."""
    spec = DETECT_GAPS_JOB
    return timedelta(seconds=spec.timeout_s * spec.max_attempts + 60)


async def fail_stale(uow: UnitOfWork, opportunity_id: UUID) -> None:
    """Mark the Opportunity's lost detections `failed` / `model_timeout`. The caller holds
    its detection lock."""
    failed = await repo.fail_stale_detections(
        uow,
        opportunity_id,
        older_than=stale_after(),
        error_code=DetectionErrorCode.MODEL_TIMEOUT.value,
    )
    if failed:
        _log.info(
            "gaps.detection_stale_failed",
            extra={"opportunity_id": str(opportunity_id), "count": failed},
        )


# --- accepting ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DetectionRequirement:
    """A Requirement the detection read, with its prompt label `R<n>`."""

    label: str
    requirement_id: UUID
    version: int
    classification: str
    text: str = field(repr=False)


def proposal(result: AgentResult) -> ClarificationOutput:
    """The agent's proposed Gaps, re-validated (AD-4). Raises `ModelOutputInvalidError` when
    the extension is missing or malformed."""
    raw = result.extensions.get(AGENT_ID)
    try:
        return ClarificationOutput.model_validate(raw)
    except ValueError:
        raise ModelOutputInvalidError("The clarification_agent extension is not valid.") from None


def candidates(output: ClarificationOutput) -> list[Candidate]:
    return [
        Candidate(
            title=gap.title,
            category=gap.category,
            why_it_matters=gap.why_it_matters,
            impact=gap.impact,
            impact_basis=gap.impact_basis,
            related=tuple(gap.related),
            question_text=gap.question.text,
            question_topic=gap.question.topic,
        )
        for gap in output.gaps
    ]


async def _resolvable(
    uow: UnitOfWork, opportunity_id: UUID, read: Sequence[DetectionRequirement]
) -> dict[str, tuple[UUID, int]]:
    """Label to `(id, version)`, for the Requirements read that are still active at the
    version read."""
    current = {
        (s.id, s.version) for s in await intake.active_requirement_snapshots(uow, opportunity_id)
    }
    return {
        r.label: (r.requirement_id, r.version)
        for r in read
        if (r.requirement_id, r.version) in current
    }


async def accept_gap_detection(
    uow: UnitOfWork,
    *,
    detection_id: UUID,
    result: AgentResult,
    requirements: Sequence[DetectionRequirement],
    actor: Actor,
) -> Validation[tuple[UUID, int]] | None:
    """`gaps.accept_gap_detection`: validate the agent's candidates, supersede the
    Opportunity's earlier open, detected Gaps (with their questions) and store the new ones
    with their Requirement links and drafted questions; mark the detection `succeeded` and
    trace it. Returns None (and writes nothing) unless the detection is still `running`.

    When a newer detection of the Opportunity has already succeeded, nothing is superseded
    or stored (this one is `succeeded` with 0 Gaps: its results are out of date). When there
    were candidates and none is valid, nothing is written and `ModelOutputInvalidError` is
    raised, so the job runs again."""
    record = await repo.get_detection(uow, detection_id)
    if record is None:
        return None
    await repo.lock_opportunity(uow, record.opportunity_id)
    record = await repo.get_detection(uow, detection_id, for_update=True)
    if record is None or record.status != DetectionStatus.RUNNING:
        return None
    proposed = candidates(proposal(result))
    labels = await _resolvable(uow, record.opportunity_id, requirements)
    validation = validate_candidates(proposed, labels)
    ids = {"detection_id": str(detection_id), "opportunity_id": str(record.opportunity_id)}
    if await repo.newer_succeeded(uow, record):
        outdated = GapsDetectionCompleted(
            gap_count=0,
            dropped_count=0,
            requirement_count=len(requirements),
            superseded_count=0,
            kept_count=0,
        )
        await _succeed(uow, record, outdated, actor)
        _log.info("gaps.detection_outdated", extra={**ids, **outdated.model_dump()})
        return validation
    if proposed and not validation.gaps:
        _log.info(
            "gaps.detection_all_invalid",
            extra={**ids, "dropped_count": validation.dropped},
        )
        raise ModelOutputInvalidError("Every proposed Gap was invalid.")
    superseded, kept = await repo.supersede_detected(uow, record.opportunity_id)
    for gap in validation.gaps:
        gap_id = new_id()
        question_id = new_id()
        await repo.insert_gap(
            uow,
            gap_id=gap_id,
            opportunity_id=record.opportunity_id,
            title=gap.title,
            category=gap.category.value,
            trigger=trigger(gap.category),
            why_it_matters=gap.why_it_matters,
            impact=gap.impact.value,
            impact_basis=gap.impact_basis,
            detection_id=detection_id,
            requirements=list(gap.related),
            question_id=question_id,
            question_text=gap.question_text,
            question_topic=gap.question_topic,
        )
        await trace.append(
            uow,
            actor=actor,
            payload=GapsGapRaised(
                detection_id=str(detection_id),
                category=gap.category.value,
                impact=gap.impact.value,
                requirement_ids=[str(rid) for rid, _ in gap.related],
            ),
            subject_type=GAP_SUBJECT_TYPE,
            subject_id=gap_id,
            opportunity_id=record.opportunity_id,
        )
        await trace.append(
            uow,
            actor=actor,
            payload=GapsClarificationQuestionDrafted(gap_id=str(gap_id)),
            subject_type=QUESTION_SUBJECT_TYPE,
            subject_id=question_id,
            opportunity_id=record.opportunity_id,
        )
    completed = GapsDetectionCompleted(
        gap_count=len(validation.gaps),
        dropped_count=validation.dropped,
        requirement_count=len(requirements),
        superseded_count=superseded,
        kept_count=kept,
    )
    await _succeed(uow, record, completed, actor)
    # Story 8.1: every successful Gap detection (re)queues the Opportunity's Estimate draft,
    # in this Unit of Work. Imported here, not at the top: estimates reads Gaps through
    # `gaps.application.public`, which imports this module, so a top-level import would be
    # circular.
    from app.modules.estimates.application import public as estimates

    await estimates.enqueue_draft(uow, record.opportunity_id)
    # Story 5.1: and queues the specialist assessment run (coalesced with one already queued
    # or running). Imported here for the same reason: assessments reads Gaps through
    # `gaps.application.public`.
    from app.modules.assessments.application import public as assessments

    await assessments.enqueue_run(uow, record.opportunity_id)
    _log.info("gaps.detection_accepted", extra={**ids, **completed.model_dump()})
    return validation


async def _succeed(
    uow: UnitOfWork,
    record: repo.DetectionRecord,
    completed: GapsDetectionCompleted,
    actor: Actor,
) -> None:
    await repo.update_detection(
        uow,
        record.id,
        from_statuses=_RUNNING,
        status=DetectionStatus.SUCCEEDED.value,
        gap_count=completed.gap_count,
        dropped_count=completed.dropped_count,
        finished=True,
    )
    await trace.append(
        uow,
        actor=actor,
        payload=completed,
        subject_type=DETECTION_SUBJECT_TYPE,
        subject_id=record.id,
        opportunity_id=record.opportunity_id,
    )


# --- the handler ----------------------------------------------------------------------------


def error_code(exc: BaseException) -> DetectionErrorCode:
    """The detection's `error_code` for the error that killed its job."""
    if isinstance(exc, ModelTimeoutError):
        return DetectionErrorCode.MODEL_TIMEOUT
    if isinstance(exc, ModelOutputInvalidError):
        return DetectionErrorCode.OUTPUT_INVALID
    # The gateway unreachable or missing, or anything else that kept the model from
    # answering.
    return DetectionErrorCode.MODEL_UNAVAILABLE


async def _mark_failed(ctx: JobContext, detection_id: UUID, code: DetectionErrorCode) -> bool:
    async with unit_of_work(ctx.engine) as uow:
        return await repo.update_detection(
            uow,
            detection_id,
            from_statuses=_IN_PROGRESS,
            status=DetectionStatus.FAILED.value,
            error_code=code.value,
            finished=True,
        )


async def detect_gaps(ctx: JobContext, payload: DetectGaps) -> None:
    """The handler. On the job's final attempt any error first marks the detection `failed`
    (best effort), so none is left `running` once its job is dead; then it re-raises."""
    ids = {"detection_id": str(payload.detection_id), "job_id": str(ctx.job_id)}
    try:
        await _detect(ctx, payload)
    except asyncio.CancelledError:
        # The job's timeout (or a stopping worker) cancelled the run. On the final attempt
        # nothing will run it again, so record it as timed out, shielded from the
        # cancellation, then let the cancellation through.
        if ctx.attempt >= ctx.max_attempts:
            await _mark_failed_shielded(ctx, payload.detection_id, ids)
        raise
    except Exception as exc:
        code = error_code(exc)
        if ctx.attempt >= ctx.max_attempts:
            try:
                recorded = await _mark_failed(ctx, payload.detection_id, code)
            except Exception as mark_exc:  # e.g. the database is down: the job still dies
                _log.warning(
                    "gaps.detection_fail_unrecorded",
                    extra={**ids, "exc_type": type(mark_exc).__name__},
                )
            else:
                _log.info(
                    "gaps.detection_failed",
                    extra={**ids, "error_code": code.value, "recorded": recorded},
                )
        else:
            _log.warning(
                "gaps.detection_retrying",
                extra={**ids, "exc_type": type(exc).__name__, "error_code": code.value},
            )
        raise


async def _mark_failed_shielded(ctx: JobContext, detection_id: UUID, ids: dict[str, str]) -> None:
    write = asyncio.ensure_future(_mark_failed(ctx, detection_id, DetectionErrorCode.MODEL_TIMEOUT))
    try:
        recorded = await asyncio.shield(write)
    except asyncio.CancelledError:  # cancelled again: still let the write land
        await asyncio.wait({write})
        recorded = not write.cancelled() and write.exception() is None and write.result()
    except Exception as exc:
        _log.warning(
            "gaps.detection_fail_unrecorded", extra={**ids, "exc_type": type(exc).__name__}
        )
        return
    _log.info(
        "gaps.detection_failed",
        extra={**ids, "error_code": DetectionErrorCode.MODEL_TIMEOUT.value, "recorded": recorded},
    )


async def _start(
    ctx: JobContext, detection_id: UUID
) -> tuple[UUID, list[DetectionRequirement]] | None:
    """Read the Opportunity's active Requirements and mark the detection `running`; None if
    it is no longer queued or running (a duplicate or late run)."""
    async with unit_of_work(ctx.engine) as uow:
        record = await repo.get_detection(uow, detection_id)
        if record is None:
            return None
        await repo.lock_opportunity(uow, record.opportunity_id)
        record = await repo.get_detection(uow, detection_id, for_update=True)
        if record is None or record.status not in _IN_PROGRESS:
            return None
        snapshots = await intake.active_requirement_snapshots(uow, record.opportunity_id)
        await repo.update_detection(
            uow,
            detection_id,
            from_statuses=_IN_PROGRESS,
            status=DetectionStatus.RUNNING.value,
        )
        read = [
            DetectionRequirement(
                label=f"R{s.number}",
                requirement_id=s.id,
                version=s.version,
                classification=s.classification,
                text=s.text,
            )
            for s in snapshots
        ]
        return record.opportunity_id, read


async def _detect(ctx: JobContext, payload: DetectGaps) -> None:
    settings = detection_settings()
    detection_id = payload.detection_id
    ids: dict[str, object] = {"detection_id": str(detection_id)}
    started = await _start(ctx, detection_id)
    if started is None:
        _log.info("gaps.detection_skipped", extra=ids)
        return
    opportunity_id, requirements = started
    ids["opportunity_id"] = str(opportunity_id)

    if requirements:
        agent = ClarificationAgent(provider.current(), profile=settings.model_profile_chat)
        result = await agent.run(
            ClarificationTask(
                opportunity_id=opportunity_id,
                run_id=detection_id,
                requirements=[
                    RequirementBlock(r.label, r.classification, r.text) for r in requirements
                ],
            )
        )
    else:  # no active Requirements: nothing to ask the model
        result = AgentResult(
            confidence=1.0,
            confidence_basis="No active Requirements.",
            needs_human_review=False,
            extensions={AGENT_ID: ClarificationOutput(gaps=[])},
        )

    actor = Actor(type="agent", id=agent_config(settings.model_profile_chat).actor_id)
    async with unit_of_work(ctx.engine) as uow:
        accepted = await accept_gap_detection(
            uow,
            detection_id=detection_id,
            result=result,
            requirements=requirements,
            actor=actor,
        )
    if accepted is None:
        _log.info("gaps.detection_skipped", extra=ids)


DETECT_GAPS_JOB = register(
    JobType(
        name=DETECT_GAPS,
        payload=DetectGaps,
        handler=detect_gaps,
        priority="background",
        # Above the worst case: (1 + PSA_MODEL_MAX_RETRIES) attempts of PSA_MODEL_TIMEOUT_S
        # (3 x 120 s) for the call, plus the wait for a model slot.
        timeout_s=900.0,
        max_attempts=2,
        backoff_base_s=15.0,
        backoff_cap_s=120.0,
    )
)
