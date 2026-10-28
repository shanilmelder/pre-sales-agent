"""workflows' retention purge step (Story 10.6): deletes one Opportunity's workflow runs
(tasks, plan versions, Decisions, progress) and their LangGraph checkpoint threads
(`thread_id` = the run id, in the `orchestration_checkpoints` schema, whose tables the
checkpointer creates on first use). Run only by the `platform.purge` job, inside the purge
role's transaction for that Opportunity."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.purge.registry import StepResult, delete_rows

CHECKPOINT_SCHEMA = "orchestration_checkpoints"
TABLES = (
    "workflows_decisions",
    "workflows_progress",
    "workflows_plan_versions",
    "workflows_tasks",
    "workflows_runs",
)
"""Every table this step empties."""
RUNS = "SELECT id FROM workflows_runs WHERE opportunity_id = :opportunity_id"
STATEMENTS = (
    "DELETE FROM workflows_decisions WHERE run_id IN (SELECT id FROM workflows_runs WHERE "
    "opportunity_id = :opportunity_id)",
    "DELETE FROM workflows_progress WHERE opportunity_id = :opportunity_id OR run_id IN (SELECT"
    " id FROM workflows_runs WHERE opportunity_id = :opportunity_id)",
    "DELETE FROM workflows_plan_versions WHERE run_id IN (SELECT id FROM workflows_runs WHERE "
    "opportunity_id = :opportunity_id)",
    "DELETE FROM workflows_tasks WHERE run_id IN (SELECT id FROM workflows_runs WHERE "
    "opportunity_id = :opportunity_id)",
    "DELETE FROM workflows_runs WHERE opportunity_id = :opportunity_id",
)
_CHECKPOINT_TABLES = (
    "SELECT table_name FROM information_schema.columns WHERE table_schema = :schema AND "
    "column_name = 'thread_id' ORDER BY table_name"
)


async def run_ids(session: AsyncSession, opportunity_id: UUID) -> list[UUID]:
    """The Opportunity's workflow runs (the platform's own rows tied to them go too)."""
    result = await session.execute(text(RUNS), {"opportunity_id": opportunity_id})
    return list(result.scalars())


async def _purge_checkpoints(session: AsyncSession, threads: list[str]) -> int:
    if not threads:
        return 0
    found = await session.execute(text(_CHECKPOINT_TABLES), {"schema": CHECKPOINT_SCHEMA})
    deleted = 0
    tables: list[str] = list(found.scalars())
    for table in tables:
        # The schema is ours and the table names come from the catalogue.
        statement = f'DELETE FROM "{CHECKPOINT_SCHEMA}"."{table}" WHERE thread_id = ANY(:threads)'  # noqa: S608
        result = await session.execute(text(statement), {"threads": threads})
        deleted += int(result.rowcount)  # type: ignore[attr-defined]
    return deleted


async def purge_opportunity(session: AsyncSession, opportunity_id: UUID) -> StepResult:
    threads = [str(run_id) for run_id in await run_ids(session, opportunity_id)]
    rows = await _purge_checkpoints(session, threads)
    rows += await delete_rows(session, STATEMENTS, opportunity_id)
    return StepResult(rows=rows)
