"""Estimate routes (Story 8.1): `GET /api/v1/opportunities/{opportunity_id}/estimate` and
`POST /api/v1/opportunities/{opportunity_id}/estimate-drafts`. No endpoint accepts a total."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter

from app.modules.estimates.application import public as estimates
from app.modules.estimates.application.public import EstimateDraft, EstimateView
from app.modules.identity.application.public import CurrentPrincipal
from app.platform.errors import PROBLEM_JSON, Problem
from app.platform.uow import UoW

PROBLEM_CONTENT = {PROBLEM_JSON: {"schema": Problem.model_json_schema()}}
_DESCRIBED: dict[int, str] = {
    401: "No valid access token (`token_missing`, `token_expired`, `token_invalid`)",
    403: "Not allowed (`forbidden`): the caller can read the Opportunity but is not its owner "
    "or a collaborator, or is a sales representative",
    404: "No Opportunity with this id, or the caller may not see it (`not_found`)",
    409: "An Estimate draft is already queued or running (`estimate_draft_in_progress`)",
    422: "The Opportunity id is not a UUID (`validation_error`)",
    503: "Sign-in service unavailable (`auth_unavailable`)",
}


def _responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {
        code: {"description": _DESCRIBED[code], "content": PROBLEM_CONTENT}
        for code in (401, 503, *codes)
    }


router = APIRouter(prefix="/opportunities/{opportunity_id}", tags=["estimates"])


@router.get("/estimate", operation_id="get_estimate", responses=_responses(404, 422))
async def get_estimate(opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW) -> EstimateView:
    """The Opportunity's current draft Estimate Version (null before the first) with its
    sections, lines, covered Requirements and server-calculated per-role hours, subtotals and
    totals; and its latest Estimate draft run (null before the first). Anyone who can read
    the Opportunity."""
    return await estimates.get_estimate(uow, actor, opportunity_id)


@router.post(
    "/estimate-drafts",
    operation_id="start_estimate_draft",
    status_code=201,
    responses={
        **_responses(403, 404, 409, 422),
        201: {"description": "The new draft, `queued`"},
    },
)
async def start_estimate_draft(
    opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW
) -> EstimateDraft:
    """Queue a new Estimate draft over the Opportunity's active Requirements, e.g. to retry a
    failed one. The owner and collaborators, except sales representatives."""
    return await estimates.start_draft(uow, actor, opportunity_id)
