"""Opportunity routes (Story 1.7), under `/api/v1/opportunities`.

Every endpoint authorizes inside its command or query. An Opportunity the caller may not
read answers 404 `not_found`, exactly like one that doesn't exist. Single-Opportunity
responses carry its `ETag`; collaborator changes need it back in `If-Match`.
"""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response

from app.modules.identity.application.public import CurrentPrincipal
from app.modules.opportunities.application import public as opportunities
from app.modules.opportunities.application.public import (
    NewOpportunity,
    Opportunity,
    OpportunityPage,
)
from app.platform.concurrency import etag
from app.platform.errors import PROBLEM_JSON, Problem
from app.platform.uow import UoW

PROBLEM_CONTENT = {PROBLEM_JSON: {"schema": Problem.model_json_schema()}}
_DESCRIBED: dict[int, str] = {
    401: "No valid access token (`token_missing`, `token_expired`, `token_invalid`)",
    403: "Not allowed (`forbidden`): creating without the presales engineer role, or "
    "changing collaborators without being the owner",
    404: "No Opportunity with this id, or the caller may not see it (`not_found`)",
    412: "The Opportunity changed since it was read (`row_version_mismatch`)",
    422: "Invalid fields (`validation_error`) or collaborator (`invalid_collaborator`)",
    428: "The write has no `If-Match` header (`if_match_required`)",
    503: "Sign-in service unavailable (`auth_unavailable`)",
}


def _responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {
        code: {"description": _DESCRIBED[code], "content": PROBLEM_CONTENT}
        for code in (401, 503, *codes)
    }


_ETAG_HEADER = {
    "ETag": {
        "description": "The Opportunity's row version, for `If-Match`.",
        "schema": {"type": "string"},
    }
}
_WRITE_RESPONSES = _responses(403, 404, 412, 422, 428)
_WRITE_RESPONSES[200] = {
    "description": "The Opportunity after the change",
    "headers": _ETAG_HEADER,
}

router = APIRouter(prefix="/opportunities", tags=["opportunities"])

IfMatchHeader = Annotated[
    str | None,
    Header(alias="If-Match", description='The ETag of the Opportunity as last read, e.g. `"3"`.'),
]


def _with_etag(response: Response, opportunity: Opportunity) -> Opportunity:
    response.headers["ETag"] = etag(opportunity.row_version)
    return opportunity


@router.post(
    "",
    operation_id="create_opportunity",
    status_code=201,
    responses={
        **_responses(403, 422),
        201: {"description": "The new Opportunity", "headers": _ETAG_HEADER},
    },
)
async def create_opportunity(
    body: NewOpportunity, actor: CurrentPrincipal, uow: UoW, response: Response
) -> Opportunity:
    """Create an Opportunity owned by the caller. Presales engineers only."""
    created = await opportunities.create(uow, actor, body)
    response.headers["Location"] = f"/api/v1/opportunities/{created.id}"
    return _with_etag(response, created)


@router.get("", operation_id="list_opportunities", responses=_responses(422))
async def list_opportunities(
    actor: CurrentPrincipal,
    uow: UoW,
    scope: Annotated[
        Literal["mine", "all"],
        Query(
            description="`mine`: owned or shared with the caller. `all`: every Opportunity "
            "the caller can read."
        ),
    ] = "all",
    page: Annotated[int, Query(ge=1, le=opportunities.MAX_PAGE)] = 1,
    page_size: Annotated[
        int, Query(ge=1, le=opportunities.MAX_PAGE_SIZE)
    ] = opportunities.DEFAULT_PAGE_SIZE,
) -> OpportunityPage:
    """Opportunities, newest first, one page at a time."""
    query = opportunities.list_mine if scope == "mine" else opportunities.list_all
    return await query(uow, actor, page=page, page_size=page_size)


@router.get(
    "/{opportunity_id}",
    operation_id="get_opportunity",
    responses={
        **_responses(404, 422),
        200: {"description": "The Opportunity", "headers": _ETAG_HEADER},
    },
)
async def get_opportunity(
    opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW, response: Response
) -> Opportunity:
    """One Opportunity with its derived status, owner and collaborators."""
    return _with_etag(response, await opportunities.get(uow, actor, opportunity_id))


@router.put(
    "/{opportunity_id}/collaborators/{user_id}",
    operation_id="add_collaborator",
    responses=_WRITE_RESPONSES,
)
async def add_collaborator(
    opportunity_id: UUID,
    user_id: UUID,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: IfMatchHeader = None,
) -> Opportunity:
    """Share the Opportunity with a user who holds a role. Owner only; adding an existing
    collaborator changes nothing."""
    changed = await opportunities.add_collaborator(uow, actor, opportunity_id, user_id, if_match)
    return _with_etag(response, changed)


@router.delete(
    "/{opportunity_id}/collaborators/{user_id}",
    operation_id="remove_collaborator",
    responses=_WRITE_RESPONSES,
)
async def remove_collaborator(
    opportunity_id: UUID,
    user_id: UUID,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: IfMatchHeader = None,
) -> Opportunity:
    """Stop sharing the Opportunity with a collaborator. Owner only; removing someone who
    isn't a collaborator changes nothing."""
    changed = await opportunities.remove_collaborator(uow, actor, opportunity_id, user_id, if_match)
    return _with_etag(response, changed)
