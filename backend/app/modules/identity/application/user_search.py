"""User search and name lookup (Story 1.7).

`search_users` backs the collaborator picker (callers with `identity.user.search`): it
matches the name or email of any provisioned user, for queries of at least two characters.
`user_names` lets other modules (through `public.py`) show names for user ids they store,
without reading identity's tables.
"""

from uuid import UUID

from pydantic import BaseModel

from app.modules.identity.actions import Action
from app.modules.identity.adapters import repository
from app.modules.identity.application.authorize import authorize
from app.modules.identity.domain.policy import Principal
from app.platform.uow import UnitOfWork

SEARCH_DEFAULT_LIMIT = 20
SEARCH_MAX_LIMIT = 50
SEARCH_MIN_QUERY = 2
SEARCH_MAX_QUERY = 100


class UserSummary(BaseModel):
    """A user as the collaborator picker shows them."""

    id: str
    name: str
    email: str


class UserSearchResult(BaseModel):
    """Matching users, ordered by name; at most `limit` of them."""

    items: list[UserSummary]


async def search_users(
    uow: UnitOfWork, actor: Principal, q: str, limit: int = SEARCH_DEFAULT_LIMIT
) -> UserSearchResult:
    authorize(actor, Action.USER_SEARCH)
    q = q.strip()
    if len(q) < SEARCH_MIN_QUERY:
        return UserSearchResult(items=[])
    limit = max(1, min(limit, SEARCH_MAX_LIMIT))
    records = await repository.search_users(uow, q[:SEARCH_MAX_QUERY], limit=limit)
    return UserSearchResult(
        items=[UserSummary(id=str(r.id), name=r.name, email=r.email) for r in records]
    )


async def user_names(
    uow: UnitOfWork, ids: list[UUID] | set[UUID] | frozenset[UUID]
) -> dict[UUID, str]:
    """`{user_id: name}` for the ids that exist. No authorization: callers decide what they
    may show."""
    return await repository.user_names(uow, sorted(set(ids)))
