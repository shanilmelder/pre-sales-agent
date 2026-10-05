"""Opportunity routes (Stories 1.7 and 1.8), under `/api/v1/opportunities`.

Every endpoint authorizes inside its command or query. An Opportunity the caller may not
read answers 404 `not_found`, exactly like one that doesn't exist. Single-Opportunity
responses carry its `ETag`; edits and collaborator changes need it back in `If-Match`.
"""

import re
from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response
from fastapi.exceptions import RequestValidationError

from app.modules.identity.application.public import CurrentPrincipal
from app.modules.opportunities.application import public as opportunities
from app.modules.opportunities.application.public import (
    NewOpportunity,
    Opportunity,
    OpportunityChanges,
    OpportunityFacets,
    OpportunityFilters,
    OpportunityPage,
    OpportunityStatus,
    TracePage,
)
from app.modules.opportunities.domain.opportunity import PRODUCT_NAME_MAX
from app.platform.concurrency import etag
from app.platform.errors import PROBLEM_JSON, Problem
from app.platform.uow import UoW

PROBLEM_CONTENT = {PROBLEM_JSON: {"schema": Problem.model_json_schema()}}
_DESCRIBED: dict[int, str] = {
    401: "No valid access token (`token_missing`, `token_expired`, `token_invalid`)",
    403: "Not allowed (`forbidden`): creating without the presales engineer role, or "
    "editing the Opportunity or changing collaborators without being the owner",
    404: "No Opportunity with this id, or the caller may not see it (`not_found`)",
    412: "The Opportunity changed since it was read (`row_version_mismatch`)",
    422: "Invalid fields (`validation_error`), e.g. a target proposal date in the past, "
    "or collaborator (`invalid_collaborator`)",
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
    status: Annotated[
        str | None,
        Query(
            description="`all` only: Opportunities with this derived status.",
            json_schema_extra={"enum": [s.value for s in OpportunityStatus]},
        ),
    ] = None,
    owner: Annotated[
        str | None,
        Query(
            description="`all` only: Opportunities this user (a UUID) owns.",
            json_schema_extra={"format": "uuid"},
        ),
    ] = None,
    product: Annotated[
        str | None,
        Query(
            description="`all` only: Opportunities with this product among theirs, trimmed "
            f"and ignoring case; at most {PRODUCT_NAME_MAX} characters once trimmed. Blank "
            "is ignored.",
        ),
    ] = None,
    date_from: Annotated[
        str | None,
        Query(
            alias="from",
            description="`all` only: target proposal date on or after this calendar date "
            "(`YYYY-MM-DD`).",
            json_schema_extra={"format": "date"},
        ),
    ] = None,
    date_to: Annotated[
        str | None,
        Query(
            alias="to",
            description="`all` only: target proposal date on or before this calendar date "
            "(`YYYY-MM-DD`, not before `from`).",
            json_schema_extra={"format": "date"},
        ),
    ] = None,
) -> OpportunityPage:
    """Opportunities, newest first, one page at a time. With `scope=all` the optional
    filters combine with AND and only ever narrow what the caller can read; an invalid one
    is a 422 naming it. `scope=mine` ignores them entirely, valid or not."""
    if scope == "mine":
        return await opportunities.list_mine(uow, actor, page=page, page_size=page_size)
    filters = _parse_filters(
        status=status, owner=owner, product=product, date_from=date_from, date_to=date_to
    )
    return await opportunities.list_all(uow, actor, page=page, page_size=page_size, filters=filters)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_date(value: str) -> date:
    if not _DATE_RE.match(value):
        raise ValueError(value)
    return date.fromisoformat(value)


def _parse_filters(
    *,
    status: str | None,
    owner: str | None,
    product: str | None,
    date_from: str | None,
    date_to: str | None,
) -> OpportunityFilters:
    """The `scope=all` filters from their raw query values. Raises a 422 naming every
    invalid parameter (both dates for a reversed range)."""
    invalid: list[str] = []
    parsed_status: OpportunityStatus | None = None
    if status is not None:
        try:
            parsed_status = OpportunityStatus(status)
        except ValueError:
            invalid.append("status")
    owner_id: UUID | None = None
    if owner is not None:
        try:
            owner_id = UUID(owner)
        except ValueError:
            invalid.append("owner")
    trimmed = product.strip() if product is not None else None
    if trimmed is not None and len(trimmed) > PRODUCT_NAME_MAX:
        invalid.append("product")
    dates: dict[str, date | None] = {"from": None, "to": None}
    for name, raw in (("from", date_from), ("to", date_to)):
        if raw is not None:
            try:
                dates[name] = _parse_date(raw)
            except ValueError:
                invalid.append(name)
    start, end = dates["from"], dates["to"]
    if start is not None and end is not None and start > end:
        invalid.extend(("from", "to"))
    if invalid:
        raise RequestValidationError(
            [{"loc": ("query", name), "msg": "invalid", "type": "value_error"} for name in invalid]
        )
    return OpportunityFilters(
        status=parsed_status,
        owner_id=owner_id,
        product=trimmed or None,
        date_from=start,
        date_to=end,
    )


@router.get("/facets", operation_id="opportunity_facets", responses=_responses())
async def opportunity_facets(actor: CurrentPrincipal, uow: UoW) -> OpportunityFacets:
    """The owners and products across the Opportunities the caller can read, for the All
    Opportunities filters. Declared before `/{opportunity_id}` so it isn't read as an id."""
    return await opportunities.facets(uow, actor)


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


@router.patch(
    "/{opportunity_id}",
    operation_id="update_opportunity",
    responses=_WRITE_RESPONSES,
)
async def update_opportunity(
    opportunity_id: UUID,
    body: OpportunityChanges,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: IfMatchHeader = None,
) -> Opportunity:
    """Edit the title and/or target proposal date. Owner only. An omitted field stays
    unchanged; a blank title falls back to the customer name. Changing nothing writes
    nothing."""
    changed = await opportunities.update(uow, actor, opportunity_id, body, if_match)
    return _with_etag(response, changed)


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


TRACE_FILTER_MAX = 200
"""The longest trace filter value accepted (the web's `MAX_FILTER_LENGTH`)."""


@router.get(
    "/{opportunity_id}/trace",
    operation_id="list_opportunity_trace",
    responses=_responses(404, 422),
)
async def list_opportunity_trace(
    opportunity_id: UUID,
    actor: CurrentPrincipal,
    uow: UoW,
    page: Annotated[int, Query(ge=1, le=opportunities.MAX_PAGE)] = 1,
    page_size: Annotated[
        int, Query(ge=1, le=opportunities.TRACE_MAX_PAGE_SIZE)
    ] = opportunities.TRACE_DEFAULT_PAGE_SIZE,
    subject_type: Annotated[
        str | None,
        Query(
            max_length=TRACE_FILTER_MAX,
            description="Only events about this subject type, e.g. `intake.requirement`.",
        ),
    ] = None,
    actor_type: Annotated[
        str | None,
        Query(
            max_length=TRACE_FILTER_MAX,
            description="Only events by this actor type: `user`, `agent` or `system`.",
        ),
    ] = None,
    event_type: Annotated[
        str | None,
        Query(
            max_length=TRACE_FILTER_MAX,
            description="Only events of this type, e.g. `estimates.assumption.accepted`.",
        ),
    ] = None,
) -> TracePage:
    """The Opportunity's Decision Trace, read-only, newest first, one page at a time, with
    the subject, actor and event types present on it (`options`, unaffected by filters).
    Filters are exact matches on the stored values and combine with AND; an unknown value
    gives an empty page and an empty one (`?actor_type=`) is no filter. Each is at most
    200 characters. Anyone who can read the Opportunity can read its trace."""
    return await opportunities.trace_page(
        uow,
        actor,
        opportunity_id,
        page=page,
        page_size=page_size,
        subject_type=subject_type or None,
        actor_type=actor_type or None,
        event_type=event_type or None,
    )
