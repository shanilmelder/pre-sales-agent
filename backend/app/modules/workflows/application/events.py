"""The per-Opportunity event stream (AD-16, AD-30; Story 5.2): Server-Sent Events of the
Opportunity's progress rows.

The caller is authorized once, when the stream opens (anyone who can read the Opportunity).
The stream then LISTENs on `psa_events`; each NOTIFY carries only `{event_id,
opportunity_id, source}`, and the row is re-read here, so no content travels through the
notification. A reconnect with `Last-Event-ID` first replays the Opportunity's rows after
that id, in order (an unknown id streams from now). Frames are

    id: <event_id>
    event: <event_type>
    data: {"event_type", "subject_type", "subject_id", "subject_version", "occurred_at",
           "summary"}

and a comment line is sent every `keepalive_s` seconds so proxies keep the connection open.
Trace events are not streamed (Story 5.7).

Story 4.7: a NOTIFY `{opportunity_id, source: "gaps"}` (any change to the Opportunity's Gaps,
Clarification Questions or answer suggestions) is forwarded as an id-less frame

    event: gaps.changed
    data: {"source": "gaps"}

so the Gaps tab, its badge and the Overview re-read; nothing is replayed for it.

Story 6.2: likewise a NOTIFY `{opportunity_id, source: "conflicts"}` (any write that changes
what the Conflicts tab shows) is forwarded as

    event: conflicts.changed
    data: {"source": "conflicts"}

so the Conflicts tab and its badge re-read.
"""

import json
from collections import deque
from collections.abc import AsyncIterator
from uuid import UUID

import psycopg
from sqlalchemy.ext.asyncio import AsyncEngine

from app.modules.identity.application.public import Principal
from app.modules.opportunities.application import public as opportunities
from app.modules.workflows.adapters import repository as repo
from app.modules.workflows.adapters.repository import (
    EVENTS_CHANNEL,
    PROGRESS_SOURCE,
    ProgressRecord,
)
from app.modules.workflows.application.models import ProgressEventData
from app.platform.db import libpq_url
from app.platform.logging import get_logger
from app.platform.uow import UnitOfWork, unit_of_work

KEEPALIVE_S = 15.0
GAPS_SOURCE = "gaps"
GAPS_CHANGED_FRAME = 'event: gaps.changed\ndata: {"source": "gaps"}\n\n'
"""The frame for a change to the Opportunity's Gaps (Story 4.7): no id, no content."""
CONFLICTS_SOURCE = "conflicts"
CONFLICTS_CHANGED_FRAME = 'event: conflicts.changed\ndata: {"source": "conflicts"}\n\n'
"""The frame for a change to the Opportunity's Conflicts (Story 6.2): no id, no content."""
_CHANGED_FRAMES = {GAPS_SOURCE: GAPS_CHANGED_FRAME, CONFLICTS_SOURCE: CONFLICTS_CHANGED_FRAME}
_SEEN_MAX = 2000
_log = get_logger(__name__)


async def authorize_stream(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> None:
    """404 unless the caller can read the Opportunity (as every Opportunity route)."""
    await opportunities.readable_resource(uow, actor, opportunity_id)


def parse_event_id(raw: str | None) -> UUID | None:
    if not raw:
        return None
    try:
        return UUID(raw.strip())
    except ValueError:
        return None


def frame(record: ProgressRecord) -> str:
    data = ProgressEventData.model_validate(
        {
            "event_type": record.event_type,
            "subject_type": record.subject_type,
            "subject_id": str(record.subject_id),
            "subject_version": record.subject_version,
            "occurred_at": record.occurred_at,
            "summary": record.summary,
        }
    )
    return f"id: {record.id}\nevent: {record.event_type}\ndata: {data.model_dump_json()}\n\n"


async def _replay(
    engine: AsyncEngine, opportunity_id: UUID, after: UUID | None
) -> list[ProgressRecord]:
    if after is None:
        return []
    async with unit_of_work(engine) as uow:
        known = await repo.get_progress(uow, after)
        if known is None or known.opportunity_id != opportunity_id:
            return []  # unknown (or pruned, or another Opportunity's) id: stream from now
        return await repo.progress_after(uow, opportunity_id, after)


async def _read(engine: AsyncEngine, event_id: UUID) -> ProgressRecord | None:
    async with unit_of_work(engine) as uow:
        return await repo.get_progress(uow, event_id)


def _notified(payload: str, opportunity_id: UUID) -> UUID | str | None:
    """For a NOTIFY about this Opportunity: the event id of a progress row, or the source
    (`GAPS_SOURCE`, `CONFLICTS_SOURCE`) of a change to its Gaps or Conflicts; else None."""
    try:
        data = json.loads(payload)
        if UUID(data["opportunity_id"]) != opportunity_id:
            return None
        if data.get("source") in _CHANGED_FRAMES:
            return str(data["source"])
        if data.get("source") != PROGRESS_SOURCE:
            return None
        return UUID(data["event_id"])
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


async def event_stream(
    engine: AsyncEngine,
    database_url: str,
    opportunity_id: UUID,
    last_event_id: UUID | None,
    *,
    keepalive_s: float = KEEPALIVE_S,
) -> AsyncIterator[str]:
    """The Opportunity's frames: the replay after `last_event_id`, then live ones, with a
    keep-alive comment every `keepalive_s` seconds. Runs until the client goes away (the
    server cancels it)."""
    seen: deque[UUID] = deque(maxlen=_SEEN_MAX)
    ids = {"opportunity_id": str(opportunity_id)}
    async with await psycopg.AsyncConnection.connect(
        libpq_url(database_url), autocommit=True
    ) as listener:
        # LISTEN before the replay, so nothing committed in between is missed; duplicates
        # are dropped by id.
        await listener.execute(f"LISTEN {EVENTS_CHANNEL}")
        _log.info("workflows.stream_opened", extra=ids)
        yield ": connected\n\n"
        for record in await _replay(engine, opportunity_id, last_event_id):
            seen.append(record.id)
            yield frame(record)
        while True:
            async for notify in listener.notifies(timeout=keepalive_s):
                event_id = _notified(notify.payload, opportunity_id)
                if isinstance(event_id, str):
                    yield _CHANGED_FRAMES[event_id]
                    continue
                if not isinstance(event_id, UUID) or event_id in seen:
                    continue
                live = await _read(engine, event_id)
                if live is None:
                    continue
                seen.append(live.id)
                yield frame(live)
            yield ": keep-alive\n\n"
