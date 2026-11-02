"""gaps' retention purge step (Story 10.6): deletes one Opportunity's answer matches, Gaps
(with their Clarification Questions, Requirement links and history) and detection runs,
children first so every row is counted. Run only by the `platform.purge` job, inside the
purge role's transaction for that Opportunity."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.purge.registry import StepResult, delete_rows

TABLES = (
    "gaps_answer_matches",
    "gaps_clarification_questions",
    "gaps_gap_requirements",
    "gaps_gap_history",
    "gaps_gaps",
    "gaps_detections",
)
"""Every table this step empties."""
STATEMENTS = (
    "DELETE FROM gaps_answer_matches WHERE opportunity_id = :opportunity_id OR question_id IN "
    "(SELECT id FROM gaps_clarification_questions WHERE gap_id IN (SELECT id FROM gaps_gaps "
    "WHERE opportunity_id = :opportunity_id))",
    "DELETE FROM gaps_clarification_questions WHERE gap_id IN (SELECT id FROM gaps_gaps WHERE "
    "opportunity_id = :opportunity_id)",
    "DELETE FROM gaps_gap_requirements WHERE gap_id IN (SELECT id FROM gaps_gaps WHERE "
    "opportunity_id = :opportunity_id)",
    "DELETE FROM gaps_gap_history WHERE gap_id IN (SELECT id FROM gaps_gaps WHERE "
    "opportunity_id = :opportunity_id)",
    "DELETE FROM gaps_gaps WHERE opportunity_id = :opportunity_id",
    "DELETE FROM gaps_detections WHERE opportunity_id = :opportunity_id",
)


async def purge_opportunity(session: AsyncSession, opportunity_id: UUID) -> StepResult:
    return StepResult(rows=await delete_rows(session, STATEMENTS, opportunity_id))
