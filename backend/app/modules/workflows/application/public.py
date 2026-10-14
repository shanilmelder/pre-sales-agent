"""workflows' public API (Story 5.2). Other modules, `app.orchestration` and the eval harness
use workflows only from here.

- Other modules: `enqueue_run` (gaps, after a Gap detection), `run_in_progress` and
  `run_number` (estimates).
- The graph's nodes (`app.orchestration`): `node_task`, `begin_task`, `lock_running_task`,
  `complete_task`, `fail_task`, `skip_blocked_task`, `plan_of`, `error_code`.
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
    retry_task,
    start_run,
)
from app.modules.workflows.application.models import (
    AssessmentRun,
    AssessmentsView,
    AssessmentTask,
    ProgressEventData,
)
from app.modules.workflows.application.runs import (
    EXECUTE,
    GraphRun,
    GraphRunner,
    NoGraphRunnerError,
    error_code,
    install_runner,
)
from app.modules.workflows.application.tasks import (
    NodeTask,
    begin_task,
    complete_task,
    fail_task,
    lock_running_task,
    node_task,
    skip_blocked_task,
)
from app.modules.workflows.domain.runs import AssessmentRunStatus, AssessmentTaskStatus
from app.platform.uow import UnitOfWork

PRUNE_PROGRESS = _progress.PRUNE_PROGRESS


async def enqueue_run(uow: UnitOfWork, opportunity_id: UUID) -> UUID:
    """Queue an assessment run of the Opportunity in the caller's Unit of Work (Story 5.1:
    after every successful Gap detection). Coalesces with a run that is queued or running;
    returns the run's id. Never refuses with a conflict; any other error (e.g. the
    database) fails the caller's Unit of Work."""
    return await _runs.enqueue_run(uow, opportunity_id)


async def run_in_progress(uow: UnitOfWork, opportunity_id: UUID) -> bool:
    """Whether one of the Opportunity's runs is queued or running (Story 8.3: the Estimate
    tab's waiting state). No authorization; for other modules."""
    return await _repo.run_in_progress(uow, opportunity_id) is not None


async def run_number(uow: UnitOfWork, opportunity_id: UUID, run_id: UUID) -> int | None:
    """The run's position among the Opportunity's runs, oldest first (Story 8.3: "from
    Assessments (run 3)"); None if it isn't one of them. No authorization."""
    return await _repo.run_number(uow, opportunity_id, run_id)


async def plan_of(uow: UnitOfWork, run_id: UUID) -> list[tuple[UUID, tuple[UUID, ...]]]:
    """The run's plan for building its graph: each task's id and the ids it requires, in a
    stable order. No authorization."""
    return [(t.id, t.requires) for t in await _repo.tasks_of(uow, run_id)]


__all__ = [
    "EXECUTE",
    "PRUNE_PROGRESS",
    "AssessmentRun",
    "AssessmentRunStatus",
    "AssessmentTask",
    "AssessmentTaskStatus",
    "AssessmentsView",
    "GraphRun",
    "GraphRunner",
    "NoGraphRunnerError",
    "NodeTask",
    "ProgressEventData",
    "begin_task",
    "cancel_run",
    "complete_task",
    "enqueue_run",
    "error_code",
    "fail_task",
    "get_assessments",
    "install_runner",
    "latest_run_view",
    "lock_running_task",
    "node_task",
    "plan_of",
    "retry_task",
    "run_in_progress",
    "run_number",
    "skip_blocked_task",
    "start_run",
]
