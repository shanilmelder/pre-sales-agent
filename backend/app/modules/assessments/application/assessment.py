"""Specialist assessment runs (Epic 5 slice 5A): the `assessments.run_assessment` job and
`assessments.accept_assessment`.

**Queueing.** `start_run` (the Run assessment API) inserts a `queued` run with one `queued`
task per specialist agent (`engineering_agent`, `pm_agent`, `security_agent`) and one job
(background priority). `retry_task` puts one `failed` task of the latest run back to
`queued`, queues the run again and enqueues a job for it. Both hold the Opportunity's run
lock until commit and refuse (409) while one of its runs is queued or running.

**The handler** (one job per run; the agents work concurrently inside it).

1. Short Unit of Work: reads the Opportunity's active Requirements at their current versions
   (`intake.active_requirement_snapshots`), labelled `R<n>`, and its open Gaps
   (`gaps.open_gap_summaries`), labelled `G<n>`; marks the run and its tasks still queued or
   running `running`. A job attempt only runs tasks not yet finished, so a retried attempt
   never re-runs a task that succeeded.
2. No active Requirements: no model call and no Assessment; the tasks and the run succeed.
3. No Unit of Work open: the agents' calls start together (asyncio) through the ModelGateway,
   whose slots (`PSA_MODEL_SLOTS`) bound how many run at once. Each result is accepted as it
   arrives, in its own Unit of Work (`accept_assessment`), which marks that task `succeeded`.
4. A task whose call or acceptance failed stays `running` while the job has an attempt left
   (the job then raises, so the queue runs it once more for the unfinished tasks); on the
   final attempt it is marked `failed` with its `error_code` (`model_unavailable`,
   `model_timeout` or `output_invalid`).
5. When no task is left in progress the run is finished: `succeeded` (all tasks did),
   `partially_failed` (some did) or `failed` (none did), and
   `assessments.assessment_run.completed` is traced.

A run stuck past `stale_after()` (its job died without recording it) is failed on the next
start or retry: its unfinished tasks `failed` / `model_timeout`.

Logs, trace and `last_error` carry ids, codes and counts only, never Requirement, Gap or
Finding text.
"""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID

from app.agents.contract import AgentConfig, AgentResult
from app.agents.engineering_agent import agent as engineering_agent
from app.agents.engineering_agent.schema import EngineeringOutput
from app.agents.pm_agent import agent as pm_agent
from app.agents.pm_agent.schema import PmOutput
from app.agents.security_agent import agent as security_agent
from app.agents.security_agent.schema import SecurityOutput
from app.agents.specialist.agent import GapBlock, RequirementBlock, SpecialistAgent, SpecialistTask
from app.agents.specialist.schema import SpecialistOutput
from app.modules.assessments.adapters import assessment_repository as repo
from app.modules.assessments.adapters.assessment_repository import RunRecord
from app.modules.assessments.domain.assessments import (
    AGENTS,
    ASSESSMENT_SUBJECT_TYPE,
    RUN_IN_PROGRESS,
    RUN_SUBJECT_TYPE,
    TASK_IN_PROGRESS,
    AssessmentAgent,
    AssessmentCandidate,
    AssessmentFindingCandidate,
    AssessmentRunStatus,
    AssessmentTaskStatus,
    AssessmentValidation,
    EffortCandidate,
    run_status,
    validate_assessment,
)
from app.modules.assessments.domain.reviews import RunErrorCode, Severity, severity_counts
from app.modules.gaps.application import public as gaps
from app.modules.intake.application import public as intake
from app.platform import trace
from app.platform.actor import Actor
from app.platform.config import Settings, get_settings
from app.platform.ids import new_id
from app.platform.jobs import JobContext, JobPayload, JobType, enqueue, register
from app.platform.logging import get_logger
from app.platform.model_gateway import provider
from app.platform.model_gateway.port import (
    ModelGatewayPort,
    ModelOutputInvalidError,
    ModelTimeoutError,
)
from app.platform.trace.catalogue import (
    AssessmentsAssessmentCompleted,
    AssessmentsAssessmentRunCompleted,
    AssessmentsAssessmentRunStarted,
)
from app.platform.uow import UnitOfWork, unit_of_work

RUN_ASSESSMENT = "assessments.run_assessment"
_RUN_IN_PROGRESS = tuple(sorted(s.value for s in RUN_IN_PROGRESS))
_TASK_IN_PROGRESS = tuple(sorted(s.value for s in TASK_IN_PROGRESS))
_RUNNING = (AssessmentTaskStatus.RUNNING.value,)
_SYSTEM = Actor(type="system", id=RUN_ASSESSMENT)
_log = get_logger(__name__)


class RunAssessment(JobPayload):
    run_id: UUID


def assessment_settings() -> Settings:
    """Settings for the handler (the chat profile). Tests replace this."""
    return get_settings()


@dataclass(frozen=True, slots=True)
class _AgentSpec:
    config: Callable[[str], AgentConfig]
    build: Callable[[ModelGatewayPort, str], SpecialistAgent]
    output: type[SpecialistOutput]


_SPECS: dict[AssessmentAgent, _AgentSpec] = {
    AssessmentAgent.ENGINEERING: _AgentSpec(
        config=engineering_agent.config,
        build=lambda gateway, profile: engineering_agent.EngineeringAgent(gateway, profile=profile),
        output=EngineeringOutput,
    ),
    AssessmentAgent.PM: _AgentSpec(
        config=pm_agent.config,
        build=lambda gateway, profile: pm_agent.PmAgent(gateway, profile=profile),
        output=PmOutput,
    ),
    AssessmentAgent.SECURITY: _AgentSpec(
        config=security_agent.config,
        build=lambda gateway, profile: security_agent.SecurityAgent(gateway, profile=profile),
        output=SecurityOutput,
    ),
}


def agent_actor(agent: AssessmentAgent, profile: str) -> Actor:
    """The trace actor of an agent: `<agent_id>@<semver>`."""
    return Actor(type="agent", id=_SPECS[agent].config(profile).actor_id)


# --- queueing -------------------------------------------------------------------------------


def stale_after() -> timedelta:
    """How long a run may stay `queued` or `running` after it was last queued before it is
    taken as lost (its job died without recording it): every attempt's timeout and the
    longest backoff before it, plus five minutes of queue slack."""
    spec = RUN_ASSESSMENT_JOB
    return timedelta(seconds=(spec.timeout_s + spec.backoff_cap_s) * spec.max_attempts + 300)


async def queue_run(uow: UnitOfWork, opportunity_id: UUID, actor: Actor) -> UUID:
    """Insert a `queued` run with one task per agent, its job, and the trace event. The
    caller holds the Opportunity's run lock."""
    run_id = new_id()
    await repo.insert_run(
        uow, run_id=run_id, opportunity_id=opportunity_id, agents=[a.value for a in AGENTS]
    )
    await enqueue(uow, RunAssessment(run_id=run_id), opportunity_id=opportunity_id)
    await _trace_started(uow, run_id, opportunity_id, actor, agent_count=len(AGENTS))
    return run_id


async def requeue_task(
    uow: UnitOfWork, run: RunRecord, agent: AssessmentAgent, actor: Actor
) -> None:
    """Put the run's `failed` task of `agent` back to `queued`, queue the run again and
    enqueue a job for it. The caller holds the Opportunity's run lock and has checked the
    task is `failed`."""
    await repo.update_tasks(
        uow,
        run.id,
        agents=[agent.value],
        from_statuses=(AssessmentTaskStatus.FAILED.value,),
        status=AssessmentTaskStatus.QUEUED.value,
        reset=True,
    )
    await repo.set_run_status(
        uow,
        run.id,
        from_statuses=tuple(s.value for s in AssessmentRunStatus),
        status=AssessmentRunStatus.QUEUED.value,
        requeued=True,
    )
    await enqueue(uow, RunAssessment(run_id=run.id), opportunity_id=run.opportunity_id)
    await _trace_started(uow, run.id, run.opportunity_id, actor, agent_count=1)


async def _trace_started(
    uow: UnitOfWork, run_id: UUID, opportunity_id: UUID, actor: Actor, *, agent_count: int
) -> None:
    await trace.append(
        uow,
        actor=actor,
        payload=AssessmentsAssessmentRunStarted(agent_count=agent_count),
        subject_type=RUN_SUBJECT_TYPE,
        subject_id=run_id,
        opportunity_id=opportunity_id,
    )


async def fail_stale(uow: UnitOfWork, opportunity_id: UUID) -> None:
    """Fail the Opportunity's lost runs: their unfinished tasks `failed` / `model_timeout`
    (with no `finished_at`: when they stopped is unknown), then the run finished. The caller
    holds the Opportunity's run lock."""
    lost = await repo.stale_runs(uow, opportunity_id, older_than=stale_after())
    for run_id in lost:
        await repo.update_tasks(
            uow,
            run_id,
            from_statuses=_TASK_IN_PROGRESS,
            status=AssessmentTaskStatus.FAILED.value,
            error_code=RunErrorCode.MODEL_TIMEOUT.value,
        )
        await finish_run(uow, run_id)
    if lost:
        _log.info(
            "assessments.assessment_run_stale_failed",
            extra={"opportunity_id": str(opportunity_id), "count": len(lost)},
        )


async def finish_run(uow: UnitOfWork, run_id: UUID) -> AssessmentRunStatus | None:
    """When none of the run's tasks is left in progress, record the run's final status
    (from its tasks') and trace it; None (and no change) otherwise, or when it is already
    finished."""
    record = await repo.get_run(uow, run_id, for_update=True)
    if record is None or AssessmentRunStatus(record.status) not in RUN_IN_PROGRESS:
        return None
    tasks = await repo.tasks_of(uow, run_id)
    statuses = [AssessmentTaskStatus(t.status) for t in tasks]
    if any(s in TASK_IN_PROGRESS for s in statuses):
        return None
    status = run_status(statuses)
    await repo.set_run_status(
        uow, run_id, from_statuses=_RUN_IN_PROGRESS, status=status.value, finished=True
    )
    succeeded = sum(1 for s in statuses if s == AssessmentTaskStatus.SUCCEEDED)
    completed = AssessmentsAssessmentRunCompleted(
        status=status.value,
        task_count=len(statuses),
        succeeded_count=succeeded,
        failed_count=len(statuses) - succeeded,
    )
    await trace.append(
        uow,
        actor=_SYSTEM,
        payload=completed,
        subject_type=RUN_SUBJECT_TYPE,
        subject_id=run_id,
        opportunity_id=record.opportunity_id,
    )
    _log.info(
        "assessments.assessment_run_finished",
        extra={
            "run_id": str(run_id),
            "opportunity_id": str(record.opportunity_id),
            **completed.model_dump(),
        },
    )
    return status


# --- accepting ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssessedRequirement:
    """A Requirement the run read, with its prompt label `R<n>`."""

    label: str
    requirement_id: UUID
    version: int
    classification: str
    text: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class AssessmentInputs:
    """What the run read: the Requirements and the number of open Gaps."""

    requirements: Sequence[AssessedRequirement]
    gap_count: int = 0


def proposal(agent: AssessmentAgent, result: AgentResult) -> SpecialistOutput:
    """The agent's proposed Assessment, re-validated (AD-4). Raises `ModelOutputInvalidError`
    when the extension is missing or malformed."""
    raw = result.extensions.get(agent.value)
    try:
        return _SPECS[agent].output.model_validate(raw)
    except ValueError:
        raise ModelOutputInvalidError(f"The {agent.value} extension is not valid.") from None


def candidate(output: SpecialistOutput) -> AssessmentCandidate:
    return AssessmentCandidate(
        recommendation=output.recommendation,
        confidence=output.confidence,
        confidence_basis=output.confidence_basis,
        findings=[
            AssessmentFindingCandidate(
                kind=f.kind,
                severity=f.severity,
                title=f.title,
                detail=f.detail,
                requirements=tuple(f.requirements),
            )
            for f in output.findings
        ],
        effort=[
            EffortCandidate(requirement=e.requirement, hours=e.hours, basis=e.basis)
            for e in output.effort
        ],
    )


async def accept_assessment(
    uow: UnitOfWork,
    *,
    run_id: UUID,
    agent: AssessmentAgent,
    result: AgentResult,
    inputs: AssessmentInputs,
    actor: Actor,
) -> AssessmentValidation[tuple[UUID, int]] | None:
    """`assessments.accept_assessment`: validate the agent's reply and store it as the
    agent's new `current` Assessment of the Opportunity, superseding its earlier one; mark
    the task `succeeded` and trace it. Returns None (and writes nothing) unless the task is
    still `running`.

    Raises `ModelOutputInvalidError` (and writes nothing) when the recommendation or
    confidence is missing or invalid, or when no Finding is valid, so the task runs again.
    Invalid Findings and effort rows are dropped and counted."""
    task = await repo.get_task(uow, run_id, agent.value)
    record = await repo.get_run(uow, run_id)
    if task is None or record is None:
        return None
    await repo.lock_agent(uow, record.opportunity_id, agent.value)
    task = await repo.get_task(uow, run_id, agent.value, for_update=True)
    if task is None or task.status != AssessmentTaskStatus.RUNNING:
        return None
    ids = {"run_id": str(run_id), "opportunity_id": str(record.opportunity_id)}

    proposed = candidate(proposal(agent, result))
    current = {
        (s.id, s.version)
        for s in await intake.active_requirement_snapshots(uow, record.opportunity_id)
    }
    labels = {
        r.label: (r.requirement_id, r.version)
        for r in inputs.requirements
        if (r.requirement_id, r.version) in current
    }
    validation = validate_assessment(proposed, labels)
    if validation is None:
        _log.info("assessments.assessment_reply_invalid", extra={**ids, "agent": agent.value})
        raise ModelOutputInvalidError(f"The {agent.value} recommendation or confidence is invalid.")
    if not validation.findings:
        _log.info(
            "assessments.assessment_all_invalid",
            extra={**ids, "agent": agent.value, "dropped_count": validation.dropped},
        )
        raise ModelOutputInvalidError(f"No proposed {agent.value} Finding was valid.")

    superseded = await repo.supersede_assessments(uow, record.opportunity_id, agent.value)
    number = await repo.latest_assessment_number(uow, record.opportunity_id, agent.value) + 1
    assessment_id = new_id()
    await repo.insert_assessment(
        uow,
        assessment_id=assessment_id,
        opportunity_id=record.opportunity_id,
        agent=agent.value,
        version=number,
        run_id=run_id,
        recommendation=validation.recommendation.value,
        confidence=validation.confidence.value,
        confidence_basis=validation.confidence_basis,
        dropped_count=validation.dropped,
        findings=[
            repo.NewFinding(
                position=position,
                kind=f.kind.value,
                severity=f.severity.value,
                title=f.title,
                detail=f.detail,
                requirements=list(f.requirements),
            )
            for position, f in enumerate(validation.findings, start=1)
        ],
        effort=[
            repo.NewEffort(
                requirement_id=e.requirement[0],
                requirement_version=e.requirement[1],
                hours=e.hours,
                basis=e.basis,
            )
            for e in validation.effort
        ],
    )
    counts = severity_counts(f.severity for f in validation.findings)
    completed = AssessmentsAssessmentCompleted(
        run_id=str(run_id),
        agent=agent.value,
        version=number,
        recommendation=validation.recommendation.value,
        confidence=validation.confidence.value,
        finding_count=len(validation.findings),
        critical_count=counts[Severity.CRITICAL],
        high_count=counts[Severity.HIGH],
        medium_count=counts[Severity.MEDIUM],
        low_count=counts[Severity.LOW],
        effort_count=len(validation.effort),
        dropped_count=validation.dropped,
        requirement_count=len(inputs.requirements),
        gap_count=inputs.gap_count,
        superseded_count=superseded,
    )
    await trace.append(
        uow,
        actor=actor,
        payload=completed,
        subject_type=ASSESSMENT_SUBJECT_TYPE,
        subject_id=assessment_id,
        subject_version=number,
        opportunity_id=record.opportunity_id,
    )
    await repo.update_tasks(
        uow,
        run_id,
        agents=[agent.value],
        from_statuses=_RUNNING,
        status=AssessmentTaskStatus.SUCCEEDED.value,
        finished=True,
    )
    _log.info(
        "assessments.assessment_accepted",
        extra={**ids, "assessment_id": str(assessment_id), **completed.model_dump()},
    )
    return validation


# --- the handler ----------------------------------------------------------------------------


def error_code(exc: BaseException) -> RunErrorCode:
    """A task's `error_code` for the error that failed it."""
    if isinstance(exc, ModelTimeoutError):
        return RunErrorCode.MODEL_TIMEOUT
    if isinstance(exc, ModelOutputInvalidError):
        return RunErrorCode.OUTPUT_INVALID
    # The gateway unreachable or missing, or anything else that kept the model from
    # answering.
    return RunErrorCode.MODEL_UNAVAILABLE


async def _fail_open(ctx: JobContext, run_id: UUID, code: RunErrorCode) -> bool:
    """Mark the run's unfinished tasks `failed` with `code` and finish the run. True when a
    task changed."""
    async with unit_of_work(ctx.engine) as uow:
        record = await repo.get_run(uow, run_id)
        if record is None:
            return False
        await repo.lock_runs(uow, record.opportunity_id)
        failed = await repo.update_tasks(
            uow,
            run_id,
            from_statuses=_TASK_IN_PROGRESS,
            status=AssessmentTaskStatus.FAILED.value,
            error_code=code.value,
            finished=True,
        )
        await finish_run(uow, run_id)
        return bool(failed)


async def run_assessment(ctx: JobContext, payload: RunAssessment) -> None:
    """The handler. On the job's final attempt any error outside the agents' tasks first
    marks the unfinished tasks `failed` and finishes the run (best effort), so none is left
    `running` once its job is dead; then it re-raises."""
    ids = {"run_id": str(payload.run_id), "job_id": str(ctx.job_id)}
    try:
        await _run(ctx, payload)
    except asyncio.CancelledError:
        # The job's timeout (or a stopping worker) cancelled the run. On the final attempt
        # nothing will run it again, so record it as timed out, shielded from the
        # cancellation, then let the cancellation through.
        if ctx.attempt >= ctx.max_attempts:
            await _fail_open_shielded(ctx, payload.run_id, ids)
        raise
    except Exception as exc:
        code = error_code(exc)
        if ctx.attempt >= ctx.max_attempts:
            try:
                recorded = await _fail_open(ctx, payload.run_id, code)
            except Exception as mark_exc:  # e.g. the database is down: the job still dies
                _log.warning(
                    "assessments.assessment_fail_unrecorded",
                    extra={**ids, "exc_type": type(mark_exc).__name__},
                )
            else:
                _log.info(
                    "assessments.assessment_failed",
                    extra={**ids, "error_code": code.value, "recorded": recorded},
                )
        else:
            _log.warning(
                "assessments.assessment_retrying",
                extra={**ids, "exc_type": type(exc).__name__, "error_code": code.value},
            )
        raise


async def _fail_open_shielded(ctx: JobContext, run_id: UUID, ids: dict[str, str]) -> None:
    write = asyncio.ensure_future(_fail_open(ctx, run_id, RunErrorCode.MODEL_TIMEOUT))
    try:
        recorded = await asyncio.shield(write)
    except asyncio.CancelledError:  # cancelled again: still let the write land
        await asyncio.wait({write})
        recorded = not write.cancelled() and write.exception() is None and write.result()
    except Exception as exc:
        _log.warning(
            "assessments.assessment_fail_unrecorded",
            extra={**ids, "exc_type": type(exc).__name__},
        )
        return
    _log.info(
        "assessments.assessment_failed",
        extra={**ids, "error_code": RunErrorCode.MODEL_TIMEOUT.value, "recorded": recorded},
    )


@dataclass(frozen=True, slots=True)
class _Started:
    opportunity_id: UUID
    agents: tuple[AssessmentAgent, ...]
    inputs: AssessmentInputs
    gaps: list[GapBlock] = field(repr=False)


async def _start(ctx: JobContext, run_id: UUID) -> _Started | None:
    """Read the Opportunity's active Requirements and open Gaps, and mark the run and its
    unfinished tasks `running`; None if the run is no longer queued or running (a duplicate
    or late job)."""
    async with unit_of_work(ctx.engine) as uow:
        record = await repo.get_run(uow, run_id)
        if record is None:
            return None
        await repo.lock_runs(uow, record.opportunity_id)
        record = await repo.get_run(uow, run_id, for_update=True)
        if record is None or AssessmentRunStatus(record.status) not in RUN_IN_PROGRESS:
            return None
        snapshots = await intake.active_requirement_snapshots(uow, record.opportunity_id)
        open_gaps = await gaps.open_gap_summaries(uow, record.opportunity_id)
        started = await repo.update_tasks(
            uow,
            run_id,
            from_statuses=_TASK_IN_PROGRESS,
            status=AssessmentTaskStatus.RUNNING.value,
            started=True,
        )
        if not started:  # nothing left to do: finish what an earlier attempt left open
            await finish_run(uow, run_id)
            return None
        await repo.set_run_status(
            uow,
            run_id,
            from_statuses=_RUN_IN_PROGRESS,
            status=AssessmentRunStatus.RUNNING.value,
        )
        return _Started(
            opportunity_id=record.opportunity_id,
            agents=tuple(a for a in AGENTS if a.value in started),
            inputs=AssessmentInputs(
                requirements=[
                    AssessedRequirement(
                        label=f"R{s.number}",
                        requirement_id=s.id,
                        version=s.version,
                        classification=s.classification,
                        text=s.text,
                    )
                    for s in snapshots
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


async def _task(
    ctx: JobContext,
    run_id: UUID,
    agent: AssessmentAgent,
    started: _Started,
    settings: Settings,
) -> BaseException | None:
    """One agent's task: the model call, then acceptance in its own Unit of Work. Returns
    the error that failed it (None when it succeeded or was no longer running). On the final
    attempt a failed task is marked `failed`; before that it stays `running` for the next
    attempt."""
    ids = {"run_id": str(run_id), "agent": agent.value}
    profile = settings.model_profile_chat
    try:
        specialist = _SPECS[agent].build(provider.current(), profile)
        result = await specialist.run(
            SpecialistTask(
                opportunity_id=started.opportunity_id,
                run_id=run_id,
                requirements=[
                    RequirementBlock(r.label, r.classification, r.text)
                    for r in started.inputs.requirements
                ],
                gaps=started.gaps,
            )
        )
        async with unit_of_work(ctx.engine) as uow:
            accepted = await accept_assessment(
                uow,
                run_id=run_id,
                agent=agent,
                result=result,
                inputs=started.inputs,
                actor=agent_actor(agent, profile),
            )
        if accepted is None:
            _log.info("assessments.assessment_task_skipped", extra=ids)
        return None
    except Exception as exc:
        code = error_code(exc)
        if ctx.attempt >= ctx.max_attempts:
            async with unit_of_work(ctx.engine) as uow:
                await repo.update_tasks(
                    uow,
                    run_id,
                    agents=[agent.value],
                    from_statuses=_TASK_IN_PROGRESS,
                    status=AssessmentTaskStatus.FAILED.value,
                    error_code=code.value,
                    finished=True,
                )
            _log.info("assessments.assessment_task_failed", extra={**ids, "error_code": code.value})
        else:
            _log.warning(
                "assessments.assessment_task_retrying",
                extra={**ids, "exc_type": type(exc).__name__, "error_code": code.value},
            )
        return exc


async def _run(ctx: JobContext, payload: RunAssessment) -> None:
    settings = assessment_settings()
    run_id = payload.run_id
    ids: dict[str, object] = {"run_id": str(run_id)}
    started = await _start(ctx, run_id)
    if started is None:
        _log.info("assessments.assessment_run_skipped", extra=ids)
        return
    ids["opportunity_id"] = str(started.opportunity_id)

    if not started.inputs.requirements:  # nothing to assess: no model call, no Assessment
        async with unit_of_work(ctx.engine) as uow:
            await repo.lock_runs(uow, started.opportunity_id)
            await repo.update_tasks(
                uow,
                run_id,
                from_statuses=_RUNNING,
                status=AssessmentTaskStatus.SUCCEEDED.value,
                finished=True,
            )
            await finish_run(uow, run_id)
        _log.info("assessments.assessment_run_empty", extra=ids)
        return

    # `return_exceptions`: a task whose failure could not even be recorded (e.g. the database
    # dropped) must not abandon its siblings mid-call; its error is collected like theirs.
    errors = [
        error
        for error in await asyncio.gather(
            *(_task(ctx, run_id, agent, started, settings) for agent in started.agents),
            return_exceptions=True,
        )
        if error is not None
    ]
    if errors and ctx.attempt < ctx.max_attempts:
        raise errors[0]  # the queue runs the job again for the unfinished tasks
    async with unit_of_work(ctx.engine) as uow:
        await repo.lock_runs(uow, started.opportunity_id)
        await finish_run(uow, run_id)
    if errors:
        raise errors[0]  # recorded; the job ends dead, as its tasks did


RUN_ASSESSMENT_JOB = register(
    JobType(
        name=RUN_ASSESSMENT,
        payload=RunAssessment,
        handler=run_assessment,
        priority="background",
        # Above the worst case: (1 + PSA_MODEL_MAX_RETRIES) attempts of PSA_MODEL_TIMEOUT_S
        # (3 x 120 s) for each call, plus the wait for a model slot.
        timeout_s=900.0,
        max_attempts=2,
        backoff_base_s=15.0,
        backoff_cap_s=120.0,
    )
)
