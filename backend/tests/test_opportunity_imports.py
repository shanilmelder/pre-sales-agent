"""Opportunity imports (Story 1.7, import from file) against a real, migrated Postgres as
psa_app, with a fake ModelGateway and the real parse child process.

Covers the spec's I/O matrix: the demo email and transcript, a stated deadline, create
(the file becomes the first Source and its parse is queued), an unreadable file, a bad type
and an oversized file (415 / 413, nothing stored or queued), reuse (409) and another user's
import (404), expiry (410), sales representatives (403), model failures, the trace, logs and
the table grants.

Reuses the fixtures of `test_intake_extraction.py`: jobs are scheduled a day ahead so no
other claimer takes them; `drain_imports` runs only the current test's import jobs.
"""

import asyncio
import logging
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.agents.opportunity_intake_agent.schema import OpportunityIntakeOutput
from app.modules.opportunities.application import imports
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.jobs import JobContext
from app.platform.jobs import queue as q
from app.platform.jobs.runner import run_job
from app.platform.model_gateway.port import (
    ModelOutputInvalidError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from app.platform.storage import BlobStore
from app.platform.uow import unit_of_work
from tests import test_intake_extraction as extraction_tests
from tests.auth_tokens import auth_app
from tests.conftest import make_client, run_async
from tests.test_health import assert_problem
from tests.test_intake_extraction import HIDDEN, LEASE, MINE, PARSE, FakeGateway
from tests.test_opportunities import PSE, _body, _user

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client

IMPORTS = "/api/v1/opportunity-imports"
OPPORTUNITIES = "/api/v1/opportunities"
READ = imports.READ_IMPORT
FIXTURES = Path(__file__).resolve().parent / "fixtures"
EMAIL = (FIXTURES / "imports" / "02-email-it-integration-follow-up.eml").read_bytes()
TRANSCRIPT = (FIXTURES / "imports" / "01-discovery-call-teams-transcript.vtt").read_bytes()
CORRUPT_PDF = (FIXTURES / "sources" / "corrupt.pdf").read_bytes()
MY_IMPORTS: list[str] = []
"""The current test's imports: `drain_imports` runs only their jobs."""


@pytest.fixture(autouse=True)
def _import_jobs(monkeypatch: pytest.MonkeyPatch, storage_dir: Path) -> Iterator[None]:
    real_enqueue = imports.enqueue

    async def hidden_enqueue(uow: Any, payload: Any, **kwargs: Any) -> UUID:
        kwargs["run_after"] = datetime.now(UTC) + HIDDEN
        return await real_enqueue(uow, payload, **kwargs)

    monkeypatch.setattr(imports, "enqueue", hidden_enqueue)
    monkeypatch.setattr(
        imports,
        "import_settings",
        lambda: Settings(
            storage_dir=storage_dir, parse_timeout_s=60, model_profile_chat="demo-chat"
        ),
    )
    MY_IMPORTS.clear()
    yield
    _retire(MY_IMPORTS)
    MY_IMPORTS.clear()


def _retire(import_ids: list[str]) -> None:
    """Retire import jobs a test left waiting, so no worker runs them later."""
    if not import_ids:
        return
    engine = sa.create_engine(_db_url())
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "UPDATE platform_jobs SET status = 'dead', last_error = 'test: not run' "
                    "WHERE job_type = :t AND status IN ('queued', 'failed_retrying') "
                    "AND payload->>'import_id' = ANY(:i)"
                ),
                {"t": READ, "i": import_ids},
            )
    finally:
        engine.dispose()


def _db_url() -> str:
    return os.environ["PSA_DATABASE_URL"]


# --- helpers --------------------------------------------------------------------------------


def _upload(client: TestClient, headers: dict[str, str], name: str, data: bytes) -> Any:
    return client.post(
        IMPORTS, headers=headers, files={"file": (name, data, "application/octet-stream")}
    )


def _import(client: TestClient, headers: dict[str, str], name: str, data: bytes) -> dict[str, Any]:
    resp = _upload(client, headers, name, data)
    assert resp.status_code == 202, resp.text
    body: dict[str, Any] = resp.json()
    MY_IMPORTS.append(body["id"])
    return body


def drain_imports(db_url: str, max_runs: int = 10) -> list[str]:
    """Run this test's import jobs until none is left; retries run at once."""

    async def claim(engine: Any) -> q.ClaimedJob | None:
        async with unit_of_work(engine) as uow:
            row = (
                await uow.session.execute(
                    sa.text(
                        "UPDATE platform_jobs SET status = 'running', lease_owner = 'test-worker', "
                        "lease_expires_at = now() + interval '30 seconds', "
                        "attempts = attempts + 1, updated_at = now() "
                        "WHERE id = (SELECT id FROM platform_jobs WHERE job_type = :t "
                        "AND status IN ('queued', 'failed_retrying') "
                        "AND payload->>'import_id' = ANY(:i) ORDER BY created_at LIMIT 1 "
                        "FOR UPDATE SKIP LOCKED) "
                        "RETURNING id, job_type, payload, attempts, opportunity_id"
                    ),
                    {"t": READ, "i": list(MY_IMPORTS)},
                )
            ).one_or_none()
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

    async def scenario() -> list[str]:
        engine = create_engine(Settings(database_url=db_url))
        outcomes: list[str] = []
        try:
            for _ in range(max_runs):
                job = await claim(engine)
                if job is None:
                    break
                outcomes.append(await run_job(engine, job, LEASE))
        finally:
            await engine.dispose()
        return outcomes

    return run_async(scenario())


def rows(engine: Engine, sql: str, **params: Any) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(sa.text(sql), params).mappings()]


def import_row(engine: Engine, import_id: str) -> dict[str, Any]:
    (row,) = rows(engine, "SELECT * FROM opportunities_imports WHERE id = :i", i=import_id)
    return row


def import_jobs(engine: Engine, import_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM platform_jobs WHERE job_type = :t AND payload->>'import_id' = :i",
        t=READ,
        i=import_id,
    )


def suggested(value: str | None, quote: str | None) -> dict[str, str | None]:
    return {"value": value, "quote": quote}


def reply(**fields: Any) -> OpportunityIntakeOutput:
    data: dict[str, Any] = {
        "title": suggested(None, None),
        "customer_name": suggested(None, None),
        "industry": suggested(None, None),
        "products": [],
        "target_proposal_date": suggested(None, None),
    }
    data.update(fields)
    return OpportunityIntakeOutput.model_validate(data)


EMAIL_REPLY = reply(
    title=suggested("Riverside DC systems and security", "Riverside DC - systems and security"),
    customer_name=suggested("Meridian Fresh Foods", "IT Manager, Meridian Fresh Foods"),
    industry=suggested("Food distribution", "Invented quote that is not in the email"),
    products=[
        {"value": "SAP integration", "quote": "goods-issue confirmations back into SAP"},
        {"value": "WMS", "quote": "your system replacing the WMS"},
    ],
)


def _engineer(client: TestClient, engine: Engine) -> dict[str, str]:
    headers, _ = _user(client, engine, "Import Person", PSE)
    return headers


# --- the demo email and transcript ----------------------------------------------------------


def test_the_demo_email_suggests_the_customer_and_fields_with_quotes(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers = _engineer(client, sync_engine)
    created = _import(client, headers, "follow-up.eml", EMAIL)
    assert created["status"] == "queued"
    assert (created["filename"], created["size_bytes"]) == ("follow-up.eml", len(EMAIL))
    assert (created["suggestions"], created["error_code"]) == (None, None)
    (job,) = import_jobs(sync_engine, created["id"])
    assert job["payload"] == {"import_id": created["id"]}
    assert (job["priority"], job["opportunity_id"]) == (0, None)  # interactive

    gateway.replies = [EMAIL_REPLY]
    assert drain_imports(db_url) == ["succeeded"]

    resp = client.get(f"{IMPORTS}/{created['id']}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "succeeded"
    suggestions = body["suggestions"]
    assert suggestions["customer_name"] == {
        "value": "Meridian Fresh Foods",
        "quote": "IT Manager, Meridian Fresh Foods",
    }
    assert suggestions["title"]["value"] == "Riverside DC systems and security"
    assert suggestions["industry"] is None  # its quote isn't in the email: dropped
    assert [p["value"] for p in suggestions["products"]] == ["SAP integration", "WMS"]
    assert suggestions["target_proposal_date"] is None

    (request,) = gateway.requests
    assert request.caller.agent_id == "opportunity_intake_agent"
    assert request.caller.run_id == UUID(created["id"])
    assert request.priority == "interactive"
    system, user = request.messages
    assert "Meridian Fresh Foods" not in system.content
    assert "<<<FILE token=" in user.content and "IT Manager, Meridian Fresh Foods" in user.content


def test_the_demo_transcript_suggests_fields_from_the_call(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers = _engineer(client, sync_engine)
    created = _import(client, headers, "discovery.vtt", TRANSCRIPT)
    gateway.replies = [
        reply(
            title=suggested("Riverside DC automation", "Riverside distribution centre"),
            customer_name=suggested(
                "Meridian Fresh Foods", "I run operations at Meridian Fresh Foods"
            ),
            products=[
                {"value": "Goods-to-person picking", "quote": "a goods-to-person picking system"}
            ],
        )
    ]
    assert drain_imports(db_url) == ["succeeded"]
    body = client.get(f"{IMPORTS}/{created['id']}", headers=headers).json()
    assert body["suggestions"]["customer_name"]["value"] == "Meridian Fresh Foods"
    assert body["suggestions"]["products"][0]["value"] == "Goods-to-person picking"


def test_a_stated_deadline_becomes_the_target_proposal_date(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers = _engineer(client, sync_engine)
    due = datetime.now(UTC).date() + timedelta(days=17)
    line = f"Proposal due: {due.day} {due.strftime('%B %Y')}."
    created = _import(client, headers, "terms.txt", f"Timeline\n- {line}\n{uuid4()}\n".encode())
    gateway.replies = [reply(target_proposal_date=suggested(due.isoformat(), line))]
    assert drain_imports(db_url) == ["succeeded"]
    body = client.get(f"{IMPORTS}/{created['id']}", headers=headers).json()
    assert body["suggestions"]["target_proposal_date"] == {"value": due.isoformat(), "quote": line}


# --- create ---------------------------------------------------------------------------------


def test_create_makes_the_file_the_first_source_and_starts_parsing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway, storage_dir: Path
) -> None:
    headers = _engineer(client, sync_engine)
    created = _import(client, headers, "follow-up.eml", EMAIL)
    gateway.replies = [EMAIL_REPLY]
    assert drain_imports(db_url) == ["succeeded"]

    resp = client.post(
        OPPORTUNITIES,
        headers=headers,
        json=_body(customer_name="Meridian Fresh Foods", import_id=created["id"]),
    )
    assert resp.status_code == 201, resp.text
    opp = resp.json()
    MINE.append(UUID(opp["id"]))

    sources = client.get(f"{OPPORTUNITIES}/{opp['id']}/sources", headers=headers).json()["items"]
    (source,) = sources
    assert (source["filename"], source["kind"], source["version"]) == (
        "follow-up.eml",
        "email",
        1,
    )
    assert source["size_bytes"] == len(EMAIL)
    assert source["parse"]["status"] == "queued"
    parse_jobs = rows(
        sync_engine,
        "SELECT * FROM platform_jobs WHERE job_type = :t AND opportunity_id = :o",
        t=PARSE,
        o=opp["id"],
    )
    assert [j["payload"]["source_id"] for j in parse_jobs] == [source["id"]]

    sha = import_row(sync_engine, created["id"])["file_sha256"]
    assert BlobStore(storage_dir).path_for(sha).read_bytes() == EMAIL
    ref_count = rows(sync_engine, "SELECT ref_count FROM platform_files WHERE sha256 = :s", s=sha)
    assert ref_count[0]["ref_count"] >= 2  # the import and the Source version
    assert import_row(sync_engine, created["id"])["consumed_at"] is not None

    events = rows(
        sync_engine,
        "SELECT * FROM platform_trace_events WHERE opportunity_id = :o ORDER BY occurred_at, id",
        o=opp["id"],
    )
    assert [e["event_type"] for e in events] == [
        "opportunities.opportunity.created",
        "intake.source.added",
    ]
    assert events[0]["payload"] == {"from_import": True}
    assert events[1]["payload"] == {"version": 1, "kind": "email", "size_bytes": len(EMAIL)}
    assert "follow-up.eml" not in str(events) and "Okafor" not in str(events)


def test_reusing_an_import_is_409_and_another_users_import_is_404(
    client: TestClient, sync_engine: Engine
) -> None:
    headers = _engineer(client, sync_engine)
    created = _import(client, headers, "notes.txt", f"Notes {uuid4()}\n".encode())
    other, _ = _user(client, sync_engine, "Other Engineer", PSE)

    resp = client.get(f"{IMPORTS}/{created['id']}", headers=other)
    assert_problem(resp.json(), 404, "not_found")
    resp = client.post(OPPORTUNITIES, headers=other, json=_body(import_id=created["id"]))
    assert_problem(resp.json(), 404, "not_found")
    resp = client.post(OPPORTUNITIES, headers=headers, json=_body(import_id=str(uuid4())))
    assert_problem(resp.json(), 404, "not_found")

    first = client.post(OPPORTUNITIES, headers=headers, json=_body(import_id=created["id"]))
    assert first.status_code == 201, first.text
    MINE.append(UUID(first.json()["id"]))
    again = client.post(OPPORTUNITIES, headers=headers, json=_body(import_id=created["id"]))
    assert_problem(again.json(), 409, "import_consumed")


def _age(import_id: str, hours: int) -> None:
    """Move an import's `created_at` back, as the owner role (psa_app can't update it)."""
    owner_url = os.environ.get("PSA_MIGRATIONS_DATABASE_URL")
    if not owner_url:
        pytest.skip("PSA_MIGRATIONS_DATABASE_URL (the owner role) is needed to age an import")
    engine = sa.create_engine(owner_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "UPDATE opportunities_imports "
                    "SET created_at = created_at - make_interval(hours => :h) WHERE id = :i"
                ),
                {"h": hours, "i": import_id},
            )
    finally:
        engine.dispose()


def test_an_import_older_than_24_hours_is_refused_410(
    client: TestClient, sync_engine: Engine
) -> None:
    headers = _engineer(client, sync_engine)
    created = _import(client, headers, "notes.txt", f"Notes {uuid4()}\n".encode())
    _age(created["id"], 25)
    resp = client.get(f"{IMPORTS}/{created['id']}", headers=headers)
    assert_problem(resp.json(), 410, "import_expired")
    resp = client.post(OPPORTUNITIES, headers=headers, json=_body(import_id=created["id"]))
    assert_problem(resp.json(), 410, "import_expired")
    assert import_row(sync_engine, created["id"])["consumed_at"] is None


def test_a_consumed_import_is_409_even_once_expired(
    client: TestClient, sync_engine: Engine
) -> None:
    headers = _engineer(client, sync_engine)
    created = _import(client, headers, "notes.txt", f"Notes {uuid4()}\n".encode())
    first = client.post(OPPORTUNITIES, headers=headers, json=_body(import_id=created["id"]))
    assert first.status_code == 201, first.text
    MINE.append(UUID(first.json()["id"]))
    _age(created["id"], 25)
    again = client.post(OPPORTUNITIES, headers=headers, json=_body(import_id=created["id"]))
    assert_problem(again.json(), 409, "import_consumed")


def test_an_invalid_field_on_create_rolls_back_and_keeps_the_import(
    client: TestClient, sync_engine: Engine
) -> None:
    headers = _engineer(client, sync_engine)
    created = _import(client, headers, "notes.txt", f"Notes {uuid4()}\n".encode())
    resp = client.post(
        OPPORTUNITIES, headers=headers, json=_body(products=[], import_id=created["id"])
    )
    assert resp.status_code == 422
    assert import_row(sync_engine, created["id"])["consumed_at"] is None


def test_sales_representatives_cannot_import_or_create(
    client: TestClient, sync_engine: Engine, storage_dir: Path
) -> None:
    rep, _ = _user(client, sync_engine, "Sales Rep", "sales_representative")
    resp = _upload(client, rep, "follow-up.eml", EMAIL)
    assert_problem(resp.json(), 403, "forbidden")
    engineer = _engineer(client, sync_engine)
    created = _import(client, engineer, "notes.txt", f"Notes {uuid4()}\n".encode())
    resp = client.post(OPPORTUNITIES, headers=rep, json=_body(import_id=created["id"]))
    assert_problem(resp.json(), 403, "forbidden")


# --- failures -------------------------------------------------------------------------------


def test_an_unreadable_file_fails_without_a_model_call(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers = _engineer(client, sync_engine)
    created = _import(client, headers, "rfp.pdf", CORRUPT_PDF)
    gateway.replies = [EMAIL_REPLY]
    assert drain_imports(db_url) == ["succeeded"]  # the job finishes; the import failed
    body = client.get(f"{IMPORTS}/{created['id']}", headers=headers).json()
    assert (body["status"], body["error_code"], body["suggestions"]) == (
        "failed",
        "unreadable",
        None,
    )
    assert gateway.requests == []
    # The form still works: the Opportunity can be created from it.
    resp = client.post(OPPORTUNITIES, headers=headers, json=_body(import_id=created["id"]))
    assert resp.status_code == 201, resp.text
    MINE.append(UUID(resp.json()["id"]))


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ModelUnavailableError("down"), "model_unavailable"),
        (ModelTimeoutError("slow"), "model_timeout"),
        (ModelOutputInvalidError("bad"), "output_invalid"),
    ],
    ids=["unavailable", "timeout", "invalid"],
)
def test_a_model_failure_is_retried_once_then_fails(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    error: Exception,
    code: str,
) -> None:
    headers = _engineer(client, sync_engine)
    created = _import(client, headers, "notes.txt", f"Notes {uuid4()}\n".encode())
    gateway.replies = [error]
    assert drain_imports(db_url) == ["failed_retrying", "dead"]
    row = import_row(sync_engine, created["id"])
    assert (row["status"], row["error_code"]) == ("failed", code)


def test_a_cancelled_final_attempt_marks_the_import_timed_out(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers = _engineer(client, sync_engine)
    created = _import(client, headers, "notes.txt", f"Notes {uuid4()}\n".encode())

    def cancelled(request: Any) -> Any:
        raise asyncio.CancelledError  # what the job's timeout does to the handler

    gateway.replies = [cancelled]

    async def scenario() -> None:
        engine = create_engine(Settings(database_url=db_url))
        ctx = JobContext(
            job_id=uuid4(),
            job_type=READ,
            attempt=2,
            max_attempts=2,
            opportunity_id=None,
            engine=engine,
        )
        try:
            with pytest.raises(asyncio.CancelledError):
                await imports.read_import(ctx, imports.ReadImport(import_id=UUID(created["id"])))
        finally:
            await engine.dispose()

    run_async(scenario())
    row = import_row(sync_engine, created["id"])
    assert (row["status"], row["error_code"]) == ("failed", "model_timeout")


@pytest.mark.parametrize(
    ("name", "data", "status", "code", "detail"),
    [
        ("setup.exe", b"MZ", 415, "file_type_not_allowed", "Rejected: .exe files aren't allowed"),
        ("big.txt", b"x" * (1024 * 1024 + 1), 413, "file_too_large", "Rejected: larger than 1 MB"),
    ],
    ids=["bad-type", "too-large"],
)
def test_a_bad_type_or_size_is_refused_before_any_job(
    db_url: str,
    sync_engine: Engine,
    storage_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    data: bytes,
    status: int,
    code: str,
    detail: str,
) -> None:
    monkeypatch.setenv("PSA_UPLOAD_MAX_BYTES", str(1024 * 1024))
    with make_client(auth_app(db_url)) as c:
        headers = _engineer(c, sync_engine)
        user_id = c.get("/api/v1/me", headers=headers).json()["id"]
        resp = _upload(c, headers, name, data)
    assert resp.status_code == status, resp.text
    assert_problem(resp.json(), status, code)
    assert resp.json()["detail"] == detail
    assert (
        rows(sync_engine, "SELECT id FROM opportunities_imports WHERE uploaded_by = :u", u=user_id)
        == []
    )
    stored = [p for p in storage_dir.rglob("*") if p.is_file()] if storage_dir.exists() else []
    assert stored == []


def test_logs_carry_ids_only(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    headers = _engineer(client, sync_engine)
    created = _import(client, headers, "follow-up.eml", EMAIL)
    gateway.replies = [EMAIL_REPLY]
    assert drain_imports(db_url) == ["succeeded"]
    text = " ".join(
        f"{r.getMessage()} {r.__dict__}" for r in caplog.records if r.name.startswith("app.")
    )
    assert created["id"] in text
    for secret in ("follow-up.eml", "Meridian", "Okafor", "goods-issue"):
        assert secret not in text


# --- grants ---------------------------------------------------------------------------------


def test_psa_app_may_update_only_the_status_suggestion_and_consumed_columns(
    sync_engine: Engine,
) -> None:
    def table(privilege: str) -> bool:
        with sync_engine.connect() as conn:
            result: bool = conn.execute(
                sa.text("SELECT has_table_privilege('opportunities_imports', :p)"),
                {"p": privilege},
            ).scalar_one()
        return result

    def column(name: str) -> bool:
        with sync_engine.connect() as conn:
            result: bool = conn.execute(
                sa.text("SELECT has_column_privilege('opportunities_imports', :c, 'UPDATE')"),
                {"c": name},
            ).scalar_one()
        return result

    assert table("SELECT") and table("INSERT")
    assert not table("DELETE") and not table("UPDATE")
    for name in ("status", "error_code", "suggestions", "consumed_at"):
        assert column(name), name
    for name in ("id", "uploaded_by", "file_sha256", "size_bytes", "filename", "created_at"):
        assert not column(name), name


def test_the_email_gets_an_industry_inferred_from_what_the_customer_does(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers = _engineer(client, sync_engine)
    created = _import(client, headers, "follow-up.eml", EMAIL)
    quote = "Item master data is a known weak spot."
    gateway.replies = [
        reply(industry=suggested("Food & grocery distribution", quote), industry_inferred=True)
    ]
    assert drain_imports(db_url) == ["succeeded"]
    body = client.get(f"{IMPORTS}/{created['id']}", headers=headers).json()
    assert body["suggestions"]["industry"] == {
        "value": "Food & grocery distribution",
        "quote": quote,
    }
    assert body["suggestions"]["industry_inferred"] is True
