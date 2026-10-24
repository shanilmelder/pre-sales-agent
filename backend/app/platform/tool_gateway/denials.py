"""The denied tool call list (Story 7.4): a read over `platform_tool_calls` for the registry's
Admin → Agents → Denied tool calls view (`tool_gateway`'s public read; no authorization here,
the caller checks it).

Rows with `outcome = 'denied'`, newest first, filtered by Agent and by a UTC calendar-date
range (both bounds inclusive), one page at a time. Each record says whether its run passed
the denial alert threshold (a `platform.tool_call.denial_threshold_exceeded` event). Ids,
codes and times only.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import func, select

from app.platform.tool_gateway.gateway import RUN_SUBJECT_TYPE, THRESHOLD_EVENT
from app.platform.tool_gateway.models import PlatformToolCall
from app.platform.tool_gateway.port import DenyReason
from app.platform.trace.models import TraceEvent
from app.platform.uow import UnitOfWork

_t = PlatformToolCall


@dataclass(frozen=True, slots=True)
class DenialRecord:
    id: UUID
    created_at: datetime
    agent_id: str
    config_version_id: UUID
    tool: str
    reason: DenyReason
    opportunity_id: UUID
    run_id: UUID | None
    task_id: UUID | None
    threshold_exceeded: bool


@dataclass(frozen=True, slots=True)
class DenialPage:
    items: list[DenialRecord]
    total: int


def _start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


async def list_denials(
    uow: UnitOfWork,
    *,
    agent_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    page_size: int = 50,
) -> DenialPage:
    """One page of denied calls, newest first, and how many match in all."""
    conditions = [_t.outcome == "denied"]
    if agent_id is not None:
        conditions.append(_t.agent_id == agent_id)
    if date_from is not None:
        conditions.append(_t.created_at >= _start(date_from))
    if date_to is not None:
        conditions.append(_t.created_at < _start(date_to + timedelta(days=1)))
    total = (
        await uow.session.execute(select(func.count()).select_from(_t).where(*conditions))
    ).scalar_one()
    found = (
        await uow.session.execute(
            select(_t)
            .where(*conditions)
            .order_by(_t.created_at.desc(), _t.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars()
    calls = list(found)
    run_ids = {c.run_id for c in calls if c.run_id is not None}
    alerted: set[UUID] = set()
    if run_ids:
        alerted = set(
            (
                await uow.session.execute(
                    select(TraceEvent.subject_id).where(
                        TraceEvent.subject_type == RUN_SUBJECT_TYPE,
                        TraceEvent.subject_id.in_(run_ids),
                        TraceEvent.event_type == THRESHOLD_EVENT,
                    )
                )
            ).scalars()
        )
    return DenialPage(
        items=[
            DenialRecord(
                id=c.id,
                created_at=c.created_at,
                agent_id=c.agent_id,
                config_version_id=c.config_version_id,
                tool=c.tool,
                reason=cast(DenyReason, c.reason),  # the table's checks: a deny code
                opportunity_id=c.opportunity_id,
                run_id=c.run_id,
                task_id=c.task_id,
                threshold_exceeded=c.run_id in alerted,
            )
            for c in calls
        ],
        total=int(total),
    )
