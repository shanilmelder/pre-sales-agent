"""Task commands and queries for the graph's nodes (Story 5.2). With the run commands in
`runs.py`, these are the only writers of task status (AD-6).

A node (`app.orchestration`) re-reads its task through `node_task`, starts it with
`begin_task` (skipped when it is no longer queued or running, its run is no longer in
progress, or a task it requires has not succeeded yet), calls its Agent outside any Unit of
Work, then, in one Unit of Work, locks it with `lock_running_task` (None once a cancel or a
lost-run failure moved it on: the reply is discarded), submits the result to its owner's
`accept_*` and marks it done with `complete_task`. On a job's final attempt a failed call
marks it `failed` (`fail_task`); a task whose required task ended without succeeding is
skipped (`skip_blocked_task`). Each change writes a progress row.
"""

from dataclasses import dataclass
from uuid import UUID

from app.modules.workflows.adapters import repository as repo
from app.modules.workflows.adapters.repository import TaskRecord
from app.modules.workflows.application import progress
from app.modules.workflows.domain.runs import (
    RUN_IN_PROGRESS,
    TASK_IN_PROGRESS,
    AssessmentRunStatus,
    AssessmentTaskStatus,
    Readiness,
    readiness,
)
from app.platform.uow import UnitOfWork

_TASK_IN_PROGRESS = tuple(sorted(s.value for s in TASK_IN_PROGRESS))
_RUNNING = (AssessmentTaskStatus.RUNNING.value,)
_QUEUED = (AssessmentTaskStatus.QUEUED.value,)


@dataclass(frozen=True, slots=True)
class NodeTask:
    """A task as its node sees it: ids, statuses and whether it may start."""

    id: UUID
    run_id: UUID
    opportunity_id: UUID
    agent: str
    config_version_id: UUID
    status: AssessmentTaskStatus
    run_status: AssessmentRunStatus
    readiness: Readiness
    requires: tuple[UUID, ...] = ()

    @property
    def pending(self) -> bool:
        """Still to be worked on: the task queued or running, in a run in progress."""
        return self.status in TASK_IN_PROGRESS and self.run_status in RUN_IN_PROGRESS


async def _node_task(uow: UnitOfWork, task: TaskRecord) -> NodeTask | None:
    run = await repo.get_run(uow, task.run_id)
    if run is None:
        return None
    statuses = {
        t.id: AssessmentTaskStatus(t.status)
        for t in await repo.tasks_of(uow, task.run_id)
        if t.id in task.requires
    }
    return NodeTask(
        id=task.id,
        run_id=task.run_id,
        opportunity_id=run.opportunity_id,
        agent=task.agent,
        config_version_id=task.config_version_id,
        status=AssessmentTaskStatus(task.status),
        run_status=AssessmentRunStatus(run.status),
        readiness=readiness(task.requires, statuses),
        requires=task.requires,
    )


async def node_task(uow: UnitOfWork, task_id: UUID) -> NodeTask | None:
    """The task's current truth (a re-read; no lock)."""
    task = await repo.get_task_by_id(uow, task_id)
    return None if task is None else await _node_task(uow, task)


async def begin_task(uow: UnitOfWork, task_id: UUID) -> NodeTask | None:
    """Mark the task `running` (stamping `started_at`) if it is pending and every task it
    requires succeeded. None (and no change) otherwise."""
    current = await node_task(uow, task_id)
    if current is None or not current.pending or current.readiness != "ready":
        return None
    changed = await repo.update_tasks(
        uow,
        current.run_id,
        task_ids=[task_id],
        from_statuses=_TASK_IN_PROGRESS,
        status=AssessmentTaskStatus.RUNNING.value,
        started=True,
    )
    if not changed:
        return None
    await progress.task_changed(
        uow,
        opportunity_id=current.opportunity_id,
        run_id=current.run_id,
        task_id=task_id,
        agent=current.agent,
        status=AssessmentTaskStatus.RUNNING,
    )
    return await node_task(uow, task_id)


async def lock_running_task(uow: UnitOfWork, task_id: UUID) -> NodeTask | None:
    """Lock the task until commit if it is still `running`; None otherwise (a cancel or a
    lost-run failure moved it on, so a late result is discarded)."""
    task = await repo.get_task_by_id(uow, task_id, for_update=True)
    if task is None or task.status != AssessmentTaskStatus.RUNNING:
        return None
    return await _node_task(uow, task)


async def _end(
    uow: UnitOfWork,
    task_id: UUID,
    *,
    from_statuses: tuple[str, ...],
    status: AssessmentTaskStatus,
    error_code: str | None = None,
    finished: bool = True,
) -> bool:
    task = await repo.get_task_by_id(uow, task_id)
    if task is None:
        return False
    run = await repo.get_run(uow, task.run_id)
    if run is None:
        return False
    changed = await repo.update_tasks(
        uow,
        task.run_id,
        task_ids=[task_id],
        from_statuses=from_statuses,
        status=status.value,
        error_code=error_code,
        finished=finished,
    )
    if not changed:
        return False
    await progress.task_changed(
        uow,
        opportunity_id=run.opportunity_id,
        run_id=run.id,
        task_id=task_id,
        agent=task.agent,
        status=status,
    )
    return True


async def complete_task(uow: UnitOfWork, task_id: UUID) -> bool:
    """`running` → `succeeded` (stamping `finished_at`). False (and no change) otherwise."""
    return await _end(uow, task_id, from_statuses=_RUNNING, status=AssessmentTaskStatus.SUCCEEDED)


async def fail_task(uow: UnitOfWork, task_id: UUID, error_code: str) -> bool:
    """Queued or running → `failed` with `error_code`. False (and no change) otherwise."""
    return await _end(
        uow,
        task_id,
        from_statuses=_TASK_IN_PROGRESS,
        status=AssessmentTaskStatus.FAILED,
        error_code=error_code,
    )


async def skip_blocked_task(uow: UnitOfWork, task_id: UUID) -> bool:
    """`queued` → `skipped` when a task it requires ended without succeeding (it never
    started, so it has no duration). False (and no change) otherwise."""
    current = await node_task(uow, task_id)
    if current is None or not current.pending or current.readiness != "blocked":
        return False
    return await _end(
        uow, task_id, from_statuses=_QUEUED, status=AssessmentTaskStatus.SKIPPED, finished=False
    )
