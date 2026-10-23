"""The ToolGateway (Story 5.4, AD-9): the only way an Agent reads data.

`ToolGateway.call(ctx, tool, args)` checks, in order: the tool is in the catalogue
(`unknown_tool`), the caller's pinned config version grants it (`tool_not_permitted`), and
no `opportunity_id` argument names another Opportunity than the task's (`out_of_scope`).
Then the owning module's handler runs, scoped to `ctx.opportunity_id`; it may deny an id
outside that Opportunity (`out_of_scope`) and then returns no data.

Owning modules register handlers at import (`register_tool`), as Evidence resolvers are
registered: this package never imports a business module. A read handler runs in a Unit of
Work: the caller's (`uow=`) or one the gateway opens. The research fetch
(`knowledge.research_page.fetch`) is different: the platform fetcher does the network work
with no Unit of Work open, then the registered research sink (knowledge) stores the
Research Snapshot in its own short one; calling it with `uow=` is a programming error.

The gateway, not the handler, records every call: one INSERT-only `platform_tool_calls` row
(ids, tool, outcome, reason, result count, duration, HTTP status) and, for a denial, the
trace event `platform.tool_call.denied`, in the same Unit of Work as the read (or its own
for the research fetch). Outcomes are values; nothing here raises for a denied or failed
call. Logs, rows and trace hold ids and codes only.
"""

import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from app.platform import trace
from app.platform.actor import Actor
from app.platform.config import Settings, get_settings
from app.platform.ids import new_id
from app.platform.logging import get_logger
from app.platform.storage import BlobStore
from app.platform.tool_gateway.allowlist import Allowlist
from app.platform.tool_gateway.catalogue import RESEARCH_PAGE_FETCH, TOOLS
from app.platform.tool_gateway.fetcher import FetchedPage, fetch
from app.platform.tool_gateway.models import PlatformToolCall
from app.platform.tool_gateway.port import (
    ToolContext,
    ToolDenied,
    ToolFailed,
    ToolOutcome,
    ToolResult,
    outcome_code,
)
from app.platform.trace.catalogue import PlatformToolCallDenied
from app.platform.uow import UnitOfWork, unit_of_work

SUBJECT_TYPE = "platform.tool_call"
_TOOL_NAME_MAX = 100
_log = get_logger(__name__)

type ReadHandler = Callable[
    [UnitOfWork, ToolContext, Mapping[str, Any]], Awaitable[ToolResult | ToolDenied]
]
"""A read tool: the records it read, or `ToolDenied(out_of_scope)` and nothing."""
type ResearchSink = Callable[
    [AsyncEngine, Settings, ToolContext, FetchedPage], Awaitable[ToolResult | ToolFailed]
]
"""Stores a fetched page as a Research Snapshot (no Unit of Work open when called)."""

_HANDLERS: dict[str, ReadHandler] = {}
_SINKS: dict[str, ResearchSink] = {}


def register_tool(name: str, handler: ReadHandler) -> None:
    """Register the handler of a catalogue read tool (once per name)."""
    spec = TOOLS.get(name)
    if spec is None or spec.network:
        raise ValueError(f"{name!r} is not a catalogue read tool")
    if name in _HANDLERS and _HANDLERS[name] is not handler:
        raise ValueError(f"a handler for {name!r} is already registered")
    _HANDLERS[name] = handler


def register_research_sink(sink: ResearchSink) -> None:
    """Register what stores a fetched page (knowledge's `capture_research_snapshot`)."""
    if RESEARCH_PAGE_FETCH in _SINKS and _SINKS[RESEARCH_PAGE_FETCH] is not sink:
        raise ValueError("a research sink is already registered")
    _SINKS[RESEARCH_PAGE_FETCH] = sink


def registered_tools() -> frozenset[str]:
    """The tools with a handler (or sink) in this process."""
    return frozenset(_HANDLERS) | frozenset(_SINKS)


def _foreign_opportunity(ctx: ToolContext, args: Mapping[str, Any]) -> bool:
    if "opportunity_id" not in args:
        return False
    try:
        return UUID(str(args["opportunity_id"])) != ctx.opportunity_id
    except ValueError:
        return True


def _precheck(ctx: ToolContext, tool: str, args: Mapping[str, Any]) -> ToolDenied | None:
    if tool not in TOOLS or (tool not in _HANDLERS and tool not in _SINKS):
        return ToolDenied("unknown_tool")
    if tool not in ctx.tool_permissions:
        return ToolDenied("tool_not_permitted")
    if _foreign_opportunity(ctx, args):
        return ToolDenied("out_of_scope")
    return None


class ToolGateway:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        engine: AsyncEngine | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        allowlist: Allowlist | None = None,
        store: BlobStore | None = None,
    ) -> None:
        """`engine` is needed for calls made without a Unit of Work (the research fetch);
        `transport` replaces the network (tests pass an `httpx.MockTransport`)."""
        self._settings = settings or get_settings()
        self._engine = engine
        self._transport = transport
        self._allowlist = allowlist
        self._store = store or BlobStore(self._settings.storage_dir)

    @property
    def allowlist(self) -> Allowlist:
        if self._allowlist is None:
            self._allowlist = Allowlist.load(self._settings.research_allowlist_path)
        return self._allowlist

    def _require_engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("this ToolGateway call needs an engine (no Unit of Work given)")
        return self._engine

    async def call(
        self,
        ctx: ToolContext,
        tool: str,
        args: Mapping[str, Any] | None = None,
        *,
        uow: UnitOfWork | None = None,
    ) -> ToolOutcome:
        """Call `tool` as the context's Agent (module docstring). Never raises for a denied
        or failed call; a handler's unexpected error propagates (and records nothing)."""
        started = time.perf_counter()
        arguments: Mapping[str, Any] = dict(args or {})
        spec = TOOLS.get(tool)
        if spec is not None and spec.network:
            if uow is not None:
                raise RuntimeError("the research fetch must not run inside a Unit of Work")
            denied = _precheck(ctx, tool, arguments)
            outcome: ToolOutcome = denied or await self._research(ctx, arguments)
            async with unit_of_work(self._require_engine()) as own:
                await self._record(own, ctx, tool, outcome, started)
            return outcome
        if uow is not None:
            return await self._read(uow, ctx, tool, arguments, started)
        async with unit_of_work(self._require_engine()) as own:
            return await self._read(own, ctx, tool, arguments, started)

    async def _read(
        self,
        uow: UnitOfWork,
        ctx: ToolContext,
        tool: str,
        args: Mapping[str, Any],
        started: float,
    ) -> ToolOutcome:
        outcome: ToolOutcome | None = _precheck(ctx, tool, args)
        if outcome is None:
            outcome = await _HANDLERS[tool](uow, ctx, args)
        await self._record(uow, ctx, tool, outcome, started)
        return outcome

    async def _research(self, ctx: ToolContext, args: Mapping[str, Any]) -> ToolOutcome:
        url = args.get("url")
        topic = args.get("topic")
        if not isinstance(url, str) or (topic is not None and not isinstance(topic, str)):
            return ToolDenied("not_allowlisted")
        page = await fetch(
            url,
            allowlist=self.allowlist,
            store=self._store,
            timeout_s=self._settings.research_fetch_timeout_s,
            max_bytes=self._settings.research_max_bytes,
            topic=topic,
            transport=self._transport,
        )
        if not isinstance(page, FetchedPage):
            return page
        sink = _SINKS[RESEARCH_PAGE_FETCH]
        return await sink(self._require_engine(), self._settings, ctx, page)

    async def _record(
        self,
        uow: UnitOfWork,
        ctx: ToolContext,
        tool: str,
        outcome: ToolOutcome,
        started: float,
    ) -> None:
        call_id = new_id()
        name = tool[:_TOOL_NAME_MAX]
        code = outcome_code(outcome)
        reason = None if isinstance(outcome, ToolResult) else outcome.reason
        http_status = None if isinstance(outcome, ToolDenied) else outcome.http_status
        count = outcome.result_count if isinstance(outcome, ToolResult) else 0
        duration_ms = max(0, round((time.perf_counter() - started) * 1000))
        await uow.session.execute(
            insert(PlatformToolCall).values(
                id=call_id,
                run_id=ctx.run_id,
                task_id=ctx.task_id,
                opportunity_id=ctx.opportunity_id,
                agent_id=ctx.agent_id,
                config_version_id=ctx.config_version_id,
                tool=name,
                outcome=code,
                reason=reason,
                result_count=count,
                duration_ms=duration_ms,
                http_status=http_status,
            )
        )
        if isinstance(outcome, ToolDenied):
            await trace.append(
                uow,
                actor=Actor(type="agent", id=ctx.actor_id),
                payload=PlatformToolCallDenied(
                    actor_id=ctx.actor_id,
                    tool=name,
                    reason=outcome.reason,
                    task_id=None if ctx.task_id is None else str(ctx.task_id),
                ),
                subject_type=SUBJECT_TYPE,
                subject_id=call_id,
                opportunity_id=ctx.opportunity_id,
                workflow_run_id=ctx.run_id,
            )
        _log.info(
            f"tool_call.{code}",
            extra={
                "tool_call_id": str(call_id),
                "tool": name,
                "agent_id": ctx.agent_id,
                "config_version_id": str(ctx.config_version_id),
                "run_id": ctx.run_id and str(ctx.run_id),
                "task_id": ctx.task_id and str(ctx.task_id),
                "opportunity_id": str(ctx.opportunity_id),
                "reason": reason,
                "result_count": count,
                "duration_ms": duration_ms,
                "http_status": http_status,
            },
        )
