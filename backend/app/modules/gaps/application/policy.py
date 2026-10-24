"""Mandatory security items behind Requirements (Story 6.6), for other modules.

A Requirement is tied to a mandatory security item when one of the Opportunity's mandatory
Gaps (any status) is linked to it and that Gap's `checklist_item` trigger is a mandatory item
of a `security`-domain Checklist version. Decided by these rules only, never by a model. No
authorization here: callers have already checked that the actor may read the Opportunity, or
run as the worker.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from app.modules.gaps.adapters import repository as repo
from app.modules.knowledge.application import public as knowledge
from app.platform.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class ChecklistItemPolicy:
    """A mandatory item of a `security`-domain Checklist version."""

    checklist_id: UUID
    version: int
    item_id: UUID


async def security_policies(
    uow: UnitOfWork, opportunity_id: UUID, requirement_ids: Iterable[UUID]
) -> dict[UUID, ChecklistItemPolicy]:
    """For each of these Requirements tied to a mandatory security item, that item (the
    first by Checklist id, version and item id when there are several)."""
    triggers = await repo.mandatory_triggers_for(
        uow, opportunity_id, sorted(set(requirement_ids), key=str)
    )
    mandatory = await knowledge.mandatory_items_in_domain(
        uow, {(c, v, i) for _, c, v, i in triggers}, knowledge.ChecklistDomain.SECURITY
    )
    found: dict[UUID, ChecklistItemPolicy] = {}
    for requirement_id, checklist_id, version, item_id in sorted(
        triggers, key=lambda t: (str(t[1]), t[2], str(t[3]))
    ):
        if (checklist_id, version, item_id) in mandatory and requirement_id not in found:
            found[requirement_id] = ChecklistItemPolicy(checklist_id, version, item_id)
    return found
