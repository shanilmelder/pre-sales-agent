"""Persistence for identity users and roles. Runs inside the caller's Unit of Work."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.modules.identity.adapters.models import IdentityUser, IdentityUserRole
from app.platform.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class UserRecord:
    id: UUID
    name: str
    email: str


async def get_by_sub(uow: UnitOfWork, auth0_sub: str) -> UserRecord | None:
    row = (
        await uow.session.execute(
            select(IdentityUser.id, IdentityUser.name, IdentityUser.email).where(
                IdentityUser.auth0_sub == auth0_sub
            )
        )
    ).one_or_none()
    return None if row is None else UserRecord(id=row.id, name=row.name, email=row.email)


async def insert_if_absent(
    uow: UnitOfWork, *, user_id: UUID, auth0_sub: str, name: str, email: str
) -> bool:
    """Insert the user unless one with this `auth0_sub` exists. True if this call inserted.

    `ON CONFLICT DO NOTHING` waits for a concurrent uncommitted insert of the same `sub`, so
    of two racing first requests exactly one inserts."""
    inserted = (
        await uow.session.execute(
            insert(IdentityUser)
            .values(id=user_id, auth0_sub=auth0_sub, name=name, email=email, row_version=1)
            .on_conflict_do_nothing(index_elements=[IdentityUser.auth0_sub])
            .returning(IdentityUser.id)
        )
    ).scalar_one_or_none()
    return inserted is not None


async def load_roles(uow: UnitOfWork, user_id: UUID) -> list[str]:
    result = await uow.session.execute(
        select(IdentityUserRole.role)
        .where(IdentityUserRole.user_id == user_id)
        .order_by(IdentityUserRole.role)
    )
    return list(result.scalars())
