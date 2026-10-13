"""Conflicts routes: `GET /api/v1/opportunities/{opportunity_id}/conflicts` (Story 6.1), and
a person's resolution or escalation of one (Story 6.3), each with `If-Match` and answering
with the Conflict and its `ETag`."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Response

from app.modules.conflicts.application import public as conflicts
from app.modules.conflicts.application.public import (
    ConflictEscalation,
    ConflictResolution,
    ConflictsView,
    ConflictView,
    EstimateLink,
)
from app.modules.estimates.application import public as estimates
from app.modules.identity.application.public import CurrentPrincipal
from app.platform.concurrency import etag
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

# The Estimate a decision on an `effort` Conflict sets, passed in so that `conflicts`' own
# layers never import `estimates` (which reads `conflicts` for its markers).
ESTIMATE = EstimateLink(lock=estimates.lock_for_decision, apply=estimates.apply_decision)


@router.get("/conflicts", operation_id="get_conflicts", responses=_responses(404, 422))
async def get_conflicts(opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW) -> ConflictsView:
    """The Conflicts between the Opportunity's specialist Assessments (and its Estimate): open
    ones first, then resolved, each section critical to low and newest first, each with its
    positions (the agent and Assessment version, or the Estimate version; the value; the
    Requirement chip), the decision or escalation, and what the caller may do; the
    open-plus-escalated count; and whom the caller may escalate to. Conflicts carried forward
    to a later run are left out. Anyone who can read the Opportunity."""
    return await conflicts.get_conflicts(uow, actor, opportunity_id)


_IF_MATCH = Annotated[
    str | None,
    Header(
        alias="If-Match",
        description='The ETag of the Conflict as last read (its `row_version`), e.g. `"1"`.',
    ),
]


def _decision_responses(
    verb: str, forbidden: str, unprocessable: str
) -> dict[int | str, dict[str, Any]]:
    return {
        401: {"description": _DESCRIBED[401], "content": PROBLEM_CONTENT},
        403: {"description": forbidden, "content": PROBLEM_CONTENT},
        404: {
            "description": "No Opportunity with this id, or the caller may not see it, or no "
            "Conflict with this id in it (`not_found`)",
            "content": PROBLEM_CONTENT,
        },
        409: {
            "description": f"The Conflict cannot be {verb}: it is already resolved "
            "(`conflict_already_resolved`) or already escalated (`conflict_not_open`)",
            "content": PROBLEM_CONTENT,
        },
        412: {
            "description": "The Conflict changed since the caller read it "
            "(`row_version_mismatch`); the `detail` names who changed it",
            "content": PROBLEM_CONTENT,
        },
        422: {"description": unprocessable, "content": PROBLEM_CONTENT},
        428: {
            "description": "No `If-Match` header (`if_match_required`)",
            "content": PROBLEM_CONTENT,
        },
        503: {"description": _DESCRIBED[503], "content": PROBLEM_CONTENT},
        200: {
            "description": "The Conflict as it is now",
            "headers": {
                "ETag": {
                    "description": "The Conflict's row version, for `If-Match`.",
                    "schema": {"type": "string"},
                }
            },
        },
    }


@router.post(
    "/conflicts/{conflict_id}/resolution",
    operation_id="resolve_conflict",
    responses=_decision_responses(
        "resolved",
        "The caller may read the Opportunity but not resolve its Conflicts: only the owner "
        "and collaborators except sales representatives, or the reviewer an escalated "
        "Conflict was escalated to (`forbidden`)",
        "`validation_error`: a blank or over-1,000-character reason, a position number the "
        "Conflict does not have, an entered position that is blank or over 200 characters "
        "(for an `effort` Conflict, not hours from 0 to 2,000 to 0.1 h); the `detail` is the "
        "sentence to show",
    ),
)
async def resolve_conflict(
    opportunity_id: UUID,
    conflict_id: UUID,
    body: ConflictResolution,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _IF_MATCH = None,
) -> ConflictView:
    """Resolve an open or escalated Conflict by choosing one of its positions or entering a
    different one, with a reason. Every original position is kept and traced. An `effort`
    decision also sets the Estimate line covering only that Requirement (as an edit with the
    reason); `applied_hours` or `not_applied` say what happened."""
    view = await conflicts.resolve_conflict(
        uow, actor, opportunity_id, conflict_id, body, if_match, ESTIMATE
    )
    response.headers["ETag"] = etag(view.row_version)
    return view


@router.post(
    "/conflicts/{conflict_id}/escalation",
    operation_id="escalate_conflict",
    responses=_decision_responses(
        "escalated",
        "The caller may read the Opportunity but not escalate its Conflicts: only the owner "
        "and collaborators except sales representatives (`forbidden`)",
        "`validation_error`: a blank or over-1,000-character reason, or a reviewer who is not "
        "the Opportunity's owner or a collaborator, or is the caller; the `detail` is the "
        "sentence to show",
    ),
)
async def escalate_conflict(
    opportunity_id: UUID,
    conflict_id: UUID,
    body: ConflictEscalation,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _IF_MATCH = None,
) -> ConflictView:
    """Escalate an open Conflict to a named reviewer on the Opportunity, with a reason. The
    reviewer can then resolve it."""
    view = await conflicts.escalate_conflict(
        uow, actor, opportunity_id, conflict_id, body, if_match
    )
    response.headers["ETag"] = etag(view.row_version)
    return view
