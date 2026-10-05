"""Persistence for detections, Gaps, their Requirement links and their Clarification
Questions (Story 4.3). Runs inside the caller's Unit of Work."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, func, insert, or_, select, text, tuple_, update

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
    opportunity_id: UUID
    title: str
    category: str
    trigger: dict[str, Any]
    why_it_matters: str
    impact: str
    impact_basis: str
    origin: str
    status: str
    converted_to: str | None
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
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    edited_by_human: bool = False
    changed_by: UUID | None = None


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


def _untouched_question_or_none() -> ColumnElement[bool]:
    """True for a Gap whose question (if any) no person has edited or approved."""
    touched = (
        select(QuestionRow.id)
        .where(
            QuestionRow.gap_id == GapRow.id,
            or_(QuestionRow.edited_by_human.is_(True), QuestionRow.status == "approved"),
        )
        .exists()
    )
    return ~touched


async def supersede_detected(uow: UnitOfWork, opportunity_id: UUID) -> tuple[int, int]:
    """Mark every `open`, `detected` Gap of the Opportunity `superseded`, together with its
    Clarification Question, except those whose question a person has edited or approved
    (Story 4.5): they stay as they are. Returns how many Gaps changed and how many were
    kept. The caller holds `lock_opportunity`, which question edits take too."""
    gap_ids = list(
        (
            await uow.session.execute(
                update(GapRow)
                .where(
                    GapRow.opportunity_id == opportunity_id,
                    GapRow.status == "open",
                    GapRow.origin == "detected",
                    _untouched_question_or_none(),
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
    kept = (
        await uow.session.execute(
            select(func.count())
            .select_from(GapRow)
            .where(
                GapRow.opportunity_id == opportunity_id,
                GapRow.status == "open",
                GapRow.origin == "detected",
            )
        )
    ).scalar_one()
    return len(gap_ids), int(kept)


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


def _gap(row: GapRow) -> GapRecord:
    return GapRecord(
        id=row.id,
        opportunity_id=row.opportunity_id,
        title=row.title,
        category=row.category,
        trigger=row.trigger,
        why_it_matters=row.why_it_matters,
        impact=row.impact,
        impact_basis=row.impact_basis,
        origin=row.origin,
        status=row.status,
        converted_to=row.converted_to,
        row_version=row.row_version,
        created_at=row.created_at,
    )


async def gaps_in(uow: UnitOfWork, opportunity_id: UUID, status: str) -> list[GapRecord]:
    """The Opportunity's Gaps in `status`, oldest first (the caller ranks them)."""
    rows = await uow.session.execute(
        select(GapRow)
        .where(GapRow.opportunity_id == opportunity_id, GapRow.status == status)
        .order_by(GapRow.created_at, GapRow.id)
    )
    return [_gap(row) for row in rows.scalars()]


async def open_gaps(uow: UnitOfWork, opportunity_id: UUID) -> list[GapRecord]:
    """The Opportunity's `open` Gaps, oldest first (the caller ranks them)."""
    return await gaps_in(uow, opportunity_id, "open")


async def gaps_by_id(
    uow: UnitOfWork, opportunity_id: UUID, gap_ids: list[UUID]
) -> dict[UUID, GapRecord]:
    """These Gaps of the Opportunity, whatever their status."""
    if not gap_ids:
        return {}
    rows = await uow.session.execute(
        select(GapRow).where(GapRow.opportunity_id == opportunity_id, GapRow.id.in_(gap_ids))
    )
    return {row.id: _gap(row) for row in rows.scalars()}


async def get_gap(uow: UnitOfWork, gap_id: UUID) -> GapRecord | None:
    row = (
        await uow.session.execute(
            select(GapRow).where(GapRow.id == gap_id).execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return None if row is None else _gap(row)


async def convert_gap(uow: UnitOfWork, gap_id: UUID, *, converted_to: str) -> GapRecord | None:
    """Mark the Gap `converted` to `converted_to` if it is `open`; None (and no change)
    otherwise."""
    changed = (
        await uow.session.execute(
            update(GapRow)
            .where(GapRow.id == gap_id, GapRow.status == "open")
            .values(
                status="converted",
                converted_to=converted_to,
                row_version=GapRow.row_version + 1,
            )
            .returning(GapRow.id)
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()
    return None if changed is None else await get_gap(uow, gap_id)


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


def _question(row: QuestionRow) -> QuestionRecord:
    return QuestionRecord(
        id=row.id,
        gap_id=row.gap_id,
        text=row.text,
        topic=row.topic,
        status=row.status,
        status_changed_at=row.status_changed_at,
        row_version=row.row_version,
        approved_by=row.approved_by,
        approved_at=row.approved_at,
        edited_by_human=row.edited_by_human,
        changed_by=row.changed_by,
    )


async def questions_for(uow: UnitOfWork, gap_ids: list[UUID]) -> dict[UUID, QuestionRecord]:
    if not gap_ids:
        return {}
    rows = await uow.session.execute(
        select(QuestionRow)
        .where(QuestionRow.gap_id.in_(gap_ids))
        .execution_options(populate_existing=True)
    )
    return {row.gap_id: _question(row) for row in rows.scalars()}


async def get_question(
    uow: UnitOfWork, opportunity_id: UUID, question_id: UUID
) -> tuple[QuestionRecord, GapRecord] | None:
    """The question with its Gap, if the Gap belongs to the Opportunity."""
    found = (
        await uow.session.execute(
            select(QuestionRow, GapRow)
            .join(GapRow, GapRow.id == QuestionRow.gap_id)
            .where(QuestionRow.id == question_id, GapRow.opportunity_id == opportunity_id)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if found is None:
        return None
    question, gap = found
    return _question(question), _gap(gap)


async def drafted_questions_of_open_gaps(
    uow: UnitOfWork, opportunity_id: UUID
) -> list[QuestionRecord]:
    """The `drafted` questions of the Opportunity's `open` Gaps, oldest Gap first."""
    rows = await uow.session.execute(
        select(QuestionRow)
        .join(GapRow, GapRow.id == QuestionRow.gap_id)
        .where(
            GapRow.opportunity_id == opportunity_id,
            GapRow.status == "open",
            QuestionRow.status == "drafted",
        )
        .order_by(GapRow.created_at, GapRow.id)
        .execution_options(populate_existing=True)
    )
    return [_question(row) for row in rows.scalars()]


async def update_question(
    uow: UnitOfWork,
    question_id: UUID,
    *,
    expected_row_version: int,
    text_: str,
    topic: str,
    status: str,
    approved_by: UUID | None,
    approved_at: datetime | None,
    edited_by_human: bool,
    changed_by: UUID,
    status_changed_at: datetime | None,
) -> QuestionRecord | None:
    """Write the question's new state if it is still at `expected_row_version` and its Gap
    is still `open` (a Gap converted by `estimates` meanwhile doesn't take the gaps lock),
    bumping it; None (and no change) otherwise. `status_changed_at` is set when given (a status
    change)."""
    values: dict[str, object] = {
        "text": text_,
        "topic": topic,
        "status": status,
        "approved_by": approved_by,
        "approved_at": approved_at,
        "edited_by_human": edited_by_human,
        "changed_by": changed_by,
        "row_version": QuestionRow.row_version + 1,
    }
    if status_changed_at is not None:
        values["status_changed_at"] = status_changed_at
    changed = (
        await uow.session.execute(
            update(QuestionRow)
            .where(
                QuestionRow.id == question_id,
                QuestionRow.row_version == expected_row_version,
                select(GapRow.id)
                .where(GapRow.id == QuestionRow.gap_id, GapRow.status == "open")
                .exists(),
            )
            .values(**values)
            .returning(QuestionRow.id)
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()
    if changed is None:
        return None
    row = (
        await uow.session.execute(
            select(QuestionRow)
            .where(QuestionRow.id == question_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    return _question(row)
