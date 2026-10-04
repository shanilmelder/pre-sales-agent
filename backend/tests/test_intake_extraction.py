"""Requirement extraction (Story 2.5 Part A) against a real, migrated Postgres as psa_app:
auto-queueing on parse, coalescing, the `intake.extract_requirements` job with a fake
ModelGateway, `accept_extraction` (passages, supersede, evidence, trace) and failures.

As in `test_intake_parse_job.py`, this module's jobs are scheduled a day ahead so that no
other claimer (a local `worker` container, another test run) takes them, and `_drain` runs
only jobs of the current test's Opportunities (`MINE`).
"""

import asyncio
import logging
import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agents.contract import AgentResult
from app.agents.intake_agent.agent import prompt
from app.agents.intake_agent.schema import IntakeOutput
from app.modules.assessments.application import review as assessments_review
from app.modules.estimates.application import assumptions as estimates_assumptions
from app.modules.estimates.application import draft as estimates_draft
from app.modules.gaps.application import detection as gaps_detection
from app.modules.intake.application import extraction as intake_extraction
from app.modules.intake.application import jobs as intake_jobs
from app.modules.intake.application import public as intake
from app.platform.actor import Actor
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.jobs import JobContext
from app.platform.jobs import queue as q
from app.platform.jobs.models import PlatformJob
from app.platform.jobs.runner import LeaseSettings, run_job
from app.platform.model_gateway import provider
from app.platform.model_gateway.port import (
    ModelOutputInvalidError,
    ModelTimeoutError,
    ModelUnavailableError,
    StructuredRequest,
    StructuredResult,
)
from app.platform.storage import BlobStore
from app.platform.uow import unit_of_work
from tests.auth_tokens import auth_app
from tests.conftest import make_client, run_async
from tests.test_opportunities import PSE, _create, _user

BASE = "/api/v1/opportunities"
PARSE = "intake.parse_source"
EXTRACT = "intake.extract_requirements"
DETECT = "gaps.detect_gaps"
DRAFT = "estimates.draft_estimate"
PROPOSE = "estimates.propose_assumptions"
RED_TEAM = "assessments.red_team_review"
LEASE = LeaseSettings(lease_s=30, heartbeat_s=5)
HIDDEN = timedelta(days=1)
MINE: list[UUID] = []
"""The current test's Opportunities: `_drain` runs only their jobs."""


# --- the fake gateway -----------------------------------------------------------------------

Reply = BaseModel | Exception | Callable[[StructuredRequest[Any]], BaseModel]


class FakeGateway:
    """Answers `complete_structured` from `replies` in order; the last one repeats."""

    def __init__(self) -> None:
        self.replies: list[Reply] = []
        self.requests: list[StructuredRequest[Any]] = []

    async def complete_structured(self, request: StructuredRequest[Any]) -> StructuredResult[Any]:
        self.requests.append(request)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        value: BaseModel = reply if isinstance(reply, BaseModel) else reply(request)
        return StructuredResult(
            value=value,
            call_id=uuid4(),
            profile="demo-chat",
            model="fake",
            model_digest="fake",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            attempts=1,
        )


def out(*items: tuple[str, str, list[tuple[str, str]]]) -> IntakeOutput:
    """`out(("text", "functional", [("S1", "quote")]), ...)`."""
    return IntakeOutput.model_validate(
        {
            "requirements": [
                {
                    "text": text,
                    "classification": classification,
                    "citations": [{"source": s, "quote": quote} for s, quote in citations],
                }
                for text, classification, citations in items
            ]
        }
    )


# --- fixtures -------------------------------------------------------------------------------


@pytest.fixture
def storage_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "files"
    monkeypatch.setenv("PSA_STORAGE_DIR", str(root))
    monkeypatch.setattr(
        intake_jobs, "parse_settings", lambda: Settings(storage_dir=root, parse_timeout_s=60)
    )
    monkeypatch.setattr(
        intake_extraction,
        "extraction_settings",
        lambda: Settings(storage_dir=root, model_profile_chat="demo-chat"),
    )
    return root


@pytest.fixture(autouse=True)
def _hidden_jobs(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    real_enqueue = intake_jobs.enqueue

    async def hidden_enqueue(uow: Any, payload: Any, **kwargs: Any) -> UUID:
        kwargs["run_after"] = datetime.now(UTC) + HIDDEN
        return await real_enqueue(uow, payload, **kwargs)

    monkeypatch.setattr(intake_jobs, "enqueue", hidden_enqueue)
    monkeypatch.setattr(intake_extraction, "enqueue", hidden_enqueue)
    monkeypatch.setattr(gaps_detection, "enqueue", hidden_enqueue)  # Story 4.3
    monkeypatch.setattr(estimates_draft, "enqueue", hidden_enqueue)  # Story 8.1
    monkeypatch.setattr(estimates_assumptions, "enqueue", hidden_enqueue)  # Story 8.4
    monkeypatch.setattr(assessments_review, "enqueue", hidden_enqueue)  # Story 6.5
    MINE.clear()
    yield
    retire_extraction_jobs(MINE)
    MINE.clear()


def retire_extraction_jobs(opportunity_ids: list[UUID]) -> None:
    """Retire extraction, Gap detection, Estimate draft, Assumption proposal and Red Team
    review jobs a test left waiting, so no worker ever runs them later (they would call the
    configured model with test text)."""
    url = os.environ.get("PSA_DATABASE_URL")
    if not url or not opportunity_ids:
        return
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "UPDATE platform_jobs SET status = 'dead', last_error = 'test: not run' "
                    "WHERE job_type = ANY(:t) AND status IN ('queued', 'failed_retrying') "
                    "AND opportunity_id = ANY(:o)"
                ),
                {"t": [EXTRACT, DETECT, DRAFT, PROPOSE, RED_TEAM], "o": list(opportunity_ids)},
            )
    finally:
        engine.dispose()


@pytest.fixture
def gateway() -> Iterator[FakeGateway]:
    fake = FakeGateway()
    provider.install(fake)
    yield fake
    provider.install(None)


@pytest.fixture
def client(db_url: str, storage_dir: Path) -> Iterator[TestClient]:
    with make_client(auth_app(db_url)) as c:
        yield c


# --- helpers --------------------------------------------------------------------------------


async def _claim_mine(engine: AsyncEngine, job_types: tuple[str, ...]) -> q.ClaimedJob | None:
    """`queue.claim`, limited to this test's Opportunities and ignoring `run_after`."""
    t = PlatformJob
    eligible = sa.or_(
        t.status.in_(("queued", "failed_retrying")),
        sa.and_(t.status == "running", t.lease_expires_at < sa.func.now()),
    )
    next_id = (
        sa.select(t.id)
        .where(t.job_type.in_(job_types), t.opportunity_id.in_(list(MINE)), eligible)
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


def drain(db_url: str, *job_types: str, max_runs: int = 20) -> list[str]:
    """Run this test's jobs of `job_types` until none is left; retries run at once."""

    async def scenario() -> list[str]:
        engine = create_engine(Settings(database_url=db_url))
        outcomes: list[str] = []
        try:
            for _ in range(max_runs):
                job = await _claim_mine(engine, job_types)
                if job is None:
                    break
                outcomes.append(await run_job(engine, job, LEASE))
        finally:
            await engine.dispose()
        return outcomes

    return run_async(scenario())


def owner(client: TestClient, engine: Engine) -> tuple[dict[str, str], dict[str, Any]]:
    headers, _ = _user(client, engine, "Owner Person", PSE)
    opp = _create(client, headers)
    MINE.append(UUID(opp["id"]))
    return headers, opp


def upload(
    client: TestClient, headers: dict[str, str], opp_id: str, name: str, text: str
) -> dict[str, Any]:
    resp = client.post(
        f"{BASE}/{opp_id}/sources",
        headers=headers,
        files={"file": (name, text.encode(), "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


def parsed(
    client: TestClient, engine: Engine, db_url: str, *files: tuple[str, str]
) -> tuple[dict[str, str], dict[str, Any], list[dict[str, Any]]]:
    """A new Opportunity whose Sources (`(name, text)`, in S1… order) are all parsed."""
    headers, opp = owner(client, engine)
    sources = [upload(client, headers, opp["id"], name, text) for name, text in files]
    assert drain(db_url, PARSE) == ["succeeded"] * len(files)
    return headers, opp, sources


def stored_text(db_url: str, storage_dir: Path, source_id: str) -> str:
    async def scenario() -> str | None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                return await intake.extracted_text(
                    uow, UUID(source_id), 1, store=BlobStore(storage_dir)
                )
        finally:
            await engine.dispose()

    text = run_async(scenario())
    assert text is not None
    return text


def jobs(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                sa.text(
                    "SELECT * FROM platform_jobs WHERE job_type = :t AND opportunity_id = :o "
                    "ORDER BY created_at, id"
                ),
                {"t": EXTRACT, "o": opp_id},
            ).mappings()
        ]


def extractions(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                sa.text(
                    "SELECT * FROM intake_extractions WHERE opportunity_id = :o "
                    "ORDER BY created_at, id"
                ),
                {"o": opp_id},
            ).mappings()
        ]


def requirements(engine: Engine, opp_id: str, status: str = "active") -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                sa.text(
                    "SELECT * FROM intake_requirements WHERE opportunity_id = :o "
                    "AND status = :s ORDER BY created_at, id"
                ),
                {"o": opp_id, "s": status},
            ).mappings()
        ]


def passages(engine: Engine, requirement_id: Any) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                sa.text(
                    "SELECT p.* FROM intake_requirement_evidence e "
                    "JOIN intake_source_passages p ON p.id = e.passage_id "
                    "WHERE e.requirement_id = :r ORDER BY p.source_id, p.start"
                ),
                {"r": requirement_id},
            ).mappings()
        ]


def completed_events(engine: Engine, extraction_id: Any) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                sa.text(
                    "SELECT * FROM platform_trace_events WHERE subject_id = :s "
                    "AND event_type = 'intake.extraction.completed'"
                ),
                {"s": extraction_id},
            ).mappings()
        ]


def span(text: str, quote: str) -> tuple[int, int]:
    start = text.index(quote)
    return start, start + len(quote)


# --- queueing -------------------------------------------------------------------------------


def test_a_successful_parse_queues_one_extraction(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    headers, opp = owner(client, sync_engine)
    upload(client, headers, opp["id"], "notes.txt", f"Needs SSO {opp['id']}")
    assert jobs(sync_engine, opp["id"]) == []  # nothing before the parse

    assert drain(db_url, PARSE) == ["succeeded"]

    (job,) = jobs(sync_engine, opp["id"])
    (extraction,) = extractions(sync_engine, opp["id"])
    assert job["payload"] == {"extraction_id": str(extraction["id"])}
    assert (job["status"], job["priority"]) == ("queued", 1)  # background
    assert extraction["status"] == "queued"
    assert extraction["error_code"] is None and extraction["source_count"] is None


def test_parses_while_one_extraction_waits_coalesce(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    headers, opp = owner(client, sync_engine)
    for n in range(3):
        upload(client, headers, opp["id"], f"n{n}.txt", f"Note {n} {opp['id']}")

    assert drain(db_url, PARSE) == ["succeeded"] * 3

    assert len(jobs(sync_engine, opp["id"])) == 1
    assert [e["status"] for e in extractions(sync_engine, opp["id"])] == ["queued"]


def test_a_parse_after_the_extraction_started_queues_another(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, _ = parsed(client, sync_engine, db_url, ("a.txt", f"One {uuid4()}"))
    gateway.replies = [out()]
    assert drain(db_url, EXTRACT) == ["succeeded"]
    upload(client, headers, opp["id"], "b.txt", f"Two {opp['id']}")
    assert drain(db_url, PARSE) == ["succeeded"]
    assert [e["status"] for e in extractions(sync_engine, opp["id"])] == ["succeeded", "queued"]


# --- the happy path -------------------------------------------------------------------------


def test_extraction_stores_cited_requirements(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    storage_dir: Path,
    gateway: FakeGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    call = (
        "Customer call notes. The system must handle 400 totes per hour.\n"
        f"Integration with SAP EWM is required. {uuid4()}"
    )
    mail = f"Hello, all users must sign in with SSO. Budget is capped at 2 MEUR. {uuid4()}"
    _, opp, (s1, s2) = parsed(client, sync_engine, db_url, ("call.txt", call), ("mail.txt", mail))
    gateway.replies = [
        out(
            ("Handle 400 totes per hour.", "functional", [("S1", "handle 400 totes per hour")]),
            ("Integrate with SAP EWM.", "integration", [("S1", "Integration with SAP EWM")]),
            ("Users sign in with SSO.", "security", [("S2", "all users must sign in with SSO")]),
        )
    ]

    with caplog.at_level(logging.DEBUG):
        assert drain(db_url, EXTRACT) == ["succeeded"]

    rows = requirements(sync_engine, opp["id"])
    assert [(r["text"], r["classification"]) for r in rows] == [
        ("Handle 400 totes per hour.", "functional"),
        ("Integrate with SAP EWM.", "integration"),
        ("Users sign in with SSO.", "security"),
    ]
    (extraction,) = extractions(sync_engine, opp["id"])
    for row in rows:
        assert (row["origin"], row["locked_by_human"], row["version"], row["row_version"]) == (
            "extracted",
            False,
            1,
            1,
        )
        assert row["extraction_id"] == extraction["id"]
    texts = {s1["id"]: stored_text(db_url, storage_dir, s1["id"])}
    texts[s2["id"]] = stored_text(db_url, storage_dir, s2["id"])
    expected = [
        (s1["id"], span(texts[s1["id"]], "handle 400 totes per hour")),
        (s1["id"], span(texts[s1["id"]], "Integration with SAP EWM")),
        (s2["id"], span(texts[s2["id"]], "all users must sign in with SSO")),
    ]
    for row, (source_id, (start, end)) in zip(rows, expected, strict=True):
        (passage,) = passages(sync_engine, row["id"])
        assert str(passage["source_id"]) == source_id and passage["source_version"] == 1
        assert (passage["start"], passage["end"]) == (start, end)

    assert extraction["status"] == "succeeded" and extraction["error_code"] is None
    assert (
        extraction["requirement_count"],
        extraction["dropped_count"],
        extraction["source_count"],
    ) == (3, 0, 2)
    assert extraction["finished_at"] is not None
    (event,) = completed_events(sync_engine, extraction["id"])
    assert event["payload"] == {"requirement_count": 3, "dropped_count": 0, "source_count": 2}
    assert (event["actor_type"], event["actor_id"]) == ("agent", "intake_agent@0.1.0")
    assert event["subject_type"] == "intake.extraction"
    assert str(event["opportunity_id"]) == opp["id"]

    # One model call: instructions as the system message, Sources only as data blocks.
    (request,) = gateway.requests
    system, user = request.messages
    assert (system.role, system.content) == ("system", prompt())
    assert call not in system.content and mail not in system.content
    assert user.role == "user"
    assert "<<<SOURCE S1 kind=note token=" in user.content and call in user.content
    assert "<<<SOURCE S2 kind=note token=" in user.content and mail in user.content
    assert request.caller.agent_id == "intake_agent"
    assert request.caller.config_version == "0.1.0"
    assert request.caller.run_id == extraction["id"]
    assert str(request.caller.opportunity_id) == opp["id"]
    assert (request.profile, request.priority) == ("demo-chat", "background")
    assert request.output_model is IntakeOutput

    # Privacy: no Source or Requirement text in logs or the trace.
    logged = caplog.text + str([r.__dict__ for r in caplog.records])
    for leak in ("totes", "SAP EWM", "SSO", "MEUR"):
        assert leak not in logged
        assert leak not in str(event)
    (job,) = jobs(sync_engine, opp["id"])
    assert (job["status"], job["last_error"]) == ("succeeded", None)


def test_a_quote_differing_in_whitespace_and_case_resolves_to_the_original_span(
    client: TestClient, sync_engine: Engine, db_url: str, storage_dir: Path, gateway: FakeGateway
) -> None:
    note = f"Intro.  The   System MUST\nsupport night shifts. {uuid4()}"
    _, opp, (s1,) = parsed(client, sync_engine, db_url, ("n.txt", note))
    gateway.replies = [
        out(("Night shifts.", "functional", [("S1", "the system must support night shifts")]))
    ]

    assert drain(db_url, EXTRACT) == ["succeeded"]

    text = stored_text(db_url, storage_dir, s1["id"])
    (row,) = requirements(sync_engine, opp["id"])
    (passage,) = passages(sync_engine, row["id"])
    start = text.index("The   System")
    assert (passage["start"], passage["end"]) == (start, text.index(" shifts.") + len(" shifts"))
    assert text[passage["start"] : passage["end"]] == "The   System MUST\nsupport night shifts"


def test_offsets_are_unicode_code_points(
    client: TestClient, sync_engine: Engine, db_url: str, storage_dir: Path, gateway: FakeGateway
) -> None:
    note = f"🚀🚀 Launch 🚀: the system must support 99.9% uptime. {uuid4()}"
    _, opp, (s1,) = parsed(client, sync_engine, db_url, ("n.txt", note))
    gateway.replies = [out(("99.9% uptime.", "non_functional", [("S1", "support 99.9% uptime")]))]

    assert drain(db_url, EXTRACT) == ["succeeded"]

    text = stored_text(db_url, storage_dir, s1["id"])
    (passage,) = passages(sync_engine, requirements(sync_engine, opp["id"])[0]["id"])
    start = text.index("support 99.9% uptime")
    assert (passage["start"], passage["end"]) == (start, start + len("support 99.9% uptime"))
    assert start == 29  # code points; UTF-16 would count each emoji twice
    assert len(text[:start].encode("utf-16-le")) // 2 == start + 3


def test_an_invented_quote_gets_one_retry_then_the_rest_is_kept(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    note = f"We need 3 shifts. Data stays in the EU. Payment in 30 days. {uuid4()}"
    _, opp, _ = parsed(client, sync_engine, db_url, ("n.txt", note))
    gateway.replies = [
        out(
            ("Three shifts.", "functional", [("S1", "We need 3 shifts")]),
            ("Invented.", "data", [("S1", "Keep backups for ten years")]),
            ("Net 30.", "commercial", [("S1", "Payment in 30 days")]),
        )
    ]

    assert drain(db_url, EXTRACT) == ["succeeded"]

    assert len(gateway.requests) == 2  # the first call and one retry, no more
    retry = gateway.requests[1].messages
    assert [m.role for m in retry] == ["system", "user", "assistant", "user"]
    assert "requirements[1]" in retry[3].content
    assert "requirements[0]" not in retry[3].content
    assert "backups" not in retry[3].content and "Invented" not in retry[3].content
    assert "Keep backups for ten years" in retry[2].content  # the previous reply

    rows = requirements(sync_engine, opp["id"])
    assert [r["text"] for r in rows] == ["Three shifts.", "Net 30."]
    (extraction,) = extractions(sync_engine, opp["id"])
    assert (extraction["requirement_count"], extraction["dropped_count"]) == (2, 1)
    (event,) = completed_events(sync_engine, extraction["id"])
    assert event["payload"]["dropped_count"] == 1


def test_the_retry_reply_is_what_gets_accepted(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    note = f"Pallets weigh up to 800 kg. {uuid4()}"
    _, opp, _ = parsed(client, sync_engine, db_url, ("n.txt", note))
    gateway.replies = [
        out(("800 kg pallets.", "functional", [("S1", "Pallets weigh 800 kg")])),
        out(("800 kg pallets.", "functional", [("S1", "Pallets weigh up to 800 kg")])),
    ]

    assert drain(db_url, EXTRACT) == ["succeeded"]

    assert len(gateway.requests) == 2
    assert [r["text"] for r in requirements(sync_engine, opp["id"])] == ["800 kg pallets."]
    (extraction,) = extractions(sync_engine, opp["id"])
    assert extraction["dropped_count"] == 0


def test_a_requirement_merged_across_sources_cites_both_passages(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp, (s1, s2) = parsed(
        client,
        sync_engine,
        db_url,
        ("call.txt", f"On the call: we must connect to SAP. {uuid4()}"),
        ("mail.txt", f"As discussed, SAP connectivity is a must. {uuid4()}"),
    )
    gateway.replies = [
        out(
            (
                "Connect to SAP.",
                "integration",
                [("S1", "we must connect to SAP"), ("S2", "SAP connectivity is a must")],
            )
        )
    ]

    assert drain(db_url, EXTRACT) == ["succeeded"]

    (row,) = requirements(sync_engine, opp["id"])
    cited = {str(p["source_id"]) for p in passages(sync_engine, row["id"])}
    assert cited == {s1["id"], s2["id"]}


def test_a_rerun_supersedes_extracted_requirements_but_not_locked_ones(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    note = f"The site runs 24/7. Peak is 900 orders per hour. {uuid4()}"
    _, opp, _ = parsed(client, sync_engine, db_url, ("n.txt", note))
    gateway.replies = [out(("Runs 24/7.", "non_functional", [("S1", "The site runs 24/7")]))]
    assert drain(db_url, EXTRACT) == ["succeeded"]
    (first,) = requirements(sync_engine, opp["id"])
    locked_id = uuid4()
    with sync_engine.begin() as conn:  # a human-locked Requirement (Story 2.6 makes these)
        conn.execute(
            sa.text(
                "INSERT INTO intake_requirements (id, opportunity_id, text, classification, "
                "origin, locked_by_human, status, version, row_version) VALUES "
                "(:i, :o, 'Locked one.', 'functional', 'extracted', true, 'active', 2, 3)"
            ),
            {"i": locked_id, "o": opp["id"]},
        )

    async def rerun() -> None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                await intake_extraction.enqueue_extraction(uow, opportunity_id=UUID(opp["id"]))
        finally:
            await engine.dispose()

    run_async(rerun())
    gateway.replies = [
        out(
            ("Runs 24/7.", "non_functional", [("S1", "The site runs 24/7")]),
            ("Peak 900 orders/hour.", "functional", [("S1", "Peak is 900 orders per hour")]),
        )
    ]
    assert drain(db_url, EXTRACT) == ["succeeded"]

    (old,) = requirements(sync_engine, opp["id"], "superseded")
    assert old["id"] == first["id"] and old["row_version"] == 2
    active = requirements(sync_engine, opp["id"])
    assert [r["text"] for r in active] == ["Locked one.", "Runs 24/7.", "Peak 900 orders/hour."]
    locked = next(r for r in active if r["id"] == locked_id)
    assert (locked["row_version"], locked["version"], locked["status"]) == (3, 2, "active")
    # The same span again reuses its immutable passage.
    assert (
        passages(sync_engine, active[1]["id"])[0]["id"]
        == passages(sync_engine, first["id"])[0]["id"]
    )
    second = extractions(sync_engine, opp["id"])[1]
    assert (second["status"], second["requirement_count"]) == ("succeeded", 2)


def test_a_duplicate_job_for_a_finished_extraction_does_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp, _ = parsed(client, sync_engine, db_url, ("n.txt", f"Needs a WMS. {uuid4()}"))
    gateway.replies = [out(("WMS.", "integration", [("S1", "Needs a WMS")]))]
    assert drain(db_url, EXTRACT) == ["succeeded"]
    (extraction,) = extractions(sync_engine, opp["id"])

    async def duplicate() -> None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                await intake_jobs.enqueue(
                    uow,
                    intake_extraction.ExtractRequirements(extraction_id=extraction["id"]),
                    opportunity_id=UUID(opp["id"]),
                )
        finally:
            await engine.dispose()

    run_async(duplicate())
    assert drain(db_url, EXTRACT) == ["succeeded"]
    assert len(gateway.requests) == 1
    assert len(requirements(sync_engine, opp["id"])) == 1
    assert len(completed_events(sync_engine, extraction["id"])) == 1


# --- failures -------------------------------------------------------------------------------


def test_input_over_the_budget_fails_without_a_model_call(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    budget = intake_extraction.input_budget_chars(32768)  # demo-chat
    big = ("Requirement text. " * (budget // 18 + 10))[: budget + 10]
    _, opp, _ = parsed(client, sync_engine, db_url, ("big.txt", f"{uuid4()} {big}"))
    gateway.replies = [out()]

    assert drain(db_url, EXTRACT) == ["succeeded"]  # permanent: no job retry

    assert gateway.requests == []
    (extraction,) = extractions(sync_engine, opp["id"])
    assert (extraction["status"], extraction["error_code"], extraction["source_count"]) == (
        "failed",
        "input_too_large",
        1,
    )
    assert completed_events(sync_engine, extraction["id"]) == []


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ModelUnavailableError("down", error_code="connection"), "model_unavailable"),
        (ModelTimeoutError("slow"), "model_timeout"),
        (ModelOutputInvalidError("cut", error_code="truncated"), "output_invalid"),
    ],
)
def test_a_gateway_error_retries_then_fails_the_extraction(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    error: Exception,
    code: str,
) -> None:
    _, opp, _ = parsed(client, sync_engine, db_url, ("n.txt", f"Needs a WMS. {uuid4()}"))
    gateway.replies = [error]

    assert drain(db_url, EXTRACT, max_runs=1) == ["failed_retrying"]
    assert extractions(sync_engine, opp["id"])[0]["status"] == "running"
    assert drain(db_url, EXTRACT) == ["dead"]

    (extraction,) = extractions(sync_engine, opp["id"])
    assert (extraction["status"], extraction["error_code"]) == ("failed", code)
    assert extraction["finished_at"] is not None
    (job,) = jobs(sync_engine, opp["id"])
    assert (job["status"], job["attempts"]) == ("dead", 2)
    assert "WMS" not in str(job["last_error"])
    assert requirements(sync_engine, opp["id"]) == []


def test_a_failing_retry_call_keeps_what_the_first_reply_resolved(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp, _ = parsed(client, sync_engine, db_url, ("n.txt", f"Needs a WMS. {uuid4()}"))
    gateway.replies = [
        out(
            ("WMS.", "integration", [("S1", "Needs a WMS")]),
            ("Invented.", "data", [("S1", "nothing like this")]),
        ),
        ModelUnavailableError("down"),
    ]

    assert drain(db_url, EXTRACT) == ["succeeded"]

    assert [r["text"] for r in requirements(sync_engine, opp["id"])] == ["WMS."]
    (extraction,) = extractions(sync_engine, opp["id"])
    assert (extraction["requirement_count"], extraction["dropped_count"]) == (1, 1)


def test_the_worker_loads_the_extraction_job_type() -> None:
    import app.main_worker as main_worker
    from app.platform.jobs import REGISTRY

    main_worker.load_job_types()
    spec = REGISTRY[EXTRACT]
    assert (spec.priority, spec.max_attempts) == ("background", 2)
    settings = Settings()
    # Two gateway calls (the first and the quote retry), each up to 1 + retries attempts.
    worst = 2 * (1 + settings.model_max_retries) * settings.model_timeout_s
    assert spec.timeout_s > worst


def test_with_no_readable_source_nothing_is_asked_or_replaced(
    client: TestClient, sync_engine: Engine, db_url: str, storage_dir: Path, gateway: FakeGateway
) -> None:
    _, opp, (s1,) = parsed(client, sync_engine, db_url, ("n.txt", f"Needs a WMS. {uuid4()}"))
    gateway.replies = [out(("WMS.", "integration", [("S1", "Needs a WMS")]))]
    assert drain(db_url, EXTRACT) == ["succeeded"]
    with sync_engine.connect() as conn:
        sha = conn.execute(
            sa.text("SELECT text_sha256 FROM intake_source_parses WHERE source_id = :s"),
            {"s": s1["id"]},
        ).scalar_one()
    BlobStore(storage_dir).path_for(sha).unlink()  # its text is gone

    async def rerun() -> None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                await intake_extraction.enqueue_extraction(uow, opportunity_id=UUID(opp["id"]))
        finally:
            await engine.dispose()

    run_async(rerun())
    assert drain(db_url, EXTRACT) == ["succeeded"]

    assert len(gateway.requests) == 1
    assert [r["text"] for r in requirements(sync_engine, opp["id"])] == ["WMS."]
    second = extractions(sync_engine, opp["id"])[1]
    assert (second["status"], second["requirement_count"], second["source_count"]) == (
        "succeeded",
        0,
        0,
    )


# --- review fixes ---------------------------------------------------------------------------


def _requeue(db_url: str, opp_id: str) -> None:
    async def scenario() -> None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                await intake_extraction.enqueue_extraction(uow, opportunity_id=UUID(opp_id))
        finally:
            await engine.dispose()

    run_async(scenario())


class _Hanging:
    async def complete_structured(self, request: StructuredRequest[Any]) -> Any:
        await asyncio.sleep(60)
        raise AssertionError("not reached")


@pytest.mark.parametrize(
    ("attempt", "status", "code"), [(2, "failed", "model_timeout"), (1, "running", None)]
)
def test_a_cancelled_run_is_recorded_as_timed_out_only_on_the_final_attempt(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    attempt: int,
    status: str,
    code: str | None,
) -> None:
    _, opp, _ = parsed(client, sync_engine, db_url, ("n.txt", f"Needs a WMS. {uuid4()}"))
    (job,) = jobs(sync_engine, opp["id"])
    provider.install(_Hanging())

    async def scenario() -> None:
        engine = create_engine(Settings(database_url=db_url))
        ctx = JobContext(
            job_id=job["id"],
            job_type=EXTRACT,
            attempt=attempt,
            max_attempts=2,
            opportunity_id=UUID(opp["id"]),
            engine=engine,
        )
        payload = intake_extraction.ExtractRequirements.model_validate(job["payload"])
        try:
            with pytest.raises(TimeoutError):  # the runner's job timeout, made short
                async with asyncio.timeout(1):
                    await intake_extraction.extract_requirements(ctx, payload)
        finally:
            await engine.dispose()

    run_async(scenario())

    (extraction,) = extractions(sync_engine, opp["id"])
    assert (extraction["status"], extraction["error_code"]) == (status, code)


def test_when_every_proposal_is_dropped_the_run_fails_and_replaces_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp, _ = parsed(client, sync_engine, db_url, ("n.txt", f"Needs a WMS. {uuid4()}"))
    gateway.replies = [out(("WMS.", "integration", [("S1", "Needs a WMS")]))]
    assert drain(db_url, EXTRACT) == ["succeeded"]
    _requeue(db_url, opp["id"])
    gateway.replies = [out(("Invented.", "data", [("S1", "nothing like this")]))]

    assert drain(db_url, EXTRACT) == ["succeeded"]  # the job is done; the run failed

    assert len(gateway.requests) == 3  # the first run, then a call and its retry
    assert [r["text"] for r in requirements(sync_engine, opp["id"])] == ["WMS."]
    assert requirements(sync_engine, opp["id"], "superseded") == []
    second = extractions(sync_engine, opp["id"])[1]
    assert (second["status"], second["error_code"], second["dropped_count"]) == (
        "failed",
        "output_invalid",
        1,
    )
    assert completed_events(sync_engine, second["id"]) == []


def test_an_older_run_accepted_after_a_newer_one_replaces_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, storage_dir: Path, gateway: FakeGateway
) -> None:
    note = f"Needs a WMS. Runs 24/7. {uuid4()}"
    _, opp, (s1,) = parsed(client, sync_engine, db_url, ("n.txt", note))
    (older,) = extractions(sync_engine, opp["id"])
    with sync_engine.begin() as conn:  # the older run is mid-call; its job is out of the way
        conn.execute(
            sa.text("UPDATE intake_extractions SET status = 'running' WHERE id = :e"),
            {"e": older["id"]},
        )
        conn.execute(
            sa.text(
                "UPDATE platform_jobs SET status = 'dead' WHERE opportunity_id = :o "
                "AND job_type = :t"
            ),
            {"o": opp["id"], "t": EXTRACT},
        )
    _requeue(db_url, opp["id"])
    gateway.replies = [out(("Runs 24/7.", "non_functional", [("S1", "Runs 24/7")]))]
    assert drain(db_url, EXTRACT) == ["succeeded"]  # the newer run

    late_result = AgentResult(
        confidence=0.5,
        confidence_basis="test",
        needs_human_review=True,
        extensions={"intake_agent": out(("WMS.", "integration", [("S1", "Needs a WMS")]))},
    )
    source = intake_extraction.ExtractionSource(
        label="S1",
        source_id=UUID(s1["id"]),
        version=1,
        kind="note",
        text=stored_text(db_url, storage_dir, s1["id"]),
    )

    async def accept_late() -> None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                await intake_extraction.accept_extraction(
                    uow,
                    extraction_id=older["id"],
                    result=late_result,
                    sources=[source],
                    actor=Actor(type="agent", id="intake_agent@0.1.0"),
                )
        finally:
            await engine.dispose()

    run_async(accept_late())

    assert [r["text"] for r in requirements(sync_engine, opp["id"])] == ["Runs 24/7."]
    first = extractions(sync_engine, opp["id"])[0]
    assert (first["status"], first["requirement_count"]) == ("succeeded", 0)
    (event,) = completed_events(sync_engine, first["id"])
    assert event["payload"]["requirement_count"] == 0


def test_a_retry_that_resolves_fewer_keeps_the_first_reply(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    note = f"We need 3 shifts. Payment in 30 days. {uuid4()}"
    _, opp, _ = parsed(client, sync_engine, db_url, ("n.txt", note))
    gateway.replies = [
        out(
            ("Three shifts.", "functional", [("S1", "We need 3 shifts")]),
            ("Invented.", "data", [("S1", "nothing like this")]),
            ("Net 30.", "commercial", [("S1", "Payment in 30 days")]),
        ),
        out(
            ("Three shifts.", "functional", [("S1", "We need three shifts")]),
            ("Invented.", "data", [("S1", "still nothing")]),
            ("Net 30.", "commercial", [("S1", "Payment in 30 days")]),
        ),
    ]

    assert drain(db_url, EXTRACT) == ["succeeded"]

    assert len(gateway.requests) == 2
    texts = [r["text"] for r in requirements(sync_engine, opp["id"])]
    assert texts == ["Three shifts.", "Net 30."]
    (extraction,) = extractions(sync_engine, opp["id"])
    assert (extraction["requirement_count"], extraction["dropped_count"]) == (2, 1)


def test_a_newer_version_that_failed_does_not_hide_the_parsed_one(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    note = f"Needs a WMS. {uuid4()}"
    headers, opp, (s1,) = parsed(client, sync_engine, db_url, ("n.txt", note))
    gateway.replies = [out(("WMS.", "integration", [("S1", "Needs a WMS")]))]
    assert drain(db_url, EXTRACT) == ["succeeded"]
    again = upload(client, headers, opp["id"], "again.txt", note)  # version 2 of the Source
    assert (again["id"], again["version"]) == (s1["id"], 2)
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE intake_source_parses SET status = 'failed', error_code = 'unreadable' "
                "WHERE source_id = :s AND version = 2"
            ),
            {"s": s1["id"]},
        )
    _requeue(db_url, opp["id"])

    assert drain(db_url, EXTRACT) == ["succeeded"]

    assert note in gateway.requests[-1].messages[1].content
    (row,) = requirements(sync_engine, opp["id"])
    (passage,) = passages(sync_engine, row["id"])
    assert passage["source_version"] == 1
    second = extractions(sync_engine, opp["id"])[1]
    assert (second["status"], second["source_count"]) == ("succeeded", 1)
