"""Gap detection (Story 4.3) against a real, migrated Postgres as psa_app: auto-queueing on
an accepted extraction, coalescing, the `gaps.detect_gaps` job with a fake ModelGateway,
`accept_gap_detection` (validation, supersede, links, questions, trace) and failures.

Reuses the fixtures of `test_intake_extraction.py`: jobs are scheduled a day ahead so no
other claimer takes them, and `drain` runs only the current test's Opportunities' jobs.
"""

import asyncio
import logging
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.agents.clarification_agent.agent import prompt
from app.agents.clarification_agent.schema import ClarificationOutput
from app.agents.contract import AgentResult
from app.modules.gaps.application import detection as gaps_detection
from app.modules.gaps.application import public as gaps
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
from tests import test_intake_extraction as extraction_tests
from tests.conftest import run_async
from tests.test_intake_extraction import (
    BASE,
    DETECT,
    EXTRACT,
    FakeGateway,
    drain,
    out,
    owner,
    parsed,
)

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client

NOTE = (
    "We must connect to SAP. The site runs 24/7. Peak is 900 orders per hour. "
    "Single sign-on is required. Pricing in EUR. "
)
ITEMS = (
    ("Connect to SAP.", "integration", [("S1", "We must connect to SAP")]),
    ("Runs 24/7.", "non_functional", [("S1", "The site runs 24/7")]),
    ("Peak 900 orders/hour.", "functional", [("S1", "Peak is 900 orders per hour")]),
    ("Single sign-on.", "security", [("S1", "Single sign-on is required")]),
    ("Prices in EUR.", "commercial", [("S1", "Pricing in EUR")]),
)


@pytest.fixture(autouse=True)
def _chat_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gaps_detection, "detection_settings", lambda: Settings(model_profile_chat="demo-chat")
    )


def gap(
    title: str,
    related: list[str],
    *,
    category: str = "integration_details",
    impact: str = "high",
    question: str | None = None,
    topic: str = "Interfaces",
) -> dict[str, Any]:
    return {
        "title": title,
        "category": category,
        "why_it_matters": f"Changes the effort for {title.lower()}.",
        "impact": impact,
        "impact_basis": "Drives the integration work package.",
        "related": related,
        "question": {
            "text": question or f"Could you tell us about {title.lower()}?",
            "topic": topic,
        },
    }


def gaps_out(*items: dict[str, Any]) -> ClarificationOutput:
    return ClarificationOutput.model_validate({"gaps": list(items)})


def extracted(
    client: TestClient, engine: Engine, db_url: str, gateway: FakeGateway, count: int = 5
) -> tuple[dict[str, str], dict[str, Any]]:
    """An Opportunity with `count` extracted Requirements (in `ITEMS` order, R1…), and its
    Gap detection queued."""
    headers, opp, _ = parsed(client, engine, db_url, ("n.txt", f"{NOTE}{uuid4()}"))
    gateway.replies = [out(*ITEMS[:count])]
    assert drain(db_url, EXTRACT) == ["succeeded"]
    return headers, opp


def rows(engine: Engine, sql: str, **params: Any) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(sa.text(sql), params).mappings()]


def detections(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM gaps_detections WHERE opportunity_id = :o ORDER BY created_at, id",
        o=opp_id,
    )


def detect_jobs(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM platform_jobs WHERE job_type = :t AND opportunity_id = :o "
        "ORDER BY created_at, id",
        t=DETECT,
        o=opp_id,
    )


def gap_rows(engine: Engine, opp_id: str, status: str = "open") -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM gaps_gaps WHERE opportunity_id = :o AND status = :s ORDER BY created_at, id",
        o=opp_id,
        s=status,
    )


def question_rows(engine: Engine, gap_id: Any) -> list[dict[str, Any]]:
    return rows(engine, "SELECT * FROM gaps_clarification_questions WHERE gap_id = :g", g=gap_id)


def link_rows(engine: Engine, gap_id: Any) -> list[dict[str, Any]]:
    return rows(engine, "SELECT * FROM gaps_gap_requirements WHERE gap_id = :g", g=gap_id)


def requirement_rows(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM intake_requirements WHERE opportunity_id = :o AND status = 'active' "
        "ORDER BY created_at, id",
        o=opp_id,
    )


def events(engine: Engine, opp_id: str, prefix: str = "gaps.") -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM platform_trace_events WHERE opportunity_id = :o "
        "AND event_type LIKE :p ORDER BY occurred_at, id",
        o=opp_id,
        p=f"{prefix}%",
    )


def requeue(db_url: str, opp_id: str) -> None:
    async def scenario() -> None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                await gaps.enqueue_detection(uow, UUID(opp_id))
        finally:
            await engine.dispose()

    run_async(scenario())


# --- queueing -------------------------------------------------------------------------------


def test_an_accepted_extraction_queues_one_detection(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp, _ = parsed(client, sync_engine, db_url, ("n.txt", f"{NOTE}{uuid4()}"))
    assert detections(sync_engine, opp["id"]) == []  # nothing before the extraction
    gateway.replies = [out(*ITEMS[:2])]

    assert drain(db_url, EXTRACT) == ["succeeded"]

    (detection,) = detections(sync_engine, opp["id"])
    (job,) = detect_jobs(sync_engine, opp["id"])
    assert job["payload"] == {"detection_id": str(detection["id"])}
    assert (job["status"], job["priority"]) == ("queued", 1)  # background
    assert (detection["status"], detection["error_code"], detection["gap_count"]) == (
        "queued",
        None,
        None,
    )


def test_extractions_while_one_detection_waits_coalesce(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = extracted(client, sync_engine, db_url, gateway, count=2)
    extraction_tests._requeue(db_url, opp["id"])
    gateway.replies = [out(*ITEMS[:3])]

    assert drain(db_url, EXTRACT) == ["succeeded"]

    assert len(detect_jobs(sync_engine, opp["id"])) == 1
    assert [d["status"] for d in detections(sync_engine, opp["id"])] == ["queued"]


def test_a_failed_extraction_queues_no_detection(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp, _ = parsed(client, sync_engine, db_url, ("n.txt", f"{NOTE}{uuid4()}"))
    gateway.replies = [ModelUnavailableError("down")]

    assert drain(db_url, EXTRACT) == ["failed_retrying", "dead"]

    assert detections(sync_engine, opp["id"]) == []


def test_the_worker_loads_the_detection_job_type() -> None:
    import app.main_worker as main_worker
    from app.platform.jobs import REGISTRY

    main_worker.load_job_types()
    spec = REGISTRY[DETECT]
    assert (spec.priority, spec.timeout_s, spec.max_attempts) == ("background", 900.0, 2)


# --- the happy path -------------------------------------------------------------------------


def test_detection_stores_ranked_gaps_with_drafted_questions(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, opp = extracted(client, sync_engine, db_url, gateway)
    reqs = requirement_rows(sync_engine, opp["id"])
    gateway.replies = [
        gaps_out(
            gap("SAP interface type", ["R1"], question="Which SAP interface do you use?"),
            gap("Peak growth", ["R3", "R2"], category="data_volumes", impact="medium"),
            gap("SSO provider", ["R4"], category="security_and_compliance", impact="low"),
            gap("Price indexation", ["R5"], category="commercial", impact="medium"),
        )
    ]

    with caplog.at_level(logging.DEBUG):
        assert drain(db_url, DETECT) == ["succeeded"]

    stored = gap_rows(sync_engine, opp["id"])
    assert [g["title"] for g in stored] == [
        "SAP interface type",
        "Peak growth",
        "SSO provider",
        "Price indexation",
    ]
    (detection,) = detections(sync_engine, opp["id"])
    assert (detection["status"], detection["gap_count"], detection["dropped_count"]) == (
        "succeeded",
        4,
        0,
    )
    assert detection["finished_at"] is not None
    first = stored[0]
    assert first["trigger"] == {"kind": "agent_category", "category": "integration_details"}
    assert (first["origin"], first["impact"], first["row_version"]) == ("detected", "high", 1)
    assert first["detection_id"] == detection["id"]
    for row in stored:
        (question,) = question_rows(sync_engine, row["id"])
        assert (question["status"], question["row_version"]) == ("drafted", 1)
        assert question["topic"] == "Interfaces"
    assert question_rows(sync_engine, first["id"])[0]["text"] == "Which SAP interface do you use?"
    links = link_rows(sync_engine, stored[1]["id"])
    assert {(link["requirement_id"], link["requirement_version"]) for link in links} == {
        (reqs[1]["id"], 1),
        (reqs[2]["id"], 1),
    }

    trace = events(sync_engine, opp["id"])
    types = [e["event_type"] for e in trace]
    assert types.count("gaps.gap.raised") == 4
    assert types.count("gaps.clarification_question.drafted") == 4
    (completed,) = [e for e in trace if e["event_type"] == "gaps.detection.completed"]
    assert completed["payload"] == {
        "gap_count": 4,
        "dropped_count": 0,
        "requirement_count": 5,
        "superseded_count": 0,
    }
    assert completed["subject_type"] == "gaps.detection"
    for event in trace:
        assert (event["actor_type"], event["actor_id"]) == ("agent", "clarification_agent@0.1.0")
    raised = next(e for e in trace if e["subject_id"] == first["id"])
    assert raised["payload"] == {
        "detection_id": str(detection["id"]),
        "category": "integration_details",
        "impact": "high",
        "requirement_ids": [str(reqs[0]["id"])],
    }

    # One model call: instructions as the system message, Requirements only as data blocks.
    (request,) = gateway.requests[-1:]
    system, user = request.messages
    assert (system.role, system.content) == ("system", prompt())
    assert "Connect to SAP." not in system.content
    assert "<<<REQUIREMENT R1 classification=integration token=" in user.content
    assert "<<<REQUIREMENT R5 classification=commercial token=" in user.content
    assert "Prices in EUR." in user.content
    assert request.caller.agent_id == "clarification_agent"
    assert request.caller.run_id == detection["id"]
    assert (request.profile, request.priority) == ("demo-chat", "background")
    assert request.output_model is ClarificationOutput

    # Privacy: no Requirement, Gap or question text in logs or the trace.
    logged = caplog.text + str([r.__dict__ for r in caplog.records])
    for leak in ("SAP", "sign-on", "EUR", "Peak growth", "interface do you use"):
        assert leak not in logged
        assert leak not in str(trace)


def test_a_candidate_citing_an_unknown_requirement_is_dropped(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = extracted(client, sync_engine, db_url, gateway)
    gateway.replies = [
        gaps_out(gap("SAP interface type", ["R1"]), gap("Invented", ["R99"]), gap("Uptime", ["R2"]))
    ]

    assert drain(db_url, DETECT) == ["succeeded"]

    assert [g["title"] for g in gap_rows(sync_engine, opp["id"])] == [
        "SAP interface type",
        "Uptime",
    ]
    (detection,) = detections(sync_engine, opp["id"])
    assert (detection["gap_count"], detection["dropped_count"]) == (2, 1)


def test_when_every_candidate_is_invalid_twice_the_detection_fails(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = extracted(client, sync_engine, db_url, gateway)
    gateway.replies = [gaps_out(gap("Invented", ["R99"]), gap("", ["R1"]))]

    assert drain(db_url, DETECT, max_runs=1) == ["failed_retrying"]
    assert detections(sync_engine, opp["id"])[0]["status"] == "running"
    assert drain(db_url, DETECT) == ["dead"]

    (detection,) = detections(sync_engine, opp["id"])
    assert (detection["status"], detection["error_code"]) == ("failed", "output_invalid")
    assert len(gateway.requests) == 1 + 2  # the extraction, then one call per attempt
    assert gap_rows(sync_engine, opp["id"]) == []
    (job,) = detect_jobs(sync_engine, opp["id"])
    assert (job["status"], job["attempts"]) == ("dead", 2)
    assert "Invented" not in str(job["last_error"])


def test_a_second_attempt_with_valid_candidates_succeeds(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = extracted(client, sync_engine, db_url, gateway)
    gateway.replies = [gaps_out(gap("Invented", ["R99"])), gaps_out(gap("Uptime", ["R2"]))]

    assert drain(db_url, DETECT) == ["failed_retrying", "succeeded"]

    assert [g["title"] for g in gap_rows(sync_engine, opp["id"])] == ["Uptime"]


def test_a_rerun_supersedes_the_earlier_gaps_and_their_questions(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = extracted(client, sync_engine, db_url, gateway)
    gateway.replies = [gaps_out(gap("SAP interface type", ["R1"]), gap("Uptime", ["R2"]))]
    assert drain(db_url, DETECT) == ["succeeded"]
    first = gap_rows(sync_engine, opp["id"])
    requeue(db_url, opp["id"])
    gateway.replies = [gaps_out(gap("SSO provider", ["R4"]))]

    assert drain(db_url, DETECT) == ["succeeded"]

    assert [g["title"] for g in gap_rows(sync_engine, opp["id"])] == ["SSO provider"]
    old = gap_rows(sync_engine, opp["id"], "superseded")
    assert {g["id"] for g in old} == {g["id"] for g in first}
    for row in old:
        assert row["row_version"] == 2
        (question,) = question_rows(sync_engine, row["id"])
        assert (question["status"], question["row_version"]) == ("superseded", 2)
    second = detections(sync_engine, opp["id"])[1]
    completed = [
        e
        for e in events(sync_engine, opp["id"])
        if e["event_type"] == "gaps.detection.completed" and e["subject_id"] == second["id"]
    ]
    assert completed[0]["payload"]["superseded_count"] == 2


def test_with_no_active_requirements_nothing_is_asked(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = owner(client, sync_engine)
    requeue(db_url, opp["id"])
    gateway.replies = [ModelUnavailableError("must not be called")]

    assert drain(db_url, DETECT) == ["succeeded"]

    assert gateway.requests == []
    (detection,) = detections(sync_engine, opp["id"])
    assert (detection["status"], detection["gap_count"], detection["dropped_count"]) == (
        "succeeded",
        0,
        0,
    )


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ModelUnavailableError("down", error_code="connection"), "model_unavailable"),
        (ModelTimeoutError("slow"), "model_timeout"),
        (ModelOutputInvalidError("cut", error_code="truncated"), "output_invalid"),
    ],
)
def test_a_gateway_error_retries_then_fails_the_detection(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    error: Exception,
    code: str,
) -> None:
    _, opp = extracted(client, sync_engine, db_url, gateway)
    gateway.replies = [error]

    assert drain(db_url, DETECT) == ["failed_retrying", "dead"]

    (detection,) = detections(sync_engine, opp["id"])
    assert (detection["status"], detection["error_code"]) == ("failed", code)
    assert detection["finished_at"] is not None
    assert gap_rows(sync_engine, opp["id"]) == []


def test_a_human_edited_requirement_is_linked_at_its_current_version(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = extracted(client, sync_engine, db_url, gateway, count=2)
    listed = client.get(f"{BASE}/{opp['id']}/requirements", headers=headers).json()["items"]
    edited = client.patch(
        f"{BASE}/{opp['id']}/requirements/{listed[0]['id']}",
        headers={**headers, "If-Match": f'"{listed[0]["row_version"]}"'},
        json={"text": "Connect to SAP EWM over IDocs."},
    )
    assert edited.status_code == 200, edited.text
    gateway.replies = [gaps_out(gap("IDoc types", ["R1"]))]

    assert drain(db_url, DETECT) == ["succeeded"]

    (row,) = gap_rows(sync_engine, opp["id"])
    (link,) = link_rows(sync_engine, row["id"])
    assert (str(link["requirement_id"]), link["requirement_version"]) == (listed[0]["id"], 2)
    assert "SAP EWM over IDocs" in gateway.requests[-1].messages[1].content


def test_an_older_detection_accepted_after_a_newer_one_replaces_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = extracted(client, sync_engine, db_url, gateway)
    (older,) = detections(sync_engine, opp["id"])
    reqs = requirement_rows(sync_engine, opp["id"])
    with sync_engine.begin() as conn:  # the older run is mid-call; its job is out of the way
        conn.execute(
            sa.text("UPDATE gaps_detections SET status = 'running' WHERE id = :d"),
            {"d": older["id"]},
        )
        conn.execute(
            sa.text(
                "UPDATE platform_jobs SET status = 'dead' WHERE opportunity_id = :o "
                "AND job_type = :t"
            ),
            {"o": opp["id"], "t": DETECT},
        )
    requeue(db_url, opp["id"])
    gateway.replies = [gaps_out(gap("Uptime", ["R2"]))]
    assert drain(db_url, DETECT) == ["succeeded"]  # the newer run

    late = AgentResult(
        confidence=0.5,
        confidence_basis="test",
        needs_human_review=True,
        extensions={"clarification_agent": gaps_out(gap("SAP interface type", ["R1"]))},
    )
    read = [
        gaps_detection.DetectionRequirement(
            label=f"R{n}",
            requirement_id=r["id"],
            version=r["version"],
            classification=r["classification"],
            text=r["text"],
        )
        for n, r in enumerate(reqs, start=1)
    ]

    async def accept_late() -> None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                await gaps_detection.accept_gap_detection(
                    uow,
                    detection_id=older["id"],
                    result=late,
                    requirements=read,
                    actor=Actor(type="agent", id="clarification_agent@0.1.0"),
                )
        finally:
            await engine.dispose()

    run_async(accept_late())

    assert [g["title"] for g in gap_rows(sync_engine, opp["id"])] == ["Uptime"]
    first = detections(sync_engine, opp["id"])[0]
    assert (first["status"], first["gap_count"]) == ("succeeded", 0)


# --- review fixes ---------------------------------------------------------------------------


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
    _, opp = extracted(client, sync_engine, db_url, gateway, count=2)
    (job,) = detect_jobs(sync_engine, opp["id"])
    provider.install(_Hanging())

    async def scenario() -> None:
        engine = create_engine(Settings(database_url=db_url))
        ctx = JobContext(
            job_id=job["id"],
            job_type=DETECT,
            attempt=attempt,
            max_attempts=2,
            opportunity_id=UUID(opp["id"]),
            engine=engine,
        )
        payload = gaps_detection.DetectGaps.model_validate(job["payload"])
        try:
            with pytest.raises(TimeoutError):  # the runner's job timeout, made short
                async with asyncio.timeout(1):
                    await gaps_detection.detect_gaps(ctx, payload)
        finally:
            await engine.dispose()

    run_async(scenario())

    (detection,) = detections(sync_engine, opp["id"])
    assert (detection["status"], detection["error_code"]) == (status, code)


def test_a_requirement_changed_after_the_read_drops_its_candidates(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = extracted(client, sync_engine, db_url, gateway, count=2)
    (detection,) = detections(sync_engine, opp["id"])
    with sync_engine.begin() as conn:  # the run has read the Requirements and is mid-call
        conn.execute(
            sa.text("UPDATE gaps_detections SET status = 'running' WHERE id = :d"),
            {"d": detection["id"]},
        )
    reqs = requirement_rows(sync_engine, opp["id"])
    read = [
        gaps_detection.DetectionRequirement(
            label=f"R{n}",
            requirement_id=r["id"],
            version=r["version"],
            classification=r["classification"],
            text=r["text"],
        )
        for n, r in enumerate(reqs, start=1)
    ]
    edited = client.patch(
        f"{BASE}/{opp['id']}/requirements/{reqs[0]['id']}",
        headers={**headers, "If-Match": f'"{reqs[0]["row_version"]}"'},
        json={"text": "Connect to SAP EWM over IDocs."},
    )
    assert edited.status_code == 200, edited.text
    result = AgentResult(
        confidence=0.5,
        confidence_basis="test",
        needs_human_review=True,
        extensions={
            "clarification_agent": gaps_out(
                gap("SAP interface type", ["R1"]), gap("Uptime window", ["R2"])
            )
        },
    )

    async def accept() -> None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                await gaps_detection.accept_gap_detection(
                    uow,
                    detection_id=detection["id"],
                    result=result,
                    requirements=read,
                    actor=Actor(type="agent", id="clarification_agent@0.1.0"),
                )
        finally:
            await engine.dispose()

    run_async(accept())

    (row,) = gap_rows(sync_engine, opp["id"])
    assert row["title"] == "Uptime window"
    (link,) = link_rows(sync_engine, row["id"])
    assert link["requirement_id"] == reqs[1]["id"]
    (finished,) = detections(sync_engine, opp["id"])
    assert (finished["status"], finished["gap_count"], finished["dropped_count"]) == (
        "succeeded",
        1,
        1,
    )


def test_queueing_fails_a_lost_detection_first(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp = extracted(client, sync_engine, db_url, gateway, count=2)
    with sync_engine.begin() as conn:  # its job died without recording it, long ago
        conn.execute(
            sa.text(
                "UPDATE gaps_detections SET created_at = now() - :age WHERE opportunity_id = :o"
            ),
            {"age": gaps_detection.stale_after() * 2, "o": opp["id"]},
        )

    requeue(db_url, opp["id"])

    lost, new = detections(sync_engine, opp["id"])
    assert (lost["status"], lost["error_code"]) == ("failed", "model_timeout")
    assert lost["finished_at"] is not None
    assert (new["status"], new["error_code"]) == ("queued", None)
    jobs = detect_jobs(sync_engine, opp["id"])
    assert len(jobs) == 2
    assert jobs[1]["payload"] == {"detection_id": str(new["id"])}
