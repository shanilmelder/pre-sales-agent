"""Persistence for Opportunities and collaborators. Runs inside the caller's Unit of Work."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Text,
    and_,
    cast,
    delete,
    func,
    insert,
    literal,
    or_,
    select,
    true,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.modules.opportunities.adapters.models import CollaboratorRow, OpportunityRow
from app.modules.opportunities.domain.opportunity import (
    SUBJECT_TYPE,
    OpportunityStatus,
    derived_status,
)
from app.platform.trace.models import TraceEvent
from app.platform.uow import UnitOfWork

Where = ColumnElement[bool]
"""A row filter built here and handed back by the application layer."""


@dataclass(frozen=True, slots=True)
class OpportunityRecord:
    id: UUID
    owner_id: UUID
    title: str
    customer_name: str
    products: list[str]
    industry: str
    target_proposal_date: date
    row_version: int
    created_at: datetime
    status: OpportunityStatus


def status_expression() -> ColumnElement[str]:
    """The derived status (AD-26) as SQL, mirroring `domain.opportunity.derived_status()`.
    Lists select it and filter on it, so the column and the filter can't disagree. Nothing
    after intake exists yet, so it is the constant `derived_status()` returns; later stories
    replace it with the real derivation here and in the domain together."""
    return cast(literal(derived_status().value, Text), Text)


_COLUMNS = (
    OpportunityRow.id,
    OpportunityRow.owner_id,
    OpportunityRow.title,
    OpportunityRow.customer_name,
    OpportunityRow.products,
    OpportunityRow.industry,
    OpportunityRow.target_proposal_date,
    OpportunityRow.row_version,
    OpportunityRow.created_at,
    status_expression().label("status"),
)


def _record(row: Any) -> OpportunityRecord:
    return OpportunityRecord(
        id=row.id,
        owner_id=row.owner_id,
        title=row.title,
        customer_name=row.customer_name,
        products=list(row.products),
        industry=row.industry,
        target_proposal_date=row.target_proposal_date,
        row_version=row.row_version,
        created_at=row.created_at,
        status=OpportunityStatus(row.status),
    )


async def insert_opportunity(
    uow: UnitOfWork,
    *,
    opportunity_id: UUID,
    owner_id: UUID,
    title: str,
    customer_name: str,
    products: list[str],
    industry: str,
    target_proposal_date: date,
) -> None:
    await uow.session.execute(
        insert(OpportunityRow).values(
            id=opportunity_id,
            owner_id=owner_id,
            title=title,
            customer_name=customer_name,
            products=products,
            industry=industry,
            target_proposal_date=target_proposal_date,
            row_version=1,
        )
    )


async def get(uow: UnitOfWork, opportunity_id: UUID) -> OpportunityRecord | None:
    row = (
        await uow.session.execute(select(*_COLUMNS).where(OpportunityRow.id == opportunity_id))
    ).one_or_none()
    return None if row is None else _record(row)


async def collaborator_ids(uow: UnitOfWork, opportunity_id: UUID) -> list[UUID]:
    """Collaborators in the order they were added."""
    rows = await uow.session.execute(
        select(CollaboratorRow.user_id)
        .where(CollaboratorRow.opportunity_id == opportunity_id)
        .order_by(CollaboratorRow.added_at, CollaboratorRow.user_id)
    )
    return list(rows.scalars())


def involving(user_id: UUID) -> ColumnElement[bool]:
    """Filter: Opportunities the user owns or collaborates on."""
    member = (
        select(CollaboratorRow.opportunity_id)
        .where(
            CollaboratorRow.opportunity_id == OpportunityRow.id,
            CollaboratorRow.user_id == user_id,
        )
        .exists()
    )
    return or_(OpportunityRow.owner_id == user_id, member)


_WHITESPACE = " \t\n\r\x0b\x0c"


def _trim(value: Any) -> ColumnElement[str]:
    """Trim ASCII whitespace (Postgres' `trim` alone strips only spaces), as Python's
    `str.strip` does when products are stored."""
    return func.btrim(value, _WHITESPACE)


def matching(
    within: Where | None = None,
    *,
    status: OpportunityStatus | None = None,
    owner_id: UUID | None = None,
    product: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> ColumnElement[bool]:
    """Filter: `within` (a visibility filter) AND the given conditions; every row when
    nothing is given. Conditions only ever narrow `within`. `product` matches any of the
    Opportunity's products, trimmed and ignoring case; the dates bound the target proposal
    date inclusively."""
    conditions: list[ColumnElement[bool]] = [] if within is None else [within]
    if status is not None:
        conditions.append(status_expression() == cast(literal(status.value, Text), Text))
    if owner_id is not None:
        conditions.append(OpportunityRow.owner_id == owner_id)
    if product is not None:
        # EXISTS (SELECT 1 FROM unnest(products) AS p WHERE lower(trim(p)) = lower(trim(:x)))
        element = func.unnest(OpportunityRow.products).column_valued("p")
        conditions.append(
            select(literal(1))
            .where(
                func.lower(_trim(element)) == func.lower(_trim(cast(literal(product, Text), Text)))
            )
            .exists()
        )
    if date_from is not None:
        conditions.append(OpportunityRow.target_proposal_date >= date_from)
    if date_to is not None:
        conditions.append(OpportunityRow.target_proposal_date <= date_to)
    return and_(true(), *conditions)


async def facets(
    uow: UnitOfWork, where: ColumnElement[bool] | None
) -> tuple[list[UUID], list[str]]:
    """The distinct owner ids and product names across the Opportunities matching `where`
    (every row when None). Products are trimmed and de-duplicated ignoring case (the
    alphabetically first spelling wins), sorted ignoring case; blank ones are left out."""
    owners_query = select(OpportunityRow.owner_id).distinct()
    # FROM opportunities JOIN LATERAL unnest(products) AS product_names(p) ON true
    names = (
        func.unnest(OpportunityRow.products)
        .table_valued("p")
        .render_derived(name="product_names")
        .lateral()
    )
    key = func.lower(_trim(names.c.p))
    products_query = (
        select(func.min(_trim(names.c.p)))
        .select_from(OpportunityRow)
        .join(names, true())
        .where(_trim(names.c.p) != "")
        .group_by(key)
        .order_by(key)
    )
    if where is not None:
        owners_query = owners_query.where(where)
        products_query = products_query.where(where)
    owners = list((await uow.session.execute(owners_query)).scalars())
    products = list((await uow.session.execute(products_query)).scalars())
    return owners, products


async def list_page(
    uow: UnitOfWork, where: ColumnElement[bool] | None, *, offset: int, limit: int
) -> tuple[list[OpportunityRecord], int]:
    """One page, newest first, and the total matching `where` (every row when None)."""
    query = select(*_COLUMNS)
    count = select(func.count()).select_from(OpportunityRow)
    if where is not None:
        query = query.where(where)
        count = count.where(where)
    rows = (
        await uow.session.execute(
            query.order_by(OpportunityRow.created_at.desc(), OpportunityRow.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    total = (await uow.session.execute(count)).scalar_one()
    return [_record(row) for row in rows], total


async def bump_row_version(uow: UnitOfWork, opportunity_id: UUID, expected: int) -> int | None:
    """Atomically move the Opportunity from `expected` to `expected + 1`. Returns the new
    version, or None when the stored version differs (the caller answers 412). The UPDATE
    row-locks the Opportunity until commit, so concurrent writers serialise."""
    return (
        await uow.session.execute(
            update(OpportunityRow)
            .where(OpportunityRow.id == opportunity_id, OpportunityRow.row_version == expected)
            .values(row_version=OpportunityRow.row_version + 1)
            .returning(OpportunityRow.row_version)
            .execution_options(synchronize_session=False)
        )
    ).scalar_one_or_none()


async def update_fields(
    uow: UnitOfWork,
    opportunity_id: UUID,
    *,
    title: str | None = None,
    target_proposal_date: date | None = None,
) -> None:
    """Write the given fields (None: leave unchanged). Call after `bump_row_version`, which
    holds the row lock and moves the version; this never touches `row_version`."""
    values: dict[str, Any] = {}
    if title is not None:
        values["title"] = title
    if target_proposal_date is not None:
        values["target_proposal_date"] = target_proposal_date
    if not values:
        return
    await uow.session.execute(
        update(OpportunityRow)
        .where(OpportunityRow.id == opportunity_id)
        .values(**values)
        .execution_options(synchronize_session=False)
    )


async def add_collaborator(uow: UnitOfWork, opportunity_id: UUID, user_id: UUID) -> bool:
    """True if this call added the collaborator (False if they already were one)."""
    inserted = (
        await uow.session.execute(
            pg_insert(CollaboratorRow)
            .values(opportunity_id=opportunity_id, user_id=user_id)
            .on_conflict_do_nothing(
                index_elements=[CollaboratorRow.opportunity_id, CollaboratorRow.user_id]
            )
            .returning(CollaboratorRow.user_id)
        )
    ).scalar_one_or_none()
    return inserted is not None


async def remove_collaborator(uow: UnitOfWork, opportunity_id: UUID, user_id: UUID) -> bool:
    """True if this call removed the collaborator (False if they were not one)."""
    deleted = (
        await uow.session.execute(
            delete(CollaboratorRow)
            .where(
                CollaboratorRow.opportunity_id == opportunity_id,
                CollaboratorRow.user_id == user_id,
            )
            .returning(CollaboratorRow.user_id)
            .execution_options(synchronize_session=False)
        )
    ).scalar_one_or_none()
    return deleted is not None


async def last_changer_id(uow: UnitOfWork, opportunity_id: UUID) -> UUID | None:
    """The user behind the Opportunity's latest trace event, if that actor was a user."""
    row = (
        await uow.session.execute(
            select(TraceEvent.actor_type, TraceEvent.actor_id)
            .where(
                TraceEvent.subject_type == SUBJECT_TYPE,
                TraceEvent.subject_id == opportunity_id,
            )
            .order_by(TraceEvent.occurred_at.desc(), TraceEvent.id.desc())
            .limit(1)
        )
    ).one_or_none()
    if row is None or row.actor_type != "user":
        return None
    try:
        return UUID(row.actor_id)
    except ValueError:
        return None


# --- Decision Trace (Story 9.8) ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TraceRecord:
    id: UUID
    occurred_at: datetime
    event_type: str
    actor_type: str
    actor_id: str
    subject_type: str
    subject_id: UUID
    subject_version: int | None
    payload: dict[str, Any]


async def trace_page(
    uow: UnitOfWork,
    opportunity_id: UUID,
    *,
    subject_type: str | None,
    actor_type: str | None,
    event_type: str | None,
    offset: int,
    limit: int,
) -> tuple[list[TraceRecord], int]:
    """One page of the Opportunity's trace events, newest first (`occurred_at desc, id
    desc`, served by the `(opportunity_id, occurred_at)` index), and the total matching.
    Filters are exact matches on the stored values (None: any)."""
    conditions: list[ColumnElement[bool]] = [TraceEvent.opportunity_id == opportunity_id]
    if subject_type is not None:
        conditions.append(TraceEvent.subject_type == subject_type)
    if actor_type is not None:
        conditions.append(TraceEvent.actor_type == actor_type)
    if event_type is not None:
        conditions.append(TraceEvent.event_type == event_type)
    rows = (
        await uow.session.execute(
            select(
                TraceEvent.id,
                TraceEvent.occurred_at,
                TraceEvent.event_type,
                TraceEvent.actor_type,
                TraceEvent.actor_id,
                TraceEvent.subject_type,
                TraceEvent.subject_id,
                TraceEvent.subject_version,
                TraceEvent.payload,
            )
            .where(*conditions)
            .order_by(TraceEvent.occurred_at.desc(), TraceEvent.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    total = (
        await uow.session.execute(select(func.count()).select_from(TraceEvent).where(*conditions))
    ).scalar_one()
    return [
        TraceRecord(
            id=row.id,
            occurred_at=row.occurred_at,
            event_type=row.event_type,
            actor_type=row.actor_type,
            actor_id=row.actor_id,
            subject_type=row.subject_type,
            subject_id=row.subject_id,
            subject_version=row.subject_version,
            payload=dict(row.payload or {}),
        )
        for row in rows
    ], total


async def trace_options(
    uow: UnitOfWork, opportunity_id: UUID
) -> tuple[list[str], list[str], list[str]]:
    """The distinct subject types, actor types and event types on the Opportunity's trace,
    each sorted."""

    async def distinct(column: Any) -> list[str]:
        result = await uow.session.execute(
            select(column)
            .where(TraceEvent.opportunity_id == opportunity_id)
            .distinct()
            .order_by(column)
        )
        return list(result.scalars())

    return (
        await distinct(TraceEvent.subject_type),
        await distinct(TraceEvent.actor_type),
        await distinct(TraceEvent.event_type),
    )
