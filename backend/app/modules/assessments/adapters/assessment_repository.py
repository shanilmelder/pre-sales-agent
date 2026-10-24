"""Persistence for the specialist Assessments with their Findings, the Findings'
Requirement links and the effort rows (Epic 5 slice 5A; runs and tasks moved to
`workflows` in Story 5.2). Runs inside the caller's Unit of Work."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, insert, select, text, update

from app.modules.assessments.adapters.models import (
    AssessmentEffortRow,
    AssessmentFindingRequirementRow,
    AssessmentFindingRow,
    AssessmentRow,
)
from app.platform.ids import new_id
from app.platform.uow import UnitOfWork


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
    config_version_id: UUID


@dataclass(frozen=True, slots=True)
class FindingRecord:
    id: UUID
    assessment_id: UUID
    position: int
    kind: str
    severity: str
    title: str = field(repr=False)
    detail: str = field(repr=False)
    injection_suspected: bool = False


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
    injection_suspected: bool = False


@dataclass(frozen=True, slots=True)
class NewEffort:
    requirement_id: UUID
    requirement_version: int
    hours: Decimal
    basis: str = field(repr=False)


# --- locks ----------------------------------------------------------------------------------


async def lock_agent(uow: UnitOfWork, opportunity_id: UUID, agent: str) -> None:
    """Serialise accepting one agent's Assessments of the Opportunity until commit (which
    numbers and supersedes them)."""
    await uow.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"assessments.assessment:{opportunity_id}:{agent}"},
    )


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
        config_version_id=row.config_version_id,
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
    config_version_id: UUID,
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
            config_version_id=config_version_id,
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
                    "injection_suspected": f.injection_suspected,
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


async def run_assessments(
    uow: UnitOfWork, opportunity_id: UUID, run_id: UUID
) -> list[AssessmentRecord]:
    """The Assessments of the Opportunity accepted in the run (Story 6.4), the newest per
    agent, current or since superseded."""
    rows = await uow.session.execute(
        select(AssessmentRow)
        .where(AssessmentRow.opportunity_id == opportunity_id, AssessmentRow.run_id == run_id)
        .order_by(AssessmentRow.agent, AssessmentRow.version.desc())
    )
    newest: dict[str, AssessmentRecord] = {}
    for row in rows.scalars():
        newest.setdefault(row.agent, _assessment(row))
    return list(newest.values())


async def assessments_by_id(
    uow: UnitOfWork, assessment_ids: Sequence[UUID]
) -> list[AssessmentRecord]:
    """These Assessments (current or superseded), in no particular order."""
    if not assessment_ids:
        return []
    rows = await uow.session.execute(
        select(AssessmentRow).where(AssessmentRow.id.in_(list(assessment_ids)))
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
            injection_suspected=row.injection_suspected,
        )
        for row in rows.scalars()
    ]


async def findings_by_id(uow: UnitOfWork, finding_ids: Sequence[UUID]) -> list[FindingRecord]:
    """These Findings (of any Assessment), in no particular order."""
    if not finding_ids:
        return []
    rows = await uow.session.execute(
        select(AssessmentFindingRow).where(AssessmentFindingRow.id.in_(list(finding_ids)))
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
            injection_suspected=row.injection_suspected,
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
