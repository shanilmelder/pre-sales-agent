"""Knowledge chunks, embedding, search and the Evidence resolver (Story 3.3) against a real,
migrated Postgres as psa_app, with the real ModelGateway over an `httpx.MockTransport`
standing in for Ollama's `/api/embed` (a deterministic bag-of-words embedding), so every
embedding writes its `platform_model_calls` row. Jobs are claimed only for this test's
Sources. Covers the spec's I/O matrix: embed, model down, empty sections, search filters,
retired and superseded Sources, and resolving good and bad references."""

import hashlib
import json
import logging
import math
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agents.contract import EvidenceRef, Span
from app.modules.knowledge.adapters import chunk_repository
from app.modules.knowledge.application import jobs as knowledge_jobs
from app.modules.knowledge.application import public as knowledge
from app.platform import evidence
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.errors import EvidenceUnresolvableError
from app.platform.jobs import JobContext
from app.platform.jobs import queue as q
from app.platform.jobs.models import PlatformJob
from app.platform.jobs.runner import LeaseSettings, run_job
from app.platform.model_gateway import provider
from app.platform.model_gateway.gateway import ModelGateway
from app.platform.uow import unit_of_work
from tests.auth_tokens import auth_app
from tests.conftest import make_client, run_async
from tests.test_health import assert_problem
from tests.test_knowledge_sources import BASE, _if_match, _tag
from tests.test_role_admin import _admin, _signed_in

SEARCH = "/api/v1/knowledge/search"
PARSE, EMBED = "knowledge.parse_source", "knowledge.embed_source"
LEASE = LeaseSettings(lease_s=30, heartbeat_s=5)
DIMS = 1024
_MINE: list[UUID] = []
_WORD = re.compile(r"[a-z0-9]+")

INSTALL = (
    "# Install guide\n\n## Prerequisites\n\n## Network\n\n"
    "Open port 4711 on the firewall for the conveyor controller.\n\n"
    "## Licences\n\nThe licence server needs a static address.\n"
)
SAFETY = "# Safety\n\nEmergency stop circuits are tested every quarter by the vendor.\n"


def fake_vector(text: str) -> list[float]:
    """A deterministic unit vector: hashed word counts (plus a constant so none is zero)."""
    vector = [0.0] * DIMS
    vector[0] = 0.05
    for word in _WORD.findall(text.lower()):
        digest = hashlib.sha256(word.encode()).digest()
        vector[1 + int.from_bytes(digest[:4], "big") % (DIMS - 1)] += 1.0
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector]


@dataclass
class OllamaStub:
    """`/api/embed` answers with `fake_vector`s unless `down` (HTTP 500) or `mode` says
    otherwise (`timeout`, `short`: a wrong-length vector, `nan`); records every request."""

    down: bool = False
    mode: str = "ok"
    requests: int = 0
    texts: int = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "bge-m3", "digest": "sha256:e"}]})
        assert request.url.path == "/api/embed", request.url.path
        self.requests += 1
        if self.down:
            return httpx.Response(500, json={"error": "model not loaded"})
        if self.mode == "timeout":
            raise httpx.ReadTimeout("slow", request=request)
        body = json.loads(request.content)
        if self.mode in ("short", "nan"):
            bad = [0.1] * (DIMS - 1) if self.mode == "short" else [float("nan")] * DIMS
            content = json.dumps({"embeddings": [bad for _ in body["input"]]})
            return httpx.Response(200, content=content.encode())
        assert body["model"] == "bge-m3"
        self.texts += len(body["input"])
        return httpx.Response(
            200,
            json={
                "embeddings": [fake_vector(t) for t in body["input"]],
                "prompt_eval_count": 7 * len(body["input"]),
            },
        )


def _gateway_settings(db_url: str) -> Settings:
    return Settings(database_url=db_url, ollama_url="http://ollama.test")


@pytest.fixture
def ollama() -> OllamaStub:
    return OllamaStub()


@pytest.fixture
def storage_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "files"
    monkeypatch.setenv("PSA_STORAGE_DIR", str(root))
    monkeypatch.setattr(
        knowledge_jobs,
        "parse_settings",
        lambda: Settings(
            storage_dir=root,
            parse_timeout_s=60,
            knowledge_chunk_chars=400,
            knowledge_chunk_overlap_chars=80,
        ),
    )
    return root


@pytest.fixture(autouse=True)
def _own_sources() -> Iterator[None]:
    _MINE.clear()
    yield
    _MINE.clear()


@pytest.fixture
def client(db_url: str, storage_dir: Path, ollama: OllamaStub) -> Iterator[TestClient]:
    app = auth_app(db_url)
    app.state.model_gateway = ModelGateway(
        _gateway_settings(db_url), app.state.engine, transport=httpx.MockTransport(ollama.handle)
    )
    with make_client(app) as c:
        yield c


# --- helpers ----------------------------------------------------------------------------------


def _register(
    client: TestClient,
    headers: dict[str, str],
    tags: list[str],
    text: str,
    *,
    product: str = "AutoStore",
    product_version: str = "2.1",
    owner_id: UUID | None = None,
) -> dict[str, Any]:
    params: list[tuple[str, str]] = [
        ("title", f"Guide {uuid4().hex[:6]}"),
        ("product", product),
        ("product_version", product_version),
        *[("integration_type_ids", t) for t in tags],
        *([("owner_id", str(owner_id))] if owner_id else []),
    ]
    data = (text + f"\n<!-- {uuid4()} -->\n").encode()  # unique: `platform_files` is shared
    resp = client.post(
        BASE,
        headers=headers,
        params=params,
        files={"file": ("guide.md", data, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    source: dict[str, Any] = resp.json()
    _MINE.append(UUID(source["id"]))
    return source


async def _claim_mine(engine: AsyncEngine) -> q.ClaimedJob | None:
    t = PlatformJob
    eligible = sa.or_(
        t.status.in_(("queued", "failed_retrying")),
        sa.and_(t.status == "running", t.lease_expires_at < sa.func.now()),
    )
    next_id = (
        sa.select(t.id)
        .where(
            t.job_type.in_((PARSE, EMBED)),
            t.payload["source_id"].astext.in_([str(i) for i in _MINE]),
            eligible,
        )
        .order_by(t.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    statement = (
        sa.update(t)
        .where(t.id == next_id)
        .values(
            status="running",
            lease_owner="test-worker",
            lease_expires_at=sa.func.now() + timedelta(seconds=LEASE.lease_s),
            attempts=t.attempts + 1,
            run_after=sa.func.now(),
            updated_at=sa.func.now(),
        )
        .returning(t.id, t.job_type, t.payload, t.attempts, t.opportunity_id)
    )
    async with unit_of_work(engine) as uow:
        row = (await uow.session.execute(statement)).one_or_none()
    if row is None:
        return None
    return q.ClaimedJob(
        id=row.id,
        job_type=row.job_type,
        payload=row.payload,
        attempts=row.attempts,
        opportunity_id=row.opportunity_id,
        lease_owner="test-worker",
    )


def _drain(db_url: str, ollama: OllamaStub, *, max_runs: int = 20) -> list[tuple[str, str]]:
    """Run this test's parse and embed jobs (retries at once) with a real gateway."""

    async def scenario() -> list[tuple[str, str]]:
        engine = create_engine(Settings(database_url=db_url))
        gateway = ModelGateway(
            _gateway_settings(db_url), engine, transport=httpx.MockTransport(ollama.handle)
        )
        provider.install(gateway)
        outcomes: list[tuple[str, str]] = []
        try:
            for _ in range(max_runs):
                job = await _claim_mine(engine)
                if job is None:
                    break
                outcomes.append((job.job_type, await run_job(engine, job, LEASE)))
        finally:
            provider.install(None)
            await gateway.aclose()
            await engine.dispose()
        return outcomes

    return run_async(scenario())


def _rows(engine: Engine, sql: str, **params: Any) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(sa.text(sql), params).mappings()]


def _chunks(engine: Engine, source_id: str, version: int = 1) -> list[dict[str, Any]]:
    return _rows(
        engine,
        "SELECT id, ordinal, text, start_offset, end_offset, product, product_version, "
        "integration_type_ids, embedding_model, embedding_dims, vector_dims(embedding) AS dims "
        "FROM knowledge_chunks WHERE source_id = :s AND version = :v ORDER BY ordinal",
        s=source_id,
        v=version,
    )


def _text(engine: Engine, storage_dir: Path, source_id: str, version: int = 1) -> str:
    (row,) = _rows(
        engine,
        "SELECT text_sha256 FROM knowledge_source_parses WHERE source_id = :s AND version = :v",
        s=source_id,
        v=version,
    )
    sha = row["text_sha256"]
    return (storage_dir / "sha256" / sha[:2] / sha[2:4] / sha).read_text(encoding="utf-8")


def _source(client: TestClient, headers: dict[str, str], source_id: str) -> dict[str, Any]:
    resp = client.get(f"{BASE}/{source_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _app_logs(caplog: pytest.LogCaptureFixture) -> str:
    """Everything the app logged (not the test's own HTTP client, which logs its URLs)."""
    return "\n".join(
        r.getMessage() + json.dumps(r.__dict__, default=str)
        for r in caplog.records
        if r.name.startswith("app")
    )


def _search(client: TestClient, headers: dict[str, str], **params: Any) -> httpx.Response:
    return client.get(SEARCH, headers=headers, params=params)


def _ready(
    client: TestClient, db_url: str, ollama: OllamaStub, admin: dict[str, str], tag: str, **kw: Any
) -> dict[str, Any]:
    source = _register(client, admin, [tag], kw.pop("text", INSTALL), **kw)
    _drain(db_url, ollama)
    assert _source(client, admin, source["id"])["embed"] == {"status": "ready", "error_code": None}
    return source


# --- embed --------------------------------------------------------------------------------------


def test_a_parsed_version_is_chunked_embedded_and_ready(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    storage_dir: Path,
    ollama: OllamaStub,
    caplog: pytest.LogCaptureFixture,
) -> None:
    admin, _ = _admin(client, "Knowledge Admin")
    tag = _tag(client, admin)
    source = _register(client, admin, [tag["id"]], INSTALL)
    assert source["embed"] is None  # not parsed yet

    caplog.set_level(logging.DEBUG)
    assert _drain(db_url, ollama) == [(PARSE, "succeeded"), (EMBED, "succeeded")]

    view = _source(client, admin, source["id"])
    assert view["parse"]["status"] == "parsed"
    assert view["embed"] == {"status": "ready", "error_code": None}
    text = _text(sync_engine, storage_dir, source["id"])
    chunks = _chunks(sync_engine, source["id"])
    assert chunks, "no chunks"
    for row in chunks:
        assert text[row["start_offset"] : row["end_offset"]] == row["text"]
        assert row["text"].strip()
        assert (row["embedding_model"], row["embedding_dims"], row["dims"]) == (
            "bge-m3",
            DIMS,
            DIMS,
        )
        assert (row["product"], row["product_version"]) == ("AutoStore", "2.1")
        assert row["integration_type_ids"] == [UUID(tag["id"])]
    # "## Prerequisites" has no body: it never forms a chunk of its own.
    assert not any(row["text"].strip() == "## Prerequisites" for row in chunks)

    (embed_row,) = _rows(
        sync_engine,
        "SELECT * FROM knowledge_source_embeds WHERE source_id = :s",
        s=source["id"],
    )
    assert (embed_row["chunk_count"], embed_row["model"]) == (len(chunks), "bge-m3")
    (event,) = _rows(
        sync_engine,
        "SELECT * FROM platform_trace_events WHERE subject_id = :s "
        "AND event_type = 'knowledge.source.embedded'",
        s=source["id"],
    )
    assert event["payload"] == {"version": 1, "chunk_count": len(chunks), "model": "bge-m3"}
    assert (event["actor_type"], event["actor_id"]) == ("system", EMBED)

    calls = _rows(
        sync_engine,
        "SELECT * FROM platform_model_calls WHERE agent_id = :a AND created_at > now() - "
        "interval '5 minutes' ORDER BY created_at DESC LIMIT 1",
        a=EMBED,
    )
    assert calls and calls[0]["profile"] == "bge-m3" and calls[0]["priority"] == "background"
    assert calls[0]["outcome"] == "ok" and calls[0]["input_tokens"] == 7 * len(chunks)

    logged = _app_logs(caplog)
    assert "4711" not in logged and "firewall" not in logged  # no chunk text in any log
    assert _drain(db_url, ollama) == []  # idempotent: nothing left


def test_versions_are_insert_only_and_old_chunks_keep_resolving(
    client: TestClient, sync_engine: Engine, db_url: str, ollama: OllamaStub
) -> None:
    admin, _ = _admin(client, "Knowledge Admin")
    tag = _tag(client, admin)
    source = _ready(client, db_url, ollama, admin, tag["id"])
    old = _chunks(sync_engine, source["id"], 1)

    resp = client.post(
        f"{BASE}/{source['id']}/versions",
        headers={**admin, **_if_match(source["row_version"])},
        params={"product_version": "3.0"},
        files={"file": ("v2.md", (SAFETY + str(uuid4())).encode(), "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    _drain(db_url, ollama)
    assert _chunks(sync_engine, source["id"], 1) == old  # untouched
    assert _chunks(sync_engine, source["id"], 2)

    async def resolve() -> None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                await knowledge.resolve_evidence(
                    uow,
                    [EvidenceRef(kind="knowledge_chunk", id=old[0]["id"], version=1)],
                )
        finally:
            await engine.dispose()

    run_async(resolve())


# --- model down, retry and the Embed action ----------------------------------------------------


def _attempt(db_url: str, ollama: OllamaStub, source_id: str, attempt: int) -> str | None:
    async def scenario() -> str | None:
        engine = create_engine(Settings(database_url=db_url))
        gateway = ModelGateway(
            _gateway_settings(db_url), engine, transport=httpx.MockTransport(ollama.handle)
        )
        provider.install(gateway)
        ctx = JobContext(
            job_id=uuid4(),
            job_type=EMBED,
            attempt=attempt,
            max_attempts=3,
            opportunity_id=None,
            engine=engine,
        )
        try:
            await knowledge_jobs.embed_source(
                ctx, knowledge_jobs.EmbedKnowledgeSource(source_id=UUID(source_id), version=1)
            )
        except Exception as exc:
            return type(exc).__name__
        finally:
            provider.install(None)
            await gateway.aclose()
            await engine.dispose()
        return None

    return run_async(scenario())


def test_model_down_fails_after_the_last_attempt_and_can_be_retried(
    client: TestClient, sync_engine: Engine, db_url: str, ollama: OllamaStub
) -> None:
    admin, _ = _admin(client, "Knowledge Admin")
    tag = _tag(client, admin)
    good = _ready(client, db_url, ollama, admin, tag["id"], text=SAFETY)
    bad = _register(client, admin, [tag["id"]], INSTALL)
    assert _drain(db_url, ollama, max_runs=1) == [(PARSE, "succeeded")]  # its embed job waits
    ollama.down = True

    assert _attempt(db_url, ollama, bad["id"], 1) == "ModelUnavailableError"
    assert _source(client, admin, bad["id"])["embed"]["status"] == "embedding"  # retried
    assert _attempt(db_url, ollama, bad["id"], 3) == "ModelUnavailableError"
    view = _source(client, admin, bad["id"])
    assert view["embed"] == {"status": "failed", "error_code": "model_unavailable"}
    assert _chunks(sync_engine, bad["id"]) == []  # no partial chunks
    assert _source(client, admin, good["id"])["embed"]["status"] == "ready"  # unaffected
    failed_calls = _rows(
        sync_engine,
        "SELECT outcome, error_code FROM platform_model_calls WHERE agent_id = :a "
        "AND outcome = 'error' AND created_at > now() - interval '5 minutes'",
        a=EMBED,
    )
    assert failed_calls and failed_calls[0]["error_code"] == "http_500"

    resp = client.post(f"{BASE}/{good['id']}/embed", headers=admin)
    assert_problem(resp.json(), 409, "embed_not_failed")
    ollama.down = False
    resp = client.post(f"{BASE}/{bad['id']}/embed", headers=admin)
    assert resp.status_code == 202, resp.text
    assert resp.json()["embed"] == {"status": "queued", "error_code": None}
    (retried,) = _rows(
        sync_engine,
        "SELECT payload FROM platform_trace_events WHERE subject_id = :s "
        "AND event_type = 'knowledge.source.embed_retried'",
        s=bad["id"],
    )
    assert retried["payload"] == {"version": 1, "error_code": "model_unavailable"}
    _drain(db_url, ollama)
    assert _source(client, admin, bad["id"])["embed"]["status"] == "ready"
    assert _chunks(sync_engine, bad["id"])


def test_a_version_parsed_before_embedding_existed_can_be_embedded(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    ollama: OllamaStub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_embed(*args: Any) -> bool:
        return False  # as before Story 3.3: parsing queued nothing

    admin, _ = _admin(client, "Knowledge Admin")
    tag = _tag(client, admin)
    source = _register(client, admin, [tag["id"]], INSTALL)
    with monkeypatch.context() as m:
        m.setattr(knowledge_jobs.chunk_repository, "queue_embed", no_embed)
        assert _drain(db_url, ollama) == [(PARSE, "succeeded")]
    view = _source(client, admin, source["id"])
    assert (view["parse"]["status"], view["embed"]) == ("parsed", None)
    (version,) = client.get(f"{BASE}/{source['id']}/versions", headers=admin).json()["items"]
    assert version["embed"] is None

    expert, _ = _signed_in(client, "Expert", "engineering_reviewer")
    assert_problem(
        client.post(f"{BASE}/{source['id']}/embed", headers=expert).json(), 403, "forbidden"
    )
    resp = client.post(f"{BASE}/{source['id']}/embed", headers=admin)
    assert resp.status_code == 202, resp.text
    assert resp.json()["embed"] == {"status": "queued", "error_code": None}
    again = client.post(f"{BASE}/{source['id']}/embed", headers=admin)
    assert_problem(again.json(), 409, "embed_not_failed")
    assert _drain(db_url, ollama) == [(EMBED, "succeeded")]
    assert _source(client, admin, source["id"])["embed"]["status"] == "ready"


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        ("timeout", "model_timeout"),
        ("short", "model_bad_output"),
        ("nan", "model_bad_output"),
        ("text", "text_missing"),
        ("crash", "internal_error"),
    ],
)
def test_the_final_attempt_records_why_embedding_failed(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    storage_dir: Path,
    ollama: OllamaStub,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    code: str,
) -> None:
    admin, _ = _admin(client, "Knowledge Admin")
    tag = _tag(client, admin)
    source = _register(client, admin, [tag["id"]], INSTALL)
    assert _drain(db_url, ollama, max_runs=1) == [(PARSE, "succeeded")]
    if failure == "text":
        for blob in storage_dir.rglob("*"):
            if blob.is_file():
                blob.unlink()
    elif failure == "crash":

        def crash(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("boom")

        monkeypatch.setattr(knowledge_jobs, "chunk_text", crash)
    else:
        ollama.mode = failure

    assert _attempt(db_url, ollama, source["id"], 3) is not None
    assert _source(client, admin, source["id"])["embed"] == {"status": "failed", "error_code": code}
    assert _chunks(sync_engine, source["id"]) == []


def test_the_owner_may_embed_their_source(
    client: TestClient, db_url: str, ollama: OllamaStub, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_embed(*args: Any) -> bool:
        return False

    admin, _ = _admin(client, "Knowledge Admin")
    tag = _tag(client, admin)
    owner, owner_id = _signed_in(client, "Owner", "engineering_reviewer")
    source = _register(client, admin, [tag["id"]], INSTALL, owner_id=owner_id)
    with monkeypatch.context() as m:
        m.setattr(knowledge_jobs.chunk_repository, "queue_embed", no_embed)
        _drain(db_url, ollama)
    resp = client.post(f"{BASE}/{source['id']}/embed", headers=owner)
    assert resp.status_code == 202, resp.text
    assert resp.json()["embed"] == {"status": "queued", "error_code": None}


def test_a_stuck_embedding_can_be_retried_but_a_live_one_cannot(
    client: TestClient, sync_engine: Engine, db_url: str, ollama: OllamaStub
) -> None:
    admin, _ = _admin(client, "Knowledge Admin")
    tag = _tag(client, admin)
    source = _register(client, admin, [tag["id"]], INSTALL)
    assert _drain(db_url, ollama, max_runs=1) == [(PARSE, "succeeded")]

    def set_embedding(age_s: float) -> None:
        with sync_engine.begin() as conn:
            conn.execute(
                sa.text(
                    "UPDATE knowledge_source_embeds SET status = 'embedding', "
                    "updated_at = now() - make_interval(secs => :a) WHERE source_id = :s"
                ),
                {"a": age_s, "s": source["id"]},
            )

    set_embedding(0)  # its job is still running
    resp = client.post(f"{BASE}/{source['id']}/embed", headers=admin)
    assert_problem(resp.json(), 409, "embed_not_failed")

    set_embedding(knowledge_jobs.embed_stale_after_s() + 60)  # its job died unrecorded
    resp = client.post(f"{BASE}/{source['id']}/embed", headers=admin)
    assert resp.status_code == 202, resp.text
    assert resp.json()["embed"] == {"status": "queued", "error_code": None}
    _drain(db_url, ollama)
    assert _source(client, admin, source["id"])["embed"]["status"] == "ready"


def test_embedding_an_unparsed_or_retired_source_is_409(
    client: TestClient, db_url: str, ollama: OllamaStub
) -> None:
    admin, _ = _admin(client, "Knowledge Admin")
    tag = _tag(client, admin)
    queued = _register(client, admin, [tag["id"]], INSTALL)
    assert_problem(
        client.post(f"{BASE}/{queued['id']}/embed", headers=admin).json(), 409, "embed_not_failed"
    )
    resp = client.post(
        f"{BASE}/{queued['id']}/retire",
        headers={**admin, **_if_match(queued["row_version"])},
        json={"reason": "Old"},
    )
    assert resp.status_code == 200, resp.text
    assert_problem(
        client.post(f"{BASE}/{queued['id']}/embed", headers=admin).json(),
        409,
        "knowledge_source_retired",
    )


# --- search -------------------------------------------------------------------------------------


def test_search_returns_citable_passages_with_filters(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    storage_dir: Path,
    ollama: OllamaStub,
    caplog: pytest.LogCaptureFixture,
) -> None:
    admin, _ = _admin(client, "Knowledge Admin")
    tag, other_tag = _tag(client, admin), _tag(client, admin)
    product = f"Prod-{uuid4().hex[:8]}"
    install = _ready(client, db_url, ollama, admin, tag["id"], product=product)
    safety = _ready(
        client,
        db_url,
        ollama,
        admin,
        other_tag["id"],
        text=SAFETY,
        product=product,
        product_version="9.9",
    )
    reader, _ = _signed_in(client, "Sales Person", "sales_representative")

    caplog.set_level(logging.DEBUG)
    resp = _search(client, reader, q="Which firewall port does the conveyor need?", product=product)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["model"] == "bge-m3"
    top = body["items"][0]
    assert top["source_id"] == install["id"] and "4711" in top["text"]
    assert (top["version"], top["stale"], top["product_version"]) == (1, False, "2.1")
    assert top["source_title"] == install["title"]
    ev = top["evidence"]
    assert (ev["kind"], ev["version"]) == ("knowledge_chunk", 1)
    text = _text(sync_engine, storage_dir, install["id"])
    assert text[ev["span"]["start"] : ev["span"]["end"]] == top["text"]
    distances = [i["distance"] for i in body["items"]]
    assert distances == sorted(distances)
    logged = _app_logs(caplog)
    assert "firewall" not in logged and "conveyor" not in logged  # the query is never logged

    def ids(**params: Any) -> set[str]:
        resp = _search(client, reader, q="port vendor licence", product=product, **params)
        assert resp.status_code == 200, resp.text
        return {i["source_id"] for i in resp.json()["items"]}

    assert ids() == {install["id"], safety["id"]}
    assert ids(integration_type_id=other_tag["id"]) == {safety["id"]}
    assert ids(product_version="9.9") == {safety["id"]}
    # A blank filter is no filter, not one that matches nothing.
    assert {
        i["source_id"]
        for i in _search(
            client, reader, q="port vendor licence", product=product, product_version="  "
        ).json()["items"]
    } == {install["id"], safety["id"]}
    assert ids(k=1) <= {install["id"], safety["id"]} and len(ids(k=1)) == 1
    resp = _search(client, reader, q="port", product=f"none-{uuid4().hex}")
    assert resp.json()["items"] == []

    query_calls = _rows(
        sync_engine,
        "SELECT profile, priority FROM platform_model_calls WHERE agent_id = 'knowledge.search' "
        "AND created_at > now() - interval '5 minutes'",
    )
    assert query_calls and query_calls[0] == {"profile": "bge-m3", "priority": "interactive"}


def test_search_validation_and_authorization(client: TestClient) -> None:
    reader, _ = _signed_in(client, "Commercial", "commercial")
    for params in ({"q": "  "}, {"q": "x" * 2001}, {"q": "port", "k": 0}, {"q": "port", "k": 51}):
        resp = _search(client, reader, **params)
        assert resp.status_code == 422, (params, resp.text)
        assert_problem(resp.json(), 422, "validation_error")
    no_role, _ = _signed_in(client, "Nobody")
    assert_problem(_search(client, no_role, q="port").json(), 403, "forbidden")
    assert_problem(client.get(SEARCH, params={"q": "port"}).json(), 401, "token_missing")


def test_search_is_503_when_the_model_is_down(client: TestClient, ollama: OllamaStub) -> None:
    reader, _ = _signed_in(client, "Commercial", "commercial")
    ollama.down = True
    resp = _search(client, reader, q="port")
    assert_problem(resp.json(), 503, "model_unavailable")


def test_retired_and_superseded_sources_are_excluded(
    client: TestClient, db_url: str, ollama: OllamaStub
) -> None:
    admin, _ = _admin(client, "Knowledge Admin")
    tag = _tag(client, admin)
    product = f"Prod-{uuid4().hex[:8]}"
    retired = _ready(client, db_url, ollama, admin, tag["id"], product=product)
    superseded = _ready(client, db_url, ollama, admin, tag["id"], product=product)

    def found() -> list[tuple[str, int]]:
        resp = _search(client, admin, q="firewall port 4711", product=product, k=50)
        assert resp.status_code == 200, resp.text
        return [(i["source_id"], i["version"]) for i in resp.json()["items"]]

    assert {s for s, _ in found()} == {retired["id"], superseded["id"]}
    resp = client.post(
        f"{BASE}/{retired['id']}/retire",
        headers={**admin, **_if_match(retired["row_version"])},
        json={"reason": "Replaced"},
    )
    assert resp.status_code == 200, resp.text
    assert {s for s, _ in found()} == {superseded["id"]}

    resp = client.post(
        f"{BASE}/{superseded['id']}/versions",
        headers={**admin, **_if_match(superseded["row_version"])},
        params={"product_version": "3.0"},
        files={"file": ("v2.md", (INSTALL + str(uuid4())).encode(), "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    assert found() == []  # v1 is superseded and v2 isn't Ready yet
    _drain(db_url, ollama)
    assert found() and all(hit == (superseded["id"], 2) for hit in found())


# --- the Evidence resolver ----------------------------------------------------------------------


def _check(db_url: str, refs: list[EvidenceRef]) -> list[str | None]:
    async def scenario() -> list[str | None]:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                return await evidence.check_all(uow, refs)
        finally:
            await engine.dispose()

    return run_async(scenario())


def _resolve(db_url: str, refs: list[EvidenceRef]) -> Exception | None:
    async def scenario() -> Exception | None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                await evidence.resolve_all(uow, refs)
        except EvidenceUnresolvableError as exc:
            return exc
        finally:
            await engine.dispose()
        return None

    return run_async(scenario())


def test_the_resolver_accepts_good_refs_and_rejects_bad_ones(
    client: TestClient, sync_engine: Engine, db_url: str, ollama: OllamaStub
) -> None:
    admin, _ = _admin(client, "Knowledge Admin")
    tag = _tag(client, admin)
    source = _ready(client, db_url, ollama, admin, tag["id"])
    chunk = _chunks(sync_engine, source["id"])[0]
    cid, start, end = chunk["id"], chunk["start_offset"], chunk["end_offset"]

    def ref(**kw: Any) -> EvidenceRef:
        fields: dict[str, Any] = {"kind": "knowledge_chunk", "id": cid, "version": 1}
        return EvidenceRef(**(fields | kw))

    good = [ref(), ref(span=Span(start=start, end=end)), ref(span=Span(start=start + 1, end=end))]
    assert _check(db_url, good) == [None, None, None]
    assert _resolve(db_url, good) is None

    unknown = uuid4()
    bad = [
        ref(id=unknown),
        ref(version=2),
        ref(version=None),
        ref(span=Span(start=start, end=end + 1)),
        ref(span=Span(start=max(start - 1, 0), end=end))
        if start
        else ref(span=Span(start=0, end=0)),
        EvidenceRef(kind="no_such_kind", id=cid),
    ]
    reasons = _check(db_url, bad)
    assert all(reason is not None for reason in reasons), reasons
    exc = _resolve(db_url, [*good, bad[0]])
    assert isinstance(exc, EvidenceUnresolvableError)
    assert str(unknown) in str(exc.detail)  # the error names the reference
    assert exc.status == 422 and exc.code == "evidence_unresolvable"


def test_search_sql_and_the_index_use_the_same_cast_and_filter(sync_engine: Engine) -> None:
    (index,) = _rows(
        sync_engine,
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_knowledge_chunks_embedding_bge_m3'",
    )
    definition = index["indexdef"]
    assert "USING hnsw" in definition and "vector(1024)" in definition
    assert "WHERE (embedding_model = 'bge-m3'::text)" in definition
    sql = chunk_repository.search_sql(
        model="bge-m3", dims=1024, product=True, tag=True, product_version=True
    )
    assert "ORDER BY c.embedding::vector(1024) <=>" in sql
    assert "c.embedding_model = 'bge-m3'" in sql
    with pytest.raises(ValueError):
        chunk_repository.search_sql(
            model="x'; DROP TABLE y; --", dims=1024, product=False, tag=False, product_version=False
        )


def test_the_worker_loads_the_embed_job() -> None:
    from app import main_worker
    from app.platform.jobs import REGISTRY

    main_worker.load_job_types()
    assert REGISTRY[EMBED].priority == "background"


def test_embed_profile_and_chunk_settings_are_validated() -> None:
    with pytest.raises(ValueError):
        Settings(model_profile_embed="nope")
    with pytest.raises(ValueError):
        Settings(knowledge_chunk_chars=400, knowledge_chunk_overlap_chars=200)
