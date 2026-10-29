"""notifications' retention purge step (Story 10.6): deletes one Opportunity's Inbox items. Run
only by the `platform.purge` job, inside the purge role's transaction for that Opportunity."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.purge.registry import StepResult, delete_rows

TABLES = ("notifications_notifications",)
"""Every table this step empties."""
STATEMENTS = ("DELETE FROM notifications_notifications WHERE opportunity_id = :opportunity_id",)


async def purge_opportunity(session: AsyncSession, opportunity_id: UUID) -> StepResult:
    return StepResult(rows=await delete_rows(session, STATEMENTS, opportunity_id))
