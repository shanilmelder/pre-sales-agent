"""Knowledge coverage: which products and Integration Types the Knowledge Base covers.
Computed on every read; nothing is stored.

`get_coverage` (Story 4.1): per product and, separately, per Integration Type, whether any
Ready Source documents it (its product, or one of its tags).

`get_pair_coverage` and `coverage_matrix` (Story 3.5) count per product and Integration
Type pair:

- A Source counts when it isn't retired and its latest version's embedding is `ready`. It
  covers its one product with each of its Integration Type tags; `stale` counts the ones not
  reviewed within `stale_months`.
- A Checklist counts when it is active and has a published version, by its published scope:
  each scoped product with each scoped Integration Type. With products but no Integration
  Types it covers every column of those products; with Integration Types but no products,
  every row of those columns; scoped only by industry, no pair (it is listed under
  `industries`). This is deliberately narrower than `find_applicable_checklists` (which
  matches on any one dimension): a cell answers whether that exact product and Integration
  Type pair is covered.

Products match trimmed and case-folded (`match_key`).

`get_coverage` and `get_pair_coverage` are for other modules (no authorization: the caller
decides what it may show); `coverage_matrix` is the Coverage view and needs a role.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from app.modules.identity.application.public import Principal
from app.modules.knowledge.adapters import checklist_repository, source_repository
from app.modules.knowledge.adapters.source_repository import CoverageSource
from app.modules.knowledge.application.catalogue import list_catalogue
from app.modules.knowledge.application.coverage_models import (
    CoverageCell,
    CoverageIndustry,
    CoverageIntegrationType,
    CoveragePair,
    CoverageRow,
    KnowledgeCoverage,
)
from app.modules.knowledge.application.source_models import (
    Coverage,
    IntegrationTypeCoverage,
    ProductCoverage,
)
from app.modules.knowledge.application.sources import today_utc
from app.modules.knowledge.domain.catalogue import Kind
from app.modules.knowledge.domain.checklists import match_key
from app.modules.knowledge.domain.coverage import coverage_status
from app.modules.knowledge.domain.sources import is_stale
from app.platform.errors import ForbiddenError
from app.platform.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class _Scope:
    """An active Checklist's published scope."""

    name: str
    products: list[str]
    industry: str | None
    integration_type_ids: list[UUID]


@dataclass(slots=True)
class _Tally:
    sources: int = 0
    stale: int = 0
    checklists: int = 0


type _Tallies = dict[tuple[str, UUID], _Tally]


async def _load(uow: UnitOfWork) -> tuple[list[CoverageSource], list[_Scope]]:
    sources = await source_repository.ready_sources(uow)
    records = sorted(
        await checklist_repository.published_active(uow), key=lambda r: (r.name.casefold(), r.id)
    )
    tags = await checklist_repository.tags_for(uow, [r.id for r in records])
    scopes = [
        _Scope(
            name=r.name,
            products=r.products,
            industry=r.industry,
            integration_type_ids=tags.get(r.id, []),
        )
        for r in records
    ]
    return sources, scopes


def _tally(
    keys: set[str],
    type_ids: set[UUID],
    sources: list[CoverageSource],
    scopes: list[_Scope],
    *,
    today: date,
    stale_months: int,
) -> _Tallies:
    """The counts of every pair of `keys` (product `match_key`s) and `type_ids` covered by
    something; pairs not in the result have none."""
    tallies: _Tallies = {}
    for source in sources:
        key = match_key(source.product)
        if key not in keys:
            continue
        stale = is_stale(source.last_reviewed_on, today, stale_months)
        for type_id in set(source.integration_type_ids) & type_ids:
            tally = tallies.setdefault((key, type_id), _Tally())
            tally.sources += 1
            tally.stale += int(stale)
    for scope in scopes:
        products = {match_key(p) for p in scope.products}
        types = set(scope.integration_type_ids)
        if not products and not types:
            continue  # Industry only.
        rows = (products & keys) if products else keys
        columns = (types & type_ids) if types else type_ids
        for key in rows:
            for type_id in columns:
                tallies.setdefault((key, type_id), _Tally()).checklists += 1
    return tallies


def _distinct(products: Iterable[str]) -> dict[str, str]:
    """`{match_key: first trimmed spelling}` of the non-blank products, in order."""
    result: dict[str, str] = {}
    for product in products:
        name = product.strip()
        if name and match_key(name) not in result:
            result[match_key(name)] = name
    return result


def _counts(tallies: _Tallies, key: str, type_id: UUID) -> dict[str, object]:
    tally = tallies.get((key, type_id), _Tally())
    return {
        "sources": tally.sources,
        "stale": tally.stale,
        "checklists": tally.checklists,
        "status": coverage_status(tally.sources, tally.stale, tally.checklists),
    }


async def get_coverage(
    uow: UnitOfWork, *, products: Iterable[str], integration_type_ids: Iterable[UUID]
) -> Coverage:
    """Per product and per Integration Type, `ready` when at least one active Source
    matches (its product, trimmed and ignoring case; or one of its tags) and its latest
    version is embedded (`ready`)."""
    wanted_products = _distinct(products)
    wanted_types = list(dict.fromkeys(integration_type_ids))

    ready = await source_repository.ready_sources(uow)
    ready_products = {match_key(source.product) for source in ready}
    ready_types = {entry_id for source in ready for entry_id in source.integration_type_ids}
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


async def get_pair_coverage(
    uow: UnitOfWork,
    *,
    products: Iterable[str],
    integration_type_ids: Iterable[UUID],
    stale_months: int,
    today: date | None = None,
) -> list[CoveragePair]:
    """The counts and status for each product (trimmed, repeats ignoring case dropped, blank
    ones skipped) with each Integration Type, products first, in the order given. For other
    modules (Gap detection, weak-coverage banners); no authorization. Retired or unknown
    Integration Type ids are dropped."""
    wanted = _distinct(products)
    active = {UUID(e.id) for e in await list_catalogue(uow, Kind.INTEGRATION_TYPE)}
    type_ids = [t for t in dict.fromkeys(integration_type_ids) if t in active]
    if not wanted or not type_ids:
        return []
    sources, scopes = await _load(uow)
    tallies = _tally(
        set(wanted),
        set(type_ids),
        sources,
        scopes,
        today=today or today_utc(),
        stale_months=stale_months,
    )
    return [
        CoveragePair.model_validate(
            {"product": name, "integration_type_id": str(t), **_counts(tallies, key, t)}
        )
        for key, name in wanted.items()
        for t in type_ids
    ]


def _industries(scopes: list[_Scope]) -> list[CoverageIndustry]:
    groups: dict[str, tuple[str, list[str]]] = {}
    for scope in scopes:
        if scope.products or scope.integration_type_ids or scope.industry is None:
            continue
        name = scope.industry.strip()
        if not name:
            continue
        groups.setdefault(match_key(name), (name, []))[1].append(scope.name)
    ordered = sorted(groups.values(), key=lambda g: (g[0].casefold(), g[0]))
    return [
        CoverageIndustry(
            industry=industry,
            checklists=len(names),
            names=sorted(names, key=lambda n: (n.casefold(), n)),
        )
        for industry, names in ordered
    ]


async def coverage_matrix(
    uow: UnitOfWork,
    actor: Principal,
    *,
    extra_products: Iterable[str],
    stale_months: int,
    today: date | None = None,
) -> KnowledgeCoverage:
    """Every product (the Sources', the Checklists' and `extra_products`, e.g. the
    Opportunities' the caller can read), sorted ignoring case, by every active Integration
    Type, and the industry-only Checklists. Any user with a role."""
    if not actor.roles:
        raise ForbiddenError("You are not allowed to perform this action.")
    entries = await list_catalogue(uow, Kind.INTEGRATION_TYPE)
    sources, scopes = await _load(uow)
    names = _distinct(
        [
            *(s.product for s in sources),
            *(p for scope in scopes for p in scope.products),
            *extra_products,
        ]
    )
    columns = [UUID(e.id) for e in entries]
    tallies = _tally(
        set(names),
        set(columns),
        sources,
        scopes,
        today=today or today_utc(),
        stale_months=stale_months,
    )
    ordered = sorted(names.items(), key=lambda item: (item[0], item[1]))
    return KnowledgeCoverage(
        integration_types=[
            CoverageIntegrationType(id=e.id, code=e.code, name=e.name) for e in entries
        ],
        rows=[
            CoverageRow(
                product=name,
                cells=[
                    CoverageCell.model_validate(
                        {"integration_type_id": str(t), **_counts(tallies, key, t)}
                    )
                    for t in columns
                ],
            )
            for key, name in ordered
        ],
        industries=_industries(scopes),
        stale_months=stale_months,
    )
