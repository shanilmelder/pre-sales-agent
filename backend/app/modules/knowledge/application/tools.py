"""knowledge's ToolGateway handlers (Story 5.4), registered at import.

- `knowledge.chunk.search`: `{"query", "k"?, "product"?, "product_version"?}`, the nearest
  citable chunks (`KnowledgeSearchHit`s), embedded through the process's ModelGateway with
  the active embedding profile (`search_chunks`, no human authorization: the gateway checked
  the Agent's permission). Its embedding call is made before the Unit of Work's first
  statement only when the gateway opened that Unit of Work.
- `knowledge.chunk.read`: `{"chunk_ids": [...]}`, those chunks with their text
  (`ChunkText`s). An unknown id denies the whole call (`out_of_scope`).
- `knowledge.catalogue_entry.list`: `{"kind"?}`, the active catalogue entries.
- `knowledge.research_page.fetch`: the research sink `capture_research_snapshot`.

Knowledge is shared across Opportunities, so these handlers read no Opportunity data; the
Research Snapshot is stored for the context's Opportunity.
"""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.modules.knowledge.adapters import chunk_repository as chunks
from app.modules.knowledge.application.catalogue import list_catalogue
from app.modules.knowledge.application.research import capture_research_snapshot
from app.modules.knowledge.application.search import search_chunks
from app.modules.knowledge.domain import embedding as rules
from app.modules.knowledge.domain.catalogue import Kind
from app.platform import tool_gateway
from app.platform.config import get_settings
from app.platform.model_gateway import provider
from app.platform.tool_gateway import ToolContext, ToolDenied, ToolResult
from app.platform.tool_gateway.catalogue import CATALOGUE_ENTRY_LIST, CHUNK_READ, CHUNK_SEARCH
from app.platform.uow import UnitOfWork

CHUNK_READ_MAX = 50


def _text(args: Mapping[str, Any], key: str) -> str | None:
    value = args.get(key)
    return value if isinstance(value, str) else None


async def search(
    uow: UnitOfWork, ctx: ToolContext, args: Mapping[str, Any]
) -> ToolResult | ToolDenied:
    settings = get_settings()
    k = args.get("k", rules.SEARCH_K_DEFAULT)
    result = await search_chunks(
        uow,
        _text(args, "query") or "",
        actor_id=ctx.actor_id,
        gateway=provider.current(),
        embed_profile=settings.model_profile_embed,
        stale_months=settings.knowledge_stale_months,
        k=k if isinstance(k, int) else rules.SEARCH_K_DEFAULT,
        product=_text(args, "product"),
        product_version=_text(args, "product_version"),
        priority="background",
    )
    return ToolResult(items=tuple(result.items))


async def read_chunks(
    uow: UnitOfWork, ctx: ToolContext, args: Mapping[str, Any]
) -> ToolResult | ToolDenied:
    raw = args.get("chunk_ids")
    if not isinstance(raw, list | tuple) or not 1 <= len(raw) <= CHUNK_READ_MAX:
        return ToolDenied("out_of_scope")
    try:
        ids = [value if isinstance(value, UUID) else UUID(str(value)) for value in raw]
    except ValueError:
        return ToolDenied("out_of_scope")
    found = await chunks.chunk_texts(uow, ids)
    if any(chunk_id not in found for chunk_id in ids):
        return ToolDenied("out_of_scope")
    return ToolResult(items=tuple(found[chunk_id] for chunk_id in dict.fromkeys(ids)))


async def list_entries(
    uow: UnitOfWork, ctx: ToolContext, args: Mapping[str, Any]
) -> ToolResult | ToolDenied:
    raw = _text(args, "kind")
    try:
        kind = None if raw is None else Kind(raw)
    except ValueError:
        return ToolDenied("out_of_scope")
    return ToolResult(items=tuple(await list_catalogue(uow, kind)))


tool_gateway.register_tool(CHUNK_SEARCH, search)
tool_gateway.register_tool(CHUNK_READ, read_chunks)
tool_gateway.register_tool(CATALOGUE_ENTRY_LIST, list_entries)
tool_gateway.register_research_sink(capture_research_snapshot)
