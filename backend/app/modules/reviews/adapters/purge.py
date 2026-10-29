"""reviews' retention purge step (Story 10.6): deletes one Opportunity's Review Requests with
their decisions and replies, and its Challenges, children first so every row is counted. Run
only by the `platform.purge` job, inside the purge role's transaction for that Opportunity."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.purge.registry import StepResult, delete_rows

TABLES = (
    "reviews_review_decisions",
    "reviews_review_replies",
    "reviews_challenges",
    "reviews_review_requests",
)
"""Every table this step empties."""
STATEMENTS = (
    "DELETE FROM reviews_review_decisions WHERE review_request_id IN (SELECT id FROM "
    "reviews_review_requests WHERE opportunity_id = :opportunity_id)",
    "DELETE FROM reviews_review_replies WHERE review_request_id IN (SELECT id FROM "
    "reviews_review_requests WHERE opportunity_id = :opportunity_id)",
    "DELETE FROM reviews_challenges WHERE opportunity_id = :opportunity_id OR review_request_id"
    " IN (SELECT id FROM reviews_review_requests WHERE opportunity_id = :opportunity_id)",
    "DELETE FROM reviews_review_requests WHERE opportunity_id = :opportunity_id",
)


async def purge_opportunity(session: AsyncSession, opportunity_id: UUID) -> StepResult:
    return StepResult(rows=await delete_rows(session, STATEMENTS, opportunity_id))
