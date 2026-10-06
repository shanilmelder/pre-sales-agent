"""Persistence for the catalogue (Story 3.1). Runs inside the caller's Unit of Work."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.sql.expression import ScalarSelect

from app.modules.knowledge.adapters.models import CatalogueEntryRow, CatalogueEntryVersionRow
from app.platform.uow import UnitOfWork

E = CatalogueEntryRow
V = CatalogueEntryVersionRow


@dataclass(frozen=True, slots=True)
class EntryRecord:
    """An entry with one of its versions (`version`; the current one unless asked for
    another) and its `current_version`."""

    id: UUID
    kind: str
    code: str
    status: str
    retired_reason: str | None
    row_version: int
    created_at: datetime
    version: int
    current_version: int
    name: str
    definition: str


@dataclass(frozen=True, slots=True)
class VersionRecord:
    version: int
    name: str
    definition: str
    changed_by: UUID
    changed_at: datetime


async def lock_kind(uow: UnitOfWork, kind: str) -> None:
    """Serialise catalogue writes of one kind until commit, so the duplicate check and the
    write that follows it can't interleave with another."""
    await uow.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"knowledge.catalogue:{kind}"},
    )


def _current_version() -> ScalarSelect[int]:
    return select(func.max(V.version)).where(V.entry_id == E.id).correlate(E).scalar_subquery()


def _record(entry: E, version: V, current: int) -> EntryRecord:
    return EntryRecord(
        id=entry.id,
        kind=entry.kind,
        code=entry.code,
        status=entry.status,
        retired_reason=entry.retired_reason,
        row_version=entry.row_version,
        created_at=entry.created_at,
        version=version.version,
        current_version=current,
        name=version.name,
        definition=version.definition,
    )


async def list_entries(
    uow: UnitOfWork, *, kind: str | None, include_retired: bool
) -> list[EntryRecord]:
    """Entries at their current version, by kind then name."""
    current = _current_version()
    statement = (
        select(E, V, current.label("current_version"))
        .join(V, (V.entry_id == E.id) & (V.version == current))
        .order_by(E.kind, func.lower(V.name), E.id)
    )
    if kind is not None:
        statement = statement.where(E.kind == kind)
    if not include_retired:
        statement = statement.where(E.status == "active")
    rows = (await uow.session.execute(statement)).all()
    return [_record(entry, version, cur) for entry, version, cur in rows]


async def get_entry(
    uow: UnitOfWork, entry_id: UUID, *, version: int | None = None
) -> EntryRecord | None:
    """The entry at `version` (the current one when None); None if there is no such entry
    or version."""
    current = _current_version()
    wanted = current if version is None else version
    statement = (
        select(E, V, current.label("current_version"))
        .join(V, (V.entry_id == E.id) & (V.version == wanted))
        .where(E.id == entry_id)
    )
    row = (await uow.session.execute(statement)).first()
    return None if row is None else _record(row[0], row[1], row[2])


async def active_entries(uow: UnitOfWork, kind: str) -> list[tuple[UUID, str, str]]:
    """`(id, code, current name)` of the active entries of the kind."""
    current = _current_version()
    rows = (
        await uow.session.execute(
            select(E.id, E.code, V.name)
            .join(V, (V.entry_id == E.id) & (V.version == current))
            .where(E.kind == kind, E.status == "active")
        )
    ).all()
    return [(i, c, n) for i, c, n in rows]


async def list_versions(uow: UnitOfWork, entry_id: UUID) -> list[VersionRecord]:
    """The entry's versions, newest first."""
    rows = (
        (
            await uow.session.execute(
                select(V).where(V.entry_id == entry_id).order_by(V.version.desc())
            )
        )
        .scalars()
        .all()
    )
    return [
        VersionRecord(
            version=r.version,
            name=r.name,
            definition=r.definition,
            changed_by=r.changed_by,
            changed_at=r.changed_at,
        )
        for r in rows
    ]


async def insert_entry(
    uow: UnitOfWork,
    *,
    entry_id: UUID,
    kind: str,
    code: str,
    name: str,
    definition: str,
    user_id: UUID,
) -> None:
    """A new active entry at row version 1 with its version 1."""
    await uow.session.execute(
        insert(E).values(
            id=entry_id, kind=kind, code=code, status="active", retired_reason=None, row_version=1
        )
    )
    await insert_version(
        uow, entry_id=entry_id, version=1, name=name, definition=definition, user_id=user_id
    )


async def insert_version(
    uow: UnitOfWork, *, entry_id: UUID, version: int, name: str, definition: str, user_id: UUID
) -> None:
    await uow.session.execute(
        insert(V).values(
            entry_id=entry_id,
            version=version,
            name=name,
            definition=definition,
            changed_by=user_id,
        )
    )


async def bump(
    uow: UnitOfWork,
    entry_id: UUID,
    *,
    expected_row_version: int,
    status: str | None = None,
    retired_reason: str | None = None,
    clear_reason: bool = False,
) -> int | None:
    """Bump the entry's row version if it is still at `expected_row_version`, optionally
    setting its status and retired reason; the new row version, or None (no change) when
    stale."""
    values: dict[str, object] = {"row_version": E.row_version + 1}
    if status is not None:
        values["status"] = status
        values["retired_reason"] = None if clear_reason else retired_reason
    row = (
        await uow.session.execute(
            update(E)
            .where(E.id == entry_id, E.row_version == expected_row_version)
            .values(**values)
            .returning(E.row_version)
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()
    return None if row is None else row[0]
