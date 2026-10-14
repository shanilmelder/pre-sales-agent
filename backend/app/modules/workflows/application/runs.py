"""Workflow Runs (Story 5.2; moved from `assessments`, Epic 5 slice 5A and Stories 5.1, 5.5,
7.1): queueing, retry, cancel, finishing, and the `workflows.execute` job.

**Queueing.** `queue_run` inserts a `queued` run (plan version 1) with one `queued` task per
specialist Agent (`engineering_agent`, `pm_agent`, `security_agent`; none `requires`
another, so they run concurrently) and one job (background priority). Each task pins its
Agent's current config version from the Agent Registry; a task whose Agent is `disabled` or
`eval_only` is inserted `skipped` (`agent_disabled`, traced). `enqueue_run` (Story 5.1:
after every successful Gap detection) queues one as the system, coalescing with a run
already queued or running. `requeue_task` puts one `failed` task back to `queued` and
enqueues a job for the run again (a fresh graph invocation on the same thread runs only that
task). The callers hold the Opportunity's run lock until commit.

**The job** (`workflows.execute`, one per run queueing). Short Unit of Work: skips the
tasks still `queued` whose Agent is no longer active and marks the run `running` (nothing
left: finishes it). Then, with no Unit of Work open, the graph runner the worker installed
(`install_runner`; only the worker imports `app.orchestration` and `langgraph`) executes the
run as a LangGraph graph checkpointed under `thread_id = run_id`: one node per task, each
re-reading its task here, starting it, calling its Agent and submitting the result. A node
whose Agent call fails reports the error and, on the job's final attempt, marks its task
`failed`; before that the task stays `running` for the next attempt, which re-runs only
unfinished tasks. When no task is left in progress the run is finished: `succeeded`,
`partially_failed` or `failed`, traced, and (when a task succeeded) the Estimate is built
from the Assessments and the Conflict rules run (Stories 8.3, 6.1).

A run stuck past `stale_after()` (its job died without recording it) is failed on the next
start, retry or cancel: its unfinished tasks `failed` / `model_timeout`.

**Cancelling** (Story 5.5). `cancel` marks the run's unfinished tasks `skipped` and the run
`cancelled`. While the graph works, the handler re-reads the run every `CANCEL_POLL_S`
seconds and, once it is `cancelled`, cancels the graph (its in-flight Agent calls release
their model slots) and ends without error; no node starts afterwards.

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
from app.modules.registry.application import public as registry
from app.modules.workflows.adapters import repository as repo
from app.modules.workflows.adapters.repository import ChangedTask, NewTask, RunRecord
from app.modules.workflows.application import progress
from app.modules.workflows.domain.runs import (
    PLAN_VERSION,
    RUN_IN_PROGRESS,
    RUN_SUBJECT_TYPE,
    TASK_IN_PROGRESS,
    AssessmentRunStatus,
    AssessmentTaskStatus,
    TaskSkipReason,
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
    AssessmentsTaskSkipped,
)
from app.platform.uow import UnitOfWork, unit_of_work

EXECUTE = "workflows.execute"
_RUN_IN_PROGRESS = tuple(sorted(s.value for s in RUN_IN_PROGRESS))
_TASK_IN_PROGRESS = tuple(sorted(s.value for s in TASK_IN_PROGRESS))
_RUNNING = (AssessmentTaskStatus.RUNNING.value,)
_QUEUED = (AssessmentTaskStatus.QUEUED.value,)
CANCEL_POLL_S = 2.0
"""How often the handler re-reads its run to notice a cancel while the graph works."""
SYSTEM = Actor(type="system", id=EXECUTE)
_log = get_logger(__name__)


class ExecuteRun(JobPayload):
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


async def queue_run(uow: UnitOfWork, opportunity_id: UUID, actor: Actor) -> UUID:
    """Insert a `queued` run with one task per specialist Agent, its job, the trace event and
    a progress row. Each task pins its Agent's current config version; an Agent that is not
    active gets a `skipped` task (`agent_disabled`, traced). The caller holds the
    Opportunity's run lock."""
    run_id = new_id()
    tasks: list[NewTask] = []
    for agent in assessments.AGENTS:
        current = await registry.current_config(uow, agent.value)
        tasks.append(
            NewTask(
                id=new_id(),
                agent=agent.value,
                config_version_id=current.current.id,
                skip_reason=None if current.runs_tasks else TaskSkipReason.AGENT_DISABLED.value,
            )
        )
    await repo.insert_run(
        uow, run_id=run_id, opportunity_id=opportunity_id, tasks=tasks, plan_version=PLAN_VERSION
    )
    await enqueue(uow, ExecuteRun(run_id=run_id), opportunity_id=opportunity_id)
    await _trace_started(uow, run_id, opportunity_id, actor, agent_count=len(tasks))
    for task in tasks:
        if task.skip_reason is not None:
            await _trace_skipped(
                uow,
                run_id,
                opportunity_id,
                actor,
                task_id=task.id,
                agent=task.agent,
                config_version_id=task.config_version_id,
            )
    await progress.run_changed(
        uow, opportunity_id=opportunity_id, run_id=run_id, status=AssessmentRunStatus.QUEUED
    )
    return run_id


async def _trace_skipped(
    uow: UnitOfWork,
    run_id: UUID,
    opportunity_id: UUID,
    actor: Actor,
    *,
    task_id: UUID,
    agent: str,
    config_version_id: UUID,
) -> None:
    await trace.append(
        uow,
        actor=actor,
        payload=AssessmentsTaskSkipped(
            run_id=str(run_id),
            task_id=str(task_id),
            agent=agent,
            config_version_id=str(config_version_id),
            reason=TaskSkipReason.AGENT_DISABLED.value,
        ),
        subject_type=RUN_SUBJECT_TYPE,
        subject_id=run_id,
        opportunity_id=opportunity_id,
    )
    _log.info(
        "workflows.task_skipped_disabled",
        extra={"run_id": str(run_id), "agent": agent, "config_version_id": str(config_version_id)},
    )


async def enqueue_run(uow: UnitOfWork, opportunity_id: UUID) -> UUID:
    """Queue an assessment run of the Opportunity in the caller's Unit of Work, as the
    system, unless one of its runs is already queued or running: then that run's id is
    returned and nothing added (a running run keeps the inputs it read). Lost runs are
    failed first. Never refuses with a conflict; any other error (e.g. the database) fails
    the caller's Unit of Work."""
    await repo.lock_runs(uow, opportunity_id)
    await fail_stale(uow, opportunity_id)
    ids = {"opportunity_id": str(opportunity_id)}
    active = await repo.run_in_progress(uow, opportunity_id)
    if active is not None:
        _log.info("workflows.run_coalesced", extra={**ids, "run_id": str(active)})
        return active
    run_id = await queue_run(uow, opportunity_id, SYSTEM)
    _log.info("workflows.run_queued", extra={**ids, "run_id": str(run_id)})
    return run_id


async def requeue_task(uow: UnitOfWork, run: RunRecord, agent: str, actor: Actor) -> None:
    """Put the run's `failed` task of `agent` back to `queued`, queue the run again and
    enqueue a job for it. The caller holds the Opportunity's run lock and has checked the
    task is `failed`."""
    await repo.update_tasks(
        uow,
        run.id,
        agents=[agent],
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
    await enqueue(uow, ExecuteRun(run_id=run.id), opportunity_id=run.opportunity_id)
    await _trace_started(uow, run.id, run.opportunity_id, actor, agent_count=1)
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
    for its duration), the run `cancelled` and finished, the trace event and progress rows.
    Assessments already accepted stay current. The caller holds the Opportunity's run lock
    and has checked the run is queued or running. Returns (skipped, succeeded) task counts."""
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
        from_statuses=_RUN_IN_PROGRESS,
        status=AssessmentRunStatus.CANCELLED.value,
        finished=True,
    )
    await _tasks_ended(uow, run, [*stopped, *unstarted], AssessmentTaskStatus.SKIPPED)
    tasks = await repo.tasks_of(uow, run.id)
    succeeded = sum(1 for t in tasks if t.status == AssessmentTaskStatus.SUCCEEDED)
    skipped = len(stopped) + len(unstarted)
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
    if succeeded:
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
    (from its tasks'), trace it and write its progress row; None (and no change) otherwise,
    or when it is already finished."""
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
    if succeeded:
        # Story 8.3: the Estimate is built from the agents' current Assessments, before the
        # Conflict detection, which therefore compares against this new version.
        await estimates.build_from_assessments(
            uow,
            record.opportunity_id,
            run_id,
            await assessments.current_sizings(uow, record.opportunity_id),
        )
    await detect_conflicts(uow, record.opportunity_id, run_id)
    return status


async def detect_conflicts(uow: UnitOfWork, opportunity_id: UUID, run_id: UUID) -> None:
    """Run the Conflict rules for the finished run (Story 6.1) over each agent's current
    Assessment and the current Estimate draft, read now."""
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
    await conflicts.detect_for_run(uow, opportunity_id, run_id, snapshots, estimate)


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
    left alone."""
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


async def _skip_disabled(uow: UnitOfWork, run: RunRecord) -> None:
    """Skip the run's tasks still `queued` whose Agent is no longer active in the Agent
    Registry (`agent_disabled`, traced as the system). Running tasks finish."""
    for task in await repo.tasks_of(uow, run.id):
        if task.status != AssessmentTaskStatus.QUEUED:
            continue
        current = await registry.current_config(uow, task.agent)
        if current.runs_tasks:
            continue
        skipped = await repo.update_tasks(
            uow,
            run.id,
            task_ids=[task.id],
            from_statuses=_QUEUED,
            status=AssessmentTaskStatus.SKIPPED.value,
            skip_reason=TaskSkipReason.AGENT_DISABLED.value,
        )
        if skipped:
            await _tasks_ended(uow, run, skipped, AssessmentTaskStatus.SKIPPED)
            await _trace_skipped(
                uow,
                run.id,
                run.opportunity_id,
                SYSTEM,
                task_id=task.id,
                agent=task.agent,
                config_version_id=task.config_version_id,
            )


async def _start(ctx: JobContext, run_id: UUID) -> RunRecord | None:
    """Mark the run `running` after skipping the tasks whose Agent is no longer active; None
    if the run is no longer queued or running (a duplicate or late job), or has no task
    left in progress (it is finished here)."""
    async with unit_of_work(ctx.engine) as uow:
        record = await repo.get_run(uow, run_id)
        if record is None:
            return None
        await repo.lock_runs(uow, record.opportunity_id)
        record = await repo.get_run(uow, run_id, for_update=True)
        if record is None or AssessmentRunStatus(record.status) not in RUN_IN_PROGRESS:
            return None
        await _skip_disabled(uow, record)
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
