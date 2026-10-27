"""workflows' public API (Story 5.2). Other modules, `app.orchestration` and the eval harness
use workflows only from here.

- Other modules: `enqueue_run` (gaps, after a Gap detection), `run_in_progress` and
  `run_number` (estimates; Story 9.5 also reviews), `run_starter` (estimates, reviews),
  `decision_status` (notifications, Story 9.2) and `start_run` with `RunType.CHALLENGE`
  (reviews, Story 9.5: a Challenge's reassessment).
- The graph's nodes (`app.orchestration`): `node_task`, `begin_task`, `lock_running_task`,
  `complete_task`, `fail_task`, `skip_blocked_task`, `plan_of`, `error_code`; for pausing
  (Story 5.5) `escalation`, `skip_disabled_task` and, for the runner, `decision_choices`.
- The worker: `install_runner` (the graph runner hook) and the job type names.
"""

from uuid import UUID

from app.modules.workflows.adapters import repository as _repo
from app.modules.workflows.application import progress as _progress
from app.modules.workflows.application import runs as _runs
from app.modules.workflows.application.assessment_runs import (
    cancel_run,
    get_assessments,
    latest_run_view,
    resolve_decision,
    retry_task,
    start_run,
)
from app.modules.workflows.application.models import (
    AssessmentRun,
    AssessmentsView,
    AssessmentTask,
    DecisionResolution,
    PlanVersion,
    PlanVersionTask,
    ProgressEventData,
    RunDecision,
    TraceEventData,
)
from app.modules.workflows.application.runs import (
    EXECUTE,
    RESUME,
    GraphRun,
    GraphRunner,
    NoGraphRunnerError,
    error_code,
    install_runner,
)
from app.modules.workflows.application.tasks import (
    Escalation,
    NodeTask,
    begin_task,
    complete_task,
    decision_choices,
    escalation,
    fail_task,
    lock_running_task,
    node_task,
    skip_blocked_task,
    skip_disabled_task,
)
from app.modules.workflows.domain.runs import (
    TASK_AGENTS,
    AssessmentRunStatus,
    AssessmentTaskStatus,
    DecisionChoice,
    DecisionStatus,
    RunType,
    TaskAgent,
)
from app.platform.uow import UnitOfWork

PRUNE_PROGRESS = _progress.PRUNE_PROGRESS


async def enqueue_run(uow: UnitOfWork, opportunity_id: UUID) -> UUID:
    """Queue an assessment run of the Opportunity in the caller's Unit of Work (Story 5.1:
    after every successful Gap detection). Coalesces with a run that is queued, running or
    waiting for a person;
    returns the run's id. Never refuses with a conflict; any other error (e.g. the
    database) fails the caller's Unit of Work."""
    return await _runs.enqueue_run(uow, opportunity_id)


async def run_in_progress(uow: UnitOfWork, opportunity_id: UUID) -> bool:
    """Whether one of the Opportunity's runs is queued or running (Story 8.3: the Estimate
    tab's waiting state; a run waiting for a person is not). No authorization; for other
    modules."""
    return await _repo.run_in_progress(uow, opportunity_id) is not None


async def run_number(uow: UnitOfWork, opportunity_id: UUID, run_id: UUID) -> int | None:
    """The run's position among the Opportunity's runs, oldest first (Story 8.3: "from
    Assessments (run 3)"); None if it isn't one of them. No authorization."""
    return await _repo.run_number(uow, opportunity_id, run_id)


async def run_starter(uow: UnitOfWork, run_id: UUID) -> UUID | None:
    """Story 9.1: the user who started the run (its plan v1's creator), or None when the
    system queued it or the run is unknown. No authorization. Story 9.2: the recipient of
    the run's `run_waiting` Inbox items."""
    return await _runs.run_starter(uow, run_id)


async def decision_status(uow: UnitOfWork, decision_id: UUID) -> DecisionStatus | None:
    """Story 9.2 (an Inbox item's subject): the decision's status now, or None when
    unknown. No authorization."""
    decision = await _repo.get_decision(uow, decision_id)
    return None if decision is None else DecisionStatus(decision.status)


async def plan_of(uow: UnitOfWork, run_id: UUID) -> list[tuple[UUID, tuple[UUID, ...]]]:
    """The run's plan for building its graph: each task's id and the ids it waits for (those
    it requires, then those it runs after, Story 6.4: the graph's edges are the same; the
    node tells them apart through `node_task`), in a stable order. No authorization."""
    return [
        (t.id, (*t.requires, *(a for a in t.after if a not in t.requires)))
        for t in await _repo.tasks_of(uow, run_id)
    ]


__all__ = [
    "EXECUTE",
    "PRUNE_PROGRESS",
    "RESUME",
    "TASK_AGENTS",
    "AssessmentRun",
    "AssessmentRunStatus",
    "AssessmentTask",
    "AssessmentTaskStatus",
    "AssessmentsView",
    "DecisionChoice",
    "DecisionResolution",
    "DecisionStatus",
    "Escalation",
    "GraphRun",
    "GraphRunner",
    "NoGraphRunnerError",
    "NodeTask",
    "PlanVersion",
    "PlanVersionTask",
    "ProgressEventData",
    "RunDecision",
    "RunType",
    "TaskAgent",
    "TraceEventData",
    "begin_task",
    "cancel_run",
    "complete_task",
    "decision_choices",
    "decision_status",
    "enqueue_run",
    "error_code",
    "escalation",
    "fail_task",
    "get_assessments",
    "install_runner",
    "latest_run_view",
    "lock_running_task",
    "node_task",
    "plan_of",
    "resolve_decision",
    "retry_task",
    "run_in_progress",
    "run_number",
    "run_starter",
    "skip_blocked_task",
    "skip_disabled_task",
    "start_run",
]
