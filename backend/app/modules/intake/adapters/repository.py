"""Persistence for Opportunity Sources, their versions and their parse state. Runs inside the
caller's Unit of Work."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Row, Select, func, insert, select, text, update

from app.modules.intake.adapters.models import SourceParseRow, SourceRow, SourceVersionRow
from app.platform.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """A Source with its latest version."""

    id: UUID
    opportunity_id: UUID
    kind: str
    created_at: datetime
    version: int
    version_count: int
    filename: str
    size_bytes: int
    uploaded_by: UUID
    uploaded_at: datetime
    parse_status: str | None
    parse_error_code: str | None


async def lock_content(uow: UnitOfWork, opportunity_id: UUID, sha256: str) -> None:
    """Serialise adds of the same bytes to the same Opportunity until commit, so concurrent
    identical uploads become consecutive versions of one Source."""
    await uow.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"intake.source:{opportunity_id}:{sha256}"},
    )


async def source_with_content(uow: UnitOfWork, opportunity_id: UUID, sha256: str) -> UUID | None:
    """The Opportunity's Source that already holds these bytes in one of its versions."""
    return (
        await uow.session.execute(
            select(SourceVersionRow.source_id)
            .join(SourceRow, SourceRow.id == SourceVersionRow.source_id)
            .where(
                SourceRow.opportunity_id == opportunity_id, SourceVersionRow.file_sha256 == sha256
            )
            .order_by(SourceRow.created_at, SourceRow.id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def insert_source(
    uow: UnitOfWork, *, source_id: UUID, opportunity_id: UUID, kind: str, created_by: UUID
) -> None:
    await uow.session.execute(
        insert(SourceRow).values(
            id=source_id,
            opportunity_id=opportunity_id,
            kind=kind,
            created_by=created_by,
            row_version=1,
        )
    )


async def next_version(uow: UnitOfWork, source_id: UUID) -> tuple[int, str]:
    """Bump the Source's `row_version` (row-locking it until commit) and return the number
    its next version gets, with the Source's kind."""
    kind = (
        await uow.session.execute(
            update(SourceRow)
            .where(SourceRow.id == source_id)
            .values(row_version=SourceRow.row_version + 1)
            .returning(SourceRow.kind)
            .execution_options(synchronize_session=False)
        )
    ).scalar_one()
    latest = (
        await uow.session.execute(
            select(func.max(SourceVersionRow.version)).where(
                SourceVersionRow.source_id == source_id
            )
        )
    ).scalar_one()
    return (latest or 0) + 1, kind


async def insert_version(
    uow: UnitOfWork,
    *,
    source_id: UUID,
    version: int,
    file_sha256: str,
    filename: str,
    size_bytes: int,
    uploaded_by: UUID,
) -> None:
    await uow.session.execute(
        insert(SourceVersionRow).values(
            source_id=source_id,
            version=version,
            file_sha256=file_sha256,
            filename=filename,
            size_bytes=size_bytes,
            uploaded_by=uploaded_by,
        )
    )


def _latest_query() -> Select[Any]:
    counts = (
        select(
            SourceVersionRow.source_id.label("source_id"),
            func.max(SourceVersionRow.version).label("latest"),
            func.count().label("version_count"),
        )
        .group_by(SourceVersionRow.source_id)
        .subquery("counts")
    )
    return (
        select(
            SourceRow.id,
            SourceRow.opportunity_id,
            SourceRow.kind,
            SourceRow.created_at,
            SourceVersionRow.version,
            counts.c.version_count,
            SourceVersionRow.filename,
            SourceVersionRow.size_bytes,
            SourceVersionRow.uploaded_by,
            SourceVersionRow.uploaded_at,
            SourceParseRow.status.label("parse_status"),
            SourceParseRow.error_code.label("parse_error_code"),
        )
        .join(counts, counts.c.source_id == SourceRow.id)
        .join(
            SourceVersionRow,
            (SourceVersionRow.source_id == SourceRow.id)
            & (SourceVersionRow.version == counts.c.latest),
        )
        .outerjoin(
            SourceParseRow,
            (SourceParseRow.source_id == SourceVersionRow.source_id)
            & (SourceParseRow.version == SourceVersionRow.version),
        )
    )


def _record(row: Row[Any]) -> SourceRecord:
    return SourceRecord(
        id=row.id,
        opportunity_id=row.opportunity_id,
        kind=row.kind,
        created_at=row.created_at,
        version=row.version,
        version_count=row.version_count,
        filename=row.filename,
        size_bytes=row.size_bytes,
        uploaded_by=row.uploaded_by,
        uploaded_at=row.uploaded_at,
        parse_status=row.parse_status,
        parse_error_code=row.parse_error_code,
    )


async def get(uow: UnitOfWork, source_id: UUID) -> SourceRecord | None:
    row = (
        await uow.session.execute(_latest_query().where(SourceRow.id == source_id))
    ).one_or_none()
    return None if row is None else _record(row)


async def list_for(uow: UnitOfWork, opportunity_id: UUID) -> list[SourceRecord]:
    """The Opportunity's Sources, newest first, each with its latest version."""
    rows = await uow.session.execute(
        _latest_query()
        .where(SourceRow.opportunity_id == opportunity_id)
        .order_by(SourceRow.created_at.desc(), SourceRow.id.desc())
    )
    return [_record(row) for row in rows]


# --- parse state (Story 2.2 Part B) ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParseTarget:
    """What the parse job needs about one Source version."""

    source_id: UUID
    version: int
    opportunity_id: UUID
    file_sha256: str
    filename: str
    status: str


@dataclass(frozen=True, slots=True)
class ParseState:
    status: str
    error_code: str | None
    text_sha256: str | None
    char_count: int | None


async def insert_parse(uow: UnitOfWork, *, source_id: UUID, version: int) -> None:
    """The version's parse row, `queued`."""
    await uow.session.execute(
        insert(SourceParseRow).values(
            source_id=source_id, version=version, status="queued", row_version=1
        )
    )


async def parse_target(uow: UnitOfWork, source_id: UUID, version: int) -> ParseTarget | None:
    row = (
        await uow.session.execute(
            select(
                SourceVersionRow.source_id,
                SourceVersionRow.version,
                SourceRow.opportunity_id,
                SourceVersionRow.file_sha256,
                SourceVersionRow.filename,
                SourceParseRow.status,
            )
            .join(SourceRow, SourceRow.id == SourceVersionRow.source_id)
            .join(
                SourceParseRow,
                (SourceParseRow.source_id == SourceVersionRow.source_id)
                & (SourceParseRow.version == SourceVersionRow.version),
            )
            .where(SourceVersionRow.source_id == source_id, SourceVersionRow.version == version)
        )
    ).one_or_none()
    if row is None:
        return None
    return ParseTarget(
        source_id=row.source_id,
        version=row.version,
        opportunity_id=row.opportunity_id,
        file_sha256=row.file_sha256,
        filename=row.filename,
        status=row.status,
    )


async def parse_state(
    uow: UnitOfWork, source_id: UUID, version: int, *, for_update: bool = False
) -> ParseState | None:
    statement = select(
        SourceParseRow.status,
        SourceParseRow.error_code,
        SourceParseRow.text_sha256,
        SourceParseRow.char_count,
    ).where(SourceParseRow.source_id == source_id, SourceParseRow.version == version)
    if for_update:
        statement = statement.with_for_update()
    row = (await uow.session.execute(statement)).one_or_none()
    if row is None:
        return None
    return ParseState(
        status=row.status,
        error_code=row.error_code,
        text_sha256=row.text_sha256,
        char_count=row.char_count,
    )


async def update_parse(
    uow: UnitOfWork,
    source_id: UUID,
    version: int,
    *,
    from_statuses: tuple[str, ...],
    status: str,
    error_code: str | None = None,
    text_sha256: str | None = None,
    char_count: int | None = None,
    parser: str | None = None,
) -> bool:
    """Move the parse row to `status` if it is in one of `from_statuses`, bumping its
    `row_version`. False (and no change) otherwise."""
    result = await uow.session.execute(
        update(SourceParseRow)
        .where(
            SourceParseRow.source_id == source_id,
            SourceParseRow.version == version,
            SourceParseRow.status.in_(from_statuses),
        )
        .values(
            status=status,
            error_code=error_code,
            text_sha256=text_sha256,
            char_count=char_count,
            parser=parser,
            updated_at=func.now(),
            row_version=SourceParseRow.row_version + 1,
        )
        .returning(SourceParseRow.version)
        .execution_options(synchronize_session=False)
    )
    return result.one_or_none() is not None
