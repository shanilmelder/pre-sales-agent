"""Persistence for drafts, Estimate Versions, their lines and the lines' Requirement links
(Story 8.1). Runs inside the caller's Unit of Work."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select, text, tuple_, update

from app.modules.estimates.adapters.models import (
    DraftRow,
    EstimateLineRow,
    EstimateVersionRow,
    LineRequirementRow,
)
from app.platform.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class DraftRecord:
    id: UUID
    opportunity_id: UUID
    status: str
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class VersionRecord:
    id: UUID
    opportunity_id: UUID
    version: int
    status: str
    template_version: str
    uncovered_count: int
    dropped_count: int
    row_version: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class LineRecord:
    id: UUID
    position: int
    section: str
    title: str
    effort_hours: Decimal
    role_mix: dict[str, Any]
    basis: str


@dataclass(frozen=True, slots=True)
class LineLinkRecord:
    line_id: UUID
    requirement_id: UUID
    requirement_version: int


@dataclass(frozen=True, slots=True)
class NewLine:
    line_id: UUID
    position: int
    section: str
    title: str
    effort_hours: Decimal
    role_mix: dict[str, int]
    basis: str
    requirements: list[tuple[UUID, int]]


# --- drafts ---------------------------------------------------------------------------------


async def lock_opportunity(uow: UnitOfWork, opportunity_id: UUID) -> None:
    """Serialise the Opportunity's Estimate drafting until commit: queueing, a job starting,
    and accepting a result (which numbers and supersedes versions)."""
    await uow.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"estimates.draft:{opportunity_id}"},
    )


def _draft(row: DraftRow) -> DraftRecord:
    return DraftRecord(
        id=row.id,
        opportunity_id=row.opportunity_id,
        status=row.status,
        error_code=row.error_code,
        created_at=row.created_at,
        finished_at=row.finished_at,
    )


async def insert_draft(uow: UnitOfWork, *, draft_id: UUID, opportunity_id: UUID) -> None:
    await uow.session.execute(
        insert(DraftRow).values(id=draft_id, opportunity_id=opportunity_id, status="queued")
    )


async def get_draft(
    uow: UnitOfWork, draft_id: UUID, *, for_update: bool = False
) -> DraftRecord | None:
    statement = select(DraftRow).where(DraftRow.id == draft_id)
    if for_update:
        statement = statement.with_for_update()
    row = (await uow.session.execute(statement)).scalar_one_or_none()
    return None if row is None else _draft(row)


async def latest_draft(uow: UnitOfWork, opportunity_id: UUID) -> DraftRecord | None:
    row = (
        await uow.session.execute(
            select(DraftRow)
            .where(DraftRow.opportunity_id == opportunity_id)
            .order_by(DraftRow.created_at.desc(), DraftRow.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return None if row is None else _draft(row)


async def draft_in(uow: UnitOfWork, opportunity_id: UUID, statuses: tuple[str, ...]) -> UUID | None:
    """A draft of the Opportunity in one of `statuses` (the oldest), if any."""
    return (
        await uow.session.execute(
            select(DraftRow.id)
            .where(DraftRow.opportunity_id == opportunity_id, DraftRow.status.in_(statuses))
            .order_by(DraftRow.created_at, DraftRow.id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def newer_succeeded(uow: UnitOfWork, record: DraftRecord) -> bool:
    """Whether a draft of the same Opportunity queued after this one has succeeded."""
    newer = await uow.session.execute(
        select(DraftRow.id)
        .where(
            DraftRow.opportunity_id == record.opportunity_id,
            DraftRow.status == "succeeded",
            tuple_(DraftRow.created_at, DraftRow.id) > (record.created_at, record.id),
        )
        .limit(1)
    )
    return newer.first() is not None


async def fail_stale_drafts(
    uow: UnitOfWork, opportunity_id: UUID, *, older_than: timedelta, error_code: str
) -> int:
    """Mark the Opportunity's drafts still `queued` or `running` after `older_than` `failed`
    with `error_code`. Returns how many changed."""
    result = await uow.session.execute(
        update(DraftRow)
        .where(
            DraftRow.opportunity_id == opportunity_id,
            DraftRow.status.in_(("queued", "running")),
            DraftRow.created_at < func.now() - older_than,
        )
        .values(status="failed", error_code=error_code, finished_at=func.now())
        .returning(DraftRow.id)
        .execution_options(synchronize_session=False)
    )
    return len(result.all())


async def update_draft(
    uow: UnitOfWork,
    draft_id: UUID,
    *,
    from_statuses: tuple[str, ...],
    status: str,
    error_code: str | None = None,
    finished: bool = False,
) -> bool:
    """Move the draft to `status` if it is in one of `from_statuses`. False (and no change)
    otherwise."""
    values: dict[str, object] = {"status": status, "error_code": error_code}
    if finished:
        values["finished_at"] = func.now()
    result = await uow.session.execute(
        update(DraftRow)
        .where(DraftRow.id == draft_id, DraftRow.status.in_(from_statuses))
        .values(**values)
        .returning(DraftRow.id)
        .execution_options(synchronize_session=False)
    )
    return result.one_or_none() is not None


# --- Estimate Versions ----------------------------------------------------------------------


def _version(row: EstimateVersionRow) -> VersionRecord:
    return VersionRecord(
        id=row.id,
        opportunity_id=row.opportunity_id,
        version=row.version,
        status=row.status,
        template_version=row.template_version,
        uncovered_count=row.uncovered_count,
        dropped_count=row.dropped_count,
        row_version=row.row_version,
        created_at=row.created_at,
    )


async def latest_version_number(uow: UnitOfWork, opportunity_id: UUID) -> int:
    """The Opportunity's highest version number, 0 before the first."""
    found = (
        await uow.session.execute(
            select(func.max(EstimateVersionRow.version)).where(
                EstimateVersionRow.opportunity_id == opportunity_id
            )
        )
    ).scalar_one_or_none()
    return found or 0


async def supersede_drafts(uow: UnitOfWork, opportunity_id: UUID) -> int:
    """Mark the Opportunity's `draft` version `superseded`. Returns how many changed."""
    result = await uow.session.execute(
        update(EstimateVersionRow)
        .where(
            EstimateVersionRow.opportunity_id == opportunity_id,
            EstimateVersionRow.status == "draft",
        )
        .values(status="superseded", row_version=EstimateVersionRow.row_version + 1)
        .returning(EstimateVersionRow.id)
        .execution_options(synchronize_session=False)
    )
    return len(result.all())


async def insert_version(
    uow: UnitOfWork,
    *,
    version_id: UUID,
    opportunity_id: UUID,
    version: int,
    template_version: str,
    uncovered_count: int,
    dropped_count: int,
    lines: list[NewLine],
) -> None:
    """A `draft` Estimate Version with its lines and their Requirement links."""
    await uow.session.execute(
        insert(EstimateVersionRow).values(
            id=version_id,
            opportunity_id=opportunity_id,
            version=version,
            status="draft",
            template_version=template_version,
            uncovered_count=uncovered_count,
            dropped_count=dropped_count,
            row_version=1,
        )
    )
    if not lines:
        return
    await uow.session.execute(
        insert(EstimateLineRow),
        [
            {
                "id": line.line_id,
                "version_id": version_id,
                "position": line.position,
                "section": line.section,
                "title": line.title,
                "effort_hours": line.effort_hours,
                "role_mix": line.role_mix,
                "basis": line.basis,
            }
            for line in lines
        ],
    )
    await uow.session.execute(
        insert(LineRequirementRow),
        [
            {"line_id": line.line_id, "requirement_id": rid, "requirement_version": version}
            for line in lines
            for rid, version in line.requirements
        ],
    )


async def current_version(uow: UnitOfWork, opportunity_id: UUID) -> VersionRecord | None:
    """The Opportunity's `draft` version, if any (the default view hides superseded ones)."""
    row = (
        await uow.session.execute(
            select(EstimateVersionRow)
            .where(
                EstimateVersionRow.opportunity_id == opportunity_id,
                EstimateVersionRow.status == "draft",
            )
            .order_by(EstimateVersionRow.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return None if row is None else _version(row)


async def lines_of(uow: UnitOfWork, version_id: UUID) -> list[LineRecord]:
    rows = await uow.session.execute(
        select(EstimateLineRow)
        .where(EstimateLineRow.version_id == version_id)
        .order_by(EstimateLineRow.position)
    )
    return [
        LineRecord(
            id=row.id,
            position=row.position,
            section=row.section,
            title=row.title,
            effort_hours=row.effort_hours,
            role_mix=row.role_mix,
            basis=row.basis,
        )
        for row in rows.scalars()
    ]


async def links_for(uow: UnitOfWork, line_ids: list[UUID]) -> list[LineLinkRecord]:
    if not line_ids:
        return []
    rows = await uow.session.execute(
        select(LineRequirementRow).where(LineRequirementRow.line_id.in_(line_ids))
    )
    return [
        LineLinkRecord(
            line_id=row.line_id,
            requirement_id=row.requirement_id,
            requirement_version=row.requirement_version,
        )
        for row in rows.scalars()
    ]
