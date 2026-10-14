"""assessments' public API. Other modules (and `app.orchestration`) import assessments only
from here."""

from uuid import UUID

from app.modules.assessments.application import review
from app.modules.assessments.application.assessment import (
    AssessedGap,
    AssessedRequirement,
    AssessmentInputs,
    accept_assessment,
    current_assessment_snapshots,
    current_sizings,
    load_inputs,
)
from app.modules.assessments.application.assessments import agent_assessments
from app.modules.assessments.application.models import (
    AgentAssessment,
    AssessmentEffort,
    AssessmentFinding,
    AssessmentView,
    FindingLine,
    FindingRequirement,
    RedTeamFinding,
    RedTeamReviewView,
    RedTeamRun,
    RedTeamView,
    SeverityCounts,
)
from app.modules.assessments.application.reviews import get_red_team, start_review
from app.modules.assessments.domain.assessments import AGENTS, AssessmentAgent
from app.modules.assessments.domain.reviews import RunErrorCode
from app.platform.uow import UnitOfWork


async def enqueue_review(uow: UnitOfWork, opportunity_id: UUID) -> UUID:
    """Queue a Red Team Review of the Opportunity in the caller's Unit of Work (Story 6.5:
    after every stored Estimate Version). Coalesces with a run that is queued and not yet
    started; returns the run's id."""
    return await review.enqueue_review(uow, opportunity_id)


__all__ = [
    "AGENTS",
    "AgentAssessment",
    "AssessedGap",
    "AssessedRequirement",
    "AssessmentAgent",
    "AssessmentEffort",
    "AssessmentFinding",
    "AssessmentInputs",
    "AssessmentView",
    "FindingLine",
    "FindingRequirement",
    "RedTeamFinding",
    "RedTeamReviewView",
    "RedTeamRun",
    "RedTeamView",
    "RunErrorCode",
    "SeverityCounts",
    "accept_assessment",
    "agent_assessments",
    "current_assessment_snapshots",
    "current_sizings",
    "enqueue_review",
    "get_red_team",
    "load_inputs",
    "start_review",
]
