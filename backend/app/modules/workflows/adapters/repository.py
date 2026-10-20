"""Persistence for Workflow Runs, their tasks and progress rows (Story 5.2; the run and task
code moved from `assessments`). Runs inside the caller's Unit of Work."""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, insert, select, text, tuple_, update

from app.modules.workflows.adapters.models import (
    WorkflowProgressRow,
    WorkflowRunRow,
    WorkflowTaskRow,
)
from app.platform.events import EVENTS_CHANNEL
from app.platform.ids import new_id
from app.platform.trace.models import TraceEvent
from app.platform.uow import UnitOfWork

_IN_PROGRESS = ("queued", "running")
PROGRESS_SOURCE = "workflows_progress"


@dataclass(frozen=True, slots=True)
class RunRecord:
    id: UUID
    opportunity_id: UUID
    status: str
    created_at: datetime
    queued_at: datetime
    finished_at: datetime | None
    plan_version: int = 1


@dataclass(frozen=True, slots=True)
class TaskRecord:
    id: UUID
    run_id: UUID
    agent: str
    status: str
    error_code: str | None
    started_at: datetime | None
    finished_at: datetime | None
    config_version_id: UUID
    skip_reason: str | None = None
    requires: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class NewTask:
    """A task of a new run: `queued`, or `skipped` with a `skip_reason` when its Agent was
    not active. `config_version_id`: the registry config version it pins."""

    id: UUID
    agent: str
    config_version_id: UUID
    skip_reason: str | None = None
    requires: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class ProgressRecord:
    id: UUID
    opportunity_id: UUID
    run_id: UUID
    task_id: UUID | None
    event_type: str
    subject_type: str
    subject_id: UUID
    subject_version: int | None
    summary: str = field(repr=False)
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class TraceRecord:
    """What the event stream reads of a trace row (Story 2.3): never its payload."""

    id: UUID
    opportunity_id: UUID | None
    event_type: str
    subject_type: str
    subject_id: UUID
    subject_version: int | None
    occurred_at: datetime


# --- locks ----------------------------------------------------------------------------------


async def lock_runs(uow: UnitOfWork, opportunity_id: UUID) -> None:
    """Serialise the Opportunity's runs until commit: starting one, retrying a task,
    cancelling, a job starting, and finishing a run. (The key predates the move to
    `workflows`; keeping it keeps old and new code serialised during a deploy.)"""
    await uow.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"assessments.assessment_run:{opportunity_id}"},
    )


# --- runs and tasks -------------------------------------------------------------------------


def _run(row: WorkflowRunRow) -> RunRecord:
    return RunRecord(
        id=row.id,
        opportunity_id=row.opportunity_id,
        status=row.status,
        created_at=row.created_at,
        queued_at=row.queued_at,
        finished_at=row.finished_at,
        plan_version=row.plan_version,
    )


def _task(row: WorkflowTaskRow) -> TaskRecord:
    return TaskRecord(
        id=row.id,
        run_id=row.run_id,
        agent=row.agent,
        status=row.status,
        error_code=row.error_code,
        started_at=row.started_at,
        finished_at=row.finished_at,
        config_version_id=row.config_version_id,
        skip_reason=row.skip_reason,
        requires=tuple(row.requires or ()),
    )


async def insert_run(
    uow: UnitOfWork,
    *,
    run_id: UUID,
    opportunity_id: UUID,
    tasks: Sequence[NewTask],
    plan_version: int,
) -> None:
    """A `queued` run with its tasks: `queued`, or `skipped` when they have a skip reason."""
    await uow.session.execute(
        insert(WorkflowRunRow).values(
            id=run_id, opportunity_id=opportunity_id, status="queued", plan_version=plan_version
        )
    )
    await uow.session.execute(
        insert(WorkflowTaskRow),
        [
            {
                "id": t.id,
                "run_id": run_id,
                "agent": t.agent,
                "status": "queued" if t.skip_reason is None else "skipped",
                "config_version_id": t.config_version_id,
                "skip_reason": t.skip_reason,
                "requires": list(t.requires),
            }
            for t in tasks
        ],
    )


async def get_run(uow: UnitOfWork, run_id: UUID, *, for_update: bool = False) -> RunRecord | None:
    statement = (
        select(WorkflowRunRow)
        .where(WorkflowRunRow.id == run_id)
        .execution_options(populate_existing=True)
    )
    if for_update:
        statement = statement.with_for_update()
    row = (await uow.session.execute(statement)).scalar_one_or_none()
    return None if row is None else _run(row)


async def latest_run(uow: UnitOfWork, opportunity_id: UUID) -> RunRecord | None:
    row = (
        await uow.session.execute(
            select(WorkflowRunRow)
            .where(WorkflowRunRow.opportunity_id == opportunity_id)
            .order_by(WorkflowRunRow.created_at.desc(), WorkflowRunRow.id.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return None if row is None else _run(row)


async def run_in_progress(uow: UnitOfWork, opportunity_id: UUID) -> UUID | None:
    """A run of the Opportunity still `queued` or `running` (the oldest), if any."""
    return (
        await uow.session.execute(
            select(WorkflowRunRow.id)
            .where(
                WorkflowRunRow.opportunity_id == opportunity_id,
                WorkflowRunRow.status.in_(_IN_PROGRESS),
            )
            .order_by(WorkflowRunRow.created_at, WorkflowRunRow.id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def run_number(uow: UnitOfWork, opportunity_id: UUID, run_id: UUID) -> int | None:
    """The run's position among the Opportunity's runs, oldest first (1-based); None if it
    isn't one of them (Story 8.3)."""
    run = (
        await uow.session.execute(
            select(WorkflowRunRow.created_at, WorkflowRunRow.id).where(
                WorkflowRunRow.id == run_id,
                WorkflowRunRow.opportunity_id == opportunity_id,
            )
        )
    ).one_or_none()
    if run is None:
        return None
    return (
        await uow.session.execute(
            select(func.count()).where(
                WorkflowRunRow.opportunity_id == opportunity_id,
                tuple_(WorkflowRunRow.created_at, WorkflowRunRow.id) <= (run.created_at, run.id),
            )
        )
    ).scalar_one()


async def stale_runs(uow: UnitOfWork, opportunity_id: UUID, *, older_than: timedelta) -> list[UUID]:
    """The Opportunity's runs still `queued` or `running` more than `older_than` after they
    were last queued."""
    rows = await uow.session.execute(
        select(WorkflowRunRow.id).where(
            WorkflowRunRow.opportunity_id == opportunity_id,
            WorkflowRunRow.status.in_(_IN_PROGRESS),
            WorkflowRunRow.queued_at < func.now() - older_than,
        )
    )
    return list(rows.scalars())


async def set_run_status(
    uow: UnitOfWork,
    run_id: UUID,
    *,
    from_statuses: tuple[str, ...],
    status: str,
    finished: bool = False,
    requeued: bool = False,
) -> bool:
    """Move the run to `status` if it is in one of `from_statuses`; `finished` stamps
    `finished_at`, `requeued` stamps `queued_at` and clears `finished_at`. False (and no
    change) otherwise."""
    values: dict[str, object] = {"status": status}
    if finished:
        values["finished_at"] = func.now()
    if requeued:
        values["queued_at"] = func.now()
        values["finished_at"] = None
    result = await uow.session.execute(
        update(WorkflowRunRow)
        .where(WorkflowRunRow.id == run_id, WorkflowRunRow.status.in_(from_statuses))
        .values(**values)
        .returning(WorkflowRunRow.id)
        .execution_options(synchronize_session=False)
    )
    return result.one_or_none() is not None


async def tasks_of(uow: UnitOfWork, run_id: UUID) -> list[TaskRecord]:
    rows = await uow.session.execute(
        select(WorkflowTaskRow)
        .where(WorkflowTaskRow.run_id == run_id)
        .order_by(WorkflowTaskRow.id)
        .execution_options(populate_existing=True)
    )
    return [_task(row) for row in rows.scalars()]


async def get_task(
    uow: UnitOfWork, run_id: UUID, agent: str, *, for_update: bool = False
) -> TaskRecord | None:
    statement = (
        select(WorkflowTaskRow)
        .where(WorkflowTaskRow.run_id == run_id, WorkflowTaskRow.agent == agent)
        .execution_options(populate_existing=True)
    )
    if for_update:
        statement = statement.with_for_update()
    row = (await uow.session.execute(statement)).scalar_one_or_none()
    return None if row is None else _task(row)


async def get_task_by_id(
    uow: UnitOfWork, task_id: UUID, *, for_update: bool = False
) -> TaskRecord | None:
    statement = (
        select(WorkflowTaskRow)
        .where(WorkflowTaskRow.id == task_id)
        .execution_options(populate_existing=True)
    )
    if for_update:
        statement = statement.with_for_update()
    row = (await uow.session.execute(statement)).scalar_one_or_none()
    return None if row is None else _task(row)


@dataclass(frozen=True, slots=True)
class ChangedTask:
    id: UUID
    agent: str


async def update_tasks(
    uow: UnitOfWork,
    run_id: UUID,
    *,
    agents: Sequence[str] | None = None,
    task_ids: Sequence[UUID] | None = None,
    from_statuses: tuple[str, ...],
    status: str,
    error_code: str | None = None,
    skip_reason: str | None = None,
    started: bool = False,
    finished: bool = False,
    reset: bool = False,
) -> list[ChangedTask]:
    """Move the run's tasks (only `agents`' / `task_ids`' when given) that are in one of
    `from_statuses` to `status`, with `error_code` and `skip_reason` (both cleared when
    None). `started` / `finished` stamp `started_at` / `finished_at`; `reset` clears both.
    Returns the tasks that changed. The only writer of task status."""
    values: dict[str, object] = {
        "status": status,
        "error_code": error_code,
        "skip_reason": skip_reason,
    }
    if started:
        values["started_at"] = func.now()
    if finished:
        values["finished_at"] = func.now()
    if reset:
        values["started_at"] = None
        values["finished_at"] = None
    conditions = [
        WorkflowTaskRow.run_id == run_id,
        WorkflowTaskRow.status.in_(from_statuses),
    ]
    if agents is not None:
        conditions.append(WorkflowTaskRow.agent.in_(list(agents)))
    if task_ids is not None:
        conditions.append(WorkflowTaskRow.id.in_(list(task_ids)))
    result = await uow.session.execute(
        update(WorkflowTaskRow)
        .where(*conditions)
        .values(**values)
        .returning(WorkflowTaskRow.id, WorkflowTaskRow.agent)
        .execution_options(synchronize_session=False)
    )
    return [ChangedTask(id=row.id, agent=row.agent) for row in result.all()]


# --- progress (AD-24, AD-30) ----------------------------------------------------------------


async def insert_progress(
    uow: UnitOfWork,
    *,
    opportunity_id: UUID,
    run_id: UUID,
    task_id: UUID | None,
    event_type: str,
    subject_type: str,
    subject_id: UUID,
    summary: str,
) -> UUID:
    """A progress row, and its NOTIFY (delivered when the Unit of Work commits). The
    notification carries ids only: `{event_id, opportunity_id, source}`."""
    progress_id = new_id()
    await uow.session.execute(
        insert(WorkflowProgressRow).values(
            id=progress_id,
            opportunity_id=opportunity_id,
            run_id=run_id,
            task_id=task_id,
            event_type=event_type,
            subject_type=subject_type,
            subject_id=subject_id,
            summary=summary,
        )
    )
    payload = json.dumps(
        {
            "event_id": str(progress_id),
            "opportunity_id": str(opportunity_id),
            "source": PROGRESS_SOURCE,
        }
    )
    await uow.session.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": EVENTS_CHANNEL, "payload": payload},
    )
    return progress_id


def _progress(row: WorkflowProgressRow) -> ProgressRecord:
    return ProgressRecord(
        id=row.id,
        opportunity_id=row.opportunity_id,
        run_id=row.run_id,
        task_id=row.task_id,
        event_type=row.event_type,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        subject_version=row.subject_version,
        summary=row.summary,
        occurred_at=row.occurred_at,
    )


async def get_progress(uow: UnitOfWork, progress_id: UUID) -> ProgressRecord | None:
    row = (
        await uow.session.execute(
            select(WorkflowProgressRow).where(WorkflowProgressRow.id == progress_id)
        )
    ).scalar_one_or_none()
    return None if row is None else _progress(row)


async def progress_after(
    uow: UnitOfWork, opportunity_id: UUID, after: UUID, *, limit: int = 500
) -> list[ProgressRecord]:
    """The Opportunity's progress rows after `after` (UUIDv7 ids sort by creation), oldest
    first."""
    rows = await uow.session.execute(
        select(WorkflowProgressRow)
        .where(
            WorkflowProgressRow.opportunity_id == opportunity_id,
            WorkflowProgressRow.id > after,
        )
        .order_by(WorkflowProgressRow.id)
        .limit(limit)
    )
    return [_progress(row) for row in rows.scalars()]


async def delete_progress_before(uow: UnitOfWork, older_than: timedelta) -> int:
    """Delete progress rows older than `older_than`. Returns how many."""
    result = await uow.session.execute(
        delete(WorkflowProgressRow)
        .where(WorkflowProgressRow.occurred_at < func.now() - older_than)
        .returning(WorkflowProgressRow.id)
        .execution_options(synchronize_session=False)
    )
    return len(result.all())


# --- trace rows for the event stream (Story 2.3) ----------------------------------------------

_TRACE_COLUMNS = (
    TraceEvent.id,
    TraceEvent.opportunity_id,
    TraceEvent.event_type,
    TraceEvent.subject_type,
    TraceEvent.subject_id,
    TraceEvent.subject_version,
    TraceEvent.occurred_at,
)


def _trace(row: Any) -> TraceRecord:
    return TraceRecord(
        id=row.id,
        opportunity_id=row.opportunity_id,
        event_type=row.event_type,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        subject_version=row.subject_version,
        occurred_at=row.occurred_at,
    )


async def get_trace(uow: UnitOfWork, event_id: UUID) -> TraceRecord | None:
    """One trace row's stream fields (the payload is never read)."""
    row = (
        await uow.session.execute(select(*_TRACE_COLUMNS).where(TraceEvent.id == event_id))
    ).one_or_none()
    return None if row is None else _trace(row)


async def trace_after(
    uow: UnitOfWork, opportunity_id: UUID, after: UUID, *, limit: int = 500
) -> list[TraceRecord]:
    """The Opportunity's trace rows after `after` (UUIDv7 ids sort by creation), oldest
    first."""
    rows = await uow.session.execute(
        select(*_TRACE_COLUMNS)
        .where(TraceEvent.opportunity_id == opportunity_id, TraceEvent.id > after)
        .order_by(TraceEvent.id)
        .limit(limit)
    )
    return [_trace(row) for row in rows.all()]
