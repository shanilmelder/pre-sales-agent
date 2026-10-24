"""Task commands and queries for the graph's nodes (Story 5.2). With the run commands in
`runs.py`, these are the only writers of task status (AD-6).

A node (`app.orchestration`) re-reads its task through `node_task`, starts it with
`begin_task` (skipped when it is no longer queued or running, its run is no longer in
progress, a task it requires has not succeeded yet, or, Story 6.4, a task it runs `after`
has not ended yet), calls its Agent outside any Unit of
Work, then, in one Unit of Work, locks it with `lock_running_task` (None once a cancel or a
lost-run failure moved it on: the reply is discarded), submits the result to its owner's
`accept_*` and marks it done with `complete_task`. On a job's final attempt a failed call
marks it `failed` (`fail_task`); a task whose required task ended without succeeding is
skipped (`skip_blocked_task`). Each change writes a progress row.

Before starting a queued task the node asks `escalation` (Story 5.5): the task's
`plan_escalation` decision, recorded `open` (idempotently) when its Agent is `disabled` or
`eval_only` and none exists yet. The decision row is the truth on every resume: open, the
node interrupts; resolved **Continue without**, the task is skipped (`skip_disabled_task`,
`agent_disabled`); resolved **Re-plan**, the task runs (re-pinned by the resolve).
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.registry.application import public as registry
from app.modules.workflows.adapters import repository as repo
from app.modules.workflows.adapters.repository import TaskRecord
from app.modules.workflows.application import progress
from app.modules.workflows.domain.runs import (
    PLAN_ESCALATION_CHOICES,
    RUN_IN_PROGRESS,
    RUN_SUBJECT_TYPE,
    TASK_IN_PROGRESS,
    AssessmentRunStatus,
    AssessmentTaskStatus,
    DecisionChoice,
    DecisionKind,
    DecisionStatus,
    Readiness,
    TaskSkipReason,
    readiness,
)
from app.platform import trace
from app.platform.actor import Actor
from app.platform.ids import new_id
from app.platform.logging import get_logger
from app.platform.trace.catalogue import AssessmentsTaskSkipped
from app.platform.uow import UnitOfWork

_TASK_IN_PROGRESS = tuple(sorted(s.value for s in TASK_IN_PROGRESS))
_RUNNING = (AssessmentTaskStatus.RUNNING.value,)
_QUEUED = (AssessmentTaskStatus.QUEUED.value,)
SYSTEM = Actor(type="system", id="workflows.execute")
_log = get_logger(__name__)


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
    after: tuple[UUID, ...] = ()

    @property
    def pending(self) -> bool:
        """Still to be worked on: the task queued or running, in a run in progress."""
        return self.status in TASK_IN_PROGRESS and self.run_status in RUN_IN_PROGRESS


async def _node_task(uow: UnitOfWork, task: TaskRecord) -> NodeTask | None:
    run = await repo.get_run(uow, task.run_id)
    if run is None:
        return None
    depends = set(task.requires) | set(task.after)
    statuses = {
        t.id: AssessmentTaskStatus(t.status)
        for t in await repo.tasks_of(uow, task.run_id)
        if t.id in depends
    }
    return NodeTask(
        id=task.id,
        run_id=task.run_id,
        opportunity_id=run.opportunity_id,
        agent=task.agent,
        config_version_id=task.config_version_id,
        status=AssessmentTaskStatus(task.status),
        run_status=AssessmentRunStatus(run.status),
        readiness=readiness(task.requires, statuses, task.after),
        requires=task.requires,
        after=task.after,
    )


async def node_task(uow: UnitOfWork, task_id: UUID) -> NodeTask | None:
    """The task's current truth (a re-read; no lock)."""
    task = await repo.get_task_by_id(uow, task_id)
    return None if task is None else await _node_task(uow, task)


async def begin_task(uow: UnitOfWork, task_id: UUID) -> NodeTask | None:
    """Mark the task `running` (stamping `started_at`) if it is pending, every task it
    requires succeeded and every task it runs after has ended. None (and no change)
    otherwise."""
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
    skip_reason: str | None = None,
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
        skip_reason=skip_reason,
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


# --- escalation (Story 5.5) -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Escalation:
    """A queued task's `plan_escalation` decision as its node sees it. `payload`: what the
    node interrupts with (ids and codes only)."""

    decision_id: UUID
    status: DecisionStatus
    choice: DecisionChoice | None
    payload: dict[str, Any]

    @property
    def open(self) -> bool:
        return self.status == DecisionStatus.OPEN


def _escalation(decision: repo.DecisionRecord) -> Escalation:
    return Escalation(
        decision_id=decision.id,
        status=DecisionStatus(decision.status),
        choice=None if decision.choice is None else DecisionChoice(decision.choice),
        payload=decision.payload,
    )


async def escalation(uow: UnitOfWork, task_id: UUID) -> Escalation | None:
    """The decision about a queued task's Agent: the one recorded (whatever the Agent's
    status now: the row is the truth; but a `cancelled` one, closed when its run ended, is
    passed over once the Agent is active again, so a retried task runs), else a new `open`
    one when the Agent is `disabled` or `eval_only` (insert on conflict do nothing, so a node
    run again records nothing twice), else None (the task runs)."""
    task = await repo.get_task_by_id(uow, task_id)
    if task is None or task.status != AssessmentTaskStatus.QUEUED:
        return None
    kind = DecisionKind.PLAN_ESCALATION.value
    found = await repo.task_decision(uow, task_id, kind)
    active = (await registry.current_config(uow, task.agent)).runs_tasks
    if found is not None and found.status == DecisionStatus.CANCELLED and active:
        # Closed unresolved when its run ended (e.g. failed on the job's final attempt); the
        # task was retried once its Agent is active again, so it runs.
        return None
    if found is not None:
        return _escalation(found)
    if active:
        return None
    decision_id = new_id()
    recorded = await repo.record_decision(
        uow,
        decision_id=decision_id,
        run_id=task.run_id,
        task_id=task_id,
        kind=kind,
        payload={
            "decision_id": str(decision_id),
            "kind": kind,
            "run_id": str(task.run_id),
            "task_id": str(task_id),
            "agent": task.agent,
            "choices": [c.value for c in PLAN_ESCALATION_CHOICES],
        },
    )
    return _escalation(recorded)


async def decision_choices(uow: UnitOfWork, decision_ids: list[UUID]) -> dict[UUID, str]:
    """The choices of the resolved decisions among `decision_ids` (for resuming a graph's
    interrupts)."""
    found = await repo.decisions_by_id(uow, decision_ids)
    return {
        decision_id: decision.choice
        for decision_id, decision in found.items()
        if decision.status == DecisionStatus.RESOLVED and decision.choice is not None
    }


async def skip_disabled_task(uow: UnitOfWork, task_id: UUID) -> bool:
    """`queued` → `skipped` (`agent_disabled`) after a person chose **Continue without** its
    Agent (it never started, so it has no duration); traced `assessments.task.skipped` by the
    system. False (and no change) otherwise."""
    current = await node_task(uow, task_id)
    if current is None or not current.pending:
        return False
    skipped = await _end(
        uow,
        task_id,
        from_statuses=_QUEUED,
        status=AssessmentTaskStatus.SKIPPED,
        skip_reason=TaskSkipReason.AGENT_DISABLED.value,
        finished=False,
    )
    if not skipped:
        return False
    await trace.append(
        uow,
        actor=SYSTEM,
        payload=AssessmentsTaskSkipped(
            run_id=str(current.run_id),
            task_id=str(task_id),
            agent=current.agent,
            config_version_id=str(current.config_version_id),
            reason=TaskSkipReason.AGENT_DISABLED.value,
        ),
        subject_type=RUN_SUBJECT_TYPE,
        subject_id=current.run_id,
        opportunity_id=current.opportunity_id,
    )
    _log.info(
        "workflows.task_skipped_disabled",
        extra={"run_id": str(current.run_id), "task_id": str(task_id), "agent": current.agent},
    )
    return True
