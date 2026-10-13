"""Persistence for Opportunity imports (Story 1.7, import from file). Runs inside the caller's
Unit of Work. `psa_app` may only update `status`, `error_code`, `suggestions` and
`consumed_at`, and never deletes."""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select, update

from app.modules.opportunities.adapters.models import ImportRow
from app.platform.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class ImportRecord:
    id: UUID
    uploaded_by: UUID
    file_sha256: str
    size_bytes: int
    filename: str
    status: str
    error_code: str | None
    suggestions: dict[str, Any] | None
    created_at: datetime
    consumed_at: datetime | None


def _record(row: ImportRow) -> ImportRecord:
    return ImportRecord(
        id=row.id,
        uploaded_by=row.uploaded_by,
        file_sha256=row.file_sha256,
        size_bytes=row.size_bytes,
        filename=row.filename,
        status=row.status,
        error_code=row.error_code,
        suggestions=row.suggestions,
        created_at=row.created_at,
        consumed_at=row.consumed_at,
    )


async def insert_import(
    uow: UnitOfWork,
    *,
    import_id: UUID,
    uploaded_by: UUID,
    file_sha256: str,
    size_bytes: int,
    filename: str,
) -> None:
    await uow.session.execute(
        insert(ImportRow).values(
            id=import_id,
            uploaded_by=uploaded_by,
            file_sha256=file_sha256,
            size_bytes=size_bytes,
            filename=filename,
            status="queued",
        )
    )


async def get(uow: UnitOfWork, import_id: UUID, *, for_update: bool = False) -> ImportRecord | None:
    statement = select(ImportRow).where(ImportRow.id == import_id)
    if for_update:
        statement = statement.with_for_update()
    row = (await uow.session.execute(statement)).scalar_one_or_none()
    return None if row is None else _record(row)


async def now(uow: UnitOfWork) -> datetime:
    """The database's transaction time (what `created_at` defaults to)."""
    value: datetime = (await uow.session.execute(select(func.now()))).scalar_one()
    return value


async def update_status(
    uow: UnitOfWork,
    import_id: UUID,
    *,
    from_statuses: Collection[str],
    status: str,
    error_code: str | None = None,
    suggestions: dict[str, Any] | None = None,
) -> bool:
    """Move the import to `status` if it is in one of `from_statuses`. Returns whether it
    changed."""
    values: dict[str, Any] = {"status": status, "error_code": error_code}
    if suggestions is not None:
        values["suggestions"] = suggestions
    result = await uow.session.execute(
        update(ImportRow)
        .where(ImportRow.id == import_id, ImportRow.status.in_(list(from_statuses)))
        .values(**values)
        .returning(ImportRow.id)
    )
    return result.first() is not None


async def consume(uow: UnitOfWork, import_id: UUID) -> bool:
    """Mark the import used, once. Returns False when it already was."""
    result = await uow.session.execute(
        update(ImportRow)
        .where(ImportRow.id == import_id, ImportRow.consumed_at.is_(None))
        .values(consumed_at=func.now())
        .returning(ImportRow.id)
    )
    return result.first() is not None
