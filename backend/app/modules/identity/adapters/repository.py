"""Persistence for identity users and the display-only role cache. Runs inside the caller's
Unit of Work."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, func, select
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
    """The user's cached roles (display only, as of their last sign-in), sorted."""
    result = await uow.session.execute(
        select(IdentityUserRole.role)
        .where(IdentityUserRole.user_id == user_id)
        .order_by(IdentityUserRole.role)
    )
    return list(result.scalars())


async def replace_roles(uow: UnitOfWork, user_id: UUID, roles: list[str]) -> None:
    """Make the user's cached roles exactly `roles`: delete the others, insert the missing.

    Row-locks the user first, so concurrent replacements for one user (e.g. requests with an
    old and a new token carrying different roles) run one after the other instead of
    deadlocking on each other's deletes and inserts; the last to commit wins. Inserts skip
    rows that already exist."""
    await uow.session.execute(
        select(IdentityUser.id).where(IdentityUser.id == user_id).with_for_update()
    )
    stale = delete(IdentityUserRole).where(IdentityUserRole.user_id == user_id)
    if roles:
        stale = stale.where(IdentityUserRole.role.not_in(roles))
    await uow.session.execute(stale.execution_options(synchronize_session=False))
    if roles:
        await uow.session.execute(
            insert(IdentityUserRole)
            .values([{"user_id": user_id, "role": role} for role in roles])
            .on_conflict_do_nothing(
                index_elements=[IdentityUserRole.user_id, IdentityUserRole.role]
            )
        )


# --- administration (Story 1.6; read-only since Story 1.9) ----------------------------------


@dataclass(frozen=True, slots=True)
class AdminUserRecord:
    id: UUID
    name: str
    email: str
    row_version: int
    roles: list[str]


_USER_COLUMNS = (IdentityUser.id, IdentityUser.name, IdentityUser.email, IdentityUser.row_version)


async def _roles_by_user(uow: UnitOfWork, user_ids: list[UUID]) -> dict[UUID, list[str]]:
    by_user: dict[UUID, list[str]] = {user_id: [] for user_id in user_ids}
    if not user_ids:
        return by_user
    rows = await uow.session.execute(
        select(IdentityUserRole.user_id, IdentityUserRole.role)
        .where(IdentityUserRole.user_id.in_(user_ids))
        .order_by(IdentityUserRole.user_id, IdentityUserRole.role)
    )
    for row in rows:
        by_user[row.user_id].append(row.role)
    return by_user


async def count_users(uow: UnitOfWork) -> int:
    return (await uow.session.execute(select(func.count()).select_from(IdentityUser))).scalar_one()


async def list_users(uow: UnitOfWork, *, offset: int, limit: int) -> list[AdminUserRecord]:
    """One page of users, ordered by name (case-insensitive) then id, with their roles."""
    rows = (
        await uow.session.execute(
            select(*_USER_COLUMNS)
            .order_by(func.lower(IdentityUser.name), IdentityUser.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    roles = await _roles_by_user(uow, [row.id for row in rows])
    return [
        AdminUserRecord(
            id=row.id,
            name=row.name,
            email=row.email,
            row_version=row.row_version,
            roles=roles[row.id],
        )
        for row in rows
    ]


async def get_user(uow: UnitOfWork, user_id: UUID) -> AdminUserRecord | None:
    row = (
        await uow.session.execute(select(*_USER_COLUMNS).where(IdentityUser.id == user_id))
    ).one_or_none()
    if row is None:
        return None
    return AdminUserRecord(
        id=row.id,
        name=row.name,
        email=row.email,
        row_version=row.row_version,
        roles=await load_roles(uow, row.id),
    )


# --- user search and names (Story 1.7) ------------------------------------------------------


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


async def search_users(uow: UnitOfWork, q: str, *, limit: int) -> list[UserRecord]:
    """Users whose name or email contains `q` (case-insensitive), ordered by name then id."""
    pattern = f"%{_escape_like(q)}%"
    rows = await uow.session.execute(
        select(IdentityUser.id, IdentityUser.name, IdentityUser.email)
        .where(
            IdentityUser.name.ilike(pattern, escape="\\")
            | IdentityUser.email.ilike(pattern, escape="\\")
        )
        .order_by(func.lower(IdentityUser.name), IdentityUser.id)
        .limit(limit)
    )
    return [UserRecord(id=row.id, name=row.name, email=row.email) for row in rows]


async def user_names(uow: UnitOfWork, user_ids: list[UUID]) -> dict[UUID, str]:
    """Names of the given users that exist."""
    if not user_ids:
        return {}
    query = select(IdentityUser.id, IdentityUser.name).where(IdentityUser.id.in_(user_ids))
    return {row.id: row.name for row in await uow.session.execute(query)}
