"""Persistence for Conflicts and their positions (Story 6.1). Runs inside the caller's Unit
of Work."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, exists, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased

from app.modules.conflicts.adapters.models import ConflictRow, PositionRow
from app.platform.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class ConflictRecord:
    id: UUID
    opportunity_id: UUID
    run_id: UUID
    type: str
    severity: str
    status: str
    detected_by: str
    fingerprint: str
    detection_pass: int
    previous_conflict_id: UUID | None
    resolved_at: datetime | None
    row_version: int
    created_at: datetime
    summary: str = field(repr=False)
    resolution_reason: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class PositionRecord:
    conflict_id: UUID
    position: int
    source: str
    assessment_id: UUID | None
    assessment_version: int | None
    estimate_version_id: UUID | None
    estimate_version: int | None
    agent: str | None
    value: Decimal | None
    requirement_id: UUID | None
    requirement_version: int | None
    summary: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class NewPosition:
    source: str
    assessment_id: UUID | None
    assessment_version: int | None
    estimate_version_id: UUID | None
    estimate_version: int | None
    agent: str | None
    value: Decimal | None
    requirement_id: UUID | None
    requirement_version: int | None
    summary: str = field(repr=False)


async def lock_opportunity(uow: UnitOfWork, opportunity_id: UUID) -> None:
    """Serialise Conflict detection for the Opportunity until commit."""
    await uow.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"conflicts.detect:{opportunity_id}"},
    )


def _conflict(row: ConflictRow) -> ConflictRecord:
    return ConflictRecord(
        id=row.id,
        opportunity_id=row.opportunity_id,
        run_id=row.run_id,
        type=row.type,
        severity=row.severity,
        status=row.status,
        detected_by=row.detected_by,
        fingerprint=row.fingerprint,
        detection_pass=row.detection_pass,
        previous_conflict_id=row.previous_conflict_id,
        resolved_at=row.resolved_at,
        row_version=row.row_version,
        created_at=row.created_at,
        summary=row.summary,
        resolution_reason=row.resolution_reason,
    )


async def insert_conflict(
    uow: UnitOfWork,
    *,
    conflict_id: UUID,
    opportunity_id: UUID,
    run_id: UUID,
    detection_pass: int,
    type: str,
    severity: str,
    detected_by: str,
    fingerprint: str,
    summary: str,
    previous_conflict_id: UUID | None,
    positions: Sequence[NewPosition],
) -> bool:
    """Insert an `open` Conflict with its positions unless the run's detection pass already
    has one with this fingerprint. True when inserted."""
    inserted = (
        await uow.session.execute(
            pg_insert(ConflictRow)
            .values(
                id=conflict_id,
                opportunity_id=opportunity_id,
                run_id=run_id,
                detection_pass=detection_pass,
                type=type,
                severity=severity,
                status="open",
                detected_by=detected_by,
                fingerprint=fingerprint,
                summary=summary,
                previous_conflict_id=previous_conflict_id,
            )
            .on_conflict_do_nothing(index_elements=["run_id", "detection_pass", "fingerprint"])
            .returning(ConflictRow.id)
        )
    ).scalar_one_or_none()
    if inserted is None:
        return False
    if positions:
        await uow.session.execute(
            insert(PositionRow),
            [
                {
                    "conflict_id": conflict_id,
                    "position": n,
                    "source": p.source,
                    "assessment_id": p.assessment_id,
                    "assessment_version": p.assessment_version,
                    "estimate_version_id": p.estimate_version_id,
                    "estimate_version": p.estimate_version,
                    "agent": p.agent,
                    "summary": p.summary,
                    "value": p.value,
                    "requirement_id": p.requirement_id,
                    "requirement_version": p.requirement_version,
                }
                for n, p in enumerate(positions, start=1)
            ],
        )
    return True


async def latest_pass(uow: UnitOfWork, run_id: UUID) -> int:
    """The run's highest stored detection pass (0 before any Conflict of it)."""
    found = (
        await uow.session.execute(
            select(func.max(ConflictRow.detection_pass)).where(ConflictRow.run_id == run_id)
        )
    ).scalar_one_or_none()
    return found or 0


async def get_by_fingerprint(
    uow: UnitOfWork, run_id: UUID, detection_pass: int, fingerprint: str
) -> ConflictRecord | None:
    row = (
        await uow.session.execute(
            select(ConflictRow)
            .where(
                ConflictRow.run_id == run_id,
                ConflictRow.detection_pass == detection_pass,
                ConflictRow.fingerprint == fingerprint,
            )
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return None if row is None else _conflict(row)


async def open_conflicts(
    uow: UnitOfWork,
    opportunity_id: UUID,
    *,
    statuses: Sequence[str] = ("open",),
    detected_by: str | None = None,
) -> list[ConflictRecord]:
    """The Opportunity's Conflicts in these statuses, oldest first."""
    statement = select(ConflictRow).where(
        ConflictRow.opportunity_id == opportunity_id, ConflictRow.status.in_(list(statuses))
    )
    if detected_by is not None:
        statement = statement.where(ConflictRow.detected_by == detected_by)
    rows = await uow.session.execute(
        statement.order_by(ConflictRow.created_at, ConflictRow.id).execution_options(
            populate_existing=True
        )
    )
    return [_conflict(row) for row in rows.scalars()]


async def resolve(uow: UnitOfWork, conflict_id: UUID, *, reason: str) -> bool:
    """Mark an `open` Conflict `resolved` with the reason; True when it changed."""
    changed = await uow.session.execute(
        update(ConflictRow)
        .where(ConflictRow.id == conflict_id, ConflictRow.status == "open")
        .values(
            status="resolved",
            resolution_reason=reason,
            resolved_at=func.now(),
            row_version=ConflictRow.row_version + 1,
        )
        .returning(ConflictRow.id)
        .execution_options(synchronize_session=False)
    )
    return changed.scalar_one_or_none() is not None


async def listed_conflicts(uow: UnitOfWork, opportunity_id: UUID) -> list[ConflictRecord]:
    """The Opportunity's Conflicts, except those carried forward (a newer Conflict links
    them as its previous one)."""
    newer = aliased(ConflictRow)
    rows = await uow.session.execute(
        select(ConflictRow)
        .where(
            ConflictRow.opportunity_id == opportunity_id,
            ~exists().where(and_(newer.previous_conflict_id == ConflictRow.id)),
        )
        .execution_options(populate_existing=True)
    )
    return [_conflict(row) for row in rows.scalars()]


async def positions_of(uow: UnitOfWork, conflict_ids: Sequence[UUID]) -> list[PositionRecord]:
    if not conflict_ids:
        return []
    rows = await uow.session.execute(
        select(PositionRow)
        .where(PositionRow.conflict_id.in_(list(conflict_ids)))
        .order_by(PositionRow.conflict_id, PositionRow.position)
    )
    return [
        PositionRecord(
            conflict_id=row.conflict_id,
            position=row.position,
            source=row.source,
            assessment_id=row.assessment_id,
            assessment_version=row.assessment_version,
            estimate_version_id=row.estimate_version_id,
            estimate_version=row.estimate_version,
            agent=row.agent,
            value=row.value,
            requirement_id=row.requirement_id,
            requirement_version=row.requirement_version,
            summary=row.summary,
        )
        for row in rows.scalars()
    ]
