"""estimates' retention purge step (Story 10.6): deletes one Opportunity's Baselines first
(they reference Estimate Versions), then its Estimate Versions with their lines, Assumptions
and Risks, and its draft jobs. Run only by the `platform.purge` job, inside the purge role's
transaction for that Opportunity."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.purge.registry import StepResult, delete_rows

TABLES = (
    "estimates_baselines",
    "estimates_line_requirements",
    "estimates_assumptions",
    "estimates_risks",
    "estimates_estimate_lines",
    "estimates_estimate_versions",
    "estimates_drafts",
)
"""Every table this step empties."""
STATEMENTS = (
    "DELETE FROM estimates_baselines WHERE opportunity_id = :opportunity_id",
    "DELETE FROM estimates_line_requirements WHERE line_id IN (SELECT id FROM "
    "estimates_estimate_lines WHERE version_id IN (SELECT id FROM estimates_estimate_versions "
    "WHERE opportunity_id = :opportunity_id))",
    "DELETE FROM estimates_assumptions WHERE version_id IN (SELECT id FROM "
    "estimates_estimate_versions WHERE opportunity_id = :opportunity_id)",
    "DELETE FROM estimates_risks WHERE version_id IN (SELECT id FROM "
    "estimates_estimate_versions WHERE opportunity_id = :opportunity_id)",
    "DELETE FROM estimates_estimate_lines WHERE version_id IN (SELECT id FROM "
    "estimates_estimate_versions WHERE opportunity_id = :opportunity_id)",
    "DELETE FROM estimates_estimate_versions WHERE opportunity_id = :opportunity_id",
    "DELETE FROM estimates_drafts WHERE opportunity_id = :opportunity_id",
)


async def purge_opportunity(session: AsyncSession, opportunity_id: UUID) -> StepResult:
    return StepResult(rows=await delete_rows(session, STATEMENTS, opportunity_id))
