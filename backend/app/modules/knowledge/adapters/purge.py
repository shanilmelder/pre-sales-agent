"""knowledge's retention purge step (Story 10.6): deletes one Opportunity's research snapshots
(each held two file references: the fetched page and its extracted text). Shared knowledge
(Sources, chunks, the catalogue, Checklists) is never touched. Run only by the
`platform.purge` job, inside the purge role's transaction for that Opportunity."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.purge.registry import StepResult

TABLES = ("knowledge_research_snapshots",)
"""Every table this step empties."""
SNAPSHOTS = (
    "DELETE FROM knowledge_research_snapshots WHERE opportunity_id = :opportunity_id RETURNING "
    "content_sha256, text_sha256"
)


async def purge_opportunity(session: AsyncSession, opportunity_id: UUID) -> StepResult:
    rows = (await session.execute(text(SNAPSHOTS), {"opportunity_id": opportunity_id})).all()
    released = [sha256 for row in rows for sha256 in row if sha256 is not None]
    return StepResult(rows=len(rows), released_sha256=released)
