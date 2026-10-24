"""Assessments routes.

- Red Team (Story 6.5): `GET /api/v1/opportunities/{opportunity_id}/red-team` and
  `POST /api/v1/opportunities/{opportunity_id}/red-team-reviews`.
- Outdated Assessments (Story 2.7): `GET …/{opportunity_id}/assessments/outdated`.
- Critic (Story 6.4): `GET …/{opportunity_id}/critic`.

The specialist Assessments' routes (`GET …/assessments` and the assessment run commands)
are served by `workflows` since Story 5.2, composed with this module's public API.

Read-only for Findings."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter

from app.modules.assessments.application import public as assessments
from app.modules.assessments.application.public import (
    CriticView,
    OutdatedAssessments,
    RedTeamRun,
    RedTeamView,
)
from app.modules.identity.application.public import CurrentPrincipal
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
