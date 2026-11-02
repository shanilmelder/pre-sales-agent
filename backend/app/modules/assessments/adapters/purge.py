"""assessments' retention purge step (Story 10.6): deletes one Opportunity's Assessments
(effort, findings), Red Team and Critic reviews (Findings with their links, overrides and
Evidence) and Red Team runs, children first so every row is counted. Run only by the
`platform.purge` job, inside the purge role's transaction for that Opportunity."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.purge.registry import StepResult, delete_rows

TABLES = (
    "assessments_finding_requirements",
    "assessments_finding_lines",
    "assessments_finding_targets",
    "assessments_finding_overrides",
    "assessments_finding_evidence",
    "assessments_findings",
    "assessments_reviews",
    "assessments_assessment_finding_requirements",
    "assessments_assessment_findings",
    "assessments_effort",
    "assessments_assessments",
    "assessments_red_team_runs",
)
"""Every table this step empties."""
STATEMENTS = (
    "DELETE FROM assessments_finding_requirements WHERE finding_id IN (SELECT f.id FROM "
    "assessments_findings f JOIN assessments_reviews r ON r.id = f.review_id WHERE "
    "r.opportunity_id = :opportunity_id)",
    "DELETE FROM assessments_finding_lines WHERE finding_id IN (SELECT f.id FROM "
    "assessments_findings f JOIN assessments_reviews r ON r.id = f.review_id WHERE "
    "r.opportunity_id = :opportunity_id)",
    "DELETE FROM assessments_finding_targets WHERE finding_id IN (SELECT f.id FROM "
    "assessments_findings f JOIN assessments_reviews r ON r.id = f.review_id WHERE "
    "r.opportunity_id = :opportunity_id)",
    "DELETE FROM assessments_finding_overrides WHERE finding_id IN (SELECT f.id FROM "
    "assessments_findings f JOIN assessments_reviews r ON r.id = f.review_id WHERE "
    "r.opportunity_id = :opportunity_id)",
    "DELETE FROM assessments_finding_evidence WHERE finding_id IN (SELECT f.id FROM "
    "assessments_findings f JOIN assessments_reviews r ON r.id = f.review_id WHERE "
    "r.opportunity_id = :opportunity_id)",
    "DELETE FROM assessments_findings WHERE id IN (SELECT f.id FROM assessments_findings f JOIN"
    " assessments_reviews r ON r.id = f.review_id WHERE r.opportunity_id = :opportunity_id)",
    "DELETE FROM assessments_reviews WHERE opportunity_id = :opportunity_id",
    "DELETE FROM assessments_assessment_finding_requirements WHERE finding_id IN (SELECT f.id "
    "FROM assessments_assessment_findings f JOIN assessments_assessments a ON a.id = "
    "f.assessment_id WHERE a.opportunity_id = :opportunity_id)",
    "DELETE FROM assessments_assessment_findings WHERE assessment_id IN (SELECT id FROM "
    "assessments_assessments WHERE opportunity_id = :opportunity_id)",
    "DELETE FROM assessments_effort WHERE assessment_id IN (SELECT id FROM "
    "assessments_assessments WHERE opportunity_id = :opportunity_id)",
    "DELETE FROM assessments_assessments WHERE opportunity_id = :opportunity_id",
    "DELETE FROM assessments_red_team_runs WHERE opportunity_id = :opportunity_id",
)


async def purge_opportunity(session: AsyncSession, opportunity_id: UUID) -> StepResult:
    return StepResult(rows=await delete_rows(session, STATEMENTS, opportunity_id))
