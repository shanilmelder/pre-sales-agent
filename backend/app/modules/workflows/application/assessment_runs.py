"""The assessment run query and commands behind the unchanged Assessments API (Story 5.2;
moved from `assessments`, Epic 5 slice 5A and Story 5.5).

- `get_assessments`: the Opportunity's latest run with its tasks, and per agent its current
  Assessment (read through `assessments`' public API), anyone who can read the Opportunity.
- `start_run`: queue a new run with one task per agent (`assessments.assessment.start`: the
  owner and collaborators except sales representatives; other readers 403, everyone else
  the Opportunity's 404). 409 `assessment_in_progress` while one is queued or running; one
  past `stale_after()` is failed (`model_timeout`) first, so it never blocks.
- `retry_task`: re-run one `failed` task of the latest run (same action). 409
  `assessment_in_progress` while the run is queued or running, 409
  `assessment_task_not_failed` unless that task is `failed` in the latest run (never in a
  cancelled one); 404 for a run that isn't the Opportunity's.
- `cancel_run`: cancel the Opportunity's latest run while it is queued or running (same
  action). 409 `assessment_not_in_progress` otherwise; 404 for a run that isn't the
  Opportunity's.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from app.modules.assessments.application import public as assessments
from app.modules.assessments.application.public import AssessmentAgent, RunErrorCode
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.opportunities.application import public as opportunities
from app.modules.registry.application import public as registry
from app.modules.workflows.adapters import repository as repo
from app.modules.workflows.adapters.repository import RunRecord, TaskRecord
from app.modules.workflows.application.models import (
    AssessmentRun,
    AssessmentsView,
    AssessmentTask,
)
from app.modules.workflows.application.runs import (
    cancel,
    fail_stale,
    queue_run,
    requeue_task,
    stale_after,
)
from app.modules.workflows.domain.runs import (
    RUN_IN_PROGRESS,
    TASK_IN_PROGRESS,
    AssessmentRunStatus,
    AssessmentTaskStatus,
    TaskSkipReason,
    run_status,
)
from app.platform.errors import (
    AssessmentInProgressError,
    AssessmentNotInProgressError,
    AssessmentTaskNotFailedError,
    NotFoundError,
)
from app.platform.logging import get_logger
from app.platform.uow import UnitOfWork

IN_PROGRESS_DETAIL = "An assessment is already running for this Opportunity."
NOT_FAILED_DETAIL = "Only a failed task of the latest assessment run can be retried."
NOT_IN_PROGRESS_DETAIL = (
    "Only the latest assessment run can be cancelled, while it is queued or running."
)
RUN_NOT_FOUND_DETAIL = "No such assessment run for this Opportunity."
_log = get_logger(__name__)


def _agent_order(agent: str) -> int:
    try:
        return assessments.AGENTS.index(AssessmentAgent(agent))
    except ValueError:  # pragma: no cover - the table only holds known agents
        return len(assessments.AGENTS)


def run_view(record: RunRecord, tasks: Sequence[TaskRecord]) -> AssessmentRun:
    """The read model of a run. One still queued or running past `stale_after()` is lost: its
    unfinished tasks read as failed with `model_timeout` and the run's status follows from
    its tasks', so it can be started again (`start_run` records that). Tasks keep their
    timestamps either way."""
    lost = (
        AssessmentRunStatus(record.status) in RUN_IN_PROGRESS
        and datetime.now(UTC) - record.queued_at > stale_after()
    )
    views: list[AssessmentTask] = []
    for task in sorted(tasks, key=lambda t: _agent_order(t.agent)):
        status = AssessmentTaskStatus(task.status)
        code = None if task.error_code is None else RunErrorCode(task.error_code)
        if lost and status in TASK_IN_PROGRESS:
            status, code = AssessmentTaskStatus.FAILED, RunErrorCode.MODEL_TIMEOUT
        views.append(
            AssessmentTask(
                agent=AssessmentAgent(task.agent),
                status=status,
                error_code=code,
                skip_reason=(
                    None if task.skip_reason is None else TaskSkipReason(task.skip_reason)
                ),
                started_at=task.started_at,
                finished_at=task.finished_at,
            )
        )
    overall = run_status(t.status for t in views) if lost else AssessmentRunStatus(record.status)
    return AssessmentRun(
        id=str(record.id),
        status=overall,
        created_at=record.created_at,
        queued_at=record.queued_at,
        finished_at=record.finished_at,
        tasks=views,
    )


async def latest_run_view(uow: UnitOfWork, opportunity_id: UUID) -> AssessmentRun | None:
    """The Opportunity's latest run (null before the first). No authorization."""
    latest = await repo.latest_run(uow, opportunity_id)
    return None if latest is None else run_view(latest, await repo.tasks_of(uow, latest.id))


async def get_assessments(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID
) -> AssessmentsView:
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    return AssessmentsView(
        run=await latest_run_view(uow, opportunity_id),
        assessments=await assessments.agent_assessments(uow, opportunity_id),
        can_start=identity.can(actor, Action.ASSESSMENT_START, resource),
    )


async def _current_run(uow: UnitOfWork, run_id: UUID) -> AssessmentRun:
    record = await repo.get_run(uow, run_id)
    assert record is not None  # inserted or locked in this Unit of Work
    return run_view(record, await repo.tasks_of(uow, run_id))


async def start_run(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> AssessmentRun:
    """Queue a new assessment run of the Opportunity: one task per specialist agent."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.ASSESSMENT_START, resource)
    await repo.lock_runs(uow, opportunity_id)
    await fail_stale(uow, opportunity_id)
    if await repo.run_in_progress(uow, opportunity_id) is not None:
        raise AssessmentInProgressError(IN_PROGRESS_DETAIL)
    run_id = await queue_run(uow, opportunity_id, actor.actor)
    _log.info(
        "workflows.run_started",
        extra={
            "opportunity_id": str(opportunity_id),
            "run_id": str(run_id),
            "actor_id": actor.actor.id,
        },
    )
    return await _current_run(uow, run_id)


async def retry_task(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    run_id: UUID,
    agent: AssessmentAgent,
) -> AssessmentRun:
    """Re-run one failed task of the Opportunity's latest assessment run."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.ASSESSMENT_START, resource)
    await repo.lock_runs(uow, opportunity_id)
    record = await repo.get_run(uow, run_id)
    if record is None or record.opportunity_id != opportunity_id:
        raise NotFoundError(RUN_NOT_FOUND_DETAIL)
    await fail_stale(uow, opportunity_id)
    if await repo.run_in_progress(uow, opportunity_id) is not None:
        raise AssessmentInProgressError(IN_PROGRESS_DETAIL)
    latest = await repo.latest_run(uow, opportunity_id)
    task = await repo.get_task(uow, run_id, agent.value)
    if (
        latest is None
        or latest.id != run_id
        # A cancelled run is final: re-queueing a task that failed before the cancel would
        # revive it.
        or latest.status == AssessmentRunStatus.CANCELLED
        or task is None
        or task.status != AssessmentTaskStatus.FAILED
    ):
        raise AssessmentTaskNotFailedError(NOT_FAILED_DETAIL)
    await registry.require_enabled(uow, agent.value)  # 409 while the agent is disabled
    await requeue_task(uow, latest, agent.value, actor.actor)
    _log.info(
        "workflows.task_retried",
        extra={
            "opportunity_id": str(opportunity_id),
            "run_id": str(run_id),
            "agent": agent.value,
            "actor_id": actor.actor.id,
        },
    )
    return await _current_run(uow, run_id)


async def cancel_run(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, run_id: UUID
) -> AssessmentRun:
    """Cancel the Opportunity's latest assessment run while it is queued or running."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.ASSESSMENT_START, resource)
    await repo.lock_runs(uow, opportunity_id)
    record = await repo.get_run(uow, run_id)
    if record is None or record.opportunity_id != opportunity_id:
        raise NotFoundError(RUN_NOT_FOUND_DETAIL)
    await fail_stale(uow, opportunity_id)
    latest = await repo.latest_run(uow, opportunity_id)
    if (
        latest is None
        or latest.id != run_id
        or AssessmentRunStatus(latest.status) not in RUN_IN_PROGRESS
        # Every task already finished: the job is about to record the outcome.
        or not any(
            AssessmentTaskStatus(t.status) in TASK_IN_PROGRESS
            for t in await repo.tasks_of(uow, run_id)
        )
    ):
        raise AssessmentNotInProgressError(NOT_IN_PROGRESS_DETAIL)
    skipped, succeeded = await cancel(uow, latest, actor.actor)
    _log.info(
        "workflows.run_cancelled",
        extra={
            "opportunity_id": str(opportunity_id),
            "run_id": str(run_id),
            "actor_id": actor.actor.id,
            "skipped_count": skipped,
            "succeeded_count": succeeded,
        },
    )
    return await _current_run(uow, run_id)
