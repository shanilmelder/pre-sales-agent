"""Research Snapshots (Story 5.4): `knowledge.capture_research_snapshot` and the
`research_snapshot` Evidence resolver.

The ToolGateway's research fetch streams an allowlisted page's raw body, unchanged, into
`platform.storage` with no Unit of Work open, then calls `capture_research_snapshot` (the
registered research sink), still with none open:

1. The raw body is parsed in the sandboxed Knowledge parse child (`.html`: stdlib
   `html.parser`, script and style dropped; `.txt` for `text/plain`). A parse failure is
   `ToolFailed(parse_failed)` and stores no snapshot.
2. The extracted text is stored as a blob too.
3. One short Unit of Work references both blobs (`platform_files`), inserts the INSERT-only
   `knowledge_research_snapshots` row and appends `knowledge.research_snapshot.captured`
   (actor: the Agent; ids, codes, sizes and hashes only, never the URL or text).

The tool returns the snapshot id and its text fenced as a data block (`platform.prompt_data`,
with the injection flag). An Assessment cites it as `{kind: research_snapshot, id, span?}`:
the resolver accepts a known snapshot (no version: snapshots never change) whose span, in
code points, is a non-empty range inside the extracted text.
"""

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from app.modules.knowledge.adapters import parse_runner
from app.modules.knowledge.adapters import research_repository as repo
from app.platform import evidence, files, trace
from app.platform.actor import Actor
from app.platform.config import Settings, get_settings
from app.platform.evidence import Ref
from app.platform.ids import new_id
from app.platform.logging import get_logger
from app.platform.parsing.rules import MAX_TEXT_CHARS, ParseError
from app.platform.prompt_data import Fenced, fence, new_token
from app.platform.storage import BlobStore
from app.platform.tool_gateway import ToolContext, ToolFailed, ToolResult
from app.platform.tool_gateway.fetcher import FetchedPage
from app.platform.trace.catalogue import KnowledgeResearchSnapshotCaptured
from app.platform.uow import UnitOfWork, unit_of_work

EVIDENCE_KIND = "research_snapshot"
SUBJECT_TYPE = "knowledge.research_snapshot"
_EXTENSIONS = {"text/html": ".html", "text/plain": ".txt"}
_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ResearchPage:
    """What `knowledge.research_page.fetch` returns: the snapshot to cite and its text as a
    fenced data block."""

    snapshot_id: UUID
    final_url: str = field(repr=False)
    char_count: int
    fenced: Fenced = field(repr=False)


async def _one(data: bytes) -> AsyncIterator[bytes]:
    yield data


async def capture_research_snapshot(
    engine: AsyncEngine, settings: Settings, ctx: ToolContext, page: FetchedPage
) -> ToolResult | ToolFailed:
    """`knowledge.capture_research_snapshot` (module docstring)."""
    store = BlobStore(settings.storage_dir)
    ext = _EXTENSIONS[page.content_type]
    try:
        output = await parse_runner.run_parse(
            store.path_for(page.body.sha256),
            ext,
            timeout_s=settings.parse_timeout_s,
            max_memory_mb=settings.parse_max_memory_mb,
        )
    except (ParseError, parse_runner.ParseTimeoutError, OSError):
        return ToolFailed("parse_failed", page.http_status)
    data = output.text.encode("utf-8")
    text_blob = await store.put_stream(_one(data), max(len(data), 1))
    snapshot_id = new_id()
    async with unit_of_work(engine) as uow:
        await files.add_reference(uow, page.body.sha256, page.body.size)
        await files.add_reference(uow, text_blob.sha256, text_blob.size)
        await repo.insert_snapshot(
            uow,
            snapshot_id=snapshot_id,
            opportunity_id=ctx.opportunity_id,
            run_id=ctx.run_id,
            task_id=ctx.task_id,
            url=page.url,
            final_url=page.final_url,
            http_status=page.http_status,
            content_type=page.content_type,
            content_sha256=page.body.sha256,
            text_sha256=text_blob.sha256,
            parser=output.parser,
        )
        await trace.append(
            uow,
            actor=Actor(type="agent", id=ctx.actor_id),
            payload=KnowledgeResearchSnapshotCaptured(
                run_id=None if ctx.run_id is None else str(ctx.run_id),
                task_id=None if ctx.task_id is None else str(ctx.task_id),
                http_status=page.http_status,
                content_type="text/html" if page.content_type == "text/html" else "text/plain",
                content_sha256=page.body.sha256,
                text_sha256=text_blob.sha256,
                byte_count=page.body.size,
                char_count=len(output.text),
                parser=output.parser,
            ),
            subject_type=SUBJECT_TYPE,
            subject_id=snapshot_id,
            opportunity_id=ctx.opportunity_id,
            workflow_run_id=ctx.run_id,
        )
    _log.info(
        "knowledge.research_snapshot_captured",
        extra={
            "snapshot_id": str(snapshot_id),
            "opportunity_id": str(ctx.opportunity_id),
            "task_id": ctx.task_id and str(ctx.task_id),
            "http_status": page.http_status,
            "byte_count": page.body.size,
            "char_count": len(output.text),
            "parser": output.parser,
        },
    )
    fenced = fence(
        "RESEARCH_SNAPSHOT",
        str(snapshot_id),
        output.text,
        new_token(),
        {"content_type": page.content_type},
    )
    return ToolResult(
        items=(
            ResearchPage(
                snapshot_id=snapshot_id,
                final_url=page.final_url,
                char_count=len(output.text),
                fenced=fenced,
            ),
        ),
        http_status=page.http_status,
    )


# --- the `research_snapshot` Evidence resolver ---------------------------------------------


async def _text_length(store: BlobStore, sha256: str) -> int | None:
    try:
        data = await asyncio.to_thread(store.path_for(sha256).read_bytes)
    except (FileNotFoundError, ValueError):
        return None
    return len(data.decode("utf-8"))


async def check_snapshot_refs(uow: UnitOfWork, refs: Sequence[Ref]) -> list[str | None]:
    """Per reference, None when it resolves, else why not (ids and numbers only)."""
    found = await repo.snapshot_refs(uow, [r.id for r in refs if r.kind == EVIDENCE_KIND])
    store = BlobStore(get_settings().storage_dir)
    lengths: dict[str, int | None] = {}
    reasons: list[str | None] = []
    for ref in refs:
        snapshot = found.get(ref.id) if ref.kind == EVIDENCE_KIND else None
        if ref.kind != EVIDENCE_KIND:
            reasons.append(f"not a {EVIDENCE_KIND} reference")
            continue
        if snapshot is None:
            reasons.append("no such Research Snapshot")
            continue
        if ref.version is not None:
            reasons.append("a Research Snapshot has no versions")
            continue
        if ref.span is None:
            reasons.append(None)
            continue
        if snapshot.text_sha256 not in lengths:
            lengths[snapshot.text_sha256] = await _text_length(store, snapshot.text_sha256)
        length = lengths[snapshot.text_sha256]
        if length is None:
            reasons.append("the snapshot's text is missing")
        elif not 0 <= ref.span.start < ref.span.end <= min(length, MAX_TEXT_CHARS):
            reasons.append(f"the span lies outside the snapshot text [0, {length})")
        else:
            reasons.append(None)
    return reasons


evidence.register_resolver(EVIDENCE_KIND, check_snapshot_refs)
