"""actuals' retention purge step (Story 10.6): deletes one Opportunity's Actuals, its closed
delivery and its imports (each import held one reference to its uploaded file). Run only by
the `platform.purge` job, inside the purge role's transaction for that Opportunity."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.purge.registry import StepResult, delete_returning, delete_rows

TABLES = ("actuals_actuals", "actuals_deliveries", "actuals_imports")
"""Every table this step empties."""
STATEMENTS = (
    "DELETE FROM actuals_actuals WHERE opportunity_id = :opportunity_id",
    "DELETE FROM actuals_deliveries WHERE opportunity_id = :opportunity_id",
)
IMPORTS = "DELETE FROM actuals_imports WHERE opportunity_id = :opportunity_id RETURNING file_sha256"


async def purge_opportunity(session: AsyncSession, opportunity_id: UUID) -> StepResult:
    rows = await delete_rows(session, STATEMENTS, opportunity_id)
    imports, released = await delete_returning(session, IMPORTS, opportunity_id)
    return StepResult(rows=rows + imports, released_sha256=released)
