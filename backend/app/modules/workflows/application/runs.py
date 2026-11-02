"""Workflow Runs (Story 5.2; moved from `assessments`, Epic 5 slice 5A and Stories 5.1, 5.5,
7.1): queueing, retry, cancel, finishing, and the `workflows.execute` job.

**Queueing.** `queue_run` inserts a `queued` run (plan version 1, stored in
`workflows_plan_versions`) with one `queued` task per specialist Agent (`engineering_agent`,
`pm_agent`, `security_agent`; none `requires` another, so they run concurrently), one
`critic_agent` task that runs `after` all of them, once each has ended whatever the outcome
(Story 6.4: the Critic reviews the Assessments the run accepted), and one job (background
priority). Each task pins its Agent's current config version from the Agent
Registry, active or not: a task whose Agent is `disabled` or `eval_only` asks a person when
its node is reached (Story 5.5, below). `enqueue_run` (Story 5.1: after every successful Gap
detection) queues one as the system, coalescing with a run already queued, running or
waiting for a person. `requeue_task` puts one `failed` task back to `queued` (Story 6.4: with
every ended task that runs `after` it, i.e. the Critic's, so the retried Assessment is
reviewed again) and enqueues a job for the run again (a fresh graph invocation on the same
thread runs only those tasks). The callers hold the Opportunity's run lock until commit.

**The job** (`workflows.execute`, one per run queueing; `workflows.resume` after a
person resolves a decision runs the same handler). Short Unit of Work: marks the run
`running` (nothing left: finishes it). Then, with no Unit of Work open, the graph runner the
worker installed (`install_runner`; only the worker imports `app.orchestration` and
`langgraph`) executes the run as a LangGraph graph checkpointed under `thread_id = run_id`:
one node per task, each re-reading its task here, starting it, calling its Agent and
submitting the result. A node whose Agent call fails reports the error and, on the job's
final attempt, marks its task `failed`; before that the task stays `running` for the next
attempt, which re-runs only unfinished tasks. When no task is left in progress the run is
finished: `succeeded`, `partially_failed` or `failed`, traced, and (when a specialist task
succeeded) the Estimate is built from the Assessments and the Conflict rules run (Stories 8.3, 6.1),
then the semantic Conflict detection is queued (Story 6.2).

A run stuck past `stale_after()` (its job died without recording it) is failed on the next
start, retry or cancel: its unfinished tasks `failed` / `model_timeout`.

**Waiting** (Story 5.5). A queued task whose Agent is `disabled` or `eval_only` records a
`plan_escalation` decision and its node interrupts the graph. When the graph returns with
an open decision and no task running, `_wait` marks the run `waiting_for_human` (a progress
row per open decision, and `workflows.run.waiting_for_human` traced once per decision) and
the job ends without error. A waiting run is never stale. Resolving the decision queues the
run again with a `workflows.resume` job, which resumes the checkpointed graph from the
interrupted node. `finish_run` and `cancel` close any decision still open.

**Cancelling** (Story 5.5). `cancel` marks the run's unfinished tasks `skipped`, its open
decisions `cancelled` and the run `cancelled` (also while it waits for a person). While the
graph works, the handler re-reads the run every `CANCEL_POLL_S` seconds and, once it is
`cancelled`, cancels the graph (its in-flight Agent calls release their model slots) and
ends without error; no node starts afterwards.

Every task start, task end, run queueing and run end also writes a progress row (and a
NOTIFY) in the same Unit of Work. Logs, trace, progress and `last_error` carry ids, codes
and counts only, never Requirement, Gap or Finding text.
"""

import asyncio
from collections.abc import Callable, Coroutine, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from app.modules.assessments.application import public as assessments
from app.modules.assessments.application.public import RunErrorCode
from app.modules.conflicts.application import public as conflicts
from app.modules.estimates.application import public as estimates
from app.modules.intake.application import public as intake
from app.modules.notifications.application import public as notifications
from app.modules.notifications.application.public import NotificationKind
from app.modules.opportunities.application import public as opportunities
from app.modules.registry.application import public as registry
from app.modules.workflows.adapters import repository as repo
from app.modules.workflows.adapters.repository import (
    ChangedTask,
    NewTask,
    PlanTask,
    RunRecord,
    TaskRecord,
)
from app.modules.workflows.application import progress
from app.modules.workflows.domain.runs import (
    DECISION_SUBJECT_TYPE,
    NON_AGENT_NODES,
    PLAN_VERSION,
    RUN_ACTIVE,
    RUN_IN_PROGRESS,
    RUN_SUBJECT_TYPE,
    TASK_IN_PROGRESS,
    AssessmentRunStatus,
    AssessmentTaskStatus,
    DecisionKind,
    DecisionStatus,
    RunType,
    TaskAgent,
    chosen_skip,
    decision_summary,
    run_status,
)
from app.platform import trace
from app.platform.actor import Actor
from app.platform.ids import new_id
from app.platform.jobs import JobContext, JobPayload, JobType, enqueue, register
from app.platform.logging import get_logger
from app.platform.model_gateway.port import ModelOutputInvalidError, ModelTimeoutError
from app.platform.trace.catalogue import (
    AssessmentsAssessmentRunCancelled,
    AssessmentsAssessmentRunCompleted,
    AssessmentsAssessmentRunStarted,
    WorkflowsRunWaitingForHuman,
)
from app.platform.uow import UnitOfWork, unit_of_work

EXECUTE = "workflows.execute"
RESUME = "workflows.resume"
_RUN_IN_PROGRESS = tuple(sorted(s.value for s in RUN_IN_PROGRESS))
_RUN_ACTIVE = tuple(sorted(s.value for s in RUN_ACTIVE))
_WAITING = (AssessmentRunStatus.WAITING_FOR_HUMAN.value,)
_TASK_IN_PROGRESS = tuple(sorted(s.value for s in TASK_IN_PROGRESS))
_RUNNING = (AssessmentTaskStatus.RUNNING.value,)
_QUEUED = (AssessmentTaskStatus.QUEUED.value,)
CANCEL_POLL_S = 2.0
"""How often the handler re-reads its run to notice a cancel while the graph works."""
SYSTEM = Actor(type="system", id=EXECUTE)
_log = get_logger(__name__)


class ExecuteRun(JobPayload):
    run_id: UUID


class ResumeRun(JobPayload):
    """Resume a run after a person resolved its decision (Story 5.5)."""

    run_id: UUID


# --- the graph runner hook ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GraphRun:
    """What the graph runner gets: ids and the job attempt, never customer content."""

    run_id: UUID
    opportunity_id: UUID
    engine: AsyncEngine
    attempt: int
    max_attempts: int

    @property
    def final_attempt(self) -> bool:
        return self.attempt >= self.max_attempts


GraphRunner = Callable[[GraphRun], Coroutine[Any, Any, Sequence[BaseException]]]
"""Executes the run's graph; returns the errors its tasks' Agent calls raised (empty when
none did). Installed by the worker (`app.orchestration.runner`)."""

_runner: GraphRunner | None = None


class NoGraphRunnerError(RuntimeError):
    """No graph runner is installed in this process (it isn't the worker)."""


def install_runner(runner: GraphRunner | None) -> None:
    """Make `runner` the process's graph runner (None removes it)."""
    global _runner
    _runner = runner


def current_runner() -> GraphRunner:
    if _runner is None:
        raise NoGraphRunnerError("No graph runner is installed in this process.")
    return _runner


# --- queueing -------------------------------------------------------------------------------


def stale_after() -> timedelta:
    """How long a run may stay `queued` or `running` after it was last queued before it is
    taken as lost (its job died without recording it): every attempt's timeout and the
    longest backoff before it, plus five minutes of queue slack."""
    spec = EXECUTE_JOB
    return timedelta(seconds=(spec.timeout_s + spec.backoff_cap_s) * spec.max_attempts + 300)


async def queue_run(
    uow: UnitOfWork,
    opportunity_id: UUID,
    actor: Actor,
    *,
    run_type: RunType = RunType.ASSESSMENT,
    trigger_ref: UUID | None = None,
    idempotency_key: str | None = None,
    agents: Sequence[str] | None = None,
) -> UUID:
    """Insert a `queued` run with one `queued` task per specialist Agent and the Critic's task
    after them (Story 6.4), its plan v1, its job, the trace event and a progress row. Each
    task pins its Agent's current config version, whatever the Agent's status: a task whose
    Agent is not active asks a person when its node starts (Story 5.5). Story 9.5: with
    `agents`, only those specialists are planned (a Challenge's confirmed Assessments), still
    followed by the Critic; `run_type`, `trigger_ref` and `idempotency_key` are stored on the
    run. The caller holds the Opportunity's run lock.

    Story 9.6: a `challenge` run plans the confirmed specialists, then `conflict_detection`
    (after them all), the Critic (after it) and `new_version` (after the Critic; it requires
    every specialist and Conflict detection to have succeeded), and its plan v1 records the
    pins (`challenge_pins`)."""
    run_id = new_id()
    tasks: list[NewTask] = []
    planned = set(agents) if agents is not None else None
    for agent in assessments.AGENTS:
        if planned is not None and agent.value not in planned:
            continue
        current = await registry.current_config(uow, agent.value)
        tasks.append(NewTask(id=new_id(), agent=agent.value, config_version_id=current.current.id))
    specialists = tuple(t.id for t in tasks)
    challenge = run_type == RunType.CHALLENGE
    if challenge:
        tasks.append(
            NewTask(
                id=new_id(),
                agent=TaskAgent.CONFLICT_DETECTION.value,
                config_version_id=None,
                after=specialists,
            )
        )
    conflict_ids = tuple(t.id for t in tasks if t.agent == TaskAgent.CONFLICT_DETECTION.value)
    critic = await registry.current_config(uow, assessments.CRITIC_AGENT)
    critic_task = NewTask(
        id=new_id(),
        agent=assessments.CRITIC_AGENT,
        config_version_id=critic.current.id,
        after=(tasks[-1].id,) if challenge else specialists,
    )
    tasks.append(critic_task)
    if challenge:
        tasks.append(
            NewTask(
                id=new_id(),
                agent=TaskAgent.NEW_VERSION.value,
                config_version_id=None,
                requires=(*specialists, *conflict_ids),
                after=(critic_task.id,),
            )
        )
    await repo.insert_run(
        uow,
        run_id=run_id,
        opportunity_id=opportunity_id,
        tasks=tasks,
        plan_version=PLAN_VERSION,
        run_type=run_type.value,
        trigger_ref=trigger_ref,
        idempotency_key=idempotency_key,
    )
    await repo.insert_plan_version(
        uow,
        run_id=run_id,
        version=PLAN_VERSION,
        tasks=[PlanTask(t.id, t.agent, t.config_version_id, t.after) for t in tasks],
        actor=actor,
        pins=await challenge_pins(uow, opportunity_id) if challenge else None,
    )
    await enqueue(uow, ExecuteRun(run_id=run_id), opportunity_id=opportunity_id)
    agent_count = sum(1 for t in tasks if t.agent not in NON_AGENT_NODES)
    await _trace_started(uow, run_id, opportunity_id, actor, agent_count=agent_count)
    await progress.run_changed(
        uow, opportunity_id=opportunity_id, run_id=run_id, status=AssessmentRunStatus.QUEUED
    )
    return run_id


async def challenge_pins(uow: UnitOfWork, opportunity_id: UUID) -> dict[str, Any]:
    """Story 9.6: what a challenge run's plan is made against: the active Requirements and
    the Sources at their versions, and the latest Estimate Version number (a newer one when
    the `new_version` node runs means the Estimate changed meanwhile)."""
    requirements = await intake.active_requirement_snapshots(uow, opportunity_id)
    sources = await intake.source_version_pins(uow, opportunity_id)
    return {
        "requirements": [{"id": str(r.id), "version": r.version} for r in requirements],
        "sources": [{"id": str(sid), "version": version} for sid, version in sources],
        "latest_estimate_version": await estimates.latest_version_number(uow, opportunity_id),
    }


async def enqueue_run(uow: UnitOfWork, opportunity_id: UUID) -> UUID:
    """Queue an assessment run of the Opportunity in the caller's Unit of Work, as the
    system, unless one of its runs is already queued, running or waiting for a person: then
    that run's id is returned and nothing added (a running run keeps the inputs it read; a
    waiting one is not rebuilt until someone resolves it). Lost runs are
    failed first. Never refuses with a conflict; any other error (e.g. the database) fails
    the caller's Unit of Work."""
    await repo.lock_runs(uow, opportunity_id)
    await fail_stale(uow, opportunity_id)
    ids = {"opportunity_id": str(opportunity_id)}
    active = await repo.run_active(uow, opportunity_id)
    if active is not None:
        _log.info("workflows.run_coalesced", extra={**ids, "run_id": str(active)})
        return active
    run_id = await queue_run(uow, opportunity_id, SYSTEM)
    _log.info("workflows.run_queued", extra={**ids, "run_id": str(run_id)})
    return run_id


async def requeue_task(uow: UnitOfWork, run: RunRecord, agent: str, actor: Actor) -> None:
    """Put the run's `failed` task of `agent` back to `queued`, with every succeeded or
    failed task that runs `after` it (Story 6.4: the Critic reviews the run again), queue the
    run again and enqueue a job for it. The caller holds the Opportunity's run lock and has
    checked the task is `failed`."""
    retried = await repo.update_tasks(
        uow,
        run.id,
        agents=[agent],
        from_statuses=(AssessmentTaskStatus.FAILED.value,),
        status=AssessmentTaskStatus.QUEUED.value,
        reset=True,
    )
    retried_ids = {t.id for t in retried}
    dependents = [
        t.id
        for t in await repo.tasks_of(uow, run.id)
        if retried_ids & set(t.after)
        and t.status in (AssessmentTaskStatus.SUCCEEDED, AssessmentTaskStatus.FAILED)
    ]
    if dependents:
        await repo.update_tasks(
            uow,
            run.id,
            task_ids=dependents,
            from_statuses=(
                AssessmentTaskStatus.SUCCEEDED.value,
                AssessmentTaskStatus.FAILED.value,
            ),
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
    await enqueue(uow, ExecuteRun(run_id=run.id), opportunity_id=run.opportunity_id)
    await _trace_started(
        uow, run.id, run.opportunity_id, actor, agent_count=len(retried) + len(dependents)
    )
    await progress.run_changed(
        uow, opportunity_id=run.opportunity_id, run_id=run.id, status=AssessmentRunStatus.QUEUED
    )


async def plan_tasks(uow: UnitOfWork, run_id: UUID) -> list[PlanTask]:
    return [
        PlanTask(t.id, t.agent, t.config_version_id, t.after)
        for t in await repo.tasks_of(uow, run_id)
    ]


async def queue_resume(uow: UnitOfWork, run: RunRecord) -> None:
    """Queue the waiting run again (`queued_at` now) with a `workflows.resume` job and its
    progress row. The caller holds the Opportunity's run lock and recorded the decision."""
    await repo.set_run_status(
        uow, run.id, from_statuses=_WAITING, status=AssessmentRunStatus.QUEUED.value, requeued=True
    )
    await enqueue(uow, ResumeRun(run_id=run.id), opportunity_id=run.opportunity_id)
    await progress.run_changed(
        uow, opportunity_id=run.opportunity_id, run_id=run.id, status=AssessmentRunStatus.QUEUED
    )


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


async def _tasks_ended(
    uow: UnitOfWork, run: RunRecord, changed: Sequence[ChangedTask], status: AssessmentTaskStatus
) -> None:
    for task in changed:
        await progress.task_changed(
            uow,
            opportunity_id=run.opportunity_id,
            run_id=run.id,
            task_id=task.id,
            agent=task.agent,
            status=status,
        )


async def cancel(uow: UnitOfWork, run: RunRecord, actor: Actor) -> tuple[int, int]:
    """Cancel the run: its unfinished tasks `skipped` (a started one keeps when it stopped,
    for its duration), its open decisions `cancelled`, the run `cancelled` and finished, the
    trace event and progress rows. Assessments already accepted stay current. The caller
    holds the Opportunity's run lock and has checked the run is queued, running or waiting.
    Returns (skipped, succeeded) task counts."""
    stopped = await repo.update_tasks(
        uow,
        run.id,
        from_statuses=_RUNNING,
        status=AssessmentTaskStatus.SKIPPED.value,
        finished=True,
    )
    unstarted = await repo.update_tasks(
        uow, run.id, from_statuses=_QUEUED, status=AssessmentTaskStatus.SKIPPED.value
    )
    await repo.set_run_status(
        uow,
        run.id,
        from_statuses=_RUN_ACTIVE,
        status=AssessmentRunStatus.CANCELLED.value,
        finished=True,
    )
    await repo.close_decisions(uow, run.id)
    await _tasks_ended(uow, run, [*stopped, *unstarted], AssessmentTaskStatus.SKIPPED)
    tasks = await repo.tasks_of(uow, run.id)
    succeeded = sum(1 for t in tasks if t.status == AssessmentTaskStatus.SUCCEEDED)
    skipped = len(stopped) + len(unstarted)
    assessed = _specialists_succeeded(tasks)
    await trace.append(
        uow,
        actor=actor,
        payload=AssessmentsAssessmentRunCancelled(skipped_count=skipped, succeeded_count=succeeded),
        subject_type=RUN_SUBJECT_TYPE,
        subject_id=run.id,
        opportunity_id=run.opportunity_id,
    )
    await progress.run_changed(
        uow,
        opportunity_id=run.opportunity_id,
        run_id=run.id,
        status=AssessmentRunStatus.CANCELLED,
    )
    if run.run_type == RunType.CHALLENGE:
        # Story 9.6: no Estimate is built; the Challenge fails and its version stays as it is.
        await _end_challenge(uow, run, tasks, AssessmentRunStatus.CANCELLED, actor=actor)
        return skipped, succeeded
    if assessed:
        # Story 8.3: the Assessments that completed before the cancel are current, so the
        # Estimate is built from them and the Conflicts re-checked, as `finish_run` does.
        await estimates.build_from_assessments(
            uow,
            run.opportunity_id,
            run.id,
            await assessments.current_sizings(uow, run.opportunity_id),
        )
        await detect_conflicts(uow, run.opportunity_id, run.id)
    return skipped, succeeded


async def fail_stale(uow: UnitOfWork, opportunity_id: UUID) -> None:
    """Fail the Opportunity's lost runs: their unfinished tasks `failed` / `model_timeout`
    (with no `finished_at`: when they stopped is unknown), then the run finished. The caller
    holds the Opportunity's run lock."""
    lost = await repo.stale_runs(uow, opportunity_id, older_than=stale_after())
    for run_id in lost:
        run = await repo.get_run(uow, run_id)
        changed = await repo.update_tasks(
            uow,
            run_id,
            from_statuses=_TASK_IN_PROGRESS,
            status=AssessmentTaskStatus.FAILED.value,
            error_code=RunErrorCode.MODEL_TIMEOUT.value,
        )
        if run is not None:
            await _tasks_ended(uow, run, changed, AssessmentTaskStatus.FAILED)
        await finish_run(uow, run_id)
    if lost:
        _log.info(
            "workflows.run_stale_failed",
            extra={"opportunity_id": str(opportunity_id), "count": len(lost)},
        )


async def finish_run(uow: UnitOfWork, run_id: UUID) -> AssessmentRunStatus | None:
    """When none of the run's tasks is left in progress, record the run's final status
    (from its tasks'), close any decision still open, trace it and write its progress row;
    None (and no change) otherwise, or when it is already finished (or waiting)."""
    record = await repo.get_run(uow, run_id, for_update=True)
    if record is None or AssessmentRunStatus(record.status) not in RUN_IN_PROGRESS:
        return None
    tasks = await repo.tasks_of(uow, run_id)
    statuses = [AssessmentTaskStatus(t.status) for t in tasks]
    if any(s in TASK_IN_PROGRESS for s in statuses):
        return None
    # Story 6.4: when the run finished before and only the Critic's task ran since (a Critic
    # retry), there is nothing new to build an Estimate from or detect Conflicts in.
    ended_before = await repo.last_run_end(uow, run_id)
    specialists_changed = ended_before is None or any(
        t.agent != assessments.CRITIC_AGENT
        and t.finished_at is not None
        and t.finished_at > ended_before
        for t in tasks
    )
    # A person's Continue without (Story 5.5) doesn't count against the run.
    chosen = sum(1 for t in tasks if chosen_skip(AssessmentTaskStatus(t.status), t.skip_reason))
    status = run_status(statuses, chosen_skips=chosen)
    if status == AssessmentRunStatus.PARTIALLY_FAILED and not _specialists_succeeded(tasks):
        # Only the Critic's task succeeded (Story 6.4): no Assessment came out of the run.
        status = AssessmentRunStatus.FAILED
    await repo.set_run_status(
        uow, run_id, from_statuses=_RUN_IN_PROGRESS, status=status.value, finished=True
    )
    await repo.close_decisions(uow, run_id)
    succeeded = sum(1 for s in statuses if s == AssessmentTaskStatus.SUCCEEDED)
    completed = AssessmentsAssessmentRunCompleted(
        status=status.value,
        task_count=len(statuses),
        succeeded_count=succeeded,
        failed_count=len(statuses) - succeeded - chosen,
    )
    await trace.append(
        uow,
        actor=SYSTEM,
        payload=completed,
        subject_type=RUN_SUBJECT_TYPE,
        subject_id=run_id,
        opportunity_id=record.opportunity_id,
    )
    await progress.run_changed(
        uow, opportunity_id=record.opportunity_id, run_id=run_id, status=status
    )
    _log.info(
        "workflows.run_finished",
        extra={
            "run_id": str(run_id),
            "opportunity_id": str(record.opportunity_id),
            **completed.model_dump(),
        },
    )
    if record.run_type == RunType.CHALLENGE:
        # Story 9.6: the run's own nodes detected the Conflicts and stored the new version.
        await _end_challenge(uow, record, tasks, status)
        return status
    if not specialists_changed:
        return status
    if _specialists_succeeded(tasks):
        # Story 8.3: the Estimate is built from the agents' current Assessments, before the
        # Conflict detection, which therefore compares against this new version. The
        # Critic's task (Story 6.4) stores no Assessment, so it doesn't count here.
        await estimates.build_from_assessments(
            uow,
            record.opportunity_id,
            run_id,
            await assessments.current_sizings(uow, record.opportunity_id),
        )
    await detect_conflicts(uow, record.opportunity_id, run_id)
    return status


async def _end_challenge(
    uow: UnitOfWork,
    run: RunRecord,
    tasks: Sequence[TaskRecord],
    status: AssessmentRunStatus,
    *,
    actor: Actor = SYSTEM,
) -> None:
    """Story 9.6: a challenge run ended. Unless its `new_version` node succeeded (which
    completed the Challenge), the Challenge fails: the run's status and the first error code
    (the node's first) are traced, and the owner and the challenger are told."""
    # Imported here: reviews starts challenge runs through this module's public API.
    from app.modules.reviews.application import public as reviews

    if run.trigger_ref is None:  # pragma: no cover - a challenge run always has its Challenge
        return
    node = next((t for t in tasks if t.agent == TaskAgent.NEW_VERSION.value), None)
    if node is not None and node.status == AssessmentTaskStatus.SUCCEEDED:
        return
    ordered = [t for t in (node, *tasks) if t is not None]
    code = next((t.error_code for t in ordered if t.error_code is not None), None)
    await reviews.fail_challenge(
        uow,
        run.trigger_ref,
        run_id=run.id,
        run_status=status.value,
        error_code=code,
        actor=actor,
    )


def _specialists_succeeded(tasks: Sequence[TaskRecord]) -> int:
    """How many specialist tasks succeeded (each stored an Assessment); the Critic's task is
    not one."""
    return sum(
        1
        for t in tasks
        if t.status == AssessmentTaskStatus.SUCCEEDED
        and t.agent not in (assessments.CRITIC_AGENT, *NON_AGENT_NODES)
    )


async def detect_conflicts(uow: UnitOfWork, opportunity_id: UUID, run_id: UUID) -> None:
    """Run the Conflict rules for the finished run (Story 6.1) over each agent's current
    Assessment and the current Estimate draft, read now; then queue the semantic detection
    of that pass (Story 6.2: when two agents have Findings and the Conflict Agent is
    active)."""
    snapshots = await assessments.current_assessment_snapshots(uow, opportunity_id)
    lines = await estimates.current_version_lines(uow, opportunity_id)
    estimate = (
        None
        if lines is None
        else conflicts.EstimateSnapshot(
            version_id=lines.version_id,
            version=lines.version,
            lines=tuple(
                conflicts.EstimateLineSnapshot(
                    effort_hours=line.effort_hours, requirement_ids=line.requirement_ids
                )
                for line in lines.lines
            ),
        )
    )
    detection = await conflicts.detect_for_run(uow, opportunity_id, run_id, snapshots, estimate)
    # Story 6.2: the Conflict Agent compares the Findings' free text afterwards, in a job.
    await conflicts.queue_semantic_detection(
        uow,
        opportunity_id=opportunity_id,
        run_id=run_id,
        detection_pass=detection.detection_pass,
    )


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


class RunIncompleteError(RuntimeError):
    """The graph ended with tasks still in progress and no error to report (e.g. a task
    waiting on one that will run again): the queue runs the job once more."""


async def _fail_open(ctx: JobContext, run_id: UUID, code: RunErrorCode) -> bool:
    """Mark the run's unfinished tasks `failed` with `code` and finish the run. True when a
    task changed. A cancelled run has no unfinished task and is already finished, so it is
    left alone; so is a run waiting for a person (its queued task waits on purpose)."""
    async with unit_of_work(ctx.engine) as uow:
        record = await repo.get_run(uow, run_id)
        if record is None:
            return False
        await repo.lock_runs(uow, record.opportunity_id)
        record = await repo.get_run(uow, run_id, for_update=True)
        if record is None or record.status == AssessmentRunStatus.WAITING_FOR_HUMAN:
            return False
        failed = await repo.update_tasks(
            uow,
            run_id,
            from_statuses=_TASK_IN_PROGRESS,
            status=AssessmentTaskStatus.FAILED.value,
            error_code=code.value,
            finished=True,
        )
        await _tasks_ended(uow, record, failed, AssessmentTaskStatus.FAILED)
        await finish_run(uow, run_id)
        return bool(failed)


async def execute_run(ctx: JobContext, payload: ExecuteRun) -> None:
    """The handler. On the job's final attempt any error outside the tasks first marks the
    unfinished tasks `failed` and finishes the run (best effort), so none is left `running`
    once its job is dead; then it re-raises."""
    ids = {"run_id": str(payload.run_id), "job_id": str(ctx.job_id)}
    try:
        await _execute(ctx, payload)
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
                    "workflows.run_fail_unrecorded",
                    extra={**ids, "exc_type": type(mark_exc).__name__},
                )
            else:
                _log.info(
                    "workflows.run_failed",
                    extra={**ids, "error_code": code.value, "recorded": recorded},
                )
        else:
            _log.warning(
                "workflows.run_retrying",
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
        _log.warning("workflows.run_fail_unrecorded", extra={**ids, "exc_type": type(exc).__name__})
        return
    _log.info(
        "workflows.run_failed",
        extra={**ids, "error_code": RunErrorCode.MODEL_TIMEOUT.value, "recorded": recorded},
    )


async def _start(ctx: JobContext, run_id: UUID) -> RunRecord | None:
    """Mark the run `running`; None if the run is no longer queued or running (a duplicate
    or late job, or the run waits for a person), or has no task left in progress (it is
    finished here)."""
    async with unit_of_work(ctx.engine) as uow:
        record = await repo.get_run(uow, run_id)
        if record is None:
            return None
        await repo.lock_runs(uow, record.opportunity_id)
        record = await repo.get_run(uow, run_id, for_update=True)
        if record is None or AssessmentRunStatus(record.status) not in RUN_IN_PROGRESS:
            return None
        tasks = await repo.tasks_of(uow, run_id)
        if not any(AssessmentTaskStatus(t.status) in TASK_IN_PROGRESS for t in tasks):
            await finish_run(uow, run_id)  # nothing left: finish what an attempt left open
            return None
        await repo.set_run_status(
            uow,
            run_id,
            from_statuses=_RUN_IN_PROGRESS,
            status=AssessmentRunStatus.RUNNING.value,
        )
        return record


async def _cancelled(ctx: JobContext, run_id: UUID) -> bool:
    """Whether the run has been cancelled (a short read, no lock)."""
    async with unit_of_work(ctx.engine) as uow:
        record = await repo.get_run(uow, run_id)
    return record is not None and record.status == AssessmentRunStatus.CANCELLED


async def _cancelled_or_unknown(ctx: JobContext, run_id: UUID) -> bool:
    """`_cancelled`, but a failed read is logged and taken as not cancelled, so the tasks'
    own errors (and their codes) still decide what happens to the job."""
    try:
        return await _cancelled(ctx, run_id)
    except Exception as exc:
        _log.warning(
            "workflows.cancel_check_failed",
            extra={"run_id": str(run_id), "exc_type": type(exc).__name__},
        )
        return False


async def _watch_cancel(ctx: JobContext, run_id: UUID, graph: asyncio.Task[Any]) -> bool:
    """Re-read the run every `CANCEL_POLL_S` seconds; once it is cancelled, cancel the graph
    (its in-flight Agent calls release their slots) and return True. A failed read is
    logged and tried again at the next tick."""
    while True:
        await asyncio.sleep(CANCEL_POLL_S)
        if await _cancelled_or_unknown(ctx, run_id):
            graph.cancel()
            return True


async def _wait(ctx: JobContext, run_id: UUID, opportunity_id: UUID) -> bool:
    """After the graph returned: when the run has an open decision and no task running,
    mark it `waiting_for_human` (from `running`), write a progress row per open decision and
    trace `workflows.run.waiting_for_human` once per decision. True when it now waits."""
    async with unit_of_work(ctx.engine) as uow:
        await repo.lock_runs(uow, opportunity_id)
        record = await repo.get_run(uow, run_id, for_update=True)
        if record is None or record.status != AssessmentRunStatus.RUNNING:
            return False
        tasks = {t.id: t for t in await repo.tasks_of(uow, run_id)}
        if any(t.status == AssessmentTaskStatus.RUNNING for t in tasks.values()):
            return False
        waiting = [
            (decision, tasks[decision.task_id])
            for decision in await repo.decisions_of(uow, run_id)
            if decision.status == DecisionStatus.OPEN
            and decision.task_id in tasks
            and tasks[decision.task_id].status == AssessmentTaskStatus.QUEUED
        ]
        if not waiting:
            return False
        await repo.set_run_status(
            uow,
            run_id,
            from_statuses=(AssessmentRunStatus.RUNNING.value,),
            status=AssessmentRunStatus.WAITING_FOR_HUMAN.value,
        )
        for decision, task in waiting:
            await _waiting_on(uow, record, decision.id, task)
    _log.info("workflows.run_waiting", extra={"run_id": str(run_id), "count": len(waiting)})
    return True


async def run_starter(uow: UnitOfWork, run_id: UUID) -> UUID | None:
    """Story 9.1: the user who started the run (its plan v1's creator), or None when the
    system queued it or the run is unknown. No authorization."""
    for plan in await repo.plan_versions_of(uow, run_id):
        if plan.version != 1 or plan.created_by_type != "user":
            continue
        try:
            return UUID(plan.created_by)
        except ValueError:
            return None
    return None


async def _notify_starter(
    uow: UnitOfWork, run: RunRecord, decision_id: UUID, task: TaskRecord
) -> None:
    """Story 9.2: the run's starter gets a `run_waiting` Inbox item, once per decision (key
    `decision:{id}`); the Opportunity's owner when the system queued the run."""
    recipient = await run_starter(uow, run.id) or await opportunities.opportunity_owner(
        uow, run.opportunity_id
    )
    if recipient is None:  # pragma: no cover - every run belongs to an Opportunity
        return
    titles = await opportunities.opportunity_titles(uow, {run.opportunity_id})
    await notifications.notify(
        uow,
        recipient_id=recipient,
        kind=NotificationKind.RUN_WAITING,
        opportunity_id=run.opportunity_id,
        subject_type=DECISION_SUBJECT_TYPE,
        subject_id=decision_id,
        subject_version=None,
        summary=decision_summary(task.agent, titles.get(run.opportunity_id)),
        dedupe_key=f"decision:{decision_id}",
    )


async def _waiting_on(uow: UnitOfWork, run: RunRecord, decision_id: UUID, task: TaskRecord) -> None:
    await progress.run_waiting(
        uow, opportunity_id=run.opportunity_id, run_id=run.id, task_id=task.id, agent=task.agent
    )
    await _notify_starter(uow, run, decision_id, task)
    if await repo.waiting_traced(uow, run.id, decision_id):
        return  # the run waits on it again (another decision was resolved meanwhile)
    await trace.append(
        uow,
        actor=SYSTEM,
        payload=WorkflowsRunWaitingForHuman(
            decision_id=str(decision_id),
            task_id=str(task.id),
            agent=task.agent,
            kind=DecisionKind.PLAN_ESCALATION.value,
        ),
        subject_type=RUN_SUBJECT_TYPE,
        subject_id=run.id,
        opportunity_id=run.opportunity_id,
    )


async def _unfinished(ctx: JobContext, run_id: UUID) -> int:
    async with unit_of_work(ctx.engine) as uow:
        tasks = await repo.tasks_of(uow, run_id)
    return sum(1 for t in tasks if AssessmentTaskStatus(t.status) in TASK_IN_PROGRESS)


async def _execute(ctx: JobContext, payload: ExecuteRun) -> None:
    run_id = payload.run_id
    ids: dict[str, object] = {"run_id": str(run_id)}
    started = await _start(ctx, run_id)
    if started is None:
        _log.info("workflows.run_skipped", extra=ids)
        return
    ids["opportunity_id"] = str(started.opportunity_id)
    runner = current_runner()
    request = GraphRun(
        run_id=run_id,
        opportunity_id=started.opportunity_id,
        engine=ctx.engine,
        attempt=ctx.attempt,
        max_attempts=ctx.max_attempts,
    )
    graph: asyncio.Task[Sequence[BaseException]] = asyncio.create_task(runner(request))
    watcher = asyncio.create_task(_watch_cancel(ctx, run_id, graph))
    try:
        await asyncio.wait({graph})
    finally:
        if not graph.done():  # this job itself is being cancelled (timeout, worker stop)
            graph.cancel()
            await asyncio.wait({graph})
        watcher.cancel()
        await asyncio.wait({watcher})
    stopped = not watcher.cancelled() and watcher.exception() is None and watcher.result()
    if stopped:
        # Cancelled by a person: the cancel already recorded the run; nothing to retry.
        _log.info("workflows.run_cancelled_stopped", extra=ids)
        return
    errors: list[BaseException]
    if graph.cancelled():  # not by the watcher: take it as unfinished work
        errors = [RunIncompleteError("graph cancelled")]
    elif graph.exception() is not None:  # the runner itself failed (e.g. the checkpointer)
        errors = [graph.exception()]  # type: ignore[list-item]
    else:
        errors = list(graph.result())
    if await _wait(ctx, run_id, started.opportunity_id):
        # Paused for a person (Story 5.5): resolving the decision resumes it.
        _log.info("workflows.run_paused", extra=ids)
        return
    unfinished = await _unfinished(ctx, run_id)
    if (errors or unfinished) and ctx.attempt < ctx.max_attempts:
        if await _cancelled_or_unknown(ctx, run_id):  # cancelled meanwhile: no retry
            _log.info("workflows.run_cancelled_stopped", extra=ids)
            return
        # The queue runs the job again: a fresh invocation re-runs only unfinished tasks.
        raise errors[0] if errors else RunIncompleteError("tasks still in progress")
    if unfinished:  # final attempt: nothing will run them again
        code = error_code(errors[0]) if errors else RunErrorCode.MODEL_UNAVAILABLE
        await _fail_open(ctx, run_id, code)
    async with unit_of_work(ctx.engine) as uow:
        await repo.lock_runs(uow, started.opportunity_id)
        await finish_run(uow, run_id)
    if errors:
        if await _cancelled_or_unknown(ctx, run_id):  # cancelled meanwhile: not dead
            _log.info("workflows.run_cancelled_stopped", extra=ids)
            return
        raise errors[0]  # recorded; the job ends dead, as its tasks did


EXECUTE_JOB = register(
    JobType(
        name=EXECUTE,
        payload=ExecuteRun,
        handler=execute_run,
        priority="background",
        # Above the worst case: (1 + PSA_MODEL_MAX_RETRIES) attempts of PSA_MODEL_TIMEOUT_S
        # (3 x 120 s) for each call, plus the wait for a model slot.
        timeout_s=900.0,
        max_attempts=2,
        backoff_base_s=15.0,
        backoff_cap_s=120.0,
    )
)


async def resume_run(ctx: JobContext, payload: ResumeRun) -> None:
    """The `workflows.resume` handler (Story 5.5): the execute handler for the run, whose
    graph runner resumes the interrupted thread with the decisions' choices."""
    await execute_run(ctx, ExecuteRun(run_id=payload.run_id))


RESUME_JOB = register(
    JobType(
        name=RESUME,
        payload=ResumeRun,
        handler=resume_run,
        priority="background",
        timeout_s=EXECUTE_JOB.timeout_s,
        max_attempts=EXECUTE_JOB.max_attempts,
        backoff_base_s=EXECUTE_JOB.backoff_base_s,
        backoff_cap_s=EXECUTE_JOB.backoff_cap_s,
    )
)
