"""intake's retention purge step (Story 10.6): deletes one Opportunity's Requirements
(versions, Evidence, tags, proposed changes), extractions and Sources (versions, parses,
passages), children first so every row is counted. Each Source version held one reference to
its file and each finished parse one to its text. Run only by the `platform.purge` job,
inside the purge role's transaction for that Opportunity."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.purge.registry import StepResult, delete_returning, delete_rows

TABLES = (
    "intake_requirement_evidence",
    "intake_requirement_integration_types",
    "intake_requirement_versions",
    "intake_requirement_changes",
    "intake_requirements",
    "intake_extractions",
    "intake_source_passages",
    "intake_source_parses",
    "intake_source_versions",
    "intake_sources",
)
"""Every table this step empties."""
STATEMENTS = (
    "DELETE FROM intake_requirement_evidence WHERE requirement_id IN (SELECT id FROM "
    "intake_requirements WHERE opportunity_id = :opportunity_id) OR passage_id IN (SELECT id "
    "FROM intake_source_passages WHERE source_id IN (SELECT id FROM intake_sources WHERE "
    "opportunity_id = :opportunity_id))",
    "DELETE FROM intake_requirement_integration_types WHERE requirement_id IN (SELECT id FROM "
    "intake_requirements WHERE opportunity_id = :opportunity_id)",
    "DELETE FROM intake_requirement_versions WHERE requirement_id IN (SELECT id FROM "
    "intake_requirements WHERE opportunity_id = :opportunity_id)",
    "DELETE FROM intake_requirement_changes WHERE requirement_id IN (SELECT id FROM "
    "intake_requirements WHERE opportunity_id = :opportunity_id) OR extraction_id IN (SELECT id"
    " FROM intake_extractions WHERE opportunity_id = :opportunity_id)",
    "DELETE FROM intake_requirements WHERE opportunity_id = :opportunity_id",
    "DELETE FROM intake_extractions WHERE opportunity_id = :opportunity_id",
    "DELETE FROM intake_source_passages WHERE source_id IN (SELECT id FROM intake_sources WHERE"
    " opportunity_id = :opportunity_id)",
)
PARSES = (
    "DELETE FROM intake_source_parses WHERE source_id IN (SELECT id FROM intake_sources WHERE "
    "opportunity_id = :opportunity_id) RETURNING text_sha256"
)
VERSIONS = (
    "DELETE FROM intake_source_versions WHERE source_id IN (SELECT id FROM intake_sources WHERE"
    " opportunity_id = :opportunity_id) RETURNING file_sha256"
)
SOURCES = "DELETE FROM intake_sources WHERE opportunity_id = :opportunity_id"


async def purge_opportunity(session: AsyncSession, opportunity_id: UUID) -> StepResult:
    rows = await delete_rows(session, STATEMENTS, opportunity_id)
    parses, texts = await delete_returning(session, PARSES, opportunity_id)
    versions, uploads = await delete_returning(session, VERSIONS, opportunity_id)
    rows += parses + versions + await delete_rows(session, (SOURCES,), opportunity_id)
    return StepResult(rows=rows, released_sha256=texts + uploads)
