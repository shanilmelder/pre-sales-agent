"""Gap data for other modules (Story 8.1): the Opportunity's open Gaps, for the
estimating agent's risk context. No authorization here: callers have already checked that
the actor may read the Opportunity, or run as the worker."""

from dataclasses import dataclass, field
from uuid import UUID

from app.modules.gaps.adapters import repository as repo
from app.modules.gaps.domain.gaps import impact_rank
from app.platform.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class GapSummary:
    """An open Gap: its category and impact, with its title and why it matters."""

    id: UUID
    category: str
    impact: str
    title: str = field(repr=False)
    why_it_matters: str = field(repr=False)


async def open_gap_summaries(uow: UnitOfWork, opportunity_id: UUID) -> list[GapSummary]:
    """The Opportunity's open Gaps, high impact first, then medium, then low (oldest first
    within an impact), as the Gaps tab lists them."""
    records = await repo.open_gaps(uow, opportunity_id)
    ranked = sorted(records, key=lambda g: (impact_rank(g.impact), g.created_at, g.id))
    return [
        GapSummary(
            id=g.id,
            category=g.category,
            impact=g.impact,
            title=g.title,
            why_it_matters=g.why_it_matters,
        )
        for g in ranked
    ]
