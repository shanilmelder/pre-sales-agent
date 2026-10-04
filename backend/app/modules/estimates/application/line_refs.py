"""Estimate line data for other modules (Story 6.5): the current draft Estimate Version's
lines, for the Red Team agent, and a given version's lines, for the Red Team Review's line
chips. No authorization here: callers have already checked that the actor may read the
Opportunity, or run as the worker."""

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from app.modules.estimates.adapters import repository as repo
from app.modules.estimates.domain.estimates import section_rank
from app.platform.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class LineRef:
    """A line of an Estimate Version: its section, effort (0.1 h) and title."""

    id: UUID
    position: int
    section: str
    effort_hours: Decimal
    title: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class VersionLines:
    """An Estimate Version's id and number, with its lines in grid order (template section
    order, then position)."""

    version_id: UUID
    version: int
    lines: list[LineRef]


async def _lines(uow: UnitOfWork, version_id: UUID) -> list[LineRef]:
    records = await repo.lines_of(uow, version_id)
    return [
        LineRef(
            id=r.id,
            position=r.position,
            section=r.section,
            effort_hours=r.effort_hours,
            title=r.title,
        )
        for r in sorted(records, key=lambda r: (section_rank(r.section), r.position))
    ]


async def current_version_lines(uow: UnitOfWork, opportunity_id: UUID) -> VersionLines | None:
    """The Opportunity's current (draft) Estimate Version with its lines; None before the
    first."""
    record = await repo.current_version(uow, opportunity_id)
    if record is None:
        return None
    return VersionLines(record.id, record.version, await _lines(uow, record.id))


async def version_lines(
    uow: UnitOfWork, opportunity_id: UUID, version_id: UUID
) -> VersionLines | None:
    """That Estimate Version of the Opportunity, whatever its status, with its lines; None if
    it isn't one of the Opportunity's."""
    record = await repo.get_version(uow, version_id)
    if record is None or record.opportunity_id != opportunity_id:
        return None
    return VersionLines(record.id, record.version, await _lines(uow, record.id))
