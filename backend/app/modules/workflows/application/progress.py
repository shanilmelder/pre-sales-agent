"""Progress rows (AD-24, AD-30; Story 5.2): written in the same Unit of Work as each run
queueing, task start, task end, run end and (Story 5.5) a run starting to wait for a person,
each with a NOTIFY carrying ids only. They are not audit records (the trace is): ids, an
event type and a summary of Agent ids and statuses, never customer text.

The `workflows.prune_progress` job, enqueued daily from `platform_schedules`, deletes rows
older than 30 days.
"""

from datetime import timedelta
from uuid import UUID

from app.modules.workflows.adapters import repository as repo
from app.modules.workflows.domain.runs import (
    PROGRESS_RETENTION_DAYS,
    RUN_PROGRESS_SUBJECT,
    TASK_PROGRESS_SUBJECT,
    AssessmentRunStatus,
    AssessmentTaskStatus,
    ProgressEvent,
    run_summary,
    task_summary,
    waiting_summary,
)
from app.platform.jobs import JobContext, JobPayload, JobType, register
from app.platform.logging import get_logger
from app.platform.uow import UnitOfWork, unit_of_work

PRUNE_PROGRESS = "workflows.prune_progress"
_log = get_logger(__name__)


async def task_changed(
    uow: UnitOfWork,
    *,
    opportunity_id: UUID,
    run_id: UUID,
    task_id: UUID,
    agent: str,
    status: AssessmentTaskStatus,
) -> None:
    """A task started (`running`) or ended (any other status)."""
    event = (
        ProgressEvent.TASK_STARTED
        if status == AssessmentTaskStatus.RUNNING
        else ProgressEvent.TASK_ENDED
    )
    await repo.insert_progress(
        uow,
        opportunity_id=opportunity_id,
        run_id=run_id,
        task_id=task_id,
        event_type=event.value,
        subject_type=TASK_PROGRESS_SUBJECT,
        subject_id=task_id,
        summary=task_summary(agent, status),
    )


async def run_changed(
    uow: UnitOfWork, *, opportunity_id: UUID, run_id: UUID, status: AssessmentRunStatus
) -> None:
    """A run was queued (again) or ended."""
    event = (
        ProgressEvent.RUN_QUEUED
        if status == AssessmentRunStatus.QUEUED
        else ProgressEvent.RUN_ENDED
    )
    await repo.insert_progress(
        uow,
        opportunity_id=opportunity_id,
        run_id=run_id,
        task_id=None,
        event_type=event.value,
        subject_type=RUN_PROGRESS_SUBJECT,
        subject_id=run_id,
        summary=run_summary(status),
    )


async def run_waiting(uow: UnitOfWork, *, opportunity_id: UUID, run_id: UUID, agent: str) -> None:
    """A run started waiting for a person on the Agent's task (Story 5.5)."""
    await repo.insert_progress(
        uow,
        opportunity_id=opportunity_id,
        run_id=run_id,
        task_id=None,
        event_type=ProgressEvent.RUN_WAITING.value,
        subject_type=RUN_PROGRESS_SUBJECT,
        subject_id=run_id,
        summary=waiting_summary(agent),
    )


# --- pruning --------------------------------------------------------------------------------


class PruneProgress(JobPayload):
    """No fields: the job prunes every Opportunity's old rows."""


def retention() -> timedelta:
    return timedelta(days=PROGRESS_RETENTION_DAYS)


async def prune_progress(ctx: JobContext, payload: PruneProgress) -> None:
    async with unit_of_work(ctx.engine) as uow:
        deleted = await repo.delete_progress_before(uow, retention())
    _log.info("workflows.progress_pruned", extra={"deleted_count": deleted})


PRUNE_PROGRESS_JOB = register(
    JobType(
        name=PRUNE_PROGRESS,
        payload=PruneProgress,
        handler=prune_progress,
        priority="background",
        timeout_s=300.0,
        max_attempts=3,
    )
)
