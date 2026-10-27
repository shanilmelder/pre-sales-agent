"""The Knowledge Graph (Story 3.6): a read model derived on every read from the Knowledge
tables and Story 3.5's coverage counts. Nothing is stored; there is no graph store.

Nodes:

- **Products**: the union, matched with `match_key`, of the Sources' products, the active
  published Checklists' products and `extra_products` (the Opportunities' the caller can
  read), spelled as first seen.
- **Integration Types**: the active ones, in catalogue order.
- **Knowledge Sources**: every non-retired Source, whatever its pipeline state.
- **Checklists**: the active Checklists that have a published version (their published scope).

Edges: a Source to its product and to each of its active Integration Type tags; a Checklist to
each scoped product and each scoped active Integration Type (none when scoped only by
industry); a product to an Integration Type when the pair is Ready (`linked`) or Partial
(`gap`, missing coverage). An uncovered pair has no edge.

Status and score (`domain.graph`) come from the pairs' coverage counts (`tally_pairs`):
a Product's and an Integration Type's pairs are its covered pairs; a Checklist's the pairs its
scope covers; a Source's its product with each of its active tags.

Only admins and the roles that edit Checklists (`knowledge.checklist.edit`) may read it.
"""

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from uuid import UUID

from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal, Resource
from app.modules.knowledge.adapters import checklist_repository
from app.modules.knowledge.adapters import source_repository as repo
from app.modules.knowledge.application.catalogue import list_catalogue
from app.modules.knowledge.application.coverage import (
    Tallies,
    Tally,
    distinct_products,
    load_coverage,
    scope_pairs,
    tally_pairs,
)
from app.modules.knowledge.application.graph_models import (
    GraphEdge,
    GraphEdgeKind,
    GraphNode,
    GraphNodeType,
    KnowledgeGraph,
)
from app.modules.knowledge.application.source_models import KnowledgeUserRef
from app.modules.knowledge.application.sources import _views as source_views
from app.modules.knowledge.application.sources import today_utc
from app.modules.knowledge.domain.catalogue import Kind
from app.modules.knowledge.domain.checklists import match_key
from app.modules.knowledge.domain.coverage import CoverageStatus, coverage_status
from app.modules.knowledge.domain.graph import (
    NodeStatus,
    aggregate_status,
    node_score,
    pair_score,
    source_node_status,
    source_score,
    stale_in_days,
)
from app.platform.uow import UnitOfWork

UNKNOWN_USER = "Unknown user"

type Pair = tuple[str, UUID]


def product_node_id(key: str) -> str:
    return f"{GraphNodeType.PRODUCT.value}:{key}"


def type_node_id(type_id: UUID | str) -> str:
    return f"{GraphNodeType.INTEGRATION_TYPE.value}:{type_id}"


def source_node_id(source_id: UUID | str) -> str:
    return f"{GraphNodeType.SOURCE.value}:{source_id}"


def checklist_node_id(checklist_id: UUID | str) -> str:
    return f"{GraphNodeType.CHECKLIST.value}:{checklist_id}"


def _status(tallies: Tallies, pair: Pair) -> CoverageStatus:
    tally = tallies.get(pair, Tally())
    return coverage_status(tally.sources, tally.stale, tally.checklists)


def _score(tallies: Tallies, pair: Pair) -> int:
    tally = tallies.get(pair, Tally())
    return pair_score(tally.sources, tally.stale, tally.checklists)


def _aggregate(tallies: Tallies, pairs: Iterable[Pair]) -> tuple[NodeStatus, int]:
    """The status and score of a node with these pairs."""
    pairs = list(pairs)
    status = aggregate_status(_status(tallies, p) for p in pairs)
    return status, node_score([_score(tallies, p) for p in pairs])


async def get_graph(
    uow: UnitOfWork,
    actor: Principal,
    *,
    extra_products: Iterable[str],
    stale_months: int,
    today: date | None = None,
) -> KnowledgeGraph:
    """The Knowledge Graph's nodes and edges (see the module docstring). Platform
    administrators and the roles that may edit Checklists; anyone else is refused (403)."""
    identity.authorize(actor, Action.KNOWLEDGE_CHECKLIST_EDIT)
    now = today or today_utc()

    entries = await list_catalogue(uow, Kind.INTEGRATION_TYPE)
    active_types = [UUID(e.id) for e in entries]
    active = set(active_types)
    ready, scopes = await load_coverage(uow)
    records = await repo.list_sources(
        uow,
        product=None,
        integration_type_id=None,
        owner_id=None,
        stale_before=None,
        stale=None,
        include_retired=False,
    )
    sources = await source_views(uow, records, stale_months=stale_months, today=now)
    sources.sort(key=lambda s: (s.title.casefold(), s.id))

    names = distinct_products(
        [
            *(s.product for s in sources),
            *(p for scope in scopes for p in scope.products),
            *extra_products,
        ]
    )
    keys = set(names)
    tallies = tally_pairs(keys, active, ready, scopes, today=now, stale_months=stale_months)

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    # Products and Integration Types, from their covered pairs.
    by_product: dict[str, list[Pair]] = defaultdict(list)
    by_type: dict[UUID, list[Pair]] = defaultdict(list)
    for pair in tallies:
        by_product[pair[0]].append(pair)
        by_type[pair[1]].append(pair)
    for key, name in sorted(names.items()):
        status, score = _aggregate(tallies, by_product[key])
        nodes.append(_plain(product_node_id(key), GraphNodeType.PRODUCT, name, status, score))
    for entry in entries:
        type_id = UUID(entry.id)
        status, score = _aggregate(tallies, by_type[type_id])
        nodes.append(
            _plain(type_node_id(type_id), GraphNodeType.INTEGRATION_TYPE, entry.name, status, score)
        )
    for key, type_id in sorted(tallies, key=lambda p: (p[0], active_types.index(p[1]))):
        pair_status = _status(tallies, (key, type_id))
        if pair_status == CoverageStatus.MISSING:  # pragma: no cover - tallies are covered
            continue
        kind = GraphEdgeKind.LINKED if pair_status == CoverageStatus.READY else GraphEdgeKind.GAP
        edges.append(
            GraphEdge(source=product_node_id(key), target=type_node_id(type_id), kind=kind)
        )

    # Knowledge Sources.
    for source in sources:
        key = match_key(source.product)
        tags = [UUID(t.id) for t in source.integration_types if UUID(t.id) in active]
        node_status = source_node_status(
            source.parse.status,
            None if source.embed is None else source.embed.status,
            stale=source.stale,
        )
        pairs = [(key, t) for t in tags]
        nodes.append(
            GraphNode(
                id=source_node_id(source.id),
                type=GraphNodeType.SOURCE,
                label=source.title,
                status=node_status,
                score=source_score(node_status, [_score(tallies, p) for p in pairs]),
                owner=source.owner,
                last_reviewed_on=source.last_reviewed_on,
                row_version=source.row_version,
                can_review=identity.can(
                    actor,
                    Action.KNOWLEDGE_SOURCE_REVIEW,
                    Resource(
                        type=identity.KNOWLEDGE_SOURCE_RESOURCE,
                        id=UUID(source.id),
                        owner_id=UUID(source.owner.id),
                    ),
                ),
                stale_in_days=stale_in_days(source.last_reviewed_on, now, stale_months),
            )
        )
        edges.append(
            GraphEdge(
                source=source_node_id(source.id),
                target=product_node_id(key),
                kind=GraphEdgeKind.LINKED,
            )
        )
        edges.extend(
            GraphEdge(
                source=source_node_id(source.id), target=type_node_id(t), kind=GraphEdgeKind.LINKED
            )
            for t in tags
        )

    # Checklists.
    creators = await identity.user_names(uow, {s.created_by for s in scopes})
    published = await checklist_repository.last_published_at(uow, [s.id for s in scopes])
    for scope in scopes:
        status, score = _aggregate(tallies, scope_pairs(scope, keys, active))
        published_at = published.get(scope.id)
        nodes.append(
            GraphNode(
                id=checklist_node_id(scope.id),
                type=GraphNodeType.CHECKLIST,
                label=scope.name,
                status=status,
                score=score,
                owner=KnowledgeUserRef(
                    id=str(scope.created_by), name=creators.get(scope.created_by, UNKNOWN_USER)
                ),
                last_reviewed_on=None if published_at is None else published_at.date(),
            )
        )
        scoped_keys = sorted({match_key(p) for p in scope.products} & keys)
        edges.extend(
            GraphEdge(
                source=checklist_node_id(scope.id),
                target=product_node_id(k),
                kind=GraphEdgeKind.LINKED,
            )
            for k in scoped_keys
        )
        edges.extend(
            GraphEdge(
                source=checklist_node_id(scope.id),
                target=type_node_id(t),
                kind=GraphEdgeKind.LINKED,
            )
            for t in scope.integration_type_ids
            if t in active
        )

    return KnowledgeGraph(nodes=nodes, edges=edges, stale_months=stale_months)


def _plain(
    node_id: str, node_type: GraphNodeType, label: str, status: NodeStatus, score: int
) -> GraphNode:
    """A Product or Integration Type node: no owner, no review."""
    return GraphNode(
        id=node_id,
        type=node_type,
        label=label,
        status=status,
        score=score,
        owner=None,
        last_reviewed_on=None,
    )
