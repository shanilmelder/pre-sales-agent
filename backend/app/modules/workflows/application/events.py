"""The per-Opportunity event stream (AD-16, AD-30; Stories 5.2 and 2.3): Server-Sent Events
of the Opportunity's progress rows and trace events.

The caller is authorized when the stream opens (anyone who can read the Opportunity), and
again before every live frame, in a short Unit of Work: once they can't read it any more the
stream ends. The stream LISTENs on `psa_events`; each NOTIFY carries only `{event_id,
opportunity_id, source}` (`workflows_progress` or `trace`), and the row is re-read here, so
no content travels through the notification. A reconnect with `Last-Event-ID` first replays
the Opportunity's progress and trace rows after that id, merged in id order and paged until
none is left (an id unknown in both tables streams from now). Frames are

    id: <event_id>
    event: <event_type>
    data: {"event_type", "subject_type", "subject_id", "subject_version", "occurred_at",
           "summary"}

where a trace frame's `summary` is its event type (the trace payload is never sent). A
comment line is sent every `keepalive_s` seconds so proxies keep the connection open.

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
    PROGRESS_SOURCE,
    ProgressRecord,
    TraceRecord,
)
from app.modules.workflows.application.models import ProgressEventData, TraceEventData
from app.platform.db import libpq_url
from app.platform.errors import NotFoundError
from app.platform.events import EVENTS_CHANNEL, TRACE_SOURCE
from app.platform.logging import get_logger
from app.platform.uow import UnitOfWork, unit_of_work

KEEPALIVE_S = 15.0
GAPS_SOURCE = "gaps"
GAPS_CHANGED_FRAME = 'event: gaps.changed\ndata: {"source": "gaps"}\n\n'
"""The frame for a change to the Opportunity's Gaps (Story 4.7): no id, no content."""
REPLAY_LIMIT = 500
CONFLICTS_SOURCE = "conflicts"
CONFLICTS_CHANGED_FRAME = 'event: conflicts.changed\ndata: {"source": "conflicts"}\n\n'
"""The frame for a change to the Opportunity's Conflicts (Story 6.2): no id, no content."""
_CHANGED_FRAMES = {GAPS_SOURCE: GAPS_CHANGED_FRAME, CONFLICTS_SOURCE: CONFLICTS_CHANGED_FRAME}
_SEEN_MAX = 2000
_log = get_logger(__name__)

type StreamRecord = ProgressRecord | TraceRecord


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


def frame(record: StreamRecord) -> str:
    """The SSE frame of a progress row or a trace row."""
    fields = {
        "event_type": record.event_type,
        "subject_type": record.subject_type,
        "subject_id": str(record.subject_id),
        "subject_version": record.subject_version,
        "occurred_at": record.occurred_at,
    }
    data: ProgressEventData | TraceEventData
    if isinstance(record, ProgressRecord):
        data = ProgressEventData.model_validate({**fields, "summary": record.summary})
    else:
        data = TraceEventData.model_validate({**fields, "summary": record.event_type})
    return f"id: {record.id}\nevent: {record.event_type}\ndata: {data.model_dump_json()}\n\n"


def merge_replay(
    progress: list[ProgressRecord], traces: list[TraceRecord], *, limit: int = REPLAY_LIMIT
) -> list[StreamRecord]:
    """Both kinds in id order. When a kind filled its `limit`, nothing after its last row
    is kept, so a later reconnect (from the last id sent) picks up where this one stopped
    without skipping rows of the other kind."""
    merged: list[StreamRecord] = sorted([*progress, *traces], key=lambda r: r.id)
    cut = [kind[-1].id for kind in (progress, traces) if kind and len(kind) >= limit]
    if cut:
        horizon = min(cut)
        merged = [r for r in merged if r.id <= horizon]
    return merged


async def _replay(
    engine: AsyncEngine, opportunity_id: UUID, after: UUID | None
) -> AsyncIterator[StreamRecord]:
    """The rows after `after`, page by page (each page `merge_replay`'d), until both kinds
    come back short of `REPLAY_LIMIT`: so nothing between a full page and the live frames is
    skipped."""
    if after is None:
        return
    async with unit_of_work(engine) as uow:
        known: StreamRecord | None = await repo.get_progress(uow, after)
        if known is None:
            known = await repo.get_trace(uow, after)
    if known is None or known.opportunity_id != opportunity_id:
        return  # unknown (or pruned, or another Opportunity's) id: stream from now
    cursor = after
    while True:
        limit = REPLAY_LIMIT
        async with unit_of_work(engine) as uow:
            progress = await repo.progress_after(uow, opportunity_id, cursor, limit=limit)
            traces = await repo.trace_after(uow, opportunity_id, cursor, limit=limit)
        page = merge_replay(progress, traces, limit=limit)
        for record in page:
            yield record
        if (len(progress) < limit and len(traces) < limit) or not page:
            return
        cursor = page[-1].id


async def _read(engine: AsyncEngine, source: str, event_id: UUID) -> StreamRecord | None:
    async with unit_of_work(engine) as uow:
        if source == TRACE_SOURCE:
            return await repo.get_trace(uow, event_id)
        return await repo.get_progress(uow, event_id)


async def _still_readable(engine: AsyncEngine, actor: Principal, opportunity_id: UUID) -> bool:
    """Whether the subscriber can still read the Opportunity (re-checked per live frame)."""
    try:
        async with unit_of_work(engine) as uow:
            await opportunities.readable_resource(uow, actor, opportunity_id)
    except NotFoundError:
        return False
    return True


def _notified(payload: str, opportunity_id: UUID) -> tuple[str, UUID | None] | None:
    """For a NOTIFY about this Opportunity: `(source, event_id)` for a progress or trace
    row, or `(source, None)` for a change to its Gaps or Conflicts (`GAPS_SOURCE`,
    `CONFLICTS_SOURCE`); else None."""
    try:
        data = json.loads(payload)
        if UUID(data["opportunity_id"]) != opportunity_id:
            return None
        source = data.get("source")
        if source in _CHANGED_FRAMES:
            return str(source), None
        if source not in (PROGRESS_SOURCE, TRACE_SOURCE):
            return None
        return source, UUID(data["event_id"])
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


async def event_stream(
    engine: AsyncEngine,
    database_url: str,
    opportunity_id: UUID,
    last_event_id: UUID | None,
    *,
    actor: Principal,
    keepalive_s: float = KEEPALIVE_S,
) -> AsyncIterator[str]:
    """The Opportunity's frames: the replay after `last_event_id`, then live ones, with a
    keep-alive comment every `keepalive_s` seconds. Before each live frame `actor` is
    re-authorized, and the stream ends once they can't read the Opportunity. Otherwise it
    runs until the client goes away (the server cancels it)."""
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
        async for record in _replay(engine, opportunity_id, last_event_id):
            seen.append(record.id)
            yield frame(record)
        while True:
            async for notify in listener.notifies(timeout=keepalive_s):
                notified = _notified(notify.payload, opportunity_id)
                if notified is None:
                    continue
                source, event_id = notified
                live: StreamRecord | None = None
                if event_id is not None:
                    if event_id in seen:
                        continue
                    live = await _read(engine, source, event_id)
                    if live is None:
                        continue
                if not await _still_readable(engine, actor, opportunity_id):
                    _log.info("workflows.stream_revoked", extra=ids)
                    return
                if live is None:
                    yield _CHANGED_FRAMES[source]
                    continue
                seen.append(live.id)
                yield frame(live)
            yield ": keep-alive\n\n"
