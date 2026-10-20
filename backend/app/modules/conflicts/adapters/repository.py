"""Persistence for Conflicts and their positions (Stories 6.1 and 6.3). Runs inside the
caller's Unit of Work."""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.modules.conflicts.adapters.models import ConflictRow, DetectionRow, PositionRow
from app.platform.trace.models import TraceEvent
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
    resolved_by: UUID | None = None
    chosen_position: int | None = None
    entered_position: str | None = field(default=None, repr=False)
    applied_hours: Decimal | None = None
    escalated_to: UUID | None = None
    escalated_by: UUID | None = None
    escalated_at: datetime | None = None
    escalation_reason: str | None = field(default=None, repr=False)

    @property
    def decided(self) -> bool:
        """Resolved by a person (Story 6.3), not by the system."""
        return self.status == "resolved" and self.resolved_by is not None


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
    finding_id: UUID | None = None


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
    finding_id: UUID | None = None


EVENTS_CHANNEL = "psa_events"
"""The NOTIFY channel of the per-Opportunity event stream (AD-30), shared with workflows."""
CONFLICTS_SOURCE = "conflicts"


async def notify_conflicts_changed(uow: UnitOfWork, opportunity_id: UUID) -> None:
    """Tell the Opportunity's event stream that its Conflicts changed (Story 6.2). Delivered
    when the Unit of Work commits, and only then; Postgres folds identical notifications of
    one transaction into one. Ids only."""
    payload = json.dumps({"opportunity_id": str(opportunity_id), "source": CONFLICTS_SOURCE})
    await uow.session.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": EVENTS_CHANNEL, "payload": payload},
    )


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
        resolved_by=row.resolved_by,
        chosen_position=row.chosen_position,
        entered_position=row.entered_position,
        applied_hours=row.applied_hours,
        escalated_to=row.escalated_to,
        escalated_by=row.escalated_by,
        escalated_at=row.escalated_at,
        escalation_reason=row.escalation_reason,
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
    escalation: ConflictRecord | None = None,
) -> bool:
    """Insert an `open` Conflict with its positions unless the run's detection pass already
    has one with this fingerprint. True when inserted. With `escalation` (Story 6.3: an
    escalated Conflict re-raised with changed positions), it is inserted `escalated` with
    that Conflict's reviewer, reason, who and when."""
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
                status="open" if escalation is None else "escalated",
                escalated_to=None if escalation is None else escalation.escalated_to,
                escalated_by=None if escalation is None else escalation.escalated_by,
                escalated_at=None if escalation is None else escalation.escalated_at,
                escalation_reason=None if escalation is None else escalation.escalation_reason,
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
                    "finding_id": p.finding_id,
                }
                for n, p in enumerate(positions, start=1)
            ],
        )
    return True


async def latest_pass(uow: UnitOfWork, run_id: UUID) -> int:
    """The run's highest detection pass (0 before the first): recorded passes, and the
    Conflicts stored before passes were recorded."""
    recorded = (
        await uow.session.execute(
            select(func.max(DetectionRow.detection_pass)).where(DetectionRow.run_id == run_id)
        )
    ).scalar_one_or_none()
    stored = (
        await uow.session.execute(
            select(func.max(ConflictRow.detection_pass)).where(ConflictRow.run_id == run_id)
        )
    ).scalar_one_or_none()
    return max(recorded or 0, stored or 0)


async def record_detection(
    uow: UnitOfWork, *, opportunity_id: UUID, run_id: UUID, detection_pass: int
) -> None:
    """Record a detection pass of the run (Story 6.2); a second record of it changes
    nothing."""
    await uow.session.execute(
        pg_insert(DetectionRow)
        .values(run_id=run_id, detection_pass=detection_pass, opportunity_id=opportunity_id)
        .on_conflict_do_nothing(index_elements=["run_id", "detection_pass"])
    )


async def latest_detection(uow: UnitOfWork, opportunity_id: UUID) -> tuple[UUID, int] | None:
    """The Opportunity's newest detection pass as (run id, pass); None before the first."""
    row = (
        await uow.session.execute(
            select(DetectionRow.run_id, DetectionRow.detection_pass)
            .where(DetectionRow.opportunity_id == opportunity_id)
            .order_by(DetectionRow.created_at.desc(), DetectionRow.detection_pass.desc())
            .limit(1)
        )
    ).one_or_none()
    return None if row is None else (row[0], row[1])


async def fingerprints_of_pass(
    uow: UnitOfWork, run_id: UUID, detection_pass: int, *, detected_by: str
) -> list[str]:
    """The fingerprints of the Conflicts a detector stored in the run's detection pass."""
    rows = await uow.session.execute(
        select(ConflictRow.fingerprint).where(
            ConflictRow.run_id == run_id,
            ConflictRow.detection_pass == detection_pass,
            ConflictRow.detected_by == detected_by,
        )
    )
    return list(rows.scalars())


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
    """The system marks an `open` or `escalated` Conflict `resolved` with the reason; True
    when it changed. An escalation's columns stay as they were."""
    changed = await uow.session.execute(
        update(ConflictRow)
        .where(ConflictRow.id == conflict_id, ConflictRow.status.in_(["open", "escalated"]))
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


async def get(uow: UnitOfWork, conflict_id: UUID) -> ConflictRecord | None:
    row = (
        await uow.session.execute(
            select(ConflictRow)
            .where(ConflictRow.id == conflict_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return None if row is None else _conflict(row)


async def latest_with_fingerprint(
    uow: UnitOfWork, opportunity_id: UUID, fingerprint: str, *, besides: tuple[UUID, int]
) -> ConflictRecord | None:
    """The Opportunity's newest Conflict with this fingerprint, in any status, from another
    run or detection pass than `besides` (run id, pass)."""
    run_id, detection_pass = besides
    row = (
        await uow.session.execute(
            select(ConflictRow)
            .where(
                ConflictRow.opportunity_id == opportunity_id,
                ConflictRow.fingerprint == fingerprint,
                ~and_(
                    ConflictRow.run_id == run_id,
                    ConflictRow.detection_pass == detection_pass,
                ),
            )
            .order_by(ConflictRow.created_at.desc(), ConflictRow.detection_pass.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return None if row is None else _conflict(row)


async def decide(
    uow: UnitOfWork,
    conflict_id: UUID,
    *,
    expected_row_version: int,
    user_id: UUID,
    reason: str,
    chosen_position: int | None,
    entered_position: str | None,
    applied_hours: Decimal | None,
) -> int | None:
    """A person resolves an `open` or `escalated` Conflict at `expected_row_version` with
    their decision. The new row version, or None (and no change) when it is at another
    version or already resolved."""
    changed = await uow.session.execute(
        update(ConflictRow)
        .where(
            ConflictRow.id == conflict_id,
            ConflictRow.row_version == expected_row_version,
            ConflictRow.status.in_(["open", "escalated"]),
        )
        .values(
            status="resolved",
            resolution_reason=reason,
            resolved_at=func.now(),
            resolved_by=user_id,
            chosen_position=chosen_position,
            entered_position=entered_position,
            applied_hours=applied_hours,
            row_version=ConflictRow.row_version + 1,
        )
        .returning(ConflictRow.row_version)
        .execution_options(synchronize_session=False)
    )
    return changed.scalar_one_or_none()


async def escalate(
    uow: UnitOfWork,
    conflict_id: UUID,
    *,
    expected_row_version: int,
    user_id: UUID,
    reviewer_id: UUID,
    reason: str,
) -> int | None:
    """A person escalates an `open` Conflict at `expected_row_version` to a reviewer. The new
    row version, or None (and no change) when it is at another version or not open."""
    changed = await uow.session.execute(
        update(ConflictRow)
        .where(
            ConflictRow.id == conflict_id,
            ConflictRow.row_version == expected_row_version,
            ConflictRow.status == "open",
        )
        .values(
            status="escalated",
            escalated_to=reviewer_id,
            escalated_by=user_id,
            escalated_at=func.now(),
            escalation_reason=reason,
            row_version=ConflictRow.row_version + 1,
        )
        .returning(ConflictRow.row_version)
        .execution_options(synchronize_session=False)
    )
    return changed.scalar_one_or_none()


async def not_applied_kinds(uow: UnitOfWork, conflict_ids: Sequence[UUID]) -> dict[UUID, str]:
    """Per Conflict a person resolved, why its `effort` decision changed no Estimate line,
    as its `conflicts.conflict.resolved` trace event records it (only those it names)."""
    if not conflict_ids:
        return {}
    rows = await uow.session.execute(
        select(TraceEvent.subject_id, TraceEvent.payload).where(
            TraceEvent.subject_type == "conflicts.conflict",
            TraceEvent.subject_id.in_(list(conflict_ids)),
            TraceEvent.event_type == "conflicts.conflict.resolved",
        )
    )
    found: dict[UUID, str] = {}
    for subject_id, payload in rows:
        if not isinstance(payload, dict) or payload.get("reason_kind") != "decided":
            continue
        kind = payload.get("not_applied")
        if isinstance(kind, str):
            found[subject_id] = kind
    return found


async def all_conflicts(uow: UnitOfWork, opportunity_id: UUID) -> list[ConflictRecord]:
    """Every Conflict of the Opportunity, oldest first."""
    rows = await uow.session.execute(
        select(ConflictRow)
        .where(ConflictRow.opportunity_id == opportunity_id)
        .order_by(ConflictRow.created_at, ConflictRow.id)
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
            finding_id=row.finding_id,
        )
        for row in rows.scalars()
    ]
