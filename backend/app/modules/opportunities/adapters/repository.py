"""Persistence for Opportunities and collaborators. Runs inside the caller's Unit of Work."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, delete, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.modules.opportunities.adapters.models import CollaboratorRow, OpportunityRow
from app.modules.opportunities.domain.opportunity import SUBJECT_TYPE
from app.platform.trace.models import TraceEvent
from app.platform.uow import UnitOfWork


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
