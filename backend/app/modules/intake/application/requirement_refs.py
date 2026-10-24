"""Requirement data for other modules (Story 4.3): the active Requirements at their current
versions, and the texts of given Requirement versions. No authorization here: callers have
already checked that the actor may read the Opportunity, or run as the worker.

Each Requirement carries its stored number (Story 2.6): given when it was created (extracted,
created, split or merged) as one past the Opportunity's highest, and never reused, so a
Requirement keeps its `R<n>` label after others are deleted, split or merged. The active
Requirements come by number, the order the Requirements tab lists them in.
"""

from dataclasses import dataclass, field
from uuid import UUID

from app.modules.intake.adapters import requirements_repository as repo
from app.platform.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class RequirementSnapshot:
    """An active Requirement at its current version."""

    id: UUID
    version: int
    number: int
    """Its stable number within the Opportunity: `R<n>`."""
    classification: str
    text: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class RequirementVersionText:
    classification: str
    text: str = field(repr=False)


async def active_requirement_snapshots(
    uow: UnitOfWork, opportunity_id: UUID
) -> list[RequirementSnapshot]:
    """The Opportunity's active Requirements at their current versions, by number."""
    records = await repo.active_requirements(uow, opportunity_id)
    return [
        RequirementSnapshot(
            id=r.id,
            version=r.version,
            number=r.number,
            classification=r.classification,
            text=r.text,
        )
        for r in records
    ]


async def active_requirement_ids(
    uow: UnitOfWork, opportunity_ids: list[UUID]
) -> dict[UUID, set[UUID]]:
    """The ids of each of these Opportunities' active Requirements, in one query (Story 8.6:
    the Opportunity list's blocker count)."""
    return await repo.active_ids_in(uow, opportunity_ids)


async def requirement_version_texts(
    uow: UnitOfWork, opportunity_id: UUID, refs: list[tuple[UUID, int]]
) -> dict[tuple[UUID, int], RequirementVersionText]:
    """The text and classification of these versions `(id, version)` of the Opportunity's
    Requirements; versions not found are left out."""
    found = await repo.version_texts(uow, opportunity_id, refs)
    return {
        ref: RequirementVersionText(classification=classification, text=text)
        for ref, (text, classification) in found.items()
    }
