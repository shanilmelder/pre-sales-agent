"""assessments' public API. Other modules import assessments only from here."""

from uuid import UUID

from app.modules.assessments.application import review
from app.modules.assessments.application.assessments import (
    cancel_run,
    get_assessments,
    retry_task,
    start_run,
)
from app.modules.assessments.application.models import (
    AgentAssessment,
    AssessmentEffort,
    AssessmentFinding,
    AssessmentRun,
    AssessmentsView,
    AssessmentTask,
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
from app.modules.assessments.domain.assessments import AssessmentAgent
from app.platform.uow import UnitOfWork


async def enqueue_review(uow: UnitOfWork, opportunity_id: UUID) -> UUID:
    """Queue a Red Team Review of the Opportunity in the caller's Unit of Work (Story 6.5:
    after every accepted Estimate draft). Coalesces with a run that is queued and not yet
    started; returns the run's id."""
    return await review.enqueue_review(uow, opportunity_id)


__all__ = [
    "AgentAssessment",
    "AssessmentAgent",
    "AssessmentEffort",
    "AssessmentFinding",
    "AssessmentRun",
    "AssessmentTask",
    "AssessmentView",
    "AssessmentsView",
    "FindingLine",
    "FindingRequirement",
    "RedTeamFinding",
    "RedTeamReviewView",
    "RedTeamRun",
    "RedTeamView",
    "SeverityCounts",
    "cancel_run",
    "enqueue_review",
    "get_assessments",
    "get_red_team",
    "retry_task",
    "start_review",
    "start_run",
]
