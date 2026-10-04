"""gaps' public API. Other modules import gaps only from here."""

from uuid import UUID

from app.modules.gaps.application import detection
from app.modules.gaps.application.conversion import mark_converted
from app.modules.gaps.application.gap_refs import GapSummary, gap_summaries, open_gap_summaries
from app.modules.gaps.application.gaps import list_gaps, start_detection
from app.modules.gaps.application.models import (
    ClarificationQuestion,
    Detection,
    Gap,
    GapList,
    GapRequirement,
    GapTrigger,
)
from app.modules.gaps.domain.gaps import GapCategory, Impact
from app.platform.uow import UnitOfWork


async def enqueue_detection(uow: UnitOfWork, opportunity_id: UUID) -> UUID:
    """Queue a Gap detection of the Opportunity in the caller's Unit of Work (Story 4.3:
    after every accepted Requirement extraction). Coalesces with a detection that is
    queued and not yet started; returns the detection's id."""
    return await detection.enqueue_detection(uow, opportunity_id)


__all__ = [
    "ClarificationQuestion",
    "Detection",
    "Gap",
    "GapCategory",
    "GapList",
    "GapRequirement",
    "GapSummary",
    "GapTrigger",
    "Impact",
    "enqueue_detection",
    "gap_summaries",
    "list_gaps",
    "mark_converted",
    "open_gap_summaries",
    "start_detection",
]
