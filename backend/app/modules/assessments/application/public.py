"""assessments' public API. Other modules import assessments only from here."""

from uuid import UUID

from app.modules.assessments.adapters import assessment_repository
from app.modules.assessments.application import assessment, review
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
    after every stored Estimate Version). Coalesces with a run that is queued and not yet
    started; returns the run's id."""
    return await review.enqueue_review(uow, opportunity_id)


async def enqueue_run(uow: UnitOfWork, opportunity_id: UUID) -> UUID:
    """Queue an assessment run of the Opportunity in the caller's Unit of Work (Story 5.1:
    after every successful Gap detection). Coalesces with a run that is queued or running;
    returns the run's id. Never refuses with a conflict; any other error (e.g. the
    database) fails the caller's Unit of Work."""
    return await assessment.enqueue_run(uow, opportunity_id)


async def run_in_progress(uow: UnitOfWork, opportunity_id: UUID) -> bool:
    """Whether one of the Opportunity's assessment runs is queued or running (Story 8.3: the
    Estimate tab's waiting state). No authorization; for other modules."""
    return await assessment_repository.run_in_progress(uow, opportunity_id) is not None


async def run_number(uow: UnitOfWork, opportunity_id: UUID, run_id: UUID) -> int | None:
    """The assessment run's position among the Opportunity's runs, oldest first (Story 8.3:
    "from Assessments (run 3)"); None if it isn't one of them. No authorization."""
    return await assessment_repository.run_number(uow, opportunity_id, run_id)


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
    "enqueue_run",
    "get_assessments",
    "get_red_team",
    "retry_task",
    "run_in_progress",
    "run_number",
    "start_review",
    "start_run",
]
