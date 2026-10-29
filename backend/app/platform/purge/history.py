"""The recent retention purges (Story 10.6): a read over the `platform.purge.completed` trace
events for Admin > Retention (`platform.purge`'s public read; no authorization here, the
caller checks it). Ids, counts and times only."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select

from app.platform.trace.catalogue import PlatformPurgeCompleted
from app.platform.trace.models import TraceEvent
from app.platform.uow import UnitOfWork

PURGE_COMPLETED = PlatformPurgeCompleted.event_type
RECENT_LIMIT = 20


@dataclass(frozen=True, slots=True)
class PurgeRecord:
    purged_opportunity_id: UUID
    rule: str
    rows_by_module: dict[str, int]
    files_deleted: int
    occurred_at: datetime


async def recent_purges(uow: UnitOfWork, limit: int = RECENT_LIMIT) -> list[PurgeRecord]:
    """The last `limit` purge events, newest first."""
    rows = (
        await uow.session.execute(
            select(TraceEvent.subject_id, TraceEvent.payload, TraceEvent.occurred_at)
            .where(TraceEvent.event_type == PURGE_COMPLETED)
            .order_by(TraceEvent.occurred_at.desc(), TraceEvent.id.desc())
            .limit(limit)
        )
    ).all()
    records: list[PurgeRecord] = []
    for subject_id, payload, occurred_at in rows:
        event = PlatformPurgeCompleted.model_validate(payload)
        records.append(
            PurgeRecord(
                purged_opportunity_id=subject_id,
                rule=event.rule,
                rows_by_module=dict(event.rows_by_module),
                files_deleted=event.files_deleted,
                occurred_at=occurred_at,
            )
        )
    return records
