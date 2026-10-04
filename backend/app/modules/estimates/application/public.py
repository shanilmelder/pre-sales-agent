"""estimates' public API. Other modules import estimates only from here."""

from uuid import UUID

from app.modules.estimates.application import draft
from app.modules.estimates.application.estimates import get_estimate, start_draft
from app.modules.estimates.application.models import (
    EstimateDraft,
    EstimateLine,
    EstimateSection,
    EstimateVersion,
    EstimateView,
    LineRequirement,
    RoleHours,
    RoleMix,
    Totals,
)
from app.platform.uow import UnitOfWork


async def enqueue_draft(uow: UnitOfWork, opportunity_id: UUID) -> UUID:
    """Queue an Estimate draft of the Opportunity in the caller's Unit of Work (Story 8.1:
    after every successful Gap detection). Coalesces with a draft that is queued and not yet
    started; returns the draft's id."""
    return await draft.enqueue_draft(uow, opportunity_id)


__all__ = [
    "EstimateDraft",
    "EstimateLine",
    "EstimateSection",
    "EstimateVersion",
    "EstimateView",
    "LineRequirement",
    "RoleHours",
    "RoleMix",
    "Totals",
    "enqueue_draft",
    "get_estimate",
    "start_draft",
]
