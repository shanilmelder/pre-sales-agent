"""Persistence for Knowledge Sources, their versions, tags and parse state (Story 3.2).
Runs inside the caller's Unit of Work."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Select, delete, exists, func, insert, select, update
from sqlalchemy.sql.expression import ScalarSelect

from app.modules.knowledge.adapters.models import (
    CatalogueEntryRow,
    SourceParseRow,
    SourceRow,
    SourceTagRow,
    SourceVersionRow,
)
from app.platform.uow import UnitOfWork

S = SourceRow
V = SourceVersionRow
P = SourceParseRow


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """A Source header with one of its versions (the latest unless another was asked for)
    and that version's parse state."""

    id: UUID
    title: str
    product: str
    owner_id: UUID
    status: str
    retired_reason: str | None
    last_reviewed_on: date
    created_by: UUID
    created_at: datetime
    row_version: int
    version: int
    version_count: int
    product_version: str
    file_sha256: str
    filename: str
    size_bytes: int
    uploaded_by: UUID
    uploaded_at: datetime
    parse_status: str
    parse_error_code: str | None


@dataclass(frozen=True, slots=True)
class VersionRecord:
    version: int
    product_version: str
    file_sha256: str
    filename: str
    size_bytes: int
    uploaded_by: UUID
    uploaded_at: datetime
    parse_status: str
    parse_error_code: str | None
    char_count: int | None


@dataclass(frozen=True, slots=True)
class ParseTarget:
    """What the parse job needs about one Source version."""

    source_id: UUID
    version: int
    file_sha256: str
    filename: str
    status: str


@dataclass(frozen=True, slots=True)
class ParseState:
    status: str
    error_code: str | None
    text_sha256: str | None
    char_count: int | None


def _latest() -> ScalarSelect[int]:
    return select(func.max(V.version)).where(V.source_id == S.id).correlate(S).scalar_subquery()


def _count() -> ScalarSelect[int]:
    return select(func.count()).where(V.source_id == S.id).correlate(S).scalar_subquery()


def _select(wanted: Any) -> Select[Any]:
    statement = (
        select(
            S,
            V,
            P.status.label("parse_status"),
            P.error_code.label("parse_error_code"),
            _count().label("version_count"),
        )
        .join(V, (V.source_id == S.id) & (V.version == wanted))
        .join(P, (P.source_id == V.source_id) & (P.version == V.version))
    )
    return cast("Select[Any]", statement)


def _record(row: Any) -> SourceRecord:
    source, version = row[0], row[1]
    return SourceRecord(
        id=source.id,
        title=source.title,
        product=source.product,
        owner_id=source.owner_id,
        status=source.status,
        retired_reason=source.retired_reason,
        last_reviewed_on=source.last_reviewed_on,
        created_by=source.created_by,
        created_at=source.created_at,
        row_version=source.row_version,
        version=version.version,
        version_count=row.version_count,
        product_version=version.product_version,
        file_sha256=version.file_sha256,
        filename=version.filename,
        size_bytes=version.size_bytes,
        uploaded_by=version.uploaded_by,
        uploaded_at=version.uploaded_at,
        parse_status=row.parse_status,
        parse_error_code=row.parse_error_code,
    )


async def list_sources(
    uow: UnitOfWork,
    *,
    product: str | None,
    integration_type_id: UUID | None,
    owner_id: UUID | None,
    stale_before: date | None,
    stale: bool | None,
    include_retired: bool,
) -> list[SourceRecord]:
    """Sources at their latest version, longest-unreviewed first (stale ones on top), then
    by title. `stale_before` is the cutoff date (reviewed before it = stale), used with
    `stale`."""
    statement = _select(_latest()).order_by(S.last_reviewed_on, func.lower(S.title), S.id)
    if product is not None:
        statement = statement.where(func.lower(S.product) == product.strip().lower())
    if owner_id is not None:
        statement = statement.where(S.owner_id == owner_id)
    if integration_type_id is not None:
        statement = statement.where(
            exists().where(
                SourceTagRow.source_id == S.id, SourceTagRow.entry_id == integration_type_id
            )
        )
    if stale is not None and stale_before is not None:
        statement = statement.where(
            S.last_reviewed_on < stale_before if stale else S.last_reviewed_on >= stale_before
        )
    if not include_retired:
        statement = statement.where(S.status == "active")
    rows = (await uow.session.execute(statement)).all()
    return [_record(r) for r in rows]


async def get_source(
    uow: UnitOfWork, source_id: UUID, *, version: int | None = None
) -> SourceRecord | None:
    """The Source at `version` (the latest when None); None if there is no such Source or
    version."""
    wanted = _latest() if version is None else version
    row = (await uow.session.execute(_select(wanted).where(S.id == source_id))).first()
    return None if row is None else _record(row)


async def tags_for(uow: UnitOfWork, source_ids: list[UUID]) -> dict[UUID, list[UUID]]:
    """`{source_id: [Integration Type entry ids]}` for the Sources."""
    if not source_ids:
        return {}
    rows = (
        await uow.session.execute(
            select(SourceTagRow.source_id, SourceTagRow.entry_id)
            .where(SourceTagRow.source_id.in_(source_ids))
            .order_by(SourceTagRow.entry_id)
        )
    ).all()
    result: dict[UUID, list[UUID]] = {}
    for source_id, entry_id in rows:
        result.setdefault(source_id, []).append(entry_id)
    return result


async def entry_kinds(uow: UnitOfWork, entry_ids: list[UUID]) -> dict[UUID, str]:
    """`{entry_id: kind}` for the catalogue entries that exist."""
    if not entry_ids:
        return {}
    rows = (
        await uow.session.execute(
            select(CatalogueEntryRow.id, CatalogueEntryRow.kind).where(
                CatalogueEntryRow.id.in_(entry_ids)
            )
        )
    ).all()
    return {i: k for i, k in rows}


async def insert_source(
    uow: UnitOfWork,
    *,
    source_id: UUID,
    title: str,
    product: str,
    owner_id: UUID,
    last_reviewed_on: date,
    created_by: UUID,
) -> None:
    await uow.session.execute(
        insert(S).values(
            id=source_id,
            title=title,
            product=product,
            owner_id=owner_id,
            status="active",
            retired_reason=None,
            last_reviewed_on=last_reviewed_on,
            created_by=created_by,
            row_version=1,
        )
    )


async def set_tags(
    uow: UnitOfWork, source_id: UUID, entry_ids: list[UUID]
) -> tuple[list[UUID], list[UUID]]:
    """Replace the Source's tags with `entry_ids`; the ids added and the ids removed."""
    current = set((await tags_for(uow, [source_id])).get(source_id, []))
    wanted = set(entry_ids)
    added = sorted(wanted - current)
    removed = sorted(current - wanted)
    if removed:
        await uow.session.execute(
            delete(SourceTagRow).where(
                SourceTagRow.source_id == source_id, SourceTagRow.entry_id.in_(removed)
            )
        )
    if added:
        await uow.session.execute(
            insert(SourceTagRow), [{"source_id": source_id, "entry_id": e} for e in added]
        )
    return added, removed


async def next_version(uow: UnitOfWork, source_id: UUID) -> int:
    latest = (
        await uow.session.execute(select(func.max(V.version)).where(V.source_id == source_id))
    ).scalar_one()
    return int(latest or 0) + 1


async def insert_version(
    uow: UnitOfWork,
    *,
    source_id: UUID,
    version: int,
    product_version: str,
    file_sha256: str,
    filename: str,
    size_bytes: int,
    uploaded_by: UUID,
) -> None:
    """The version row and its `queued` parse row."""
    await uow.session.execute(
        insert(V).values(
            source_id=source_id,
            version=version,
            product_version=product_version,
            file_sha256=file_sha256,
            filename=filename,
            size_bytes=size_bytes,
            uploaded_by=uploaded_by,
        )
    )
    await uow.session.execute(
        insert(P).values(source_id=source_id, version=version, status="queued")
    )


async def bump(
    uow: UnitOfWork,
    source_id: UUID,
    *,
    expected_row_version: int,
    title: str | None = None,
    product: str | None = None,
    owner_id: UUID | None = None,
    last_reviewed_on: date | None = None,
    retire_with_reason: str | None = None,
) -> int | None:
    """Bump the header's row version if it is still at `expected_row_version`, setting
    the fields given; the new row version, or None (no change) when stale."""
    values: dict[str, object] = {"row_version": S.row_version + 1}
    if title is not None:
        values["title"] = title
    if product is not None:
        values["product"] = product
    if owner_id is not None:
        values["owner_id"] = owner_id
    if last_reviewed_on is not None:
        values["last_reviewed_on"] = last_reviewed_on
    if retire_with_reason is not None:
        values["status"] = "retired"
        values["retired_reason"] = retire_with_reason
    row = (
        await uow.session.execute(
            update(S)
            .where(S.id == source_id, S.row_version == expected_row_version)
            .values(**values)
            .returning(S.row_version)
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()
    return None if row is None else row[0]


async def list_versions(uow: UnitOfWork, source_id: UUID) -> list[VersionRecord]:
    """The Source's versions, newest first, each with its parse state."""
    rows = (
        await uow.session.execute(
            select(V, P.status, P.error_code, P.char_count)
            .join(P, (P.source_id == V.source_id) & (P.version == V.version))
            .where(V.source_id == source_id)
            .order_by(V.version.desc())
        )
    ).all()
    return [
        VersionRecord(
            version=v.version,
            product_version=v.product_version,
            file_sha256=v.file_sha256,
            filename=v.filename,
            size_bytes=v.size_bytes,
            uploaded_by=v.uploaded_by,
            uploaded_at=v.uploaded_at,
            parse_status=status,
            parse_error_code=error_code,
            char_count=char_count,
        )
        for v, status, error_code, char_count in rows
    ]


# --- parse state ----------------------------------------------------------------------------


async def parse_target(uow: UnitOfWork, source_id: UUID, version: int) -> ParseTarget | None:
    row = (
        await uow.session.execute(
            select(V.source_id, V.version, V.file_sha256, V.filename, P.status)
            .join(P, (P.source_id == V.source_id) & (P.version == V.version))
            .where(V.source_id == source_id, V.version == version)
        )
    ).one_or_none()
    if row is None:
        return None
    return ParseTarget(
        source_id=row.source_id,
        version=row.version,
        file_sha256=row.file_sha256,
        filename=row.filename,
        status=row.status,
    )


async def parse_state(
    uow: UnitOfWork, source_id: UUID, version: int, *, for_update: bool = False
) -> ParseState | None:
    statement = select(P.status, P.error_code, P.text_sha256, P.char_count).where(
        P.source_id == source_id, P.version == version
    )
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
    """Move the parse row to `status` if it is in one of `from_statuses`. False (and no
    change) otherwise."""
    result = await uow.session.execute(
        update(P)
        .where(P.source_id == source_id, P.version == version, P.status.in_(from_statuses))
        .values(
            status=status,
            error_code=error_code,
            text_sha256=text_sha256,
            char_count=char_count,
            parser=parser,
            updated_at=func.now(),
        )
        .returning(P.version)
        .execution_options(synchronize_session=False)
    )
    return result.one_or_none() is not None
