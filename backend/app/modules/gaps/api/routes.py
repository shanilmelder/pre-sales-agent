"""Gap routes (Story 4.3): `GET /api/v1/opportunities/{opportunity_id}/gaps` and
`POST /api/v1/opportunities/{opportunity_id}/gap-detections`."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter

from app.modules.gaps.application import public as gaps
from app.modules.gaps.application.public import Detection, GapList
from app.modules.identity.application.public import CurrentPrincipal
from app.platform.errors import PROBLEM_JSON, Problem
from app.platform.uow import UoW

PROBLEM_CONTENT = {PROBLEM_JSON: {"schema": Problem.model_json_schema()}}
_DESCRIBED: dict[int, str] = {
    401: "No valid access token (`token_missing`, `token_expired`, `token_invalid`)",
    403: "Not allowed (`forbidden`): the caller can read the Opportunity but is not its owner "
    "or a collaborator, or is a sales representative",
    404: "No Opportunity with this id, or the caller may not see it (`not_found`)",
    409: "A Gap detection is already queued or running (`gap_detection_in_progress`)",
    422: "The Opportunity id is not a UUID (`validation_error`)",
    503: "Sign-in service unavailable (`auth_unavailable`)",
}


def _responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {
        code: {"description": _DESCRIBED[code], "content": PROBLEM_CONTENT}
        for code in (401, 503, *codes)
    }


router = APIRouter(prefix="/opportunities/{opportunity_id}", tags=["gaps"])


@router.get("/gaps", operation_id="list_gaps", responses=_responses(404, 422))
async def list_gaps(opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW) -> GapList:
    """The Opportunity's open Gaps, high impact first, then medium, then low (oldest first
    within an impact), then its converted Gaps in the same order, each with the Requirements
    it relates to and its drafted Clarification Question; and its latest Gap detection (null
    before the first). Anyone who can read the Opportunity."""
    return await gaps.list_gaps(uow, actor, opportunity_id)


@router.post(
    "/gap-detections",
    operation_id="start_gap_detection",
    status_code=201,
    responses={
        **_responses(403, 404, 409, 422),
        201: {"description": "The new detection, `queued`"},
    },
)
async def start_gap_detection(opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW) -> Detection:
    """Queue a new Gap detection over the Opportunity's active Requirements, e.g. to retry a
    failed one. The owner and collaborators, except sales representatives."""
    return await gaps.start_detection(uow, actor, opportunity_id)
