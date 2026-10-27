"""Knowledge Graph route (Story 3.6): `GET /api/v1/knowledge/graph`. Platform administrators
and the roles that may edit Checklists.

The product nodes include the products of the Opportunities the caller can read, read here
through `opportunities`' public `facets`, so the knowledge application itself never imports
`opportunities`."""

from typing import Any

from fastapi import APIRouter, Request

from app.modules.identity.application.public import CurrentPrincipal
from app.modules.knowledge.application import public as knowledge
from app.modules.knowledge.application.public import KnowledgeGraph
from app.modules.opportunities.application import public as opportunities
from app.platform.config import Settings
from app.platform.errors import PROBLEM_JSON, Problem
from app.platform.uow import UoW

PROBLEM_CONTENT = {PROBLEM_JSON: {"schema": Problem.model_json_schema()}}
_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"description": description, "content": PROBLEM_CONTENT}
    for code, description in (
        (401, "No valid access token (`token_missing`, `token_expired`, `token_invalid`)"),
        (403, "The caller may not edit Checklists (`forbidden`)"),
        (503, "Sign-in service unavailable (`auth_unavailable`)"),
    )
}

router = APIRouter(prefix="/knowledge/graph", tags=["knowledge"])


@router.get("", operation_id="get_knowledge_graph", responses=_RESPONSES)
async def get_knowledge_graph(
    request: Request, actor: CurrentPrincipal, uow: UoW
) -> KnowledgeGraph:
    """Products (from Sources, Checklists and the Opportunities the caller can read), active
    Integration Types, non-retired Knowledge Sources and active published Checklists, each
    with a status and a Coverage score (0 to 100), and the links between them: tags and
    scopes (`linked`), and product to Integration Type pairs that are Ready (`linked`) or
    Partial (`gap`). Platform administrators and the roles that may edit Checklists."""
    settings: Settings = request.app.state.settings
    facets = await opportunities.facets(uow, actor)
    return await knowledge.get_graph(
        uow,
        actor,
        extra_products=facets.products,
        stale_months=settings.knowledge_stale_months,
    )
