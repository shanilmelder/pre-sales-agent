"""Estimate drafting (Story 8.1) against a real, migrated Postgres as psa_app: auto-queueing on
an accepted Gap detection, coalescing, the `estimates.draft_estimate` job with a fake
ModelGateway, `accept_draft` (validation, versions, links, counts, trace) and failures.

Reuses the fixtures of `test_intake_extraction.py`: jobs are scheduled a day ahead so no
other claimer takes them, and `drain` runs only the current test's Opportunities' jobs.
"""

import asyncio
import logging
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.agents.contract import AgentResult
from app.agents.estimating_agent.agent import prompt
from app.agents.estimating_agent.schema import EstimatingOutput
from app.modules.estimates.application import draft as estimates_draft
from app.modules.estimates.application import public as estimates
from app.platform.actor import Actor
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.jobs import JobContext
from app.platform.model_gateway import provider
from app.platform.model_gateway.port import (
    ModelOutputInvalidError,
    ModelTimeoutError,
    ModelUnavailableError,
    StructuredRequest,
)
from app.platform.uow import unit_of_work
from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests.conftest import run_async
from tests.test_gaps_detection import (
    extracted,
    gap,
    gaps_out,
    requirement_rows,
    rows,
)
from tests.test_intake_extraction import (
    BASE,
    DETECT,
    DRAFT,
    FakeGateway,
    drain,
    owner,
)

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile


@pytest.fixture(autouse=True)
def _draft_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        estimates_draft, "draft_settings", lambda: Settings(model_profile_chat="demo-chat")
    )


MIX = {"engineer": 60, "project_manager": 20, "qa": 20}


def est_line(
    title: str,
    covers: list[str],
    *,
    section: str = "integration",
    effort: float = 10.0,
    mix: dict[str, int] | None = None,
    basis: str | None = None,
) -> dict[str, Any]:
    return {
        "section": section,
        "title": title,
        "covers": covers,
        "effort_hours": effort,
        "role_mix": mix or MIX,
        "basis": basis or f"Sized from {title.lower()}.",
    }


def lines_out(*items: dict[str, Any]) -> EstimatingOutput:
    return EstimatingOutput.model_validate({"lines": list(items)})


def detected(
    client: TestClient,
    engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    count: int = 5,
    *,
    gap_titles: tuple[str, ...] = ("SAP interface type",),
) -> tuple[dict[str, str], dict[str, Any]]:
    """An Opportunity with `count` extracted Requirements (R1…), its Gaps detected (one per
    title, about R1), and its Estimate draft queued."""
    headers, opp = extracted(client, engine, db_url, gateway, count=count)
    gateway.replies = [gaps_out(*(gap(t, ["R1"]) for t in gap_titles))]
    assert drain(db_url, DETECT) == ["succeeded"]
    return headers, opp


def drafts(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM estimates_drafts WHERE opportunity_id = :o ORDER BY created_at, id",
        o=opp_id,
    )


def draft_jobs(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM platform_jobs WHERE job_type = :t AND opportunity_id = :o "
        "ORDER BY created_at, id",
        t=DRAFT,
        o=opp_id,
    )


def versions(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM estimates_estimate_versions WHERE opportunity_id = :o ORDER BY version",
        o=opp_id,
    )


def line_rows(engine: Engine, version_id: Any) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM estimates_estimate_lines WHERE version_id = :v ORDER BY position",
        v=version_id,
    )


def link_rows(engine: Engine, line_id: Any) -> list[dict[str, Any]]:
    return rows(engine, "SELECT * FROM estimates_line_requirements WHERE line_id = :l", l=line_id)


def events(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM platform_trace_events WHERE opportunity_id = :o "
        "AND event_type LIKE 'estimates.%' ORDER BY occurred_at, id",
        o=opp_id,
    )


def requeue(db_url: str, opp_id: str) -> None:
    async def scenario() -> None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                await estimates.enqueue_draft(uow, UUID(opp_id))
        finally:
            await engine.dispose()

    run_async(scenario())


SIX = (
    est_line("SAP order interface", ["R1"], effort=40.0),
    est_line("24/7 operations", ["R2"], section="non_functional", effort=16.0),
    est_line("Order throughput", ["R3"], section="functional", effort=24.5),
    est_line("Single sign-on", ["R4"], section="security", effort=12.0),
    est_line("Commercial set-up", ["R5"], section="commercial", effort=6.0),
    est_line("Project management", ["R1", "R2", "R3", "R4", "R5"], section="commercial"),
)


# --- queueing -------------------------------------------------------------------------------


def test_an_accepted_gap_detection_queues_one_draft(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = extracted(client, sync_engine, db_url, gateway, count=2)
    assert drafts(sync_engine, opp["id"]) == []  # nothing before the detection
    gateway.replies = [gaps_out(gap("SAP interface type", ["R1"]))]

    assert drain(db_url, DETECT) == ["succeeded"]

    (draft,) = drafts(sync_engine, opp["id"])
    (job,) = draft_jobs(sync_engine, opp["id"])
    assert job["payload"] == {"draft_id": str(draft["id"])}
    assert (job["status"], job["priority"]) == ("queued", 1)  # background
    assert (draft["status"], draft["error_code"], draft["finished_at"]) == ("queued", None, None)


def test_detections_while_one_draft_waits_coalesce(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = detected(client, sync_engine, db_url, gateway, count=2)
    detection_tests.requeue(db_url, opp["id"])
    gateway.replies = [gaps_out(gap("Uptime", ["R2"]))]

    assert drain(db_url, DETECT) == ["succeeded"]

    assert len(draft_jobs(sync_engine, opp["id"])) == 1
    assert [d["status"] for d in drafts(sync_engine, opp["id"])] == ["queued"]


def test_a_failed_gap_detection_queues_no_draft(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = extracted(client, sync_engine, db_url, gateway, count=2)
    gateway.replies = [ModelUnavailableError("down")]

    assert drain(db_url, DETECT) == ["failed_retrying", "dead"]

    assert drafts(sync_engine, opp["id"]) == []


def test_the_worker_loads_the_draft_job_type() -> None:
    import app.main_worker as main_worker
    from app.platform.jobs import REGISTRY

    main_worker.load_job_types()
    spec = REGISTRY[DRAFT]
    assert (spec.priority, spec.timeout_s, spec.max_attempts) == ("background", 900.0, 2)


# --- the happy path -------------------------------------------------------------------------


def test_a_draft_stores_version_1_with_lines_links_and_one_event(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, opp = detected(client, sync_engine, db_url, gateway, gap_titles=("Peak growth",))
    reqs = requirement_rows(sync_engine, opp["id"])
    gateway.replies = [lines_out(*SIX)]

    with caplog.at_level(logging.DEBUG):
        assert drain(db_url, DRAFT) == ["succeeded"]

    (version,) = versions(sync_engine, opp["id"])
    assert (version["version"], version["status"], version["template_version"]) == (
        1,
        "draft",
        "demo-1",
    )
    assert (version["uncovered_count"], version["dropped_count"], version["row_version"]) == (
        0,
        0,
        1,
    )
    stored = line_rows(sync_engine, version["id"])
    assert [(r["position"], r["title"]) for r in stored] == [
        (n, item["title"]) for n, item in enumerate(SIX, start=1)
    ]
    first = stored[0]
    assert (first["section"], str(first["effort_hours"])) == ("integration", "40.0")
    assert first["role_mix"] == MIX
    assert first["basis"] == "Sized from sap order interface."
    assert str(stored[2]["effort_hours"]) == "24.5"
    (link,) = link_rows(sync_engine, first["id"])
    assert (link["requirement_id"], link["requirement_version"]) == (reqs[0]["id"], 1)
    assert {r["requirement_id"] for r in link_rows(sync_engine, stored[5]["id"])} == {
        r["id"] for r in reqs
    }
    (draft,) = drafts(sync_engine, opp["id"])
    assert (draft["status"], draft["error_code"]) == ("succeeded", None)
    assert draft["finished_at"] is not None

    (event,) = events(sync_engine, opp["id"])
    assert event["event_type"] == "estimates.estimate_version.created"
    assert (event["subject_type"], event["subject_id"]) == (
        "estimates.estimate_version",
        version["id"],
    )
    assert (event["actor_type"], event["actor_id"]) == ("agent", "estimating_agent@0.1.0")
    assert event["payload"] == {
        "version": 1,
        "template_version": "demo-1",
        "line_count": 6,
        "dropped_count": 0,
        "uncovered_count": 0,
        "requirement_count": 5,
        "superseded_count": 0,
        "carried_assumption_count": 0,  # a first draft carries nothing
        "carried_edit_count": 0,
        "uncarried_edit_count": 0,
    }

    # One model call: instructions as the system message, Requirements and Gaps only as
    # data blocks.
    request = gateway.requests[-1]
    system, user = request.messages
    assert (system.role, system.content) == ("system", prompt())
    assert "<<<REQUIREMENT R1 classification=integration token=" in user.content
    assert "<<<REQUIREMENT R5 classification=commercial token=" in user.content
    assert "<<<GAP G1 category=integration_details impact=high token=" in user.content
    assert "Peak growth" in user.content
    assert "Prices in EUR." in user.content
    assert request.caller.agent_id == "estimating_agent"
    assert request.caller.run_id == draft["id"]
    assert (request.profile, request.priority) == ("demo-chat", "background")
    assert request.output_model is EstimatingOutput

    # Privacy: no Requirement, Gap or line text in logs or the trace.
    logged = caplog.text + str([r.__dict__ for r in caplog.records])
    for leak in ("SAP", "sign-on", "EUR", "Peak growth", "Order throughput", "Sized from"):
        assert leak not in logged
        assert leak not in str(events(sync_engine, opp["id"]))


def test_invalid_lines_are_dropped_and_uncovered_requirements_counted(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = detected(client, sync_engine, db_url, gateway)
    gateway.replies = [
        lines_out(
            est_line("SAP order interface", ["R1"]),
            est_line("Bad mix", ["R2"], mix={"engineer": 60, "project_manager": 20, "qa": 10}),
            est_line("Bad label", ["R99"]),
            est_line("Throughput", ["R3", "R99"], section="functional"),
            est_line("Single sign-on", ["R4"], section="security"),
        )
    ]

    assert drain(db_url, DRAFT) == ["succeeded"]

    (version,) = versions(sync_engine, opp["id"])
    assert [r["title"] for r in line_rows(sync_engine, version["id"])] == [
        "SAP order interface",
        "Throughput",
        "Single sign-on",
    ]
    # R2 (its line dropped) and R5 (never covered).
    assert (version["dropped_count"], version["uncovered_count"]) == (2, 2)


def test_when_every_line_is_invalid_twice_the_draft_fails(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = detected(client, sync_engine, db_url, gateway)
    requests_before = len(gateway.requests)
    gateway.replies = [
        lines_out(
            est_line("Bad label", ["R99"]),
            est_line("Bad mix", ["R1"], mix={"engineer": 60, "project_manager": 20, "qa": 10}),
        )
    ]

    assert drain(db_url, DRAFT, max_runs=1) == ["failed_retrying"]
    assert drafts(sync_engine, opp["id"])[0]["status"] == "running"
    assert drain(db_url, DRAFT) == ["dead"]

    (draft,) = drafts(sync_engine, opp["id"])
    assert (draft["status"], draft["error_code"]) == ("failed", "output_invalid")
    assert len(gateway.requests) == requests_before + 2  # one call per attempt
    assert versions(sync_engine, opp["id"]) == []
    (job,) = draft_jobs(sync_engine, opp["id"])
    assert (job["status"], job["attempts"]) == ("dead", 2)
    assert "Bad label" not in str(job["last_error"])
    assert events(sync_engine, opp["id"]) == []


def test_an_empty_reply_is_invalid_and_retried(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = detected(client, sync_engine, db_url, gateway)
    gateway.replies = [lines_out(), lines_out(est_line("SAP order interface", ["R1"]))]

    assert drain(db_url, DRAFT) == ["failed_retrying", "succeeded"]

    (version,) = versions(sync_engine, opp["id"])
    assert version["uncovered_count"] == 4


def test_a_redraft_supersedes_the_earlier_version(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = detected(client, sync_engine, db_url, gateway)
    gateway.replies = [lines_out(*SIX)]
    assert drain(db_url, DRAFT) == ["succeeded"]
    requeue(db_url, opp["id"])
    gateway.replies = [lines_out(est_line("Everything", ["R1", "R2", "R3", "R4", "R5"]))]

    assert drain(db_url, DRAFT) == ["succeeded"]

    v1, v2 = versions(sync_engine, opp["id"])
    assert (v1["version"], v1["status"], v1["row_version"]) == (1, "superseded", 2)
    assert (v2["version"], v2["status"], v2["row_version"]) == (2, "draft", 1)
    assert len(line_rows(sync_engine, v1["id"])) == 6  # kept, read-only
    assert [r["title"] for r in line_rows(sync_engine, v2["id"])] == ["Everything"]
    created = [e["payload"] for e in events(sync_engine, opp["id"])]
    assert [(p["version"], p["superseded_count"]) for p in created] == [(1, 0), (2, 1)]
    assert [p["carried_assumption_count"] for p in created] == [0, 0]  # nothing accepted


def test_with_no_active_requirements_nothing_is_asked(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = owner(client, sync_engine)
    requeue(db_url, opp["id"])
    gateway.replies = [ModelUnavailableError("must not be called")]

    assert drain(db_url, DRAFT) == ["succeeded"]

    assert gateway.requests == []
    (draft,) = drafts(sync_engine, opp["id"])
    assert draft["status"] == "succeeded"
    assert versions(sync_engine, opp["id"]) == []


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ModelUnavailableError("down", error_code="connection"), "model_unavailable"),
        (ModelTimeoutError("slow"), "model_timeout"),
        (ModelOutputInvalidError("cut", error_code="truncated"), "output_invalid"),
    ],
)
def test_a_gateway_error_retries_then_fails_the_draft(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    error: Exception,
    code: str,
) -> None:
    _, opp = detected(client, sync_engine, db_url, gateway)
    gateway.replies = [error]

    assert drain(db_url, DRAFT) == ["failed_retrying", "dead"]

    (draft,) = drafts(sync_engine, opp["id"])
    assert (draft["status"], draft["error_code"]) == ("failed", code)
    assert draft["finished_at"] is not None
    assert versions(sync_engine, opp["id"]) == []


def _read(engine: Engine, opp_id: str) -> list[estimates_draft.DraftRequirement]:
    return [
        estimates_draft.DraftRequirement(
            label=f"R{n}",
            requirement_id=r["id"],
            version=r["version"],
            classification=r["classification"],
            text=r["text"],
        )
        for n, r in enumerate(requirement_rows(engine, opp_id), start=1)
    ]


def _accept(db_url: str, draft_id: Any, output: EstimatingOutput, read: list[Any]) -> None:
    result = AgentResult(
        confidence=0.5,
        confidence_basis="test",
        needs_human_review=True,
        extensions={"estimating_agent": output},
    )

    async def scenario() -> None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                await estimates_draft.accept_draft(
                    uow,
                    draft_id=draft_id,
                    result=result,
                    requirements=read,
                    actor=Actor(type="agent", id="estimating_agent@0.1.0"),
                )
        finally:
            await engine.dispose()

    run_async(scenario())


def test_an_older_draft_accepted_after_a_newer_one_writes_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = detected(client, sync_engine, db_url, gateway)
    (older,) = drafts(sync_engine, opp["id"])
    read = _read(sync_engine, opp["id"])
    with sync_engine.begin() as conn:  # the older run is mid-call; its job is out of the way
        conn.execute(
            sa.text("UPDATE estimates_drafts SET status = 'running' WHERE id = :d"),
            {"d": older["id"]},
        )
        conn.execute(
            sa.text(
                "UPDATE platform_jobs SET status = 'dead' WHERE opportunity_id = :o "
                "AND job_type = :t"
            ),
            {"o": opp["id"], "t": DRAFT},
        )
    requeue(db_url, opp["id"])
    gateway.replies = [lines_out(est_line("Newer", ["R1"]))]
    assert drain(db_url, DRAFT) == ["succeeded"]  # the newer run

    _accept(db_url, older["id"], lines_out(est_line("Older", ["R1"])), read)

    (version,) = versions(sync_engine, opp["id"])
    assert [r["title"] for r in line_rows(sync_engine, version["id"])] == ["Newer"]
    assert drafts(sync_engine, opp["id"])[0]["status"] == "succeeded"


def test_an_outdated_draft_with_an_invalid_reply_succeeds_and_writes_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = detected(client, sync_engine, db_url, gateway)
    (older,) = drafts(sync_engine, opp["id"])
    read = _read(sync_engine, opp["id"])
    with sync_engine.begin() as conn:  # the older run is mid-call; its job is out of the way
        conn.execute(
            sa.text("UPDATE estimates_drafts SET status = 'running' WHERE id = :d"),
            {"d": older["id"]},
        )
        conn.execute(
            sa.text(
                "UPDATE platform_jobs SET status = 'dead' WHERE opportunity_id = :o "
                "AND job_type = :t"
            ),
            {"o": opp["id"], "t": DRAFT},
        )
    requeue(db_url, opp["id"])
    gateway.replies = [lines_out(est_line("Newer", ["R1"]))]
    assert drain(db_url, DRAFT) == ["succeeded"]  # the newer run

    _accept(db_url, older["id"], lines_out(), read)  # empty: invalid if it were current

    (version,) = versions(sync_engine, opp["id"])
    assert [r["title"] for r in line_rows(sync_engine, version["id"])] == ["Newer"]
    assert len(events(sync_engine, opp["id"])) == 1
    assert drafts(sync_engine, opp["id"])[0]["status"] == "succeeded"


def test_lines_and_links_are_insert_only_for_psa_app(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = detected(client, sync_engine, db_url, gateway, count=2)
    gateway.replies = [lines_out(est_line("SAP order interface", ["R1"]))]
    assert drain(db_url, DRAFT) == ["succeeded"]
    (version,) = versions(sync_engine, opp["id"])
    (row,) = line_rows(sync_engine, version["id"])
    denied = [
        ("UPDATE estimates_estimate_lines SET title = 'x' WHERE id = :i", row["id"]),
        ("DELETE FROM estimates_estimate_lines WHERE id = :i", row["id"]),
        (
            "UPDATE estimates_line_requirements SET requirement_version = 9 WHERE line_id = :i",
            row["id"],
        ),
        ("DELETE FROM estimates_line_requirements WHERE line_id = :i", row["id"]),
        ("DELETE FROM estimates_estimate_versions WHERE id = :i", version["id"]),
        ("DELETE FROM estimates_drafts WHERE opportunity_id = :i", opp["id"]),
    ]
    for sql, value in denied:
        with pytest.raises(sa.exc.ProgrammingError), sync_engine.begin() as conn:
            conn.execute(sa.text(sql), {"i": value})


def test_a_requirement_changed_after_the_read_is_not_covered(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway, count=2)
    (draft,) = drafts(sync_engine, opp["id"])
    with sync_engine.begin() as conn:  # the run has read the Requirements and is mid-call
        conn.execute(
            sa.text("UPDATE estimates_drafts SET status = 'running' WHERE id = :d"),
            {"d": draft["id"]},
        )
    read = _read(sync_engine, opp["id"])
    reqs = requirement_rows(sync_engine, opp["id"])
    edited = client.patch(
        f"{BASE}/{opp['id']}/requirements/{reqs[0]['id']}",
        headers={**headers, "If-Match": f'"{reqs[0]["row_version"]}"'},
        json={"text": "Connect to SAP EWM over IDocs."},
    )
    assert edited.status_code == 200, edited.text

    _accept(
        db_url,
        draft["id"],
        lines_out(est_line("SAP order interface", ["R1"]), est_line("Uptime", ["R2"])),
        read,
    )

    (version,) = versions(sync_engine, opp["id"])
    (row,) = line_rows(sync_engine, version["id"])
    assert row["title"] == "Uptime"
    assert (version["dropped_count"], version["uncovered_count"]) == (1, 1)


# --- review-style edges ---------------------------------------------------------------------


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
    _, opp = detected(client, sync_engine, db_url, gateway, count=2)
    (job,) = draft_jobs(sync_engine, opp["id"])
    provider.install(_Hanging())

    async def scenario() -> None:
        engine = create_engine(Settings(database_url=db_url))
        ctx = JobContext(
            job_id=job["id"],
            job_type=DRAFT,
            attempt=attempt,
            max_attempts=2,
            opportunity_id=UUID(opp["id"]),
            engine=engine,
        )
        payload = estimates_draft.DraftEstimate.model_validate(job["payload"])
        try:
            with pytest.raises(TimeoutError):  # the runner's job timeout, made short
                async with asyncio.timeout(1):
                    await estimates_draft.draft_estimate(ctx, payload)
        finally:
            await engine.dispose()

    run_async(scenario())

    (draft,) = drafts(sync_engine, opp["id"])
    assert (draft["status"], draft["error_code"]) == (status, code)


def test_queueing_fails_a_lost_draft_first(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = detected(client, sync_engine, db_url, gateway, count=2)
    with sync_engine.begin() as conn:  # its job died without recording it, long ago
        conn.execute(
            sa.text(
                "UPDATE estimates_drafts SET created_at = now() - :age WHERE opportunity_id = :o"
            ),
            {"age": estimates_draft.stale_after() * 2, "o": opp["id"]},
        )

    requeue(db_url, opp["id"])

    lost, new = drafts(sync_engine, opp["id"])
    assert (lost["status"], lost["error_code"]) == ("failed", "model_timeout")
    assert (new["status"], new["error_code"]) == ("queued", None)
    assert len(draft_jobs(sync_engine, opp["id"])) == 2
