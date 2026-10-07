"""Persistence for assessment runs, their tasks, and the specialist Assessments with their
Findings, the Findings' Requirement links and the effort rows (Epic 5 slice 5A). Runs
inside the caller's Unit of Work."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, insert, select, text, tuple_, update

from app.modules.assessments.adapters.models import (
    AssessmentEffortRow,
    AssessmentFindingRequirementRow,
    AssessmentFindingRow,
    AssessmentRow,
    AssessmentRunRow,
    AssessmentTaskRow,
)
from app.platform.ids import new_id
from app.platform.uow import UnitOfWork

_IN_PROGRESS = ("queued", "running")


@dataclass(frozen=True, slots=True)
class RunRecord:
    id: UUID
    opportunity_id: UUID
    status: str
    created_at: datetime
    queued_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class TaskRecord:
    id: UUID
    run_id: UUID
    agent: str
    status: str
    error_code: str | None
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class AssessmentRecord:
    id: UUID
    opportunity_id: UUID
    agent: str
    version: int
    run_id: UUID
    status: str
    recommendation: str
    confidence: str
    confidence_basis: str = field(repr=False)
    dropped_count: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class FindingRecord:
    id: UUID
    assessment_id: UUID
    position: int
    kind: str
    severity: str
    title: str = field(repr=False)
    detail: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class FindingRequirementRecord:
    finding_id: UUID
    requirement_id: UUID
    requirement_version: int


@dataclass(frozen=True, slots=True)
class EffortRecord:
    id: UUID
    assessment_id: UUID
    requirement_id: UUID
    requirement_version: int
    hours: Decimal
    basis: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class NewFinding:
    position: int
    kind: str
    severity: str
    title: str = field(repr=False)
    detail: str = field(repr=False)
    requirements: Sequence[tuple[UUID, int]] = ()


@dataclass(frozen=True, slots=True)
class NewEffort:
    requirement_id: UUID
    requirement_version: int
    hours: Decimal
    basis: str = field(repr=False)


# --- locks ----------------------------------------------------------------------------------


async def lock_runs(uow: UnitOfWork, opportunity_id: UUID) -> None:
    """Serialise the Opportunity's assessment runs until commit: starting one, retrying a
    task, a job starting, and finishing a run."""
    await uow.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"assessments.assessment_run:{opportunity_id}"},
    )


async def lock_agent(uow: UnitOfWork, opportunity_id: UUID, agent: str) -> None:
    """Serialise accepting one agent's Assessments of the Opportunity until commit (which
    numbers and supersedes them)."""
    await uow.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"assessments.assessment:{opportunity_id}:{agent}"},
    )


# --- runs and tasks -------------------------------------------------------------------------


def _run(row: AssessmentRunRow) -> RunRecord:
    return RunRecord(
        id=row.id,
        opportunity_id=row.opportunity_id,
        status=row.status,
        created_at=row.created_at,
        queued_at=row.queued_at,
        finished_at=row.finished_at,
    )


def _task(row: AssessmentTaskRow) -> TaskRecord:
    return TaskRecord(
        id=row.id,
        run_id=row.run_id,
        agent=row.agent,
        status=row.status,
        error_code=row.error_code,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


async def insert_run(
    uow: UnitOfWork, *, run_id: UUID, opportunity_id: UUID, agents: Sequence[str]
) -> None:
    """A `queued` run with one `queued` task per agent."""
    await uow.session.execute(
        insert(AssessmentRunRow).values(id=run_id, opportunity_id=opportunity_id, status="queued")
    )
    await uow.session.execute(
        insert(AssessmentTaskRow),
        [{"id": new_id(), "run_id": run_id, "agent": a, "status": "queued"} for a in agents],
    )


async def get_run(uow: UnitOfWork, run_id: UUID, *, for_update: bool = False) -> RunRecord | None:
    statement = (
        select(AssessmentRunRow)
        .where(AssessmentRunRow.id == run_id)
        .execution_options(populate_existing=True)
    )
    if for_update:
        statement = statement.with_for_update()
    row = (await uow.session.execute(statement)).scalar_one_or_none()
    return None if row is None else _run(row)


async def latest_run(uow: UnitOfWork, opportunity_id: UUID) -> RunRecord | None:
    row = (
        await uow.session.execute(
            select(AssessmentRunRow)
            .where(AssessmentRunRow.opportunity_id == opportunity_id)
            .order_by(AssessmentRunRow.created_at.desc(), AssessmentRunRow.id.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return None if row is None else _run(row)


async def run_in_progress(uow: UnitOfWork, opportunity_id: UUID) -> UUID | None:
    """A run of the Opportunity still `queued` or `running` (the oldest), if any."""
    return (
        await uow.session.execute(
            select(AssessmentRunRow.id)
            .where(
                AssessmentRunRow.opportunity_id == opportunity_id,
                AssessmentRunRow.status.in_(_IN_PROGRESS),
            )
            .order_by(AssessmentRunRow.created_at, AssessmentRunRow.id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def run_number(uow: UnitOfWork, opportunity_id: UUID, run_id: UUID) -> int | None:
    """The run's position among the Opportunity's runs, oldest first (1-based); None if it
    isn't one of them (Story 8.3)."""
    run = (
        await uow.session.execute(
            select(AssessmentRunRow.created_at, AssessmentRunRow.id).where(
                AssessmentRunRow.id == run_id,
                AssessmentRunRow.opportunity_id == opportunity_id,
            )
        )
    ).one_or_none()
    if run is None:
        return None
    return (
        await uow.session.execute(
            select(func.count()).where(
                AssessmentRunRow.opportunity_id == opportunity_id,
                tuple_(AssessmentRunRow.created_at, AssessmentRunRow.id)
                <= (run.created_at, run.id),
            )
        )
    ).scalar_one()


async def stale_runs(uow: UnitOfWork, opportunity_id: UUID, *, older_than: timedelta) -> list[UUID]:
    """The Opportunity's runs still `queued` or `running` more than `older_than` after they
    were last queued."""
    rows = await uow.session.execute(
        select(AssessmentRunRow.id).where(
            AssessmentRunRow.opportunity_id == opportunity_id,
            AssessmentRunRow.status.in_(_IN_PROGRESS),
            AssessmentRunRow.queued_at < func.now() - older_than,
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
        update(AssessmentRunRow)
        .where(AssessmentRunRow.id == run_id, AssessmentRunRow.status.in_(from_statuses))
        .values(**values)
        .returning(AssessmentRunRow.id)
        .execution_options(synchronize_session=False)
    )
    return result.one_or_none() is not None


async def tasks_of(uow: UnitOfWork, run_id: UUID) -> list[TaskRecord]:
    rows = await uow.session.execute(
        select(AssessmentTaskRow)
        .where(AssessmentTaskRow.run_id == run_id)
        .execution_options(populate_existing=True)
    )
    return [_task(row) for row in rows.scalars()]


async def get_task(
    uow: UnitOfWork, run_id: UUID, agent: str, *, for_update: bool = False
) -> TaskRecord | None:
    statement = (
        select(AssessmentTaskRow)
        .where(AssessmentTaskRow.run_id == run_id, AssessmentTaskRow.agent == agent)
        .execution_options(populate_existing=True)
    )
    if for_update:
        statement = statement.with_for_update()
    row = (await uow.session.execute(statement)).scalar_one_or_none()
    return None if row is None else _task(row)


async def update_tasks(
    uow: UnitOfWork,
    run_id: UUID,
    *,
    agents: Sequence[str] | None = None,
    from_statuses: tuple[str, ...],
    status: str,
    error_code: str | None = None,
    started: bool = False,
    finished: bool = False,
    reset: bool = False,
) -> list[str]:
    """Move the run's tasks (only `agents`' when given) that are in one of `from_statuses`
    to `status`. `started` / `finished` stamp `started_at` / `finished_at`; `reset` clears
    both. Returns the agents whose task changed."""
    values: dict[str, object] = {"status": status, "error_code": error_code}
    if started:
        values["started_at"] = func.now()
    if finished:
        values["finished_at"] = func.now()
    if reset:
        values["started_at"] = None
        values["finished_at"] = None
    conditions = [
        AssessmentTaskRow.run_id == run_id,
        AssessmentTaskRow.status.in_(from_statuses),
    ]
    if agents is not None:
        conditions.append(AssessmentTaskRow.agent.in_(list(agents)))
    result = await uow.session.execute(
        update(AssessmentTaskRow)
        .where(*conditions)
        .values(**values)
        .returning(AssessmentTaskRow.agent)
        .execution_options(synchronize_session=False)
    )
    return list(result.scalars())


# --- Assessments ----------------------------------------------------------------------------


def _assessment(row: AssessmentRow) -> AssessmentRecord:
    return AssessmentRecord(
        id=row.id,
        opportunity_id=row.opportunity_id,
        agent=row.agent,
        version=row.version,
        run_id=row.run_id,
        status=row.status,
        recommendation=row.recommendation,
        confidence=row.confidence,
        confidence_basis=row.confidence_basis,
        dropped_count=row.dropped_count,
        created_at=row.created_at,
    )


async def latest_assessment_number(uow: UnitOfWork, opportunity_id: UUID, agent: str) -> int:
    """The agent's highest Assessment version for the Opportunity, 0 before the first."""
    found = (
        await uow.session.execute(
            select(func.max(AssessmentRow.version)).where(
                AssessmentRow.opportunity_id == opportunity_id, AssessmentRow.agent == agent
            )
        )
    ).scalar_one_or_none()
    return found or 0


async def supersede_assessments(uow: UnitOfWork, opportunity_id: UUID, agent: str) -> int:
    """Mark the agent's `current` Assessment of the Opportunity `superseded`. Returns how many
    changed."""
    result = await uow.session.execute(
        update(AssessmentRow)
        .where(
            AssessmentRow.opportunity_id == opportunity_id,
            AssessmentRow.agent == agent,
            AssessmentRow.status == "current",
        )
        .values(status="superseded")
        .returning(AssessmentRow.id)
        .execution_options(synchronize_session=False)
    )
    return len(result.all())


async def insert_assessment(
    uow: UnitOfWork,
    *,
    assessment_id: UUID,
    opportunity_id: UUID,
    agent: str,
    version: int,
    run_id: UUID,
    recommendation: str,
    confidence: str,
    confidence_basis: str,
    dropped_count: int,
    findings: Sequence[NewFinding],
    effort: Sequence[NewEffort],
) -> None:
    """A `current` Assessment with its Findings, their Requirement links and its effort."""
    await uow.session.execute(
        insert(AssessmentRow).values(
            id=assessment_id,
            opportunity_id=opportunity_id,
            agent=agent,
            version=version,
            run_id=run_id,
            status="current",
            recommendation=recommendation,
            confidence=confidence,
            confidence_basis=confidence_basis,
            dropped_count=dropped_count,
        )
    )
    finding_ids = [new_id() for _ in findings]
    if findings:
        await uow.session.execute(
            insert(AssessmentFindingRow),
            [
                {
                    "id": finding_id,
                    "assessment_id": assessment_id,
                    "position": f.position,
                    "kind": f.kind,
                    "severity": f.severity,
                    "title": f.title,
                    "detail": f.detail,
                }
                for finding_id, f in zip(finding_ids, findings, strict=True)
            ],
        )
        await uow.session.execute(
            insert(AssessmentFindingRequirementRow),
            [
                {"finding_id": finding_id, "requirement_id": rid, "requirement_version": at}
                for finding_id, f in zip(finding_ids, findings, strict=True)
                for rid, at in f.requirements
            ],
        )
    if effort:
        await uow.session.execute(
            insert(AssessmentEffortRow),
            [
                {
                    "id": new_id(),
                    "assessment_id": assessment_id,
                    "requirement_id": e.requirement_id,
                    "requirement_version": e.requirement_version,
                    "hours": e.hours,
                    "basis": e.basis,
                }
                for e in effort
            ],
        )


async def current_assessments(uow: UnitOfWork, opportunity_id: UUID) -> list[AssessmentRecord]:
    """The Opportunity's `current` Assessments, one per agent at most (superseded ones are
    hidden)."""
    rows = await uow.session.execute(
        select(AssessmentRow).where(
            AssessmentRow.opportunity_id == opportunity_id, AssessmentRow.status == "current"
        )
    )
    return [_assessment(row) for row in rows.scalars()]


async def findings_of(uow: UnitOfWork, assessment_ids: Sequence[UUID]) -> list[FindingRecord]:
    if not assessment_ids:
        return []
    rows = await uow.session.execute(
        select(AssessmentFindingRow)
        .where(AssessmentFindingRow.assessment_id.in_(list(assessment_ids)))
        .order_by(AssessmentFindingRow.assessment_id, AssessmentFindingRow.position)
    )
    return [
        FindingRecord(
            id=row.id,
            assessment_id=row.assessment_id,
            position=row.position,
            kind=row.kind,
            severity=row.severity,
            title=row.title,
            detail=row.detail,
        )
        for row in rows.scalars()
    ]


async def requirement_links_for(
    uow: UnitOfWork, finding_ids: Sequence[UUID]
) -> list[FindingRequirementRecord]:
    if not finding_ids:
        return []
    rows = await uow.session.execute(
        select(AssessmentFindingRequirementRow).where(
            AssessmentFindingRequirementRow.finding_id.in_(list(finding_ids))
        )
    )
    return [
        FindingRequirementRecord(
            finding_id=row.finding_id,
            requirement_id=row.requirement_id,
            requirement_version=row.requirement_version,
        )
        for row in rows.scalars()
    ]


async def effort_of(uow: UnitOfWork, assessment_ids: Sequence[UUID]) -> list[EffortRecord]:
    if not assessment_ids:
        return []
    rows = await uow.session.execute(
        select(AssessmentEffortRow).where(
            AssessmentEffortRow.assessment_id.in_(list(assessment_ids))
        )
    )
    return [
        EffortRecord(
            id=row.id,
            assessment_id=row.assessment_id,
            requirement_id=row.requirement_id,
            requirement_version=row.requirement_version,
            hours=row.hours,
            basis=row.basis,
        )
        for row in rows.scalars()
    ]
