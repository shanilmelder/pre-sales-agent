"""Admin > Retention (Story 10.6) under `/api/v1/admin/retention`: read only. Platform
administrators (`platform.retention.read`) only; anyone else gets 403. There is deliberately
no endpoint that deletes: only the daily `platform.purge` job does."""

from fastapi import APIRouter

from app.modules.identity.application.public import CurrentPrincipal
from app.modules.opportunities.application import public as opportunities
from app.modules.opportunities.application.public import RetentionOverview
from app.platform.errors import PROBLEM_JSON, Problem
from app.platform.uow import UoW

PROBLEM_CONTENT = {PROBLEM_JSON: {"schema": Problem.model_json_schema()}}

router = APIRouter(prefix="/admin/retention", tags=["admin"])


@router.get(
    "",
    operation_id="get_retention_overview",
    responses={
        401: {
            "description": "No valid access token (`token_missing`, `token_expired`, "
            "`token_invalid`)",
            "content": PROBLEM_CONTENT,
        },
        403: {
            "description": "The caller lacks `platform.retention.read` (`forbidden`)",
            "content": PROBLEM_CONTENT,
        },
        503: {
            "description": "Sign-in service unavailable (`auth_unavailable`)",
            "content": PROBLEM_CONTENT,
        },
    },
)
async def get_retention_overview(actor: CurrentPrincipal, uow: UoW) -> RetentionOverview:
    """The Opportunities whose retention date is within the next 30 days (overdue ones not
    yet purged included), earliest first, and the last 20 purges, newest first. Ids,
    outcomes, dates and counts only."""
    return await opportunities.retention_overview(uow, actor)
