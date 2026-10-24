"""The research fetch (Story 5.4): allowlisted HTTPS GETs through httpx with every redirect
hop re-checked, limits on time, size and type, and the immutable Research Snapshot it keeps
(two blobs, one INSERT-only row, a trace event) that Assessments cite as
`{kind: research_snapshot, id, span}`. The network is an `httpx.MockTransport`: no test
makes a real request."""

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine

import app.modules.knowledge.application.public  # noqa: F401 - registers the research sink
from app.agents.contract import EvidenceRef, Span
from app.modules.knowledge.application import research
from app.platform import evidence
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.storage import BlobStore
from app.platform.tool_gateway import ToolContext, ToolDenied, ToolFailed, ToolGateway, ToolResult
from app.platform.tool_gateway.allowlist import Allowlist, AllowlistError
from app.platform.tool_gateway.catalogue import RESEARCH_PAGE_FETCH
from app.platform.tool_gateway.fetcher import MAX_REDIRECTS, FetchedPage, fetch
from app.platform.uow import unit_of_work
from tests.conftest import run_async
from tests.test_gaps_detection import rows

ALLOWLIST = Allowlist.parse(
    {"version": 1, "topics": {"standards": ["example.com"], "cloud": ["docs.cloud.test"]}}
)
PAGE = (
    b"<html><head><title>Token lifetimes</title><script>steal()</script></head>"
    b"<body><p>Access tokens last 60 minutes.</p></body></html>"
)
PAGE_TEXT = "Token lifetimes\n\nAccess tokens last 60 minutes."

Handler = Callable[[httpx.Request], httpx.Response]


class Network:
    """A MockTransport that records every request it was sent."""

    def __init__(self, handler: Handler) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)

    @property
    def urls(self) -> list[str]:
        return [str(r.url) for r in self.requests]


def html(
    body: bytes = PAGE, status: int = 200, headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(
        status,
        content=body,
        headers={"content-type": "text/html; charset=utf-8", **(headers or {})},
    )


def do_fetch(
    tmp_path: Path,
    network: Network,
    url: str,
    *,
    max_bytes: int = 2 * 1024 * 1024,
    timeout_s: float = 5,
    topic: str | None = None,
) -> FetchedPage | ToolDenied | ToolFailed:
    return run_async(
        fetch(
            url,
            allowlist=ALLOWLIST,
            store=BlobStore(tmp_path / "files"),
            timeout_s=timeout_s,
            max_bytes=max_bytes,
            topic=topic,
            transport=network.transport,
        )
    )


def stored_blobs(tmp_path: Path) -> list[Path]:
    root = tmp_path / "files" / "sha256"
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


# --- the allowlist --------------------------------------------------------------------------


def test_hosts_match_exactly_or_as_subdomains_over_https_only() -> None:
    assert ALLOWLIST.allows("https://example.com/a")
    assert ALLOWLIST.allows("https://www.example.com/a?b=c")
    assert ALLOWLIST.allows("https://EXAMPLE.com./a")
    assert ALLOWLIST.allows("https://example.com:443/a")
    for denied in (
        "http://example.com/a",
        "https://notexample.com/a",
        "https://example.com.evil.test/a",
        "https://example.com:8443/a",
        "https://user:pw@example.com/a",
        "ftp://example.com/a",
        "https://cloud.test/a",
        "not a url",
    ):
        assert not ALLOWLIST.allows(denied), denied
    assert ALLOWLIST.allows("https://docs.cloud.test/x", "cloud")
    assert not ALLOWLIST.allows("https://example.com/x", "cloud")
    assert not ALLOWLIST.allows("https://example.com/x", "unknown_topic")


def test_the_allowlist_file_loads_and_a_missing_one_denies_everything(tmp_path: Path) -> None:
    path = tmp_path / "allow.yaml"
    path.write_text("version: 3\ntopics:\n  a: [Example.COM]\n", encoding="utf-8")
    loaded = Allowlist.load(path)
    assert (loaded.version, loaded.hosts()) == (3, ("example.com",))
    assert not Allowlist.load(tmp_path / "missing.yaml").allows("https://example.com/")
    assert not Allowlist.load(None).allows("https://example.com/")
    for bad in ("topics: [a]", "topics:\n  a: example.com", "topics:\n  a: ['ex ample']"):
        path.write_text(bad, encoding="utf-8")
        with pytest.raises(AllowlistError):
            Allowlist.load(path)


def test_the_repository_allowlist_parses() -> None:
    root = Path(__file__).resolve().parents[2]
    loaded = Allowlist.load(root / "ops" / "research-allowlist.yaml")
    assert loaded.version == 1 and loaded.hosts()


# --- the fetcher ----------------------------------------------------------------------------


def test_an_allowlisted_page_is_stored_unchanged(tmp_path: Path) -> None:
    network = Network(lambda request: html())
    page = do_fetch(tmp_path, network, "https://docs.example.com/tokens")
    assert isinstance(page, FetchedPage)
    assert (page.url, page.final_url, page.http_status, page.content_type) == (
        "https://docs.example.com/tokens",
        "https://docs.example.com/tokens",
        200,
        "text/html",
    )
    assert BlobStore(tmp_path / "files").path_for(page.body.sha256).read_bytes() == PAGE
    (request,) = network.requests
    assert request.method == "GET"
    assert "cookie" not in request.headers and "authorization" not in request.headers


@pytest.mark.parametrize(
    "url", ["http://example.com/a", "https://evil.test/a", "https://example.com:8080/a"]
)
def test_a_url_off_the_list_is_denied_without_a_request(tmp_path: Path, url: str) -> None:
    network = Network(lambda request: html())
    assert do_fetch(tmp_path, network, url) == ToolDenied("not_allowlisted")
    assert network.requests == []


def test_each_redirect_hop_is_rechecked_and_a_bad_hop_is_never_requested(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/next", "set-cookie": "s=1"})
        if request.url.path == "/next":
            return httpx.Response(301, headers={"location": "https://www.example.com/final"})
        if request.url.path == "/final":
            return html()
        return httpx.Response(301, headers={"location": "http://example.com/plain"})

    network = Network(handler)
    page = do_fetch(tmp_path, network, "https://example.com/start")
    assert isinstance(page, FetchedPage)
    assert page.final_url == "https://www.example.com/final"
    assert network.urls == [
        "https://example.com/start",
        "https://example.com/next",
        "https://www.example.com/final",
    ]
    assert all("cookie" not in r.headers for r in network.requests)  # no cookie jar

    network = Network(handler)
    assert do_fetch(tmp_path, network, "https://example.com/downgrade") == ToolDenied(
        "not_allowlisted"
    )
    assert network.urls == ["https://example.com/downgrade"]  # the http:// hop never sent

    off_list = Network(lambda r: httpx.Response(302, headers={"location": "https://evil.test/"}))
    assert do_fetch(tmp_path, off_list, "https://example.com/") == ToolDenied("not_allowlisted")
    assert off_list.urls == ["https://example.com/"]


def test_more_than_five_redirects_fail(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        hop = int(request.url.params.get("n", "0"))
        return httpx.Response(302, headers={"location": f"/loop?n={hop + 1}"})

    network = Network(handler)
    assert do_fetch(tmp_path, network, "https://example.com/loop") == ToolFailed(
        "too_many_redirects", 302
    )
    assert len(network.requests) == MAX_REDIRECTS + 1


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(404, text="nope"), ToolFailed("http_error", 404)),
        (httpx.Response(503, text="down"), ToolFailed("http_error", 503)),
        (httpx.Response(302), ToolFailed("http_error", 302)),  # a redirect with no Location
        (
            httpx.Response(200, content=b"%PDF-1.7", headers={"content-type": "application/pdf"}),
            ToolFailed("unsupported_content", 200),
        ),
        (
            httpx.Response(200, content=b"{}", headers={"content-type": "application/json"}),
            ToolFailed("unsupported_content", 200),
        ),
    ],
)
def test_failures_are_typed_and_store_nothing(
    tmp_path: Path, response: httpx.Response, expected: ToolFailed
) -> None:
    network = Network(lambda request: response)
    assert do_fetch(tmp_path, network, "https://example.com/x") == expected
    assert stored_blobs(tmp_path) == []


def test_a_body_past_the_limit_is_too_large_streamed_or_declared(tmp_path: Path) -> None:
    def streamed(request: httpx.Request) -> httpx.Response:
        async def chunks() -> Any:
            for _ in range(10):
                yield b"x" * 1024

        return httpx.Response(200, content=chunks(), headers={"content-type": "text/plain"})

    assert do_fetch(tmp_path, Network(streamed), "https://example.com/big", max_bytes=4096) == (
        ToolFailed("too_large", 200)
    )
    declared = Network(lambda r: html(b"<p>small</p>", headers={"content-length": "999999"}))
    assert do_fetch(tmp_path, declared, "https://example.com/big", max_bytes=4096) == ToolFailed(
        "too_large", 200
    )
    assert stored_blobs(tmp_path) == []


def test_a_slow_or_timing_out_server_is_a_timeout(tmp_path: Path) -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(2)
        return html()

    network = Network(lambda request: html())
    network.transport = httpx.MockTransport(slow)
    assert do_fetch(tmp_path, network, "https://example.com/", timeout_s=0.2) == ToolFailed(
        "timeout"
    )

    def raises(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    assert do_fetch(tmp_path, Network(raises), "https://example.com/") == ToolFailed("timeout")

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    assert do_fetch(tmp_path, Network(refused), "https://example.com/") == ToolFailed("http_error")

    def invalid(request: httpx.Request) -> httpx.Response:
        raise httpx.InvalidURL("bad host")  # not an HTTPError: still a typed failure

    assert do_fetch(tmp_path, Network(invalid), "https://example.com/") == ToolFailed("http_error")
    assert stored_blobs(tmp_path) == []


# --- through the gateway: the Research Snapshot ---------------------------------------------


@pytest.fixture
def files_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "files"
    monkeypatch.setattr(research, "get_settings", lambda: Settings(storage_dir=root))
    return root


def context(*tools: str) -> ToolContext:
    return ToolContext(
        agent_id="engineering_agent",
        semver="0.1.0",
        config_version_id=uuid4(),
        tool_permissions=frozenset(tools),
        opportunity_id=uuid4(),
        run_id=uuid4(),
        task_id=uuid4(),
    )


def gateway_fetch(
    db_url: str, root: Path, network: Network, ctx: ToolContext, args: dict[str, Any]
) -> Any:
    async def scenario() -> Any:
        engine = create_engine(Settings(database_url=db_url))
        try:
            gateway = ToolGateway(
                Settings(database_url=db_url, storage_dir=root, parse_timeout_s=60),
                engine=engine,
                transport=network.transport,
                allowlist=ALLOWLIST,
            )
            return await gateway.call(ctx, RESEARCH_PAGE_FETCH, args)
        finally:
            await engine.dispose()

    return run_async(scenario())


def snapshots(engine: Engine, ctx: ToolContext) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM knowledge_research_snapshots WHERE opportunity_id = :o",
        o=ctx.opportunity_id,
    )


def tool_calls(engine: Engine, ctx: ToolContext) -> list[dict[str, Any]]:
    return rows(engine, "SELECT * FROM platform_tool_calls WHERE task_id = :t", t=ctx.task_id)


def trace_events(engine: Engine, ctx: ToolContext) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM platform_trace_events WHERE opportunity_id = :o ORDER BY occurred_at",
        o=ctx.opportunity_id,
    )


def test_a_fetched_page_becomes_a_snapshot_with_two_blobs_and_a_trace_event(
    sync_engine: Engine, db_url: str, files_root: Path
) -> None:
    ctx = context(RESEARCH_PAGE_FETCH)
    network = Network(lambda request: html())
    outcome = gateway_fetch(
        db_url, files_root, network, ctx, {"url": "https://docs.example.com/t?q=acme-secret"}
    )

    assert isinstance(outcome, ToolResult) and outcome.http_status == 200
    (page,) = outcome.items
    assert isinstance(page, research.ResearchPage)
    assert page.char_count == len(PAGE_TEXT)
    assert page.fenced.block == (
        f"<<<RESEARCH_SNAPSHOT {page.snapshot_id} content_type=text/html token="
        + page.fenced.block.split("token=", 1)[1].split(">>>", 1)[0]
        + f">>>\n{PAGE_TEXT}\n<<<END {page.snapshot_id} token="
        + page.fenced.block.rsplit("token=", 1)[1]
    )
    assert page.fenced.injection_suspected is False

    (row,) = snapshots(sync_engine, ctx)
    assert row["id"] == page.snapshot_id
    assert (row["run_id"], row["task_id"]) == (ctx.run_id, ctx.task_id)
    assert row["url"] == row["final_url"] == "https://docs.example.com/t?q=acme-secret"
    assert (row["http_status"], row["content_type"], row["parser"]) == (200, "text/html", "html@1")
    store = BlobStore(files_root)
    assert store.path_for(row["content_sha256"]).read_bytes() == PAGE
    assert store.path_for(row["text_sha256"]).read_text(encoding="utf-8") == PAGE_TEXT
    counted = rows(
        sync_engine,
        "SELECT sha256 FROM platform_files WHERE sha256 = ANY(:s)",
        s=[row["content_sha256"], row["text_sha256"]],
    )
    assert len(counted) == 2

    (event,) = trace_events(sync_engine, ctx)
    assert event["event_type"] == "knowledge.research_snapshot.captured"
    assert (event["actor_type"], event["actor_id"]) == ("agent", "engineering_agent@0.1.0")
    assert (event["subject_type"], event["subject_id"]) == (
        "knowledge.research_snapshot",
        page.snapshot_id,
    )
    assert event["payload"] == {
        "run_id": str(ctx.run_id),
        "task_id": str(ctx.task_id),
        "http_status": 200,
        "content_type": "text/html",
        "content_sha256": row["content_sha256"],
        "text_sha256": row["text_sha256"],
        "byte_count": len(PAGE),
        "char_count": len(PAGE_TEXT),
        "parser": "html@1",
    }
    (call,) = tool_calls(sync_engine, ctx)
    assert (call["tool"], call["outcome"], call["reason"], call["result_count"]) == (
        RESEARCH_PAGE_FETCH,
        "ok",
        None,
        1,
    )
    assert call["http_status"] == 200
    # Privacy: no URL or page text in the trace or the call row.
    for leak in ("acme-secret", "Access tokens", "steal"):
        assert leak not in str(event) and leak not in str(call)


@pytest.mark.parametrize(
    ("response", "reason", "status"),
    [
        (httpx.Response(404, text="gone"), "http_error", 404),
        (
            httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"}),
            "unsupported_content",
            200,
        ),
        (html(b"<script>only()</script>"), "parse_failed", 200),
    ],
)
def test_a_failed_fetch_stores_no_snapshot_and_records_the_reason(
    sync_engine: Engine,
    db_url: str,
    files_root: Path,
    response: httpx.Response,
    reason: str,
    status: int,
) -> None:
    ctx = context(RESEARCH_PAGE_FETCH)
    outcome = gateway_fetch(
        db_url, files_root, Network(lambda r: response), ctx, {"url": "https://example.com/x"}
    )
    assert outcome == ToolFailed(reason, status)  # type: ignore[arg-type]
    assert snapshots(sync_engine, ctx) == []
    (call,) = tool_calls(sync_engine, ctx)
    assert (call["outcome"], call["reason"], call["http_status"]) == ("failed", reason, status)
    assert trace_events(sync_engine, ctx) == []  # failures aren't denials: no trace event


def test_a_denied_fetch_is_traced_and_sends_nothing(
    sync_engine: Engine, db_url: str, files_root: Path
) -> None:
    network = Network(lambda request: html())
    ctx = context(RESEARCH_PAGE_FETCH)
    outcome = gateway_fetch(db_url, files_root, network, ctx, {"url": "http://example.com/"})
    assert outcome == ToolDenied("not_allowlisted")
    unpermitted = context()
    assert gateway_fetch(
        db_url, files_root, network, unpermitted, {"url": "https://example.com/"}
    ) == ToolDenied("tool_not_permitted")
    assert network.requests == []
    (call,) = tool_calls(sync_engine, ctx)
    assert (call["outcome"], call["reason"]) == ("denied", "not_allowlisted")
    (event,) = trace_events(sync_engine, ctx)
    assert event["event_type"] == "platform.tool_call.denied"
    assert event["payload"]["reason"] == "not_allowlisted"
    assert snapshots(sync_engine, ctx) == []


def test_assessments_cite_snapshots_by_span(
    sync_engine: Engine, db_url: str, files_root: Path
) -> None:
    ctx = context(RESEARCH_PAGE_FETCH)
    outcome = gateway_fetch(
        db_url, files_root, Network(lambda r: html()), ctx, {"url": "https://example.com/p"}
    )
    assert isinstance(outcome, ToolResult)
    snapshot_id: UUID = outcome.items[0].snapshot_id
    refs = [
        EvidenceRef(kind="research_snapshot", id=snapshot_id, span=Span(start=0, end=5)),
        EvidenceRef(kind="research_snapshot", id=snapshot_id),
        EvidenceRef(
            kind="research_snapshot",
            id=snapshot_id,
            span=Span(start=0, end=len(PAGE_TEXT)),
        ),
        EvidenceRef(
            kind="research_snapshot",
            id=snapshot_id,
            span=Span(start=3, end=len(PAGE_TEXT) + 1),
        ),
        EvidenceRef(kind="research_snapshot", id=uuid4(), span=Span(start=0, end=1)),
        EvidenceRef(kind="research_snapshot", id=snapshot_id, span=Span(start=4, end=4)),
        EvidenceRef(kind="research_snapshot", id=snapshot_id, version=1),
    ]

    async def scenario() -> list[str | None]:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                return await evidence.check_all(uow, refs)
        finally:
            await engine.dispose()

    reasons = run_async(scenario())
    assert reasons[:3] == [None, None, None]
    assert reasons[3] == f"the span lies outside the snapshot text [0, {len(PAGE_TEXT)})"
    assert reasons[4] == "no such Research Snapshot"
    assert reasons[5] is not None  # an empty span
    assert reasons[6] == "a Research Snapshot has no versions"


def test_snapshots_are_insert_only_for_the_application_role(sync_engine: Engine) -> None:
    for statement in (
        "UPDATE knowledge_research_snapshots SET url = 'x' WHERE false",
        "DELETE FROM knowledge_research_snapshots WHERE false",
    ):
        with pytest.raises(sa.exc.ProgrammingError, match="permission denied"):
            with sync_engine.begin() as conn:
                conn.execute(sa.text(statement))
