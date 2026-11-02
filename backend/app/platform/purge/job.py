"""The retention purge (Story 10.6): the daily `platform.purge` job, enqueued from its
`platform_schedules` row. The only code that deletes Opportunity data.

It connects as the privileged `psa_purge` role (`PSA_PURGE_DATABASE_URL`, set on the worker
only); nothing else gets that URL. Unset: it logs `purge.not_configured` and completes
without deleting anything.

1. The registered selector (`opportunities`) lists the Opportunities whose retention date
   is before today (UTC): lost 3 years after the outcome, won 7 years after contract end.
   Open Opportunities have no retention date and are never selected.
2. Each one is purged in its own transaction on the purge engine. Its row is locked first
   (`SELECT ... FOR UPDATE`) and re-checked with the domain rule: one reopened, changed or
   already purged since the selection is skipped (no deletes, no event). Its workflow run
   ids are
   collected, every registered module step runs in order, then the platform's own rows go
   (trace events, model and tool calls, jobs: by `opportunity_id` or by one of its runs).
   Every file reference the deleted rows held is released; `platform.purge.completed` is
   appended (`opportunity_id` null, subject the purged UUID, the rule, rows per module and
   files deleted). A blob whose count reached zero is deleted only after that commit.
3. A failure rolls back that Opportunity only; the others still run. If any failed, the job
   raises so the queue retries it with backoff; on the last attempt it first queues a
   `purge_failed` alert email (counts and UUIDs only), then goes `dead`.

Reruns are safe: a purged Opportunity is gone, so it is never selected again. Logs and the
event carry ids and counts only, never names or content.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import delete, or_
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.platform import files, trace
from app.platform.actor import Actor
from app.platform.alerts.jobs import MAX_LISTED_IDS, AlertEmailJob, PurgeFailedAlert
from app.platform.config import Settings, get_settings
from app.platform.jobs import JobContext, JobPayload, JobType, enqueue, register
from app.platform.jobs.models import PlatformJob
from app.platform.logging import get_logger
from app.platform.model_gateway.models import PlatformModelCall
from app.platform.purge import registry
from app.platform.purge.registry import RetentionDue
from app.platform.storage import BlobStore
from app.platform.tool_gateway.models import PlatformToolCall
from app.platform.trace.catalogue import PlatformPurgeCompleted
from app.platform.trace.models import TraceEvent
from app.platform.uow import UnitOfWork, unit_of_work

PURGE = "platform.purge"
SYSTEM = Actor(type="system", id=PURGE)
SUBJECT_TYPE = "opportunities.opportunity"
"""The purged Opportunity's subject type (`opportunities`' own, named here as a string:
`platform` never imports modules)."""
PLATFORM_MODULE = "platform"
PLATFORM_TABLES = frozenset(
    {"platform_trace_events", "platform_model_calls", "platform_tool_calls", "platform_jobs"}
)
"""The platform's own per-Opportunity tables, emptied by `_purge_platform_rows`."""
_log = get_logger(__name__)


class PurgeIncompleteError(Exception):
    """Some Opportunities could not be purged this attempt: the queue retries the job."""


@dataclass(slots=True)
class PurgeReport:
    purged: list[UUID] = field(default_factory=list)
    failed: list[UUID] = field(default_factory=list)
    files_deleted: int = 0


def purge_settings() -> Settings:
    """Settings for the job (the purge URL, the file store). Tests replace this."""
    return get_settings()


def create_purge_engine(url: str, settings: Settings) -> AsyncEngine:
    """The privileged engine, sessions in UTC like the app's (`platform.db.create_engine`)."""
    return create_async_engine(
        url,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": max(1, int(settings.db_connect_timeout_s)),
            "options": "-c timezone=UTC",
        },
    )


def today_utc() -> date:
    return datetime.now(UTC).date()


async def due_opportunities(engine: AsyncEngine, today: date) -> list[RetentionDue]:
    """The Opportunities whose retention date is before `today`."""
    select_due = registry.selector()
    async with unit_of_work(engine) as uow:
        return await select_due(uow.session, today)


async def _purge_platform_rows(
    session: AsyncSession, opportunity_id: UUID, run_ids: list[UUID]
) -> int:
    """The platform's own rows of the Opportunity: by `opportunity_id`, or by one of its runs."""
    statements = [
        delete(TraceEvent).where(
            or_(
                TraceEvent.opportunity_id == opportunity_id, TraceEvent.workflow_run_id.in_(run_ids)
            )
        ),
        delete(PlatformModelCall).where(
            or_(
                PlatformModelCall.opportunity_id == opportunity_id,
                PlatformModelCall.run_id.in_(run_ids),
            )
        ),
        delete(PlatformToolCall).where(
            or_(
                PlatformToolCall.opportunity_id == opportunity_id,
                PlatformToolCall.run_id.in_(run_ids),
            )
        ),
        delete(PlatformJob).where(PlatformJob.opportunity_id == opportunity_id),
    ]
    deleted = 0
    for statement in statements:
        result = await session.execute(statement)
        deleted += int(result.rowcount)  # type: ignore[attr-defined]
    return deleted


async def _purge_one(
    uow: UnitOfWork, due: RetentionDue, today: date
) -> tuple[RetentionDue, dict[str, int], set[str]] | None:
    """Delete everything of one Opportunity inside `uow`: its due state, rows per module and
    the blobs left with no reference. None (nothing deleted, no event) when, once its row is
    locked, it is gone (already purged) or no longer due (reopened or changed)."""
    session = uow.session
    current = await registry.lock()(session, due.opportunity_id, today)
    if current is None:
        return None
    run_ids: set[UUID] = set()
    for provider in registry.run_id_providers():
        run_ids.update(await provider(session, current.opportunity_id))
    rows: dict[str, int] = {}
    released: list[str] = []
    for step in registry.steps():
        result = await step.fn(session, current.opportunity_id)
        rows[step.module] = rows.get(step.module, 0) + result.rows
        released.extend(result.released_sha256)
    rows[PLATFORM_MODULE] = await _purge_platform_rows(
        session, current.opportunity_id, sorted(run_ids)
    )
    unreferenced: set[str] = set()
    for sha256 in released:
        if await files.release_reference(uow, sha256):
            unreferenced.add(sha256)
    await trace.append(
        uow,
        actor=SYSTEM,
        payload=PlatformPurgeCompleted(
            purged_opportunity_id=str(current.opportunity_id),
            rule=current.rule.value,
            retention_until=current.retention_until.isoformat(),
            rows_by_module=rows,
            files_deleted=len(unreferenced),
        ),
        subject_type=SUBJECT_TYPE,
        subject_id=current.opportunity_id,
    )
    return current, rows, unreferenced


async def _delete_blobs(engine: AsyncEngine, store: BlobStore, candidates: set[str]) -> int:
    """After the purge committed: delete each blob still at zero references, holding its
    `platform_files` row locked meanwhile so a concurrent new reference waits."""
    if not candidates:
        return 0
    deleted = 0
    async with unit_of_work(engine) as uow:
        for sha256 in sorted(await files.unreferenced(uow, sorted(candidates))):
            try:
                await store.delete(sha256)
            except OSError as exc:  # the row stays at zero; the blob is only orphaned
                _log.warning("purge.blob_delete_failed", extra={"exc_type": type(exc).__name__})
                continue
            deleted += 1
    return deleted


async def purge_opportunity(
    engine: AsyncEngine, store: BlobStore, due: RetentionDue, today: date
) -> int | None:
    """Purge one Opportunity in its own transaction; how many blobs were deleted, or None
    when it was skipped (gone or no longer due once locked)."""
    async with unit_of_work(engine) as uow:
        purged = await _purge_one(uow, due, today)
    if purged is None:
        _log.info("purge.opportunity_skipped", extra={"opportunity_id": str(due.opportunity_id)})
        return None
    current, rows, unreferenced = purged
    try:  # committed: a blob that can't be deleted now stays orphaned, the purge stands
        deleted = await _delete_blobs(engine, store, unreferenced)
    except Exception as exc:
        _log.warning("purge.blob_delete_failed", extra={"exc_type": type(exc).__name__})
        deleted = 0
    _log.info(
        "purge.opportunity_purged",
        extra={
            "opportunity_id": str(current.opportunity_id),
            "rule": current.rule.value,
            "rows": sum(rows.values()),
            "files_deleted": deleted,
        },
    )
    return deleted


async def run_purge(engine: AsyncEngine, store: BlobStore, *, today: date) -> PurgeReport:
    """Purge every due Opportunity, each on its own; a failure never stops the others."""
    report = PurgeReport()
    for due in await due_opportunities(engine, today):
        try:
            deleted = await purge_opportunity(engine, store, due, today)
        except Exception as exc:
            _log.warning(
                "purge.opportunity_failed",
                extra={"opportunity_id": str(due.opportunity_id), "exc_type": type(exc).__name__},
            )
            report.failed.append(due.opportunity_id)
            continue
        if deleted is None:
            continue
        report.files_deleted += deleted
        report.purged.append(due.opportunity_id)
    _log.info(
        "purge.completed",
        extra={
            "purged": len(report.purged),
            "failed": len(report.failed),
            "files_deleted": report.files_deleted,
        },
    )
    return report


class Purge(JobPayload):
    """No fields: the job purges every Opportunity that is due."""


async def _alert(ctx: JobContext, failed: list[UUID], purged: int) -> None:
    async with unit_of_work(ctx.engine) as uow:
        await enqueue(
            uow,
            AlertEmailJob(
                alert=PurgeFailedAlert(
                    failed_count=len(failed),
                    failed_opportunity_ids=failed[:MAX_LISTED_IDS],
                    purged_count=purged,
                    attempts=ctx.attempt,
                )
            ),
        )


async def purge(ctx: JobContext, payload: Purge) -> None:
    settings = purge_settings()
    if settings.purge_database_url is None:
        _log.warning("purge.not_configured", extra={"missing": ["PSA_PURGE_DATABASE_URL"]})
        return
    last_attempt = ctx.attempt >= ctx.max_attempts
    engine = create_purge_engine(settings.purge_database_url, settings)
    try:
        report = await run_purge(engine, BlobStore(settings.storage_dir), today=today_utc())
    except Exception:  # e.g. the purge role cannot connect: nothing was selected
        if last_attempt:
            await _alert(ctx, [], 0)
        raise
    finally:
        await engine.dispose()
    if report.failed:
        if last_attempt:
            await _alert(ctx, report.failed, len(report.purged))
        raise PurgeIncompleteError(f"{len(report.failed)} Opportunities were not purged")


PURGE_JOB = register(
    JobType(
        name=PURGE,
        payload=Purge,
        handler=purge,
        priority="background",
        timeout_s=1800.0,
        max_attempts=3,
        backoff_base_s=300.0,
        backoff_cap_s=3600.0,
    )
)
