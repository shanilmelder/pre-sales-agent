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

**Escalation** (Story 5.5). Before a queued task starts, its node asks `escalation`: when
the task's Agent is `disabled` or `eval_only` in the Agent Registry, a `plan_escalation`
decision is recorded (idempotently: one per task) and returned `open`, and the node
interrupts the graph; the run then waits for a person. Once the decision is resolved, the
node (re-run on resume) gets the resolved choice from the same call: Continue without skips
the task (`skip_disabled_task`, `agent_disabled`), Re-plan lets it run (the resolve command
already re-pinned it). The decision row is the truth, not the value the graph resumed with.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.registry.application import public as registry
from app.modules.workflows.adapters import repository as repo
from app.modules.workflows.adapters.repository import DecisionRecord, TaskRecord
from app.modules.workflows.application import progress
from app.modules.workflows.domain.runs import (
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
NODE_ACTOR = Actor(type="system", id="workflows.execute")
"""Who a node's own commands act as (the job's system actor)."""
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


# --- escalation (Story 5.5) -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Escalation:
    """A task's `plan_escalation` as its node sees it. `payload`: what the node passes to
    `interrupt()` while it is `open` (ids and codes only)."""

    decision_id: UUID
    status: DecisionStatus
    choice: DecisionChoice | None
    payload: dict[str, Any]

    @property
    def open(self) -> bool:
        return self.status == DecisionStatus.OPEN

    @property
    def continue_without(self) -> bool:
        return (
            self.status == DecisionStatus.RESOLVED
            and self.choice == DecisionChoice.CONTINUE_WITHOUT
        )

    @property
    def replanned(self) -> bool:
        return self.status == DecisionStatus.RESOLVED and self.choice == DecisionChoice.REPLAN


def _escalation(decision: DecisionRecord) -> Escalation:
    return Escalation(
        decision_id=decision.id,
        status=DecisionStatus(decision.status),
        choice=None if decision.choice is None else DecisionChoice(decision.choice),
        payload=dict(decision.payload),
    )


def escalation_payload(decision_id: UUID, task: TaskRecord) -> dict[str, Any]:
    """The interrupt payload of a task's `plan_escalation`: ids, codes and the choices."""
    return {
        "decision_id": str(decision_id),
        "kind": DecisionKind.PLAN_ESCALATION.value,
        "run_id": str(task.run_id),
        "task_id": str(task.id),
        "agent": task.agent,
        "choices": [c.value for c in DecisionChoice],
    }


async def escalation(uow: UnitOfWork, task_id: UUID) -> Escalation | None:
    """The task's `plan_escalation`, recording it first when its Agent is not active: None
    when the task may run (no decision and its Agent is active, or the task isn't queued).
    Recording is idempotent (insert on conflict do nothing), so a node that runs again
    before the decision is resolved finds the same open decision."""
    task = await repo.get_task_by_id(uow, task_id)
    if task is None:
        return None
    kind = DecisionKind.PLAN_ESCALATION.value
    existing = await repo.task_decision(uow, task_id, kind)
    if existing is not None:
        return _escalation(existing)
    if task.status != AssessmentTaskStatus.QUEUED:
        return None  # already started (e.g. it runs again after a failed attempt)
    agent = await registry.current_config(uow, task.agent)
    if agent.runs_tasks:
        return None
    decision_id = new_id()
    inserted = await repo.insert_decision(
        uow,
        decision_id=decision_id,
        run_id=task.run_id,
        task_id=task_id,
        kind=kind,
        payload=escalation_payload(decision_id, task),
    )
    if inserted:
        _log.info(
            "workflows.decision_recorded",
            extra={
                "run_id": str(task.run_id),
                "task_id": str(task_id),
                "decision_id": str(decision_id),
                "agent": task.agent,
                "kind": kind,
            },
        )
    recorded = await repo.task_decision(uow, task_id, kind)
    assert recorded is not None  # inserted here or by a concurrent node
    return _escalation(recorded)


async def skip_disabled_task(uow: UnitOfWork, task_id: UUID) -> bool:
    """`queued` → `skipped` / `agent_disabled` (Continue without; it never started, so it
    has no duration), traced as `assessments.task.skipped` by the system. False (and no
    change) otherwise."""
    task = await repo.get_task_by_id(uow, task_id)
    if task is None:
        return False
    run = await repo.get_run(uow, task.run_id)
    if run is None:
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
        actor=NODE_ACTOR,
        payload=AssessmentsTaskSkipped(
            run_id=str(task.run_id),
            task_id=str(task_id),
            agent=task.agent,
            config_version_id=str(task.config_version_id),
            reason=TaskSkipReason.AGENT_DISABLED.value,
        ),
        subject_type=RUN_SUBJECT_TYPE,
        subject_id=task.run_id,
        opportunity_id=run.opportunity_id,
    )
    _log.info(
        "workflows.task_skipped_disabled",
        extra={
            "run_id": str(task.run_id),
            "task_id": str(task_id),
            "agent": task.agent,
            "config_version_id": str(task.config_version_id),
        },
    )
    return True
