"""Users & roles administration (Story 1.6): list users, assign and remove roles.

Every command follows the AD-3 path inside the caller's Unit of Work: authorize, domain
rules, `row_version` (`If-Match`), write, then trace. Assign and remove are idempotent:
assigning a held role or removing a missing one writes nothing, bumps no version and
appends no event, and still returns the current user.

Removing `platform_administrator` row-locks every administrator grant first, so two
concurrent removals serialise and the platform can never be left without an administrator.
Trace payloads and logs carry IDs and the role only, never names or emails.
"""

from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.identity.actions import Action
from app.modules.identity.adapters import repository
from app.modules.identity.adapters.repository import AdminUserRecord
from app.modules.identity.application.authorize import authorize
from app.modules.identity.application.provisioning import USER_SUBJECT
from app.modules.identity.domain.policy import Principal, Resource
from app.modules.identity.domain.roles import Role
from app.platform import trace
from app.platform.concurrency import parse_if_match
from app.platform.errors import LastAdministratorError, NotFoundError, RowVersionMismatchError
from app.platform.logging import get_logger
from app.platform.trace.catalogue import IdentityUserRoleAssigned, IdentityUserRoleRemoved
from app.platform.uow import UnitOfWork

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
MAX_PAGE = 1_000_000
MAX_ROW_VERSION = 2**31 - 1
LAST_ADMINISTRATOR_DETAIL = "At least one platform administrator is required"
_ROLE_VALUES = frozenset(role.value for role in Role)
_log = get_logger(__name__)


class AdminUser(BaseModel):
    """A platform user as administrators see it. `row_version` is also the `ETag`.

    `last_changed_by` is the name of whoever made the latest role change, or null when no
    role change is recorded (the UI then says "another administrator")."""

    id: str
    name: str
    email: str
    roles: list[Role]
    row_version: int
    last_changed_by: str | None


class AdminUserPage(BaseModel):
    """One page of users, ordered by name."""

    items: list[AdminUser]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)


def _known_roles(stored: list[str]) -> list[Role]:
    return sorted(Role(value) for value in stored if value in _ROLE_VALUES)


def _admin_user(record: AdminUserRecord, last_changed_by: str | None) -> AdminUser:
    return AdminUser(
        id=str(record.id),
        name=record.name,
        email=record.email,
        roles=_known_roles(record.roles),
        row_version=record.row_version,
        last_changed_by=last_changed_by,
    )


def _user_resource(user_id: UUID) -> Resource:
    return Resource(type=USER_SUBJECT, id=user_id)


async def _load(uow: UnitOfWork, user_id: UUID) -> AdminUser:
    record = await repository.get_user(uow, user_id)
    if record is None:
        raise NotFoundError("No user with this id.")
    changers = await repository.last_role_changers(uow, [user_id])
    return _admin_user(record, changers.get(user_id))


async def list_users(
    uow: UnitOfWork, actor: Principal, *, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE
) -> AdminUserPage:
    authorize(actor, Action.USER_LIST)
    records = await repository.list_users(uow, offset=(page - 1) * page_size, limit=page_size)
    changers = await repository.last_role_changers(uow, [r.id for r in records])
    return AdminUserPage(
        items=[_admin_user(r, changers.get(r.id)) for r in records],
        page=page,
        page_size=page_size,
        total=await repository.count_users(uow),
    )


async def get_user(uow: UnitOfWork, actor: Principal, user_id: UUID) -> AdminUser:
    authorize(actor, Action.USER_LIST, _user_resource(user_id))
    return await _load(uow, user_id)


async def assign_role(
    uow: UnitOfWork, actor: Principal, user_id: UUID, role: Role, if_match: str | None
) -> AdminUser:
    """Give `user_id` the role. `if_match` is the raw `If-Match` header (428/412)."""
    authorize(actor, Action.USER_ASSIGN_ROLE, _user_resource(user_id))
    return await _change_role(
        uow, actor, user_id, role, if_match, removing=False, write=repository.add_role
    )


async def remove_role(
    uow: UnitOfWork, actor: Principal, user_id: UUID, role: Role, if_match: str | None
) -> AdminUser:
    """Take the role from `user_id`. Removing the last `platform_administrator` is a 409
    `last_administrator`, including an administrator removing their own role."""
    authorize(actor, Action.USER_REMOVE_ROLE, _user_resource(user_id))
    return await _change_role(
        uow, actor, user_id, role, if_match, removing=True, write=repository.remove_role
    )


async def _change_role(
    uow: UnitOfWork,
    actor: Principal,
    user_id: UUID,
    role: Role,
    if_match: str | None,
    *,
    removing: bool,
    write: Callable[[UnitOfWork, UUID, str], Coroutine[Any, Any, bool]],
) -> AdminUser:
    """Shared AD-3 path. A removal applies only when the user holds the role, an assignment
    only when they don't; otherwise it is a no-op."""
    expected = parse_if_match(if_match)
    if expected > MAX_ROW_VERSION:
        raise _stale()  # no stored version can be this large (int4 column)
    record = await repository.get_user(uow, user_id)
    if record is None:
        raise NotFoundError("No user with this id.")

    # Domain rule, under the lock that serialises concurrent administrator removals.
    if removing and role is Role.PLATFORM_ADMINISTRATOR:
        holders = await repository.lock_admin_holders(uow)
        if holders == [user_id]:
            raise LastAdministratorError(LAST_ADMINISTRATOR_DETAIL)

    # Re-read the roles after the lock so the no-op decision sees committed state.
    roles = await repository.load_roles(uow, user_id)
    if (role.value in roles) != removing:
        # Nothing to change, but a stale view must still be told to reload.
        current = await _load(uow, user_id)
        if current.row_version != expected:
            raise _stale()
        return current

    new_version = await repository.bump_row_version(uow, user_id, expected)
    if new_version is None:
        raise _stale()
    if not await write(uow, user_id, role.value):
        # The role changed by a path that did not bump the version: the caller's view is
        # out of date. Raising rolls back the bump.
        raise _stale()

    payload = (IdentityUserRoleRemoved if removing else IdentityUserRoleAssigned)(role=role.value)
    await trace.append(
        uow,
        actor=actor.actor,
        payload=payload,
        subject_type=USER_SUBJECT,
        subject_id=user_id,
        subject_version=new_version,
    )
    _log.info(
        "identity.user_role_removed" if removing else "identity.user_role_assigned",
        extra={"user_id": str(user_id), "actor_id": actor.actor.id, "role": role.value},
    )
    return await _load(uow, user_id)


def _stale() -> RowVersionMismatchError:
    return RowVersionMismatchError(
        "The user was changed by someone else since you opened it. Reload and try again."
    )
