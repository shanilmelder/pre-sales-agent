"""The Gaps tab context (Story 4.1): `gaps_context`, read by anyone who can read the
Opportunity (sales representatives included). It composes, through the public APIs only:
the Opportunity's products and industry (`opportunities.get`), the Integration Types on its
active Requirements and its untagged integration Requirements (`intake.integration_scope`),
the applicable Checklists (`knowledge.find_applicable_checklists`) and the scope the
Knowledge Base doesn't document (`knowledge.get_coverage`). It changes nothing and queues no
detection."""

from uuid import UUID

from app.modules.gaps.application.models import (
    GapsContext,
    GapsContextChecklist,
    UncoveredIntegrationType,
    UncoveredScope,
)
from app.modules.identity.application.public import Principal
from app.modules.intake.application import public as intake
from app.modules.knowledge.application import public as knowledge
from app.modules.opportunities.application import public as opportunities
from app.platform.uow import UnitOfWork


async def gaps_context(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> GapsContext:
    opportunity = await opportunities.get(uow, actor, opportunity_id)  # 404 when hidden
    tag_ids, untagged = await intake.integration_scope(uow, opportunity_id)
    checklists = await knowledge.find_applicable_checklists(
        uow,
        products=opportunity.products,
        industry=opportunity.industry,
        integration_type_ids=tag_ids,
    )
    coverage = await knowledge.get_coverage(
        uow, products=opportunity.products, integration_type_ids=tag_ids
    )
    uncovered_types: list[UncoveredIntegrationType] = []
    for item in coverage.integration_types:
        if item.ready:
            continue
        entry = await knowledge.get_catalogue_entry(uow, UUID(item.id))
        # A retired type can't be chosen in the Sources filter, so it isn't reported.
        if entry is not None and not entry.retired:
            uncovered_types.append(UncoveredIntegrationType(id=entry.id, name=entry.name))
    return GapsContext(
        applicable_checklists=[
            GapsContextChecklist(
                checklist_id=c.checklist_id, version=c.version, name=c.name, domain=c.domain
            )
            for c in checklists
        ],
        untagged_integration_count=untagged,
        uncovered=UncoveredScope(
            products=[p.product for p in coverage.products if not p.ready],
            integration_types=uncovered_types,
        ),
    )
