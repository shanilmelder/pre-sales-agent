"""Gap data for other modules (Stories 8.1 and 8.4): the Opportunity's open Gaps, for the
estimating agent, and Gaps by id, for the Assumptions Register. No authorization here:
callers have already checked that the actor may read the Opportunity, or run as the
worker."""

from dataclasses import dataclass, field
from uuid import UUID

from app.modules.gaps.adapters import repository as repo
from app.modules.gaps.adapters.repository import GapRecord
from app.modules.gaps.domain.gaps import impact_rank
from app.platform.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class GapSummary:
    """A Gap: its category, impact, status and row version, with its title, why it matters
    and its drafted Clarification Question (empty when it has none). `converted_to` is set
    once the Gap is `converted` (`condition` or `contingency`)."""

    id: UUID
    category: str
    impact: str
    title: str = field(repr=False)
    why_it_matters: str = field(repr=False)
    question: str = field(repr=False, default="")
    status: str = "open"
    row_version: int = 1
    converted_to: str | None = None


def _ranked(records: list[GapRecord]) -> list[GapRecord]:
    return sorted(records, key=lambda g: (impact_rank(g.impact), g.created_at, g.id))


async def _summaries(uow: UnitOfWork, records: list[GapRecord]) -> list[GapSummary]:
    questions = await repo.questions_for(uow, [g.id for g in records])
    summaries: list[GapSummary] = []
    for g in records:
        question = questions.get(g.id)
        summaries.append(
            GapSummary(
                id=g.id,
                category=g.category,
                impact=g.impact,
                title=g.title,
                why_it_matters=g.why_it_matters,
                question="" if question is None else question.text,
                status=g.status,
                row_version=g.row_version,
                converted_to=g.converted_to,
            )
        )
    return summaries


async def open_gap_summaries(uow: UnitOfWork, opportunity_id: UUID) -> list[GapSummary]:
    """The Opportunity's open Gaps, high impact first, then medium, then low (oldest first
    within an impact), as the Gaps tab lists them, each with its drafted question."""
    return await _summaries(uow, _ranked(await repo.open_gaps(uow, opportunity_id)))


async def gap_summaries(
    uow: UnitOfWork, opportunity_id: UUID, gap_ids: list[UUID]
) -> dict[UUID, GapSummary]:
    """These Gaps of the Opportunity, whatever their status; ids of other Opportunities'
    Gaps, or unknown ones, are left out."""
    found = await repo.gaps_by_id(uow, opportunity_id, gap_ids)
    return {s.id: s for s in await _summaries(uow, list(found.values()))}
