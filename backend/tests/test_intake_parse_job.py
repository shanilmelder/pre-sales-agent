"""Parsing Sources in the background (Story 2.2 Part B) against a real, migrated Postgres as
psa_app: enqueue, the `intake.parse_source` job, the read model and the Retry API.

Jobs are run through the real runner (`run_job`), claimed like `queue.claim` but limited to
`intake.parse_source` jobs of the current test's Opportunities (`_MINE`): the database is
shared with other tests and test runs, whose jobs are never claimed or retired here. Files
go to a temp `PSA_STORAGE_DIR`.
"""

import hashlib
import logging
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

from app.modules.intake.adapters import parse_runner
from app.modules.intake.application import extraction as intake_extraction
from app.modules.intake.application import jobs as intake_jobs
from app.modules.intake.application import public as intake
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.jobs import queue as q
from app.platform.jobs.models import PlatformJob
from app.platform.jobs.runner import LeaseSettings, run_job
from app.platform.storage import BlobStore
from app.platform.uow import unit_of_work
from tests.auth_tokens import auth_app
from tests.conftest import make_client, run_async
from tests.test_health import assert_problem
from tests.test_intake_extraction import retire_extraction_jobs
from tests.test_intake_parsers import expected, fixture
from tests.test_opportunities import PSE, _add, _create, _user

BASE = "/api/v1/opportunities"
JOB_TYPE = "intake.parse_source"
LEASE = LeaseSettings(lease_s=30, heartbeat_s=5)


@pytest.fixture
def storage_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "files"
    monkeypatch.setenv("PSA_STORAGE_DIR", str(root))
    return root


@pytest.fixture
def parse_timeout(monkeypatch: pytest.MonkeyPatch, storage_dir: Path) -> dict[str, float]:
    """The handler's settings: the temp store, and a parse timeout tests may lower."""
    limits = {"timeout_s": 60.0}
    monkeypatch.setattr(
        intake_jobs,
        "parse_settings",
        lambda: Settings(storage_dir=storage_dir, parse_timeout_s=limits["timeout_s"]),
    )
    return limits


_MINE: list[UUID] = []
"""The current test's Opportunities: `_drain` runs only their jobs. The database is shared
with other tests (and other test runs), whose parse jobs must never be claimed here."""


HIDDEN = timedelta(days=1)
"""How far ahead this module's jobs are scheduled, so that no other claimer (a local
`worker` container, another test run) takes them; `_claim_mine` ignores `run_after`."""


@pytest.fixture(autouse=True)
def _own_opportunities(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    real_enqueue = intake_jobs.enqueue

    async def hidden_enqueue(uow: Any, payload: Any, **kwargs: Any) -> UUID:
        kwargs["run_after"] = datetime.now(UTC) + HIDDEN
        return await real_enqueue(uow, payload, **kwargs)

    monkeypatch.setattr(intake_jobs, "enqueue", hidden_enqueue)
    # A successful parse also queues a Requirement extraction (Story 2.5): hide it too.
    monkeypatch.setattr(intake_extraction, "enqueue", hidden_enqueue)
    _MINE.clear()
    yield
    retire_extraction_jobs(_MINE)
    _MINE.clear()


async def _hide_mine(engine: AsyncEngine) -> None:
    """Push this test's waiting jobs out of other claimers' reach again."""
    async with unit_of_work(engine) as uow:
        await uow.session.execute(
            sa.text(
                "UPDATE platform_jobs SET run_after = now() + interval '1 day' "
                "WHERE job_type = :t AND status IN ('queued', 'failed_retrying') "
                "AND opportunity_id = ANY(:o)"
            ),
            {"t": JOB_TYPE, "o": list(_MINE)},
        )


@pytest.fixture
def client(db_url: str, storage_dir: Path, parse_timeout: dict[str, float]) -> Iterator[TestClient]:
    with make_client(auth_app(db_url)) as c:
        yield c


async def _claim_mine(engine: AsyncEngine) -> q.ClaimedJob | None:
    """`queue.claim`, limited to parse jobs of this test's Opportunities, and ignoring
    `run_after` (they are scheduled far ahead; retries are due at once)."""
    t = PlatformJob
    eligible = sa.or_(
        t.status.in_(("queued", "failed_retrying")),
        sa.and_(t.status == "running", t.lease_expires_at < sa.func.now()),
    )
    next_id = (
        sa.select(t.id)
        .where(t.job_type == JOB_TYPE, t.opportunity_id.in_(list(_MINE)), eligible)
        .order_by(t.priority, t.run_after, t.created_at)
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


def _drain(db_url: str, *, max_runs: int = 20) -> list[str]:
    """Claim and run this test's parse jobs until none is left; retries run at once."""

    async def scenario() -> list[str]:
        engine = create_engine(Settings(database_url=db_url))
        outcomes: list[str] = []
        try:
            for _ in range(max_runs):
                job = await _claim_mine(engine)
                if job is None:
                    break
                outcomes.append(await run_job(engine, job, LEASE))
                await _hide_mine(engine)  # a retry's own backoff would make it claimable
        finally:
            await engine.dispose()
        return outcomes

    return run_async(scenario())


def _upload(
    client: TestClient, headers: dict[str, str], opp_id: str, name: str, data: bytes
) -> Any:
    resp = client.post(
        f"{BASE}/{opp_id}/sources",
        headers=headers,
        files={"file": (name, data, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _list(client: TestClient, headers: dict[str, str], opp_id: str) -> dict[str, Any]:
    resp = client.get(f"{BASE}/{opp_id}/sources", headers=headers)
    assert resp.status_code == 200, resp.text
    return {s["id"]: s for s in resp.json()["items"]}


def _parse_row(engine: Engine, source_id: str, version: int = 1) -> dict[str, Any]:
    with engine.connect() as conn:
        return dict(
            conn.execute(
                sa.text("SELECT * FROM intake_source_parses WHERE source_id = :s AND version = :v"),
                {"s": source_id, "v": version},
            )
            .mappings()
            .one()
        )


def _jobs(engine: Engine, source_id: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                sa.text(
                    "SELECT * FROM platform_jobs WHERE job_type = :t "
                    "AND payload->>'source_id' = :s ORDER BY created_at, id"
                ),
                {"t": JOB_TYPE, "s": source_id},
            ).mappings()
        ]


def _events(engine: Engine, source_id: str, event_type: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                sa.text(
                    "SELECT * FROM platform_trace_events WHERE subject_id = :s "
                    "AND event_type = :e ORDER BY occurred_at, id"
                ),
                {"s": source_id, "e": event_type},
            ).mappings()
        ]


def _text(db_url: str, storage_dir: Path, source_id: str, version: int = 1) -> str | None:
    async def scenario() -> str | None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                return await intake.extracted_text(
                    uow, UUID(source_id), version, store=BlobStore(storage_dir)
                )
        finally:
            await engine.dispose()

    return run_async(scenario())


def _owner(client: TestClient, engine: Engine) -> tuple[dict[str, str], dict[str, Any]]:
    headers, _ = _user(client, engine, "Owner Person", PSE)
    opp = _create(client, headers)
    _MINE.append(UUID(opp["id"]))
    return headers, opp


# --- enqueue --------------------------------------------------------------------------------


def test_upload_and_paste_each_queue_one_parse(client: TestClient, sync_engine: Engine) -> None:
    headers, opp = _owner(client, sync_engine)
    uploaded = _upload(client, headers, opp["id"], "call.vtt", fixture("sample.vtt"))
    resp = client.post(
        f"{BASE}/{opp['id']}/sources/text", headers=headers, json={"text": "a pasted note"}
    )
    assert resp.status_code == 201, resp.text
    pasted = resp.json()

    for source in (uploaded, pasted):
        assert source["parse"] == {"status": "queued", "error_code": None}
        row = _parse_row(sync_engine, source["id"])
        assert (row["status"], row["error_code"], row["text_sha256"]) == ("queued", None, None)
        (job,) = _jobs(sync_engine, source["id"])
        assert job["payload"] == {"source_id": source["id"], "version": 1}
        assert (job["status"], job["priority"]) == ("queued", 0)
        assert str(job["opportunity_id"]) == opp["id"]


def test_same_bytes_again_queue_the_next_version(client: TestClient, sync_engine: Engine) -> None:
    headers, opp = _owner(client, sync_engine)
    first = _upload(client, headers, opp["id"], "a.txt", b"same bytes")
    second = _upload(client, headers, opp["id"], "b.txt", b"same bytes")
    assert second["id"] == first["id"] and second["version"] == 2
    assert _parse_row(sync_engine, first["id"], 2)["status"] == "queued"
    assert [j["payload"]["version"] for j in _jobs(sync_engine, first["id"])] == [1, 2]


# --- each kind ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["sample.txt", "sample.eml", "html-only.eml", "sample.vtt", "sample.pdf", "sample.docx"]
)
def test_each_kind_is_parsed_and_its_text_stored(
    client: TestClient, sync_engine: Engine, db_url: str, storage_dir: Path, name: str
) -> None:
    headers, opp = _owner(client, sync_engine)
    source = _upload(client, headers, opp["id"], name, fixture(name))

    assert _drain(db_url) == ["succeeded"]

    want = expected(name)
    row = _parse_row(sync_engine, source["id"])
    assert row["status"] == "parsed" and row["error_code"] is None
    assert row["char_count"] == len(want)
    assert row["parser"].split("@")[0] in {"text", "email", "vtt", "pypdf", "docx"}
    assert BlobStore(storage_dir).path_for(row["text_sha256"]).read_bytes() == want.encode()
    assert _text(db_url, storage_dir, source["id"]) == want
    with sync_engine.connect() as conn:
        refs = conn.execute(
            sa.text("SELECT ref_count FROM platform_files WHERE sha256 = :s"),
            {"s": row["text_sha256"]},
        ).scalar_one()
    assert refs >= 1

    (event,) = _events(sync_engine, source["id"], "intake.source.parsed")
    assert event["payload"] == {"version": 1, "char_count": len(want)}
    assert (event["actor_type"], event["actor_id"]) == ("system", JOB_TYPE)
    assert event["subject_version"] == 1 and str(event["opportunity_id"]) == opp["id"]

    listed = _list(client, headers, opp["id"])[source["id"]]
    assert listed["parse"] == {"status": "parsed", "error_code": None}


def test_crlf_and_nfd_are_stored_normalised(
    client: TestClient, sync_engine: Engine, db_url: str, storage_dir: Path
) -> None:
    headers, opp = _owner(client, sync_engine)
    data = f"a\r\nb é {opp['id']}".encode()
    source = _upload(client, headers, opp["id"], "notes.txt", data)

    _drain(db_url)

    want = f"a\nb é {opp['id']}"
    assert _text(db_url, storage_dir, source["id"]) == want
    assert _parse_row(sync_engine, source["id"])["char_count"] == len(want)


def test_pasted_text_is_parsed_as_txt(
    client: TestClient, sync_engine: Engine, db_url: str, storage_dir: Path
) -> None:
    headers, opp = _owner(client, sync_engine)
    text = f"Call note {opp['id']}\nNeeds SSO"
    resp = client.post(f"{BASE}/{opp['id']}/sources/text", headers=headers, json={"text": text})
    source = resp.json()

    _drain(db_url)

    assert _text(db_url, storage_dir, source["id"]) == text
    assert _parse_row(sync_engine, source["id"])["parser"] == "text@1"


# --- failures -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("sample.msg", "not_supported"),
        ("corrupt.pdf", "unreadable"),
        ("scanned.pdf", "no_text"),
    ],
)
def test_permanent_failures_finish_the_job_without_retry(
    client: TestClient, sync_engine: Engine, db_url: str, name: str, code: str
) -> None:
    headers, opp = _owner(client, sync_engine)
    source = _upload(client, headers, opp["id"], name, fixture(name))

    assert _drain(db_url) == ["succeeded"]

    row = _parse_row(sync_engine, source["id"])
    assert (row["status"], row["error_code"], row["text_sha256"]) == ("failed", code, None)
    (job,) = _jobs(sync_engine, source["id"])
    assert (job["status"], job["attempts"], job["last_error"]) == ("succeeded", 1, None)
    assert _events(sync_engine, source["id"], "intake.source.parsed") == []
    assert _list(client, headers, opp["id"])[source["id"]]["parse"] == {
        "status": "failed",
        "error_code": code,
    }
    assert _text(db_url, Path("unused"), source["id"]) is None


def test_hang_is_killed_retried_then_failed_with_timeout(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    parse_timeout: dict[str, float],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    headers, opp = _owner(client, sync_engine)
    secret = f"secret customer words {opp['id']}"
    source = _upload(client, headers, opp["id"], "secret-name.txt", secret.encode())
    parse_timeout["timeout_s"] = 0.5
    monkeypatch.setattr(
        parse_runner,
        "child_command",
        lambda path, ext: [sys.executable, "-c", "import time; time.sleep(30)"],
    )

    with caplog.at_level(logging.DEBUG):
        assert _drain(db_url) == ["failed_retrying", "dead"]

    row = _parse_row(sync_engine, source["id"])
    assert (row["status"], row["error_code"]) == ("failed", "timeout")
    (job,) = _jobs(sync_engine, source["id"])
    assert (job["status"], job["attempts"]) == ("dead", 2)
    assert job["last_error"] == "ParseTimeoutError: parse exceeded 0.5s"
    # Privacy: no text or file name in logs, trace or last_error.
    logged = caplog.text + str([r.__dict__ for r in caplog.records])
    for leak in ("secret customer", "secret-name"):
        assert leak not in logged
        assert leak not in str(job)
    with sync_engine.connect() as conn:
        trace = conn.execute(
            sa.text("SELECT payload FROM platform_trace_events WHERE subject_id = :s"),
            {"s": source["id"]},
        ).all()
    assert "secret" not in str(trace)


def test_first_attempt_timeout_leaves_the_row_parsing(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    parse_timeout: dict[str, float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, opp = _owner(client, sync_engine)
    source = _upload(client, headers, opp["id"], "a.txt", f"x {opp['id']}".encode())
    parse_timeout["timeout_s"] = 0.5
    real_child = parse_runner.child_command
    monkeypatch.setattr(
        parse_runner,
        "child_command",
        lambda path, ext: [sys.executable, "-c", "import time; time.sleep(30)"],
    )

    assert _drain(db_url, max_runs=1) == ["failed_retrying"]
    assert _parse_row(sync_engine, source["id"])["status"] == "parsing"
    assert _list(client, headers, opp["id"])[source["id"]]["parse"]["status"] == "parsing"

    # The retry parses normally.
    parse_timeout["timeout_s"] = 60
    monkeypatch.setattr(parse_runner, "child_command", real_child)
    assert _drain(db_url) == ["succeeded"]
    assert _parse_row(sync_engine, source["id"])["status"] == "parsed"


def test_one_corrupt_source_does_not_block_the_others(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    headers, opp = _owner(client, sync_engine)
    first = _upload(client, headers, opp["id"], "call.vtt", fixture("sample.vtt"))
    middle = _upload(client, headers, opp["id"], "broken.pdf", fixture("corrupt.pdf"))
    last = _upload(client, headers, opp["id"], "spec.docx", fixture("sample.docx"))

    assert _drain(db_url) == ["succeeded"] * 3

    listed = _list(client, headers, opp["id"])
    assert listed[first["id"]]["parse"]["status"] == "parsed"
    assert listed[middle["id"]]["parse"] == {"status": "failed", "error_code": "unreadable"}
    assert listed[last["id"]]["parse"]["status"] == "parsed"


def test_a_job_for_an_already_parsed_version_does_nothing(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    headers, opp = _owner(client, sync_engine)
    source = _upload(client, headers, opp["id"], "a.txt", f"once {opp['id']}".encode())
    _drain(db_url)
    before = _parse_row(sync_engine, source["id"])

    async def duplicate() -> None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                await intake_jobs.enqueue_parse(
                    uow, source_id=UUID(source["id"]), version=1, opportunity_id=UUID(opp["id"])
                )
        finally:
            await engine.dispose()

    run_async(duplicate())
    assert _drain(db_url) == ["succeeded"]
    assert _parse_row(sync_engine, source["id"]) == before
    assert len(_events(sync_engine, source["id"], "intake.source.parsed")) == 1


# --- retry API ------------------------------------------------------------------------------


def _retry(client: TestClient, headers: dict[str, str], opp_id: str, source_id: str) -> Any:
    return client.post(f"{BASE}/{opp_id}/sources/{source_id}/parse", headers=headers)


def test_retry_requeues_a_failed_version(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    headers, opp = _owner(client, sync_engine)
    member_headers, member_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    opp = _add(client, headers, opp, member_id).json()
    source = _upload(client, headers, opp["id"], "broken.pdf", fixture("corrupt.pdf"))
    _drain(db_url)
    assert _parse_row(sync_engine, source["id"])["status"] == "failed"

    resp = _retry(client, member_headers, opp["id"], source["id"])

    assert resp.status_code == 202, resp.text
    assert resp.json()["parse"] == {"status": "queued", "error_code": None}
    row = _parse_row(sync_engine, source["id"])
    assert (row["status"], row["error_code"]) == ("queued", None)
    jobs = _jobs(sync_engine, source["id"])
    assert [j["status"] for j in jobs] == ["succeeded", "queued"]
    (event,) = _events(sync_engine, source["id"], "intake.source.parse_retried")
    assert event["payload"] == {"version": 1, "error_code": "unreadable"}
    assert (event["actor_type"], event["actor_id"]) == ("user", str(member_id))

    # Still corrupt: it fails again, and can be retried again.
    _drain(db_url)
    assert _parse_row(sync_engine, source["id"])["status"] == "failed"
    assert _retry(client, headers, opp["id"], source["id"]).status_code == 202


def test_retry_of_a_version_that_has_not_failed_is_409(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    headers, opp = _owner(client, sync_engine)
    source = _upload(client, headers, opp["id"], "a.txt", f"fine {opp['id']}".encode())

    queued = _retry(client, headers, opp["id"], source["id"])
    assert queued.status_code == 409
    assert_problem(queued.json(), 409, "parse_not_failed")

    _drain(db_url)
    parsed = _retry(client, headers, opp["id"], source["id"])
    assert parsed.status_code == 409
    assert len(_jobs(sync_engine, source["id"])) == 1


def test_retry_by_a_reader_who_is_not_a_collaborator_is_403(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    headers, opp = _owner(client, sync_engine)
    source = _upload(client, headers, opp["id"], "broken.pdf", fixture("corrupt.pdf"))
    _drain(db_url)
    reader, _ = _user(client, sync_engine, "Head Person", "head_of_delivery")

    resp = _retry(client, reader, opp["id"], source["id"])

    assert resp.status_code == 403, resp.text
    assert_problem(resp.json(), 403, "forbidden")
    assert _parse_row(sync_engine, source["id"])["status"] == "failed"


def test_retry_404s(client: TestClient, sync_engine: Engine, db_url: str) -> None:
    headers, opp = _owner(client, sync_engine)
    other_opp = _create(client, headers)
    source = _upload(client, headers, opp["id"], "broken.pdf", fixture("corrupt.pdf"))
    _drain(db_url)
    outsider, _ = _user(client, sync_engine, "Outsider", PSE)

    # A Source of another Opportunity, an unknown Source, and a caller who can't see it.
    for resp in (
        _retry(client, headers, other_opp["id"], source["id"]),
        _retry(client, headers, opp["id"], "00000000-0000-7000-8000-000000000000"),
        _retry(client, outsider, opp["id"], source["id"]),
    ):
        assert resp.status_code == 404, resp.text
        assert_problem(resp.json(), 404, "not_found")
    assert _parse_row(sync_engine, source["id"])["status"] == "failed"


# --- wiring ---------------------------------------------------------------------------------


def test_the_worker_loads_the_parse_job_type() -> None:
    import app.main_worker as main_worker
    from app.platform.jobs import REGISTRY

    main_worker.load_job_types()
    spec = REGISTRY[JOB_TYPE]
    assert (spec.priority, spec.max_attempts) == ("interactive", 2)
    # The child's own limit (at most 600 s) always fires before the job's timeout.
    assert spec.timeout_s > Settings.model_fields["parse_timeout_s"].metadata[-1].le


def test_every_source_version_has_a_parse_row(sync_engine: Engine) -> None:
    """Migration 0007 backfilled versions added before it; new ones get theirs on add."""
    with sync_engine.connect() as conn:
        missing = conn.execute(
            sa.text(
                "SELECT count(*) FROM intake_source_versions v LEFT JOIN intake_source_parses p "
                "ON p.source_id = v.source_id AND p.version = v.version WHERE p.source_id IS NULL"
            )
        ).scalar_one()
    assert missing == 0


# --- retryable errors and the final attempt -------------------------------------------------


def test_an_unexpected_error_retries_then_marks_the_row_failed_on_the_final_attempt(
    client: TestClient, sync_engine: Engine, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, opp = _owner(client, sync_engine)
    source = _upload(client, headers, opp["id"], "a.txt", f"boom {opp['id']}".encode())

    async def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("spawn failed")

    monkeypatch.setattr(parse_runner, "run_parse", broken)

    assert _drain(db_url, max_runs=1) == ["failed_retrying"]
    assert _parse_row(sync_engine, source["id"])["status"] == "parsing"
    assert _drain(db_url) == ["dead"]
    row = _parse_row(sync_engine, source["id"])
    assert (row["status"], row["error_code"]) == ("failed", "unreadable")


def test_a_missing_stored_file_is_retried_not_unreadable(
    client: TestClient, sync_engine: Engine, db_url: str, storage_dir: Path
) -> None:
    headers, opp = _owner(client, sync_engine)
    data = f"vanishing {opp['id']}".encode()
    source = _upload(client, headers, opp["id"], "a.txt", data)
    blob = BlobStore(storage_dir).path_for(hashlib.sha256(data).hexdigest())
    moved = blob.with_name("moved-away")
    blob.rename(moved)

    assert _drain(db_url, max_runs=1) == ["failed_retrying"]
    (job,) = _jobs(sync_engine, source["id"])
    assert job["last_error"] == "BlobMissingError: stored file missing"
    assert _parse_row(sync_engine, source["id"])["status"] == "parsing"

    moved.rename(blob)  # back before the final attempt
    assert _drain(db_url) == ["succeeded"]
    assert _parse_row(sync_engine, source["id"])["status"] == "parsed"


def test_extracted_text_is_none_when_its_blob_is_missing(
    client: TestClient, sync_engine: Engine, db_url: str, storage_dir: Path
) -> None:
    headers, opp = _owner(client, sync_engine)
    source = _upload(client, headers, opp["id"], "a.txt", f"text {opp['id']}".encode())
    _drain(db_url)
    row = _parse_row(sync_engine, source["id"])
    BlobStore(storage_dir).path_for(row["text_sha256"]).unlink()

    assert _text(db_url, storage_dir, source["id"]) is None


# --- migration 0007 backfill ------------------------------------------------------------------


def _alembic(*args: str) -> None:
    owner_url = os.environ.get("PSA_MIGRATIONS_DATABASE_URL")
    assert owner_url, "PSA_MIGRATIONS_DATABASE_URL (the owner role) is needed to migrate"
    result = subprocess.run(  # a separate process: alembic's logging setup stays out of pytest
        [sys.executable, "-m", "alembic", *args],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PSA_MIGRATIONS_DATABASE_URL": owner_url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_migration_backfills_a_parse_row_and_one_job_for_existing_versions(
    sync_engine: Engine, db_url: str, storage_dir: Path, parse_timeout: dict[str, float]
) -> None:
    data = f"Added before 0007 {uuid4()}".encode()

    async def store() -> str:
        async def chunks() -> AsyncIterator[bytes]:
            yield data

        return (await BlobStore(storage_dir).put_stream(chunks(), len(data))).sha256

    sha = run_async(store())
    source_id, opportunity_id, user_id = uuid4(), uuid4(), uuid4()
    _MINE.append(opportunity_id)
    _alembic("downgrade", "0006_platform_jobs")
    try:
        with sync_engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO intake_sources (id, opportunity_id, kind, created_by, row_version)"
                    " VALUES (:s, :o, 'note', :u, 1)"
                ),
                {"s": source_id, "o": opportunity_id, "u": user_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO intake_source_versions "
                    "(source_id, version, file_sha256, filename, size_bytes, uploaded_by) "
                    "VALUES (:s, 1, :sha, 'old.txt', :n, :u)"
                ),
                {"s": source_id, "sha": sha, "n": len(data), "u": user_id},
            )
    finally:
        _alembic("upgrade", "head")

    async def hide() -> None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            await _hide_mine(engine)
        finally:
            await engine.dispose()

    run_async(hide())  # the backfill queued it as due now

    row = _parse_row(sync_engine, str(source_id))
    assert (row["status"], row["row_version"]) == ("queued", 1)
    (job,) = _jobs(sync_engine, str(source_id))
    payload = intake_jobs.ParseSource.model_validate(job["payload"])
    assert (payload.source_id, payload.version) == (source_id, 1)
    assert (job["status"], job["opportunity_id"]) == ("queued", opportunity_id)

    # The backfill re-queued every other test's versions too (background priority, which
    # the app never uses): retire those, so this test leaves no claimable jobs behind.
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE platform_jobs SET status = 'dead', last_error = 'test: backfill leftover' "
                "WHERE job_type = :t AND priority = 1 AND status = 'queued' AND id <> :j"
            ),
            {"t": JOB_TYPE, "j": job["id"]},
        )
    assert _drain(db_url) == ["succeeded"]
    assert _parse_row(sync_engine, str(source_id))["status"] == "parsed"
    assert _text(db_url, storage_dir, str(source_id)) == data.decode()
