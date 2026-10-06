"""Administration routes: Users & roles (Story 1.6; read-only since Story 1.9), under
`/api/v1/admin/users`.

Roles are managed in Auth0; these endpoints only show each user's roles as of their last
sign-in. Every endpoint authorizes inside its query (`identity.user.list`); callers without
that permission get 403 `forbidden`. Single-user responses carry the user's `ETag`.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.modules.identity.api.routes import AUTH_RESPONSES, PROBLEM_CONTENT
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import (
    AdminUser,
    AdminUserPage,
    CurrentPrincipal,
)
from app.platform.concurrency import etag
from app.platform.uow import UoW


def _responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    described: dict[int, str] = {
        403: "No `identity.user.list` permission (`forbidden`)",
        404: "No user with this id (`not_found`)",
        422: "Invalid path or query parameter (`validation_error`)",
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

router = APIRouter(prefix="/admin/users", tags=["admin"])


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
    """Users and their roles (as of each user's last sign-in), ordered by name, one page at
    a time."""
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
    """One user with their roles as of their last sign-in."""
    return _with_etag(response, await identity.get_user(uow, actor, user_id))
