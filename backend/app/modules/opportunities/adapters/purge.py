"""opportunities' retention purge step (Story 10.6): deletes the Opportunity row and its
collaborators, last of all (other modules' rows reference it by foreign key). Run only by
the `platform.purge` job, inside the purge role's transaction for that Opportunity."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.purge.registry import StepResult, delete_rows

TABLES = ("opportunities_collaborators", "opportunities_opportunities")
"""Every table this step empties."""
STATEMENTS = (
    "DELETE FROM opportunities_collaborators WHERE opportunity_id = :opportunity_id",
    "DELETE FROM opportunities_opportunities WHERE id = :opportunity_id",
)


async def purge_opportunity(session: AsyncSession, opportunity_id: UUID) -> StepResult:
    return StepResult(rows=await delete_rows(session, STATEMENTS, opportunity_id))
