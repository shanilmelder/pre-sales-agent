"""assessments' public API. Other modules import assessments only from here."""

from uuid import UUID

from app.modules.assessments.application import review
from app.modules.assessments.application.models import (
    FindingLine,
    FindingRequirement,
    RedTeamFinding,
    RedTeamReviewView,
    RedTeamRun,
    RedTeamView,
    SeverityCounts,
)
from app.modules.assessments.application.reviews import get_red_team, start_review
from app.platform.uow import UnitOfWork


async def enqueue_review(uow: UnitOfWork, opportunity_id: UUID) -> UUID:
    """Queue a Red Team Review of the Opportunity in the caller's Unit of Work (Story 6.5:
    after every accepted Estimate draft). Coalesces with a run that is queued and not yet
    started; returns the run's id."""
    return await review.enqueue_review(uow, opportunity_id)


__all__ = [
    "FindingLine",
    "FindingRequirement",
    "RedTeamFinding",
    "RedTeamReviewView",
    "RedTeamRun",
    "RedTeamView",
    "SeverityCounts",
    "enqueue_review",
    "get_red_team",
    "start_review",
]
