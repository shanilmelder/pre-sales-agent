"""Administration routes: Users & roles (Story 1.6), under `/api/v1/admin/users`.

Every endpoint authorizes inside its command or query (`identity.user.list`,
`identity.user.assign_role`, `identity.user.remove_role`); non-admins get 403 `forbidden`.
Single-user responses carry the user's `ETag`; writes need it back in `If-Match`.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response

from app.modules.identity.api.routes import AUTH_RESPONSES, PROBLEM_CONTENT
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import (
    AdminUser,
    AdminUserPage,
    CurrentPrincipal,
    Role,
)
from app.platform.concurrency import etag
from app.platform.uow import UoW


def _responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    described: dict[int, str] = {
        403: "Not a platform administrator (`forbidden`)",
        404: "No user with this id (`not_found`)",
        409: "Would leave no platform administrator (`last_administrator`)",
        412: "The user changed since it was read (`row_version_mismatch`)",
        422: "Invalid path or query parameter, e.g. an unknown role (`validation_error`)",
        428: "The write has no `If-Match` header (`if_match_required`)",
    }
    out: dict[int | str, dict[str, Any]] = dict(AUTH_RESPONSES)
    for code in codes:
        out[code] = {"description": described[code], "content": PROBLEM_CONTENT}
    return out


_ETAG_HEADER = {
    "ETag": {
        "description": "The user's row version, for `If-Match`.",
        "schema": {"type": "string"},
    }
}
_WRITE_RESPONSES = _responses(403, 404, 409, 412, 422, 428)
_WRITE_RESPONSES[200] = {"description": "The user after the change", "headers": _ETAG_HEADER}

router = APIRouter(prefix="/admin/users", tags=["admin"])

IfMatchHeader = Annotated[
    str | None,
    Header(
        alias="If-Match",
        description='The ETag of the user as last read, e.g. `"3"`.',
    ),
]


def _with_etag(response: Response, user: AdminUser) -> AdminUser:
    response.headers["ETag"] = etag(user.row_version)
    return user


@router.get("", operation_id="list_admin_users", responses=_responses(403, 422))
async def list_admin_users(
    actor: CurrentPrincipal,
    uow: UoW,
    page: Annotated[int, Query(ge=1, le=identity.MAX_PAGE)] = 1,
    page_size: Annotated[int, Query(ge=1, le=identity.MAX_PAGE_SIZE)] = identity.DEFAULT_PAGE_SIZE,
) -> AdminUserPage:
    """Users and their roles, ordered by name, one page at a time."""
    return await identity.list_users(uow, actor, page=page, page_size=page_size)


@router.get(
    "/{user_id}",
    operation_id="get_admin_user",
    responses={
        **_responses(403, 404, 422),
        200: {"description": "The user", "headers": _ETAG_HEADER},
    },
)
async def get_admin_user(
    user_id: UUID, actor: CurrentPrincipal, uow: UoW, response: Response
) -> AdminUser:
    """One user with their roles and who last changed them."""
    return _with_etag(response, await identity.get_user(uow, actor, user_id))


@router.put("/{user_id}/roles/{role}", operation_id="assign_role", responses=_WRITE_RESPONSES)
async def assign_role(
    user_id: UUID,
    role: Role,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: IfMatchHeader = None,
) -> AdminUser:
    """Give the user a role. Assigning a role they already hold changes nothing."""
    user = await identity.assign_role(uow, actor, user_id, role, if_match)
    return _with_etag(response, user)


@router.delete("/{user_id}/roles/{role}", operation_id="remove_role", responses=_WRITE_RESPONSES)
async def remove_role(
    user_id: UUID,
    role: Role,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: IfMatchHeader = None,
) -> AdminUser:
    """Take a role from the user. Removing a role they don't hold changes nothing; removing
    the last platform administrator is rejected with 409."""
    user = await identity.remove_role(uow, actor, user_id, role, if_match)
    return _with_etag(response, user)
