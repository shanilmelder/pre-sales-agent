"""User search (Story 1.7): `GET /api/v1/users/search?q=`, for picking collaborators."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.modules.identity.api.routes import AUTH_RESPONSES, PROBLEM_CONTENT
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import CurrentPrincipal, UserSearchResult
from app.platform.uow import UoW

router = APIRouter(prefix="/users", tags=["identity"])


@router.get(
    "/search",
    operation_id="search_users",
    responses={
        **AUTH_RESPONSES,
        403: {
            "description": "No `identity.user.search` permission (`forbidden`)",
            "content": PROBLEM_CONTENT,
        },
        422: {
            "description": "Invalid query parameter (`validation_error`)",
            "content": PROBLEM_CONTENT,
        },
    },
)
async def search_users(
    actor: CurrentPrincipal,
    uow: UoW,
    q: Annotated[
        str, Query(min_length=identity.SEARCH_MIN_QUERY, max_length=identity.SEARCH_MAX_QUERY)
    ],
    limit: Annotated[
        int, Query(ge=1, le=identity.SEARCH_MAX_LIMIT)
    ] = identity.SEARCH_DEFAULT_LIMIT,
) -> UserSearchResult:
    """Provisioned users whose name or email contains `q` (case-insensitive), ordered by
    name."""
    return await identity.search_users(uow, actor, q, limit)
