"""Persistence for Checklists, their scope tags, published versions and items (Story 3.4).
Runs inside the caller's Unit of Work."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, insert, select, tuple_, update
from sqlalchemy.sql.expression import ScalarSelect

from app.modules.knowledge.adapters.models import (
    ChecklistItemRow,
    ChecklistRow,
    ChecklistScopeTagRow,
    ChecklistVersionRow,
)
from app.platform.uow import UnitOfWork

C = ChecklistRow
T = ChecklistScopeTagRow
V = ChecklistVersionRow
I = ChecklistItemRow  # noqa: E741

_UNSET: Any = object()


@dataclass(frozen=True, slots=True)
class ChecklistRecord:
    """A Checklist header with its latest published version number (None before the first
    Publish)."""

    id: UUID
    name: str
    domain: str
    products: list[str]
    industry: str | None
    draft: dict[str, Any] | None
    status: str
    retired_reason: str | None
    created_by: UUID
    created_at: datetime
    row_version: int
    current_version: int | None


@dataclass(frozen=True, slots=True)
class VersionRecord:
    checklist_id: UUID
    version: int
    name: str
    domain: str
    scope: dict[str, Any]
    published_by: UUID
    published_at: datetime


@dataclass(frozen=True, slots=True)
class ItemRecord:
    item_id: UUID
    ordinal: int
    kind: str
    text: str
    why_it_matters: str
    affected_entry_id: UUID | None
    impact: str
    mandatory: bool


def _latest() -> ScalarSelect[int]:
    return select(func.max(V.version)).where(V.checklist_id == C.id).correlate(C).scalar_subquery()


def _record(row: Any) -> ChecklistRecord:
    checklist: C = row[0]
    return ChecklistRecord(
        id=checklist.id,
        name=checklist.name,
        domain=checklist.domain,
        products=list(checklist.products),
        industry=checklist.industry,
        draft=checklist.draft,
        status=checklist.status,
        retired_reason=checklist.retired_reason,
        created_by=checklist.created_by,
        created_at=checklist.created_at,
        row_version=checklist.row_version,
        current_version=row[1],
    )


async def list_checklists(uow: UnitOfWork, *, include_retired: bool) -> list[ChecklistRecord]:
    """Checklists by name (active only unless `include_retired`)."""
    statement = select(C, _latest().label("current_version")).order_by(func.lower(C.name), C.id)
    if not include_retired:
        statement = statement.where(C.status == "active")
    rows = (await uow.session.execute(statement)).all()
    return [_record(r) for r in rows]


async def get_checklist(uow: UnitOfWork, checklist_id: UUID) -> ChecklistRecord | None:
    row = (
        await uow.session.execute(
            select(C, _latest().label("current_version")).where(C.id == checklist_id)
        )
    ).first()
    return None if row is None else _record(row)


async def published_active(uow: UnitOfWork) -> list[ChecklistRecord]:
    """Active Checklists that have at least one published version."""
    latest = _latest()
    rows = (
        await uow.session.execute(
            select(C, latest.label("current_version")).where(
                C.status == "active", latest.is_not(None)
            )
        )
    ).all()
    return [_record(r) for r in rows]


async def tags_for(uow: UnitOfWork, checklist_ids: list[UUID]) -> dict[UUID, list[UUID]]:
    """`{checklist_id: [Integration Type entry ids]}` of the published scopes."""
    if not checklist_ids:
        return {}
    rows = (
        await uow.session.execute(
            select(T.checklist_id, T.entry_id)
            .where(T.checklist_id.in_(checklist_ids))
            .order_by(T.entry_id)
        )
    ).all()
    result: dict[UUID, list[UUID]] = {}
    for checklist_id, entry_id in rows:
        result.setdefault(checklist_id, []).append(entry_id)
    return result


async def set_tags(uow: UnitOfWork, checklist_id: UUID, entry_ids: list[UUID]) -> None:
    """Replace the published scope's Integration Types with `entry_ids`."""
    current = set((await tags_for(uow, [checklist_id])).get(checklist_id, []))
    wanted = set(entry_ids)
    removed = sorted(current - wanted)
    added = sorted(wanted - current)
    if removed:
        await uow.session.execute(
            delete(T).where(T.checklist_id == checklist_id, T.entry_id.in_(removed))
        )
    if added:
        await uow.session.execute(
            insert(T), [{"checklist_id": checklist_id, "entry_id": e} for e in added]
        )


async def insert_checklist(
    uow: UnitOfWork,
    *,
    checklist_id: UUID,
    name: str,
    domain: str,
    draft: dict[str, Any],
    created_by: UUID,
) -> None:
    """A new active Checklist at row version 1 with its first draft and no version."""
    await uow.session.execute(
        insert(C).values(
            id=checklist_id,
            name=name,
            domain=domain,
            products=[],
            industry=None,
            draft=draft,
            status="active",
            retired_reason=None,
            created_by=created_by,
            row_version=1,
        )
    )


async def bump(
    uow: UnitOfWork,
    checklist_id: UUID,
    *,
    expected_row_version: int,
    draft: dict[str, Any] | None = _UNSET,
    name: str | None = None,
    domain: str | None = None,
    products: list[str] | None = None,
    industry: str | None = _UNSET,
    retire_with_reason: str | None = None,
) -> int | None:
    """Bump the header's row version if it is still at `expected_row_version`, setting the
    fields given (`draft` and `industry` may be set to None); the new row version, or None
    (no change) when stale."""
    values: dict[str, object] = {"row_version": C.row_version + 1}
    if draft is not _UNSET:
        values["draft"] = draft
    if name is not None:
        values["name"] = name
    if domain is not None:
        values["domain"] = domain
    if products is not None:
        values["products"] = products
    if industry is not _UNSET:
        values["industry"] = industry
    if retire_with_reason is not None:
        values["status"] = "retired"
        values["retired_reason"] = retire_with_reason
    row = (
        await uow.session.execute(
            update(C)
            .where(C.id == checklist_id, C.row_version == expected_row_version)
            .values(**values)
            .returning(C.row_version)
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()
    return None if row is None else row[0]


async def next_version(uow: UnitOfWork, checklist_id: UUID) -> int:
    latest = (
        await uow.session.execute(select(func.max(V.version)).where(V.checklist_id == checklist_id))
    ).scalar_one()
    return int(latest or 0) + 1


async def insert_version(
    uow: UnitOfWork,
    *,
    checklist_id: UUID,
    version: int,
    name: str,
    domain: str,
    scope: dict[str, Any],
    published_by: UUID,
    items: list[ItemRecord],
) -> None:
    """The version row and its item rows."""
    await uow.session.execute(
        insert(V).values(
            checklist_id=checklist_id,
            version=version,
            name=name,
            domain=domain,
            scope=scope,
            published_by=published_by,
        )
    )
    if items:
        await uow.session.execute(
            insert(I),
            [
                {
                    "checklist_id": checklist_id,
                    "version": version,
                    "item_id": item.item_id,
                    "ordinal": item.ordinal,
                    "kind": item.kind,
                    "text": item.text,
                    "why_it_matters": item.why_it_matters,
                    "affected_entry_id": item.affected_entry_id,
                    "impact": item.impact,
                    "mandatory": item.mandatory,
                }
                for item in items
            ],
        )


def _version(row: V) -> VersionRecord:
    return VersionRecord(
        checklist_id=row.checklist_id,
        version=row.version,
        name=row.name,
        domain=row.domain,
        scope=row.scope,
        published_by=row.published_by,
        published_at=row.published_at,
    )


async def list_versions(uow: UnitOfWork, checklist_id: UUID) -> list[VersionRecord]:
    """The Checklist's published versions, newest first."""
    rows = (
        (
            await uow.session.execute(
                select(V).where(V.checklist_id == checklist_id).order_by(V.version.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_version(r) for r in rows]


async def get_version(uow: UnitOfWork, checklist_id: UUID, version: int) -> VersionRecord | None:
    row = (
        await uow.session.execute(
            select(V).where(V.checklist_id == checklist_id, V.version == version)
        )
    ).scalar_one_or_none()
    return None if row is None else _version(row)


async def last_published_at(uow: UnitOfWork, checklist_ids: list[UUID]) -> dict[UUID, datetime]:
    """`{checklist_id: when its latest version was published}` for the published ones."""
    if not checklist_ids:
        return {}
    rows = (
        await uow.session.execute(
            select(V.checklist_id, func.max(V.published_at))
            .where(V.checklist_id.in_(checklist_ids))
            .group_by(V.checklist_id)
        )
    ).all()
    return {checklist_id: published_at for checklist_id, published_at in rows}


async def item_counts(uow: UnitOfWork, checklist_id: UUID) -> dict[int, tuple[int, int]]:
    """`{version: (item count, mandatory count)}` for the Checklist's versions."""
    rows = (
        await uow.session.execute(
            select(
                I.version,
                func.count(),
                func.count().filter(I.mandatory.is_(True)),
            )
            .where(I.checklist_id == checklist_id)
            .group_by(I.version)
        )
    ).all()
    return {version: (int(total), int(mandatory)) for version, total, mandatory in rows}


async def items_of(
    uow: UnitOfWork, pairs: list[tuple[UUID, int]]
) -> dict[tuple[UUID, int], list[ItemRecord]]:
    """The items of each `(checklist_id, version)`, in order."""
    if not pairs:
        return {}
    rows = (
        (
            await uow.session.execute(
                select(I)
                .where(tuple_(I.checklist_id, I.version).in_(pairs))
                .order_by(I.checklist_id, I.version, I.ordinal)
            )
        )
        .scalars()
        .all()
    )
    result: dict[tuple[UUID, int], list[ItemRecord]] = {pair: [] for pair in pairs}
    for r in rows:
        result[(r.checklist_id, r.version)].append(
            ItemRecord(
                item_id=r.item_id,
                ordinal=r.ordinal,
                kind=r.kind,
                text=r.text,
                why_it_matters=r.why_it_matters,
                affected_entry_id=r.affected_entry_id,
                impact=r.impact,
                mandatory=r.mandatory,
            )
        )
    return result


async def published_item_ids(uow: UnitOfWork, checklist_id: UUID) -> set[UUID]:
    """Every item id any published version of the Checklist has used."""
    rows = (
        await uow.session.execute(
            select(I.item_id).where(I.checklist_id == checklist_id).distinct()
        )
    ).scalars()
    return set(rows)
