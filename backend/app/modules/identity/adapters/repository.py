"""Persistence for identity users and roles. Runs inside the caller's Unit of Work."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Text, cast, delete, func, select, update
from sqlalchemy.dialects.postgresql import distinct_on, insert

from app.modules.identity.adapters.models import IdentityUser, IdentityUserRole
from app.platform.trace.models import TraceEvent
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


# --- administration (Story 1.6) -------------------------------------------------------------

ADMIN_ROLE = "platform_administrator"
ROLE_EVENT_TYPES = ("identity.user.role_assigned", "identity.user.role_removed")


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


async def bump_row_version(uow: UnitOfWork, user_id: UUID, expected: int) -> int | None:
    """Atomically move the user from `expected` to `expected + 1`. Returns the new version,
    or None when the stored version is not `expected` (the caller answers 412).

    The UPDATE row-locks the user until commit: a concurrent writer holding the same
    `expected` waits, then re-checks the WHERE clause against the committed row and fails."""
    return (
        await uow.session.execute(
            update(IdentityUser)
            .where(IdentityUser.id == user_id, IdentityUser.row_version == expected)
            .values(row_version=IdentityUser.row_version + 1)
            .returning(IdentityUser.row_version)
            .execution_options(synchronize_session=False)
        )
    ).scalar_one_or_none()


async def add_role(uow: UnitOfWork, user_id: UUID, role: str) -> bool:
    """Insert the role; True if this call inserted it (False if already held)."""
    inserted = (
        await uow.session.execute(
            insert(IdentityUserRole)
            .values(user_id=user_id, role=role)
            .on_conflict_do_nothing(
                index_elements=[IdentityUserRole.user_id, IdentityUserRole.role]
            )
            .returning(IdentityUserRole.role)
        )
    ).scalar_one_or_none()
    return inserted is not None


async def remove_role(uow: UnitOfWork, user_id: UUID, role: str) -> bool:
    """Delete the role; True if this call deleted it (False if it was not held)."""
    deleted = (
        await uow.session.execute(
            delete(IdentityUserRole)
            .where(IdentityUserRole.user_id == user_id, IdentityUserRole.role == role)
            .returning(IdentityUserRole.role)
            .execution_options(synchronize_session=False)
        )
    ).scalar_one_or_none()
    return deleted is not None


async def lock_admin_holders(uow: UnitOfWork) -> list[UUID]:
    """Row-lock every `platform_administrator` grant until commit and return the holders.

    Two concurrent removals serialise here: the second waits for the first to commit, then
    (READ COMMITTED) skips the grant the first deleted and sees the remaining holders.
    Locked in `user_id` order so concurrent lockers never deadlock on each other."""
    rows = await uow.session.execute(
        select(IdentityUserRole.user_id)
        .where(IdentityUserRole.role == ADMIN_ROLE)
        .order_by(IdentityUserRole.user_id)
        .with_for_update()
    )
    return list(rows.scalars())


async def last_role_changers(uow: UnitOfWork, user_ids: list[UUID]) -> dict[UUID, str]:
    """For each user, the name of the user who made their latest role change, if any.

    Reads the trace (role events have the user as subject). Actors that are not platform
    users (agents, system) or no longer exist are left out."""
    if not user_ids:
        return {}
    latest = (
        select(TraceEvent.subject_id, TraceEvent.actor_type, TraceEvent.actor_id)
        .where(
            TraceEvent.subject_type == "identity.user",
            TraceEvent.subject_id.in_(user_ids),
            TraceEvent.event_type.in_(ROLE_EVENT_TYPES),
        )
        .order_by(TraceEvent.subject_id, TraceEvent.occurred_at.desc(), TraceEvent.id.desc())
        .ext(distinct_on(TraceEvent.subject_id))
        .subquery()
    )
    rows = await uow.session.execute(
        select(latest.c.subject_id, IdentityUser.name).join(
            IdentityUser,
            (latest.c.actor_type == "user") & (cast(IdentityUser.id, Text) == latest.c.actor_id),
        )
    )
    return {row.subject_id: row.name for row in rows}


# --- user search and names (Story 1.7) ------------------------------------------------------


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


_HAS_ROLE = (
    select(IdentityUserRole.user_id).where(IdentityUserRole.user_id == IdentityUser.id).exists()
)


async def search_users(uow: UnitOfWork, q: str, *, limit: int) -> list[UserRecord]:
    """Users holding at least one role whose name or email contains `q` (case-insensitive),
    ordered by name then id."""
    pattern = f"%{_escape_like(q)}%"
    rows = await uow.session.execute(
        select(IdentityUser.id, IdentityUser.name, IdentityUser.email)
        .where(
            _HAS_ROLE,
            IdentityUser.name.ilike(pattern, escape="\\")
            | IdentityUser.email.ilike(pattern, escape="\\"),
        )
        .order_by(func.lower(IdentityUser.name), IdentityUser.id)
        .limit(limit)
    )
    return [UserRecord(id=row.id, name=row.name, email=row.email) for row in rows]


async def user_names(
    uow: UnitOfWork, user_ids: list[UUID], *, with_roles_only: bool = False
) -> dict[UUID, str]:
    """Names of the given users that exist (and, if asked, hold at least one role)."""
    if not user_ids:
        return {}
    query = select(IdentityUser.id, IdentityUser.name).where(IdentityUser.id.in_(user_ids))
    if with_roles_only:
        query = query.where(_HAS_ROLE)
    return {row.id: row.name for row in await uow.session.execute(query)}
