"""Persistence for Actuals and Close delivery (Story 10.1) and Actuals imports (Story 10.2).
Runs inside the caller's Unit of Work. Actual and delivery rows are only inserted; the one
change ever made is clearing `is_current` on the version a correction replaces. An import's
status, rows and apply counts change as it moves through its states; it is never deleted."""

from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select, update

from app.modules.actuals.adapters.models import ActualRow, DeliveryRow, ImportRow
from app.platform.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class ActualRecord:
    id: UUID
    opportunity_id: UUID
    estimate_version_id: UUID
    estimate_line_id: UUID | None
    actual_group_id: UUID
    version: int
    is_current: bool
    kind: str
    effort_hours: Decimal
    recorded_by: UUID
    recorded_at: datetime
    row_version: int = 1
    integration_type_ids: tuple[UUID, ...] = ()
    work_package_id: UUID | None = None
    milestone_label: str | None = None
    duration_days: Decimal | None = None
    cost_minor: int | None = None
    currency: str | None = None
    variance_cause: str | None = None
    failed_assumptions: tuple[tuple[UUID, int], ...] = ()
    note: str | None = None
    correction_reason: str | None = None


@dataclass(frozen=True, slots=True)
class NewActual:
    id: UUID
    opportunity_id: UUID
    estimate_version_id: UUID
    estimate_line_id: UUID | None
    actual_group_id: UUID
    version: int
    kind: str
    effort_hours: Decimal
    recorded_by: UUID
    integration_type_ids: list[UUID] = field(default_factory=list)
    work_package_id: UUID | None = None
    milestone_label: str | None = None
    duration_days: Decimal | None = None
    cost_minor: int | None = None
    currency: str | None = None
    variance_cause: str | None = None
    failed_assumptions: list[tuple[UUID, int]] = field(default_factory=list)
    note: str | None = None
    correction_reason: str | None = None


@dataclass(frozen=True, slots=True)
class DeliveryRecord:
    id: UUID
    opportunity_id: UUID
    estimate_version_id: UUID
    closed_by: UUID
    closed_at: datetime


def _refs(value: list[dict[str, Any]]) -> tuple[tuple[UUID, int], ...]:
    return tuple((UUID(str(r["assumption_id"])), int(r["version"])) for r in value)


def _actual(row: ActualRow) -> ActualRecord:
    return ActualRecord(
        id=row.id,
        opportunity_id=row.opportunity_id,
        estimate_version_id=row.estimate_version_id,
        estimate_line_id=row.estimate_line_id,
        actual_group_id=row.actual_group_id,
        version=row.version,
        is_current=row.is_current,
        kind=row.kind,
        effort_hours=row.effort_hours,
        recorded_by=row.recorded_by,
        recorded_at=row.recorded_at,
        row_version=row.row_version,
        integration_type_ids=tuple(row.integration_type_ids or ()),
        work_package_id=row.work_package_id,
        milestone_label=row.milestone_label,
        duration_days=row.duration_days,
        cost_minor=row.cost_minor,
        currency=row.currency,
        variance_cause=row.variance_cause,
        failed_assumptions=_refs(row.failed_assumptions or []),
        note=row.note,
        correction_reason=row.correction_reason,
    )


async def actuals_of(
    uow: UnitOfWork, opportunity_id: UUID, *, current_only: bool = False
) -> list[ActualRecord]:
    """The Opportunity's Actuals, oldest first (each group's versions in order)."""
    statement = (
        select(ActualRow)
        .where(ActualRow.opportunity_id == opportunity_id)
        .order_by(ActualRow.recorded_at, ActualRow.actual_group_id, ActualRow.version)
        .execution_options(populate_existing=True)
    )
    if current_only:
        statement = statement.where(ActualRow.is_current.is_(True))
    rows = await uow.session.execute(statement)
    return [_actual(row) for row in rows.scalars()]


async def get_actual(uow: UnitOfWork, actual_id: UUID) -> ActualRecord | None:
    row = (
        await uow.session.execute(
            select(ActualRow)
            .where(ActualRow.id == actual_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return None if row is None else _actual(row)


async def change_count(uow: UnitOfWork, opportunity_id: UUID) -> int:
    """How many Actual versions and deliveries the Opportunity has: rows are only ever
    inserted, so this grows with every write and serves as the Actuals tab's ETag."""
    actuals = select(func.count()).where(ActualRow.opportunity_id == opportunity_id)
    deliveries = select(func.count()).where(DeliveryRow.opportunity_id == opportunity_id)
    found = (
        await uow.session.execute(select(actuals.scalar_subquery(), deliveries.scalar_subquery()))
    ).one()
    return int(found[0]) + int(found[1])


async def retire(uow: UnitOfWork, actual_id: UUID) -> bool:
    """Clear `is_current` on the Actual a correction replaces; False if it wasn't current."""
    result = await uow.session.execute(
        update(ActualRow)
        .where(ActualRow.id == actual_id, ActualRow.is_current.is_(True))
        .values(is_current=False)
        .returning(ActualRow.id)
    )
    return result.scalar_one_or_none() is not None


async def insert_actual(uow: UnitOfWork, new: NewActual) -> ActualRecord:
    """A new current Actual version, recorded now (clock time, after the caller's lock)."""
    await uow.session.execute(
        insert(ActualRow).values(
            id=new.id,
            opportunity_id=new.opportunity_id,
            estimate_version_id=new.estimate_version_id,
            estimate_line_id=new.estimate_line_id,
            actual_group_id=new.actual_group_id,
            version=new.version,
            is_current=True,
            integration_type_ids=new.integration_type_ids,
            work_package_id=new.work_package_id,
            kind=new.kind,
            milestone_label=new.milestone_label,
            effort_hours=new.effort_hours,
            duration_days=new.duration_days,
            cost_minor=new.cost_minor,
            currency=new.currency,
            variance_cause=new.variance_cause,
            failed_assumptions=[
                {"assumption_id": str(a), "version": v} for a, v in new.failed_assumptions
            ],
            note=new.note,
            correction_reason=new.correction_reason,
            row_version=1,
            recorded_by=new.recorded_by,
            recorded_at=func.clock_timestamp(),
        )
    )
    stored = await get_actual(uow, new.id)
    assert stored is not None
    return stored


def _delivery(row: DeliveryRow) -> DeliveryRecord:
    return DeliveryRecord(
        id=row.id,
        opportunity_id=row.opportunity_id,
        estimate_version_id=row.estimate_version_id,
        closed_by=row.closed_by,
        closed_at=row.closed_at,
    )


async def get_delivery(uow: UnitOfWork, opportunity_id: UUID) -> DeliveryRecord | None:
    row = (
        await uow.session.execute(
            select(DeliveryRow).where(DeliveryRow.opportunity_id == opportunity_id)
        )
    ).scalar_one_or_none()
    return None if row is None else _delivery(row)


async def insert_delivery(
    uow: UnitOfWork,
    *,
    delivery_id: UUID,
    opportunity_id: UUID,
    estimate_version_id: UUID,
    closed_by: UUID,
) -> DeliveryRecord:
    await uow.session.execute(
        insert(DeliveryRow).values(
            id=delivery_id,
            opportunity_id=opportunity_id,
            estimate_version_id=estimate_version_id,
            closed_by=closed_by,
            closed_at=func.clock_timestamp(),
        )
    )
    stored = await get_delivery(uow, opportunity_id)
    assert stored is not None
    return stored


# --- imports (Story 10.2) -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ImportRecord:
    id: UUID
    opportunity_id: UUID
    uploaded_by: UUID
    file_sha256: str
    size_bytes: int
    filename: str
    file_kind: str
    status: str
    error_code: str | None
    rows: list[dict[str, Any]] | None
    created_at: datetime
    applied_at: datetime | None = None
    applied_by: UUID | None = None
    created_count: int | None = None
    corrected_count: int | None = None
    excluded_count: int | None = None
    skipped_count: int | None = None


def _import(row: ImportRow) -> ImportRecord:
    return ImportRecord(
        id=row.id,
        opportunity_id=row.opportunity_id,
        uploaded_by=row.uploaded_by,
        file_sha256=row.file_sha256,
        size_bytes=row.size_bytes,
        filename=row.filename,
        file_kind=row.file_kind,
        status=row.status,
        error_code=row.error_code,
        rows=row.rows,
        created_at=row.created_at,
        applied_at=row.applied_at,
        applied_by=row.applied_by,
        created_count=row.created_count,
        corrected_count=row.corrected_count,
        excluded_count=row.excluded_count,
        skipped_count=row.skipped_count,
    )


async def insert_import(
    uow: UnitOfWork,
    *,
    import_id: UUID,
    opportunity_id: UUID,
    uploaded_by: UUID,
    file_sha256: str,
    size_bytes: int,
    filename: str,
    file_kind: str,
) -> None:
    await uow.session.execute(
        insert(ImportRow).values(
            id=import_id,
            opportunity_id=opportunity_id,
            uploaded_by=uploaded_by,
            file_sha256=file_sha256,
            size_bytes=size_bytes,
            filename=filename,
            file_kind=file_kind,
            status="queued",
            created_at=func.clock_timestamp(),
        )
    )


async def get_import(
    uow: UnitOfWork, import_id: UUID, *, for_update: bool = False
) -> ImportRecord | None:
    statement = (
        select(ImportRow).where(ImportRow.id == import_id).execution_options(populate_existing=True)
    )
    if for_update:
        statement = statement.with_for_update()
    row = (await uow.session.execute(statement)).scalar_one_or_none()
    return None if row is None else _import(row)


async def latest_import(uow: UnitOfWork, opportunity_id: UUID) -> ImportRecord | None:
    """The Opportunity's most recent import, whatever its status."""
    row = (
        await uow.session.execute(
            select(ImportRow)
            .where(ImportRow.opportunity_id == opportunity_id)
            .order_by(ImportRow.created_at.desc(), ImportRow.id.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return None if row is None else _import(row)


async def applied_with_sha(
    uow: UnitOfWork, opportunity_id: UUID, file_sha256: str, *, excluding: UUID
) -> ImportRecord | None:
    """The earliest applied import of the same file on the Opportunity, other than
    `excluding`."""
    row = (
        await uow.session.execute(
            select(ImportRow)
            .where(
                ImportRow.opportunity_id == opportunity_id,
                ImportRow.file_sha256 == file_sha256,
                ImportRow.status == "applied",
                ImportRow.id != excluding,
            )
            .order_by(ImportRow.applied_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    return None if row is None else _import(row)


async def update_import_status(
    uow: UnitOfWork,
    import_id: UUID,
    *,
    from_statuses: Collection[str],
    status: str,
    error_code: str | None = None,
    rows: list[dict[str, Any]] | None = None,
) -> bool:
    """Move the import to `status` if it is in one of `from_statuses` (`rows` set when
    given). Returns whether it changed."""
    values: dict[str, Any] = {"status": status, "error_code": error_code}
    if rows is not None:
        values["rows"] = rows
    result = await uow.session.execute(
        update(ImportRow)
        .where(ImportRow.id == import_id, ImportRow.status.in_(list(from_statuses)))
        .values(**values)
        .returning(ImportRow.id)
    )
    return result.first() is not None


async def mark_applied(
    uow: UnitOfWork,
    import_id: UUID,
    *,
    applied_by: UUID,
    created: int,
    corrected: int,
    excluded: int,
    skipped: int,
) -> bool:
    """`parsed -> applied`, once, with who applied it and the counts."""
    result = await uow.session.execute(
        update(ImportRow)
        .where(ImportRow.id == import_id, ImportRow.status == "parsed")
        .values(
            status="applied",
            applied_at=func.clock_timestamp(),
            applied_by=applied_by,
            created_count=created,
            corrected_count=corrected,
            excluded_count=excluded,
            skipped_count=skipped,
        )
        .returning(ImportRow.id)
    )
    return result.first() is not None
