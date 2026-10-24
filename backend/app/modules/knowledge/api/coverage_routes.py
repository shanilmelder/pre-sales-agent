"""Knowledge coverage route (Story 3.5): `GET /api/v1/knowledge/coverage`. Any user with a
role.

The rows include the products of the Opportunities the caller can read, read here through
`opportunities`' public `facets` (admins and Head of Delivery see every Opportunity), so the
knowledge application itself never imports `opportunities`."""

from typing import Any

from fastapi import APIRouter, Request

from app.modules.identity.application.public import CurrentPrincipal
from app.modules.knowledge.application import public as knowledge
from app.modules.knowledge.application.public import KnowledgeCoverage
from app.modules.opportunities.application import public as opportunities
from app.platform.config import Settings
from app.platform.errors import PROBLEM_JSON, Problem
from app.platform.uow import UoW

PROBLEM_CONTENT = {PROBLEM_JSON: {"schema": Problem.model_json_schema()}}
_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"description": description, "content": PROBLEM_CONTENT}
    for code, description in (
        (401, "No valid access token (`token_missing`, `token_expired`, `token_invalid`)"),
        (403, "The caller has no role (`forbidden`)"),
        (503, "Sign-in service unavailable (`auth_unavailable`)"),
    )
}

router = APIRouter(prefix="/knowledge/coverage", tags=["knowledge"])


@router.get("", operation_id="get_knowledge_coverage", responses=_RESPONSES)
async def get_knowledge_coverage(
    request: Request, actor: CurrentPrincipal, uow: UoW
) -> KnowledgeCoverage:
    """Products (from Sources, Checklists and the Opportunities the caller can read, sorted
    ignoring case) by active Integration Types: per cell the Ready Sources, how many of them
    are stale, the published Checklists and the status (`ready`, `partial`, `missing`).
    Checklists scoped only by industry are listed under `industries`. Any user with a role."""
    settings: Settings = request.app.state.settings
    # A caller with no role reads no Opportunity, and `coverage_matrix` then answers 403.
    facets = await opportunities.facets(uow, actor)
    return await knowledge.coverage_matrix(
        uow,
        actor,
        extra_products=facets.products,
        stale_months=settings.knowledge_stale_months,
    )
