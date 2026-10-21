"""Knowledge search (Story 3.3, FR-8): the top-k citable chunks for a query.

`search` authorizes the read (`knowledge.chunk.search`, every user with a role), embeds the
query through the ModelGateway it is given with the active embedding profile, then asks the
chunk repository for the nearest chunks of Ready, active, latest Source versions embedded
with that same profile, optionally filtered by product, Integration Type and product version.
The gateway call happens before any database statement, so no transaction is open across it
(AD-25). Each hit carries a citable Evidence reference
`{kind: knowledge_chunk, id, version, span}` and the Source's derived `stale` flag.

The query text is never logged, traced or stored (only its length, `k` and which filters were
set); the gateway's call row holds counts only.
"""

from datetime import UTC, date, datetime
from uuid import UUID

from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.knowledge.adapters import chunk_repository as chunks
from app.modules.knowledge.application.source_models import (
    KnowledgeEvidence,
    KnowledgeSearchHit,
    KnowledgeSearchResult,
    KnowledgeSpan,
)
from app.modules.knowledge.domain import embedding as rules
from app.modules.knowledge.domain.sources import is_stale
from app.platform.errors import ModelUnavailableProblem, UnprocessableError
from app.platform.jobs.registry import Priority
from app.platform.logging import get_logger
from app.platform.model_gateway.port import (
    CallerMetadata,
    EmbedRequest,
    ModelGatewayError,
    ModelGatewayPort,
)
from app.platform.model_gateway.profiles import get_embed_profile
from app.platform.uow import UnitOfWork

SEARCH_AGENT_ID = "knowledge.search"
"""The `agent_id` recorded on a query's `platform_model_calls` row."""
UNAVAILABLE_DETAIL = "Search is unavailable right now: the embedding model could not be reached."
_log = get_logger(__name__)


async def search(
    uow: UnitOfWork,
    actor: Principal,
    query: str,
    *,
    gateway: ModelGatewayPort,
    embed_profile: str,
    stale_months: int,
    k: int = rules.SEARCH_K_DEFAULT,
    product: str | None = None,
    integration_type_id: UUID | None = None,
    product_version: str | None = None,
    priority: Priority = "interactive",
    today: date | None = None,
) -> KnowledgeSearchResult:
    """The `k` chunks nearest to `query`, nearest first (module docstring). 403 without a
    role; 422 for a blank or too-long query or `k` outside 1..`SEARCH_K_MAX`; 503 when the
    embedding model fails."""
    identity.authorize(actor, Action.KNOWLEDGE_CHUNK_SEARCH)
    try:
        text = rules.search_query(query)
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from None
    if not 1 <= k <= rules.SEARCH_K_MAX:
        raise UnprocessableError(f"k must be between 1 and {rules.SEARCH_K_MAX}.")
    # A blank filter is no filter.
    product = (product or "").strip() or None
    product_version = (product_version or "").strip() or None
    profile = get_embed_profile(embed_profile)
    try:
        (vector,) = await gateway.embed(
            EmbedRequest(
                texts=[text],
                caller=CallerMetadata(agent_id=SEARCH_AGENT_ID, config_version=profile.name),
                profile=profile.name,
                priority=priority,
            )
        )
    except ModelGatewayError:
        raise ModelUnavailableProblem(UNAVAILABLE_DETAIL) from None
    hits = await chunks.search(
        uow,
        vector,
        model=profile.name,
        dims=profile.dims,
        k=k,
        product=product,
        integration_type_id=integration_type_id,
        product_version=product_version,
    )
    now = today or datetime.now(UTC).date()
    _log.info(
        "knowledge.searched",
        extra={
            "actor_id": actor.actor.id,
            "query_chars": len(text),
            "k": k,
            "results": len(hits),
            "product_filter": product is not None,
            "integration_type_filter": integration_type_id is not None,
            "product_version_filter": product_version is not None,
            "model": profile.name,
        },
    )
    return KnowledgeSearchResult(
        items=[
            KnowledgeSearchHit(
                text=h.text,
                source_id=str(h.source_id),
                source_title=h.title,
                version=h.version,
                product=h.product,
                product_version=h.product_version,
                stale=is_stale(h.last_reviewed_on, now, stale_months),
                distance=h.distance,
                evidence=KnowledgeEvidence(
                    kind=rules.EVIDENCE_KIND,
                    id=str(h.id),
                    version=h.version,
                    span=KnowledgeSpan(start=h.start, end=h.end),
                ),
            )
            for h in hits
        ],
        model=profile.name,
        stale_months=stale_months,
    )
