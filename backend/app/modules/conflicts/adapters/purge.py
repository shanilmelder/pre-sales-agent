"""conflicts' retention purge step (Story 10.6): deletes one Opportunity's Conflicts (with
their positions) and detection passes. One statement deletes every Conflict, so a
`previous_conflict_id` is checked at its end. Run only by the `platform.purge` job, inside
the purge role's transaction for that Opportunity."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.purge.registry import StepResult, delete_rows

TABLES = ("conflicts_positions", "conflicts_conflicts", "conflicts_detections")
"""Every table this step empties."""
STATEMENTS = (
    "DELETE FROM conflicts_positions WHERE conflict_id IN (SELECT id FROM conflicts_conflicts "
    "WHERE opportunity_id = :opportunity_id)",
    "DELETE FROM conflicts_conflicts WHERE opportunity_id = :opportunity_id",
    "DELETE FROM conflicts_detections WHERE opportunity_id = :opportunity_id",
)


async def purge_opportunity(session: AsyncSession, opportunity_id: UUID) -> StepResult:
    return StepResult(rows=await delete_rows(session, STATEMENTS, opportunity_id))
