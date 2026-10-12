"""Conflicts routes (Story 6.1): `GET /api/v1/opportunities/{opportunity_id}/conflicts`.
Read-only."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter

from app.modules.conflicts.application import public as conflicts
from app.modules.conflicts.application.public import ConflictsView
from app.modules.identity.application.public import CurrentPrincipal
from app.platform.errors import PROBLEM_JSON, Problem
from app.platform.uow import UoW

PROBLEM_CONTENT = {PROBLEM_JSON: {"schema": Problem.model_json_schema()}}
_DESCRIBED: dict[int, str] = {
    401: "No valid access token (`token_missing`, `token_expired`, `token_invalid`)",
    404: "No Opportunity with this id, or the caller may not see it (`not_found`)",
    422: "The Opportunity id is not a UUID (`validation_error`)",
    503: "Sign-in service unavailable (`auth_unavailable`)",
}


def _responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {
        code: {"description": _DESCRIBED[code], "content": PROBLEM_CONTENT}
        for code in (401, 503, *codes)
    }


router = APIRouter(prefix="/opportunities/{opportunity_id}", tags=["conflicts"])


@router.get("/conflicts", operation_id="get_conflicts", responses=_responses(404, 422))
async def get_conflicts(opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW) -> ConflictsView:
    """The Conflicts between the Opportunity's specialist Assessments (and its Estimate): open
    ones first, then resolved, each section critical to low and newest first, each with its
    positions (the agent and Assessment version, or the Estimate version; the value; the
    Requirement chip); and the open-plus-escalated count. Conflicts carried forward to a later
    run are left out. Anyone who can read the Opportunity."""
    return await conflicts.get_conflicts(uow, actor, opportunity_id)
