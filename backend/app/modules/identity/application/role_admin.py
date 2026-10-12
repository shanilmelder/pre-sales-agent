"""Users & roles (Story 1.6; read-only since Story 1.9): list users and their roles.

Roles are assigned in Auth0, not here. The roles shown come from `identity_user_roles`, a
display-only cache refreshed from each user's access token, so they are the roles as of
that user's last sign-in. Nothing here authorizes from the cache.
"""

from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.identity.actions import Action
from app.modules.identity.adapters import repository
from app.modules.identity.adapters.repository import AdminUserRecord
from app.modules.identity.application.authorize import authorize
from app.modules.identity.application.provisioning import USER_SUBJECT
from app.modules.identity.domain.policy import Principal, Resource
from app.modules.identity.domain.roles import Role
from app.platform.errors import NotFoundError
from app.platform.uow import UnitOfWork

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
MAX_PAGE = 1_000_000
_ROLE_VALUES = frozenset(role.value for role in Role)


class AdminUser(BaseModel):
    """A platform user as administrators see it. `roles` are as of the user's last sign-in
    (managed in Auth0). `row_version` is also the `ETag`."""

    id: str
    name: str
    email: str
    roles: list[Role]
    row_version: int


class AdminUserPage(BaseModel):
    """One page of users, ordered by name."""

    items: list[AdminUser]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)


def _admin_user(record: AdminUserRecord) -> AdminUser:
    return AdminUser(
        id=str(record.id),
        name=record.name,
        email=record.email,
        roles=sorted(Role(value) for value in record.roles if value in _ROLE_VALUES),
        row_version=record.row_version,
    )


async def list_users(
    uow: UnitOfWork, actor: Principal, *, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE
) -> AdminUserPage:
    authorize(actor, Action.USER_LIST)
    records = await repository.list_users(uow, offset=(page - 1) * page_size, limit=page_size)
    return AdminUserPage(
        items=[_admin_user(r) for r in records],
        page=page,
        page_size=page_size,
        total=await repository.count_users(uow),
    )


async def get_user(uow: UnitOfWork, actor: Principal, user_id: UUID) -> AdminUser:
    authorize(actor, Action.USER_LIST, Resource(type=USER_SUBJECT, id=user_id))
    record = await repository.get_user(uow, user_id)
    if record is None:
        raise NotFoundError("No user with this id.")
    return _admin_user(record)
