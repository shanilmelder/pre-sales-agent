"""Assessments routes.

- Red Team (Story 6.5): `GET /api/v1/opportunities/{opportunity_id}/red-team` and
  `POST /api/v1/opportunities/{opportunity_id}/red-team-reviews`.
- Outdated Assessments (Story 2.7): `GET …/{opportunity_id}/assessments/outdated`.
- Critic (Story 6.4): `GET …/{opportunity_id}/critic`.
- Blocking Findings (Story 6.6): `POST …/{opportunity_id}/findings/{finding_id}/evidence`,
  `…/resolution` and `…/override` on a Critic or Red Team Finding, each with `If-Match` and
  answering with the Finding's state and its `ETag`.

The specialist Assessments' routes (`GET …/assessments` and the assessment run commands)
are served by `workflows` since Story 5.2, composed with this module's public API.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Response

from app.modules.assessments.application import public as assessments
from app.modules.assessments.application.public import (
    CriticView,
    FindingEvidenceSubmission,
    FindingReason,
    FindingState,
    OutdatedAssessments,
    RedTeamRun,
    RedTeamView,
)
from app.modules.identity.application.public import CurrentPrincipal
from app.platform.concurrency import etag
from app.platform.errors import PROBLEM_JSON, Problem
from app.platform.uow import UoW

PROBLEM_CONTENT = {PROBLEM_JSON: {"schema": Problem.model_json_schema()}}
_DESCRIBED: dict[int, str] = {
    401: "No valid access token (`token_missing`, `token_expired`, `token_invalid`)",
    403: "Not allowed (`forbidden`): the caller can read the Opportunity but is not its owner "
    "or a collaborator, or is a sales representative",
    404: "No Opportunity with this id, or the caller may not see it (`not_found`)",
    409: "A Red Team review is already queued or running (`red_team_review_in_progress`), or "
    "the Red Team Agent is disabled in the Agent Registry (`registry_agent_disabled`)",
    422: "The Opportunity id is not a UUID (`validation_error`)",
    503: "Sign-in service unavailable (`auth_unavailable`)",
}


def _responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Problem responses by status; a variant description is keyed status x 10 + n."""
    return {
        (code if code < 1000 else code // 10): {
            "description": _DESCRIBED[code],
            "content": PROBLEM_CONTENT,
        }
        for code in (401, 503, *codes)
    }


router = APIRouter(prefix="/opportunities/{opportunity_id}", tags=["assessments"])


@router.get("/red-team", operation_id="get_red_team", responses=_responses(404, 422))
async def get_red_team(opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW) -> RedTeamView:
    """The Opportunity's current Red Team Review (null before the first) with its Findings,
    critical first, then high, medium and low, each with the Requirements and Estimate lines it
    challenges, and the counts per severity; and its latest Red Team run (null before the
    first). Anyone who can read the Opportunity."""
    return await assessments.get_red_team(uow, actor, opportunity_id)


@router.get("/critic", operation_id="get_critic", responses=_responses(404, 422))
async def get_critic(opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW) -> CriticView:
    """The Opportunity's current Critic Review (null before the first): the Critic's Findings
    on the latest assessment run's Assessments, critical first, then high, medium and low,
    each with the Requirements and the specialist Findings (at their Assessment version) it
    cites, and the counts per severity. Anyone who can read the Opportunity; read-only."""
    return await assessments.get_critic(uow, actor, opportunity_id)


@router.post(
    "/red-team-reviews",
    operation_id="start_red_team_review",
    status_code=201,
    responses={
        **_responses(403, 404, 409, 422),
        201: {"description": "The new Red Team run, `queued`"},
    },
)
async def start_red_team_review(
    opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW
) -> RedTeamRun:
    """Queue a new Red Team review of the Opportunity's active Requirements, open Gaps and
    draft Estimate, e.g. to retry a failed one. The owner and collaborators, except sales
    representatives."""
    return await assessments.start_review(uow, actor, opportunity_id)


@router.get(
    "/assessments/outdated",
    operation_id="list_outdated_assessments",
    responses=_responses(404, 422),
)
async def list_outdated_assessments(
    opportunity_id: UUID, actor: CurrentPrincipal, uow: UoW
) -> OutdatedAssessments:
    """The Opportunity's current Assessments that used a Requirement version that has changed
    since (a newer version, or the Requirement is no longer active), each with those
    Requirements' labels. Empty when none did; nothing is rerun. Anyone who can read the
    Opportunity."""
    return await assessments.outdated_assessments(uow, actor, opportunity_id)


# --- blocking Findings and overrides (Story 6.6) --------------------------------------------

_IF_MATCH = Annotated[
    str | None,
    Header(
        alias="If-Match",
        description='The ETag of the Finding as last read (its `row_version`), e.g. `"1"`.',
    ),
]


def _decision_responses(forbidden: str, unprocessable: str) -> dict[int | str, dict[str, Any]]:
    return {
        401: {"description": _DESCRIBED[401], "content": PROBLEM_CONTENT},
        403: {"description": forbidden, "content": PROBLEM_CONTENT},
        404: {
            "description": "No Opportunity with this id, or the caller may not see it, or no "
            "Critic or Red Team Finding with this id in it (`not_found`)",
            "content": PROBLEM_CONTENT,
        },
        409: {
            "description": "The Finding is no longer open (already resolved or overridden), "
            "or belongs to a superseded Review (`finding_not_open`)",
            "content": PROBLEM_CONTENT,
        },
        412: {
            "description": "The Finding changed since the caller read it "
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
            "description": "The Finding's state as it is now",
            "headers": {
                "ETag": {
                    "description": "The Finding's row version, for `If-Match`.",
                    "schema": {"type": "string"},
                }
            },
        },
    }


_RESOLVE_FORBIDDEN = (
    "The caller may read the Opportunity but not resolve its Findings: only the owner and "
    "collaborators, except sales representatives (`forbidden`)"
)
_REASON_INVALID = "`validation_error`: a blank or over-1,000-character reason"


@router.post(
    "/findings/{finding_id}/evidence",
    operation_id="supply_finding_evidence",
    responses=_decision_responses(
        _RESOLVE_FORBIDDEN,
        f"{_REASON_INVALID} (the note), or 1 to 20 references needed; "
        "`evidence_unresolvable`: a reference that is not a Requirement or Source version of "
        "this Opportunity",
    ),
)
async def supply_finding_evidence(
    opportunity_id: UUID,
    finding_id: UUID,
    body: FindingEvidenceSubmission,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _IF_MATCH = None,
) -> FindingState:
    """Resolve an open Critic or Red Team Finding by citing Evidence (the Opportunity's
    Requirements or Sources, at a version) with a note. The Finding becomes `resolved`
    (`evidence_supplied`) and no longer blocks submission."""
    state = await assessments.supply_evidence(
        uow, actor, opportunity_id, finding_id, body, if_match
    )
    response.headers["ETag"] = etag(state.row_version)
    return state


@router.post(
    "/findings/{finding_id}/resolution",
    operation_id="resolve_finding",
    responses=_decision_responses(_RESOLVE_FORBIDDEN, _REASON_INVALID),
)
async def resolve_finding(
    opportunity_id: UUID,
    finding_id: UUID,
    body: FindingReason,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _IF_MATCH = None,
) -> FindingState:
    """Mark an open Critic or Red Team Finding resolved (addressed) with a reason."""
    state = await assessments.mark_resolved(uow, actor, opportunity_id, finding_id, body, if_match)
    response.headers["ETag"] = etag(state.row_version)
    return state


@router.post(
    "/findings/{finding_id}/override",
    operation_id="override_finding",
    responses=_decision_responses(
        "The caller may read the Opportunity but not override this Finding: only the "
        "Opportunity's owner, a Head of Delivery, or a security reviewer on a security "
        "Finding (`forbidden`)",
        f"{_REASON_INVALID}; `finding_not_overridable`: the Finding is tied to a mandatory "
        "security Checklist item (no role may override it, checked first)",
    ),
)
async def override_finding(
    opportunity_id: UUID,
    finding_id: UUID,
    body: FindingReason,
    actor: CurrentPrincipal,
    uow: UoW,
    response: Response,
    if_match: _IF_MATCH = None,
) -> FindingState:
    """Override an open Critic or Red Team Finding with a reason: it becomes `overridden` and
    no longer blocks submission. Re-applying an earlier Finding's override is this command on
    the newer Finding (its `previous_override` holds the reason to reuse)."""
    state = await assessments.override_finding(
        uow, actor, opportunity_id, finding_id, body, if_match
    )
    response.headers["ETag"] = etag(state.row_version)
    return state
