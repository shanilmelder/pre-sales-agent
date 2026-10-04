"""Persistence for detections, Gaps, their Requirement links and their Clarification
Questions (Story 4.3). Runs inside the caller's Unit of Work."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select, text, tuple_, update

from app.modules.gaps.adapters.models import (
    DetectionRow,
    GapRequirementRow,
    GapRow,
    QuestionRow,
)
from app.platform.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class DetectionRecord:
    id: UUID
    opportunity_id: UUID
    status: str
    error_code: str | None
    gap_count: int | None
    dropped_count: int | None
    created_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class GapRecord:
    id: UUID
    title: str
    category: str
    trigger: dict[str, Any]
    why_it_matters: str
    impact: str
    impact_basis: str
    origin: str
    status: str
    row_version: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class GapLinkRecord:
    gap_id: UUID
    requirement_id: UUID
    requirement_version: int


@dataclass(frozen=True, slots=True)
class QuestionRecord:
    id: UUID
    gap_id: UUID
    text: str
    topic: str
    status: str
    status_changed_at: datetime
    row_version: int


# --- detections -----------------------------------------------------------------------------


async def lock_opportunity(uow: UnitOfWork, opportunity_id: UUID) -> None:
    """Serialise detection bookkeeping for one Opportunity until commit: queueing, a job
    starting, and accepting a result."""
    await uow.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"gaps.detection:{opportunity_id}"},
    )


def _detection(row: DetectionRow) -> DetectionRecord:
    return DetectionRecord(
        id=row.id,
        opportunity_id=row.opportunity_id,
        status=row.status,
        error_code=row.error_code,
        gap_count=row.gap_count,
        dropped_count=row.dropped_count,
        created_at=row.created_at,
        finished_at=row.finished_at,
    )


async def insert_detection(uow: UnitOfWork, *, detection_id: UUID, opportunity_id: UUID) -> None:
    await uow.session.execute(
        insert(DetectionRow).values(id=detection_id, opportunity_id=opportunity_id, status="queued")
    )


async def get_detection(
    uow: UnitOfWork, detection_id: UUID, *, for_update: bool = False
) -> DetectionRecord | None:
    statement = select(DetectionRow).where(DetectionRow.id == detection_id)
    if for_update:
        statement = statement.with_for_update()
    row = (await uow.session.execute(statement)).scalar_one_or_none()
    return None if row is None else _detection(row)


async def latest_detection(uow: UnitOfWork, opportunity_id: UUID) -> DetectionRecord | None:
    row = (
        await uow.session.execute(
            select(DetectionRow)
            .where(DetectionRow.opportunity_id == opportunity_id)
            .order_by(DetectionRow.created_at.desc(), DetectionRow.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return None if row is None else _detection(row)


async def detection_in(
    uow: UnitOfWork, opportunity_id: UUID, statuses: tuple[str, ...]
) -> UUID | None:
    """A detection of the Opportunity in one of `statuses` (the oldest), if any."""
    return (
        await uow.session.execute(
            select(DetectionRow.id)
            .where(
                DetectionRow.opportunity_id == opportunity_id,
                DetectionRow.status.in_(statuses),
            )
            .order_by(DetectionRow.created_at, DetectionRow.id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def newer_succeeded(uow: UnitOfWork, record: DetectionRecord) -> bool:
    """Whether a detection of the same Opportunity queued after this one has succeeded."""
    newer = await uow.session.execute(
        select(DetectionRow.id)
        .where(
            DetectionRow.opportunity_id == record.opportunity_id,
            DetectionRow.status == "succeeded",
            tuple_(DetectionRow.created_at, DetectionRow.id) > (record.created_at, record.id),
        )
        .limit(1)
    )
    return newer.first() is not None


async def fail_stale_detections(
    uow: UnitOfWork, opportunity_id: UUID, *, older_than: timedelta, error_code: str
) -> int:
    """Mark the Opportunity's detections still `queued` or `running` after `older_than`
    `failed` with `error_code`. Returns how many changed."""
    result = await uow.session.execute(
        update(DetectionRow)
        .where(
            DetectionRow.opportunity_id == opportunity_id,
            DetectionRow.status.in_(("queued", "running")),
            DetectionRow.created_at < func.now() - older_than,
        )
        .values(status="failed", error_code=error_code, finished_at=func.now())
        .returning(DetectionRow.id)
        .execution_options(synchronize_session=False)
    )
    return len(result.all())


async def update_detection(
    uow: UnitOfWork,
    detection_id: UUID,
    *,
    from_statuses: tuple[str, ...],
    status: str,
    error_code: str | None = None,
    gap_count: int | None = None,
    dropped_count: int | None = None,
    finished: bool = False,
) -> bool:
    """Move the detection to `status` if it is in one of `from_statuses`. Counts left None
    keep their value. False (and no change) otherwise."""
    values: dict[str, object] = {"status": status, "error_code": error_code}
    if gap_count is not None:
        values["gap_count"] = gap_count
    if dropped_count is not None:
        values["dropped_count"] = dropped_count
    if finished:
        values["finished_at"] = func.now()
    result = await uow.session.execute(
        update(DetectionRow)
        .where(DetectionRow.id == detection_id, DetectionRow.status.in_(from_statuses))
        .values(**values)
        .returning(DetectionRow.id)
        .execution_options(synchronize_session=False)
    )
    return result.one_or_none() is not None


# --- Gaps -----------------------------------------------------------------------------------


async def supersede_detected(uow: UnitOfWork, opportunity_id: UUID) -> int:
    """Mark every `open`, `detected` Gap of the Opportunity `superseded`, together with its
    Clarification Question. Returns how many Gaps changed."""
    gap_ids = list(
        (
            await uow.session.execute(
                update(GapRow)
                .where(
                    GapRow.opportunity_id == opportunity_id,
                    GapRow.status == "open",
                    GapRow.origin == "detected",
                )
                .values(status="superseded", row_version=GapRow.row_version + 1)
                .returning(GapRow.id)
                .execution_options(synchronize_session=False)
            )
        ).scalars()
    )
    if gap_ids:
        await uow.session.execute(
            update(QuestionRow)
            .where(QuestionRow.gap_id.in_(gap_ids), QuestionRow.status != "superseded")
            .values(
                status="superseded",
                status_changed_at=func.now(),
                row_version=QuestionRow.row_version + 1,
            )
            .execution_options(synchronize_session=False)
        )
    return len(gap_ids)


async def insert_gap(
    uow: UnitOfWork,
    *,
    gap_id: UUID,
    opportunity_id: UUID,
    title: str,
    category: str,
    trigger: dict[str, Any],
    why_it_matters: str,
    impact: str,
    impact_basis: str,
    detection_id: UUID,
    requirements: list[tuple[UUID, int]],
    question_id: UUID,
    question_text: str,
    question_topic: str,
) -> None:
    """An `open`, `detected` Gap, its Requirement links `(id, version)` and its `drafted`
    Clarification Question."""
    await uow.session.execute(
        insert(GapRow).values(
            id=gap_id,
            opportunity_id=opportunity_id,
            title=title,
            category=category,
            trigger=trigger,
            why_it_matters=why_it_matters,
            impact=impact,
            impact_basis=impact_basis,
            origin="detected",
            status="open",
            detection_id=detection_id,
            row_version=1,
        )
    )
    await uow.session.execute(
        insert(GapRequirementRow),
        [
            {"gap_id": gap_id, "requirement_id": rid, "requirement_version": version}
            for rid, version in requirements
        ],
    )
    await uow.session.execute(
        insert(QuestionRow).values(
            id=question_id,
            gap_id=gap_id,
            text=question_text,
            topic=question_topic,
            status="drafted",
            row_version=1,
        )
    )


async def open_gaps(uow: UnitOfWork, opportunity_id: UUID) -> list[GapRecord]:
    """The Opportunity's `open` Gaps, oldest first (the caller ranks them)."""
    rows = await uow.session.execute(
        select(GapRow)
        .where(GapRow.opportunity_id == opportunity_id, GapRow.status == "open")
        .order_by(GapRow.created_at, GapRow.id)
    )
    return [
        GapRecord(
            id=row.id,
            title=row.title,
            category=row.category,
            trigger=row.trigger,
            why_it_matters=row.why_it_matters,
            impact=row.impact,
            impact_basis=row.impact_basis,
            origin=row.origin,
            status=row.status,
            row_version=row.row_version,
            created_at=row.created_at,
        )
        for row in rows.scalars()
    ]


async def links_for(uow: UnitOfWork, gap_ids: list[UUID]) -> list[GapLinkRecord]:
    if not gap_ids:
        return []
    rows = await uow.session.execute(
        select(GapRequirementRow).where(GapRequirementRow.gap_id.in_(gap_ids))
    )
    return [
        GapLinkRecord(
            gap_id=row.gap_id,
            requirement_id=row.requirement_id,
            requirement_version=row.requirement_version,
        )
        for row in rows.scalars()
    ]


async def questions_for(uow: UnitOfWork, gap_ids: list[UUID]) -> dict[UUID, QuestionRecord]:
    if not gap_ids:
        return {}
    rows = await uow.session.execute(select(QuestionRow).where(QuestionRow.gap_id.in_(gap_ids)))
    return {
        row.gap_id: QuestionRecord(
            id=row.id,
            gap_id=row.gap_id,
            text=row.text,
            topic=row.topic,
            status=row.status,
            status_changed_at=row.status_changed_at,
            row_version=row.row_version,
        )
        for row in rows.scalars()
    }
