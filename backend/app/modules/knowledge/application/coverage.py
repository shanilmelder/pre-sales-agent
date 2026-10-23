"""Knowledge coverage (Story 4.1): `get_coverage`, whether the Knowledge Base documents the
products and Integration Types an Opportunity has in scope. For other modules: no
authorization, like `find_applicable_checklists` (callers decide what they may show)."""

from collections.abc import Iterable
from uuid import UUID

from app.modules.knowledge.adapters import source_repository as repo
from app.modules.knowledge.application.source_models import (
    Coverage,
    IntegrationTypeCoverage,
    ProductCoverage,
)
from app.modules.knowledge.domain.checklists import match_key
from app.platform.uow import UnitOfWork


async def get_coverage(
    uow: UnitOfWork, *, products: Iterable[str], integration_type_ids: Iterable[UUID]
) -> Coverage:
    """Per product and per Integration Type, `ready` when at least one active Source
    matches (its product, trimmed and ignoring case; or one of its tags) and its latest
    version is embedded (`ready`)."""
    wanted_products: dict[str, str] = {}
    for product in products:
        if product.strip():
            wanted_products.setdefault(match_key(product), product.strip())
    wanted_types = list(dict.fromkeys(integration_type_ids))

    ready = await repo.ready_sources(uow)
    ready_products = {match_key(product) for _, product in ready}
    tags = await repo.tags_for(uow, [source_id for source_id, _ in ready]) if wanted_types else {}
    ready_types = {entry_id for ids in tags.values() for entry_id in ids}
    return Coverage(
        products=[
            ProductCoverage(product=name, ready=key in ready_products)
            for key, name in wanted_products.items()
        ],
        integration_types=[
            IntegrationTypeCoverage(id=str(entry_id), ready=entry_id in ready_types)
            for entry_id in wanted_types
        ],
    )
