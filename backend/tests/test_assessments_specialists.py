"""Specialist assessment runs (Epic 5 slice 5A) against a real, migrated Postgres as psa_app:
the `assessments.run_assessment` job with a fake ModelGateway that answers per agent and
records each call's time window, `accept_assessment` (validation, versions, links, effort,
trace), partial failure, task retry, re-runs, cancelling (Story 5.5), privacy and the table
grants.

Reuses the fixtures of `test_intake_extraction.py`: jobs are scheduled a day ahead so no
other claimer takes them, and `drain` runs only the current test's Opportunities' jobs.
"""

import asyncio
import logging
import time
from collections import defaultdict
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.engine import Engine

from app.agents.contract import AgentResult
from app.agents.engineering_agent.agent import prompt as engineering_prompt
from app.agents.engineering_agent.schema import EngineeringOutput
from app.agents.pm_agent.agent import prompt as pm_prompt
from app.agents.security_agent.agent import prompt as security_prompt
from app.agents.specialist.schema import SpecialistOutput
from app.modules.assessments.application import assessment as assessments_assessment
from app.modules.assessments.domain.assessments import AssessmentAgent
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
    StructuredResult,
)
from app.platform.uow import unit_of_work
from tests import test_estimates_draft as draft_tests
from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests.conftest import run_async
from tests.test_estimates_draft import detected
from tests.test_gaps_detection import requirement_rows, rows
from tests.test_intake_extraction import ASSESS, BASE, FakeGateway, drain, owner

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile
_draft_profile = draft_tests._draft_profile

AGENTS = ("engineering_agent", "pm_agent", "security_agent")


@pytest.fixture(autouse=True)
def _assessment_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        assessments_assessment,
        "assessment_settings",
        lambda: Settings(model_profile_chat="demo-chat"),
    )


# --- the per-agent fake gateway -------------------------------------------------------------

Reply = BaseModel | Exception | Callable[[StructuredRequest[Any]], BaseModel]


class AgentGateway:
    """Answers `complete_structured` from `replies[agent_id]` in order (the last one
    repeats), after a short sleep, and records each call's time window per agent."""

    def __init__(self, replies: Mapping[str, list[Reply]], *, delay_s: float = 0.2) -> None:
        self.replies = {agent: list(queue) for agent, queue in replies.items()}
        self.requests: list[StructuredRequest[Any]] = []
        self.windows: dict[str, list[tuple[float, float]]] = defaultdict(list)
        self.delay_s = delay_s

    def calls(self, agent: str) -> int:
        return sum(1 for r in self.requests if r.caller.agent_id == agent)

    async def complete_structured(self, request: StructuredRequest[Any]) -> StructuredResult[Any]:
        agent = request.caller.agent_id
        self.requests.append(request)
        started = time.monotonic()
        await asyncio.sleep(self.delay_s)
        queue = self.replies[agent]
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        self.windows[agent].append((started, time.monotonic()))
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


def finding(
    title: str,
    requirements: list[str],
    *,
    kind: str = "risk",
    severity: str = "high",
    detail: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "severity": severity,
        "title": title,
        "detail": detail or f"Nothing shows {title.lower()} is settled.",
        "requirements": requirements,
    }


def effort(requirement: str, hours: float, basis: str | None = None) -> dict[str, Any]:
    return {"requirement": requirement, "hours": hours, "basis": basis or f"Sized {requirement}."}


def assessment_out(
    *findings: dict[str, Any],
    efforts: tuple[dict[str, Any], ...] = (),
    recommendation: str = "proceed_with_conditions",
    confidence: str = "medium",
    basis: str = "Volumes are known; the interface details are not.",
) -> SpecialistOutput:
    return SpecialistOutput.model_validate(
        {
            "recommendation": recommendation,
            "confidence": confidence,
            "confidence_basis": basis,
            "findings": list(findings),
            "effort": list(efforts),
        }
    )


ENGINEERING = assessment_out(
    finding("SAP IDoc custom fields not specified", ["R1"], severity="critical"),
    finding("Peak 900 orders/hour — no seasonal profile", ["R3"], kind="constraint"),
    finding("Uptime target needs redundant controls", ["R2", "R1"], severity="medium"),
    efforts=(effort("R3", 24.25), effort("R1", 40)),
)
PM = assessment_out(
    finding("Customer IT not named as interface counterpart", ["R1"], kind="dependency"),
    finding("24/7 go-live needs a hypercare rota", ["R2"], severity="low"),
    finding("EUR pricing set before hardware quotes", ["R5"], severity="medium"),
    efforts=(effort("R1", 16), effort("R2", 8), effort("R5", 2.5)),
    recommendation="proceed",
    confidence="high",
)
SECURITY = assessment_out(
    finding("Single sign-on — identity provider not named", ["R4"], kind="dependency"),
    finding("Remote access to controls during 24/7 operation", ["R2"]),
    finding("SAP connection credentials ownership unclear", ["R1"], severity="low"),
    efforts=(),
    confidence="low",
)


def replies(**overrides: list[Reply]) -> dict[str, list[Reply]]:
    base: dict[str, list[Reply]] = {
        "engineering_agent": [ENGINEERING],
        "pm_agent": [PM],
        "security_agent": [SECURITY],
    }
    base.update(overrides)
    return base


# --- helpers --------------------------------------------------------------------------------


def prepared(
    client: TestClient, engine: Engine, db_url: str, gateway: FakeGateway, count: int = 5
) -> tuple[dict[str, str], dict[str, Any]]:
    """An Opportunity with `count` Requirements (R1…) and one open Gap about R1."""
    return detected(client, engine, db_url, gateway, count=count)


def install(fake: AgentGateway) -> AgentGateway:
    provider.install(fake)
    return fake


def start(client: TestClient, headers: dict[str, str], opp_id: str) -> Any:
    return client.post(f"{BASE}/{opp_id}/assessment-runs", headers=headers)


def retry(client: TestClient, headers: dict[str, str], opp_id: str, run_id: str, agent: str) -> Any:
    return client.post(
        f"{BASE}/{opp_id}/assessment-runs/{run_id}/tasks/{agent}/retry", headers=headers
    )


def cancel(client: TestClient, headers: dict[str, str], opp_id: str, run_id: str) -> Any:
    return client.post(f"{BASE}/{opp_id}/assessment-runs/{run_id}/cancel", headers=headers)


def run_rows(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM assessments_runs WHERE opportunity_id = :o ORDER BY created_at, id",
        o=opp_id,
    )


def task_rows(engine: Engine, run_id: Any) -> dict[str, dict[str, Any]]:
    return {
        r["agent"]: r
        for r in rows(engine, "SELECT * FROM assessments_tasks WHERE run_id = :r", r=run_id)
    }


def assessment_rows(engine: Engine, opp_id: str, agent: str | None = None) -> list[dict[str, Any]]:
    found = rows(
        engine,
        "SELECT * FROM assessments_assessments WHERE opportunity_id = :o ORDER BY agent, version",
        o=opp_id,
    )
    return [r for r in found if agent is None or r["agent"] == agent]


def current(engine: Engine, opp_id: str, agent: str) -> dict[str, Any]:
    (row,) = [r for r in assessment_rows(engine, opp_id, agent) if r["status"] == "current"]
    return row


def finding_rows(engine: Engine, assessment_id: Any) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM assessments_assessment_findings WHERE assessment_id = :a ORDER BY position",
        a=assessment_id,
    )


def link_rows(engine: Engine, finding_id: Any) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM assessments_assessment_finding_requirements WHERE finding_id = :f",
        f=finding_id,
    )


def effort_rows(engine: Engine, assessment_id: Any) -> list[dict[str, Any]]:
    return rows(
        engine, "SELECT * FROM assessments_effort WHERE assessment_id = :a", a=assessment_id
    )


def assess_jobs(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM platform_jobs WHERE job_type = :t AND opportunity_id = :o "
        "ORDER BY created_at, id",
        t=ASSESS,
        o=opp_id,
    )


def events(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM platform_trace_events WHERE opportunity_id = :o "
        "AND event_type LIKE 'assessments.assessment%' ORDER BY occurred_at, id",
        o=opp_id,
    )


def started(client: TestClient, headers: dict[str, str], opp_id: str) -> dict[str, Any]:
    response = start(client, headers, opp_id)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


# --- the happy path -------------------------------------------------------------------------


def test_the_worker_loads_the_job_type_and_three_model_slots_are_the_default() -> None:
    import app.main_worker as main_worker
    from app.platform.jobs import REGISTRY

    main_worker.load_job_types()
    spec = REGISTRY[ASSESS]
    assert (spec.priority, spec.timeout_s, spec.max_attempts) == ("background", 900.0, 2)
    assert Settings.model_fields["model_slots"].default == 3


def test_a_run_stores_three_assessments_with_findings_effort_and_trace(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    reqs = requirement_rows(sync_engine, opp["id"])
    fake = install(AgentGateway(replies()))

    body = started(client, headers, opp["id"])

    assert body["status"] == "queued"
    assert [(t["agent"], t["status"], t["error_code"]) for t in body["tasks"]] == [
        (agent, "queued", None) for agent in AGENTS
    ]
    (job,) = assess_jobs(sync_engine, opp["id"])
    assert job["payload"] == {"run_id": body["id"]}
    assert (job["status"], job["priority"]) == ("queued", 1)  # background

    with caplog.at_level(logging.DEBUG):
        assert drain(db_url, ASSESS) == ["succeeded"]

    (run,) = run_rows(sync_engine, opp["id"])
    assert (run["status"], str(run["id"])) == ("succeeded", body["id"])
    assert run["finished_at"] is not None
    tasks = task_rows(sync_engine, run["id"])
    assert {a: (t["status"], t["error_code"]) for a, t in tasks.items()} == {
        a: ("succeeded", None) for a in AGENTS
    }
    assert all(t["started_at"] and t["finished_at"] for t in tasks.values())

    engineering = current(sync_engine, opp["id"], "engineering_agent")
    assert (engineering["version"], engineering["run_id"]) == (1, run["id"])
    assert (engineering["recommendation"], engineering["confidence"]) == (
        "proceed_with_conditions",
        "medium",
    )
    assert engineering["confidence_basis"] == "Volumes are known; the interface details are not."
    assert engineering["dropped_count"] == 0
    stored = finding_rows(sync_engine, engineering["id"])
    assert [(f["position"], f["kind"], f["severity"]) for f in stored] == [
        (1, "risk", "critical"),
        (2, "constraint", "high"),
        (3, "risk", "medium"),
    ]
    assert {
        (r["requirement_id"], r["requirement_version"])
        for r in link_rows(sync_engine, stored[2]["id"])
    } == {
        (reqs[0]["id"], 1),
        (reqs[1]["id"], 1),
    }
    assert {
        (r["requirement_id"], r["hours"], r["basis"])
        for r in effort_rows(sync_engine, engineering["id"])
    } == {
        (reqs[2]["id"], Decimal("24.3"), "Sized R3."),  # 0.1 h precision
        (reqs[0]["id"], Decimal("40.0"), "Sized R1."),
    }
    pm = current(sync_engine, opp["id"], "pm_agent")
    assert (pm["recommendation"], pm["confidence"]) == ("proceed", "high")
    assert len(effort_rows(sync_engine, pm["id"])) == 3
    security = current(sync_engine, opp["id"], "security_agent")
    assert effort_rows(sync_engine, security["id"]) == []  # Security may size nothing
    assert len(finding_rows(sync_engine, security["id"])) == 3

    trail = events(sync_engine, opp["id"])
    assert trail[0]["event_type"] == "assessments.assessment_run.started"
    assert trail[0]["actor_type"] == "user"
    assert trail[0]["payload"] == {"agent_count": 3}
    assert (trail[0]["subject_type"], str(trail[0]["subject_id"])) == (
        "assessments.assessment_run",
        body["id"],
    )
    completed = {
        e["payload"]["agent"]: e
        for e in trail
        if e["event_type"] == "assessments.assessment.completed"
    }
    assert set(completed) == set(AGENTS)
    eng = completed["engineering_agent"]
    assert (eng["actor_type"], eng["actor_id"]) == ("agent", "engineering_agent@0.1.0")
    assert (eng["subject_type"], eng["subject_id"], eng["subject_version"]) == (
        "assessments.assessment",
        engineering["id"],
        1,
    )
    assert eng["payload"] == {
        "run_id": str(run["id"]),
        "agent": "engineering_agent",
        "version": 1,
        "recommendation": "proceed_with_conditions",
        "confidence": "medium",
        "finding_count": 3,
        "critical_count": 1,
        "high_count": 1,
        "medium_count": 1,
        "low_count": 0,
        "effort_count": 2,
        "dropped_count": 0,
        "requirement_count": 5,
        "gap_count": 1,
        "superseded_count": 0,
    }
    assert completed["pm_agent"]["actor_id"] == "pm_agent@0.1.0"
    assert completed["security_agent"]["actor_id"] == "security_agent@0.1.0"
    last = trail[-1]
    assert last["event_type"] == "assessments.assessment_run.completed"
    assert (last["actor_type"], last["actor_id"]) == ("system", ASSESS)
    assert last["payload"] == {
        "status": "succeeded",
        "task_count": 3,
        "succeeded_count": 3,
        "failed_count": 0,
    }

    # One call per agent: its own instructions as the system message; the Requirements and
    # Gaps only as data blocks.
    assert sorted(r.caller.agent_id for r in fake.requests) == list(AGENTS)
    prompts = {
        "engineering_agent": engineering_prompt(),
        "pm_agent": pm_prompt(),
        "security_agent": security_prompt(),
    }
    for request in fake.requests:
        system, user = request.messages
        assert (system.role, system.content) == ("system", prompts[request.caller.agent_id])
        assert "<<<REQUIREMENT R1 classification=integration token=" in user.content
        assert "<<<REQUIREMENT R5 classification=commercial token=" in user.content
        assert "<<<GAP G1 category=integration_details impact=high token=" in user.content
        assert "Prices in EUR." in user.content
        assert request.caller.run_id == run["id"]
        assert (request.profile, request.priority) == ("demo-chat", "background")
    engineering_request = next(r for r in fake.requests if r.caller.agent_id == "engineering_agent")
    assert engineering_request.output_model is EngineeringOutput

    # Privacy: no Requirement, Gap or Finding text in logs or the trace.
    logged = caplog.text + str([r.__dict__ for r in caplog.records])
    trace_text = str(trail)
    for leak in (
        "SAP",
        "EUR",
        "sign-on",
        "seasonal",
        "Nothing shows",
        "interface type",
        "Volumes are known",
        "Sized R",
    ):
        assert leak not in logged
        assert leak not in trace_text


def test_the_three_agents_work_at_the_same_time(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    fake = install(AgentGateway(replies(), delay_s=0.5))
    started(client, headers, opp["id"])

    assert drain(db_url, ASSESS) == ["succeeded"]

    windows = [fake.windows[agent][0] for agent in AGENTS]
    # Every call started before any of them ended: the three calls overlap.
    assert max(start for start, _ in windows) < min(end for _, end in windows)


# --- failures and retry ---------------------------------------------------------------------


def test_a_failing_agent_leaves_the_run_partially_failed_and_the_others_stored(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=5)
    fake = install(
        AgentGateway(
            replies(security_agent=[ModelUnavailableError("down", error_code="connection")])
        )
    )
    body = started(client, headers, opp["id"])

    assert drain(db_url, ASSESS, max_runs=1) == ["failed_retrying"]
    (run,) = run_rows(sync_engine, opp["id"])
    assert run["status"] == "running"
    tasks = task_rows(sync_engine, run["id"])
    assert tasks["security_agent"]["status"] == "running"  # one more attempt to come
    assert tasks["engineering_agent"]["status"] == "succeeded"

    assert drain(db_url, ASSESS) == ["dead"]

    (run,) = run_rows(sync_engine, opp["id"])
    assert run["status"] == "partially_failed"
    tasks = task_rows(sync_engine, run["id"])
    assert (tasks["security_agent"]["status"], tasks["security_agent"]["error_code"]) == (
        "failed",
        "model_unavailable",
    )
    assert [r["agent"] for r in assessment_rows(sync_engine, opp["id"])] == [
        "engineering_agent",
        "pm_agent",
    ]
    # The second attempt only re-ran the unfinished task.
    assert (fake.calls("engineering_agent"), fake.calls("pm_agent")) == (1, 1)
    assert fake.calls("security_agent") == 2
    done = events(sync_engine, opp["id"])[-1]
    assert done["payload"] == {
        "status": "partially_failed",
        "task_count": 3,
        "succeeded_count": 2,
        "failed_count": 1,
    }

    # Retry the Security task only: on success the run becomes succeeded.
    fake.replies["security_agent"] = [SECURITY]
    retried = retry(client, headers, opp["id"], body["id"], "security_agent")
    assert retried.status_code == 201, retried.text
    assert retried.json()["status"] == "queued"
    assert {t["agent"]: t["status"] for t in retried.json()["tasks"]} == {
        "engineering_agent": "succeeded",
        "pm_agent": "succeeded",
        "security_agent": "queued",
    }
    assert len(assess_jobs(sync_engine, opp["id"])) == 2

    assert drain(db_url, ASSESS) == ["succeeded"]

    assert (fake.calls("engineering_agent"), fake.calls("pm_agent")) == (1, 1)
    assert fake.calls("security_agent") == 3
    (run,) = run_rows(sync_engine, opp["id"])
    assert run["status"] == "succeeded"
    assert {t["status"] for t in task_rows(sync_engine, run["id"]).values()} == {"succeeded"}
    assert current(sync_engine, opp["id"], "security_agent")["version"] == 1
    trail = events(sync_engine, opp["id"])
    restarted = [e for e in trail if e["event_type"] == "assessments.assessment_run.started"]
    assert [e["payload"] for e in restarted] == [{"agent_count": 3}, {"agent_count": 1}]
    assert trail[-1]["payload"]["status"] == "succeeded"


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ModelTimeoutError("slow"), "model_timeout"),
        (ModelOutputInvalidError("cut", error_code="truncated"), "output_invalid"),
    ],
)
def test_every_agent_failing_fails_the_run(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    error: Exception,
    code: str,
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    install(AgentGateway({agent: [error] for agent in AGENTS}))
    started(client, headers, opp["id"])

    assert drain(db_url, ASSESS) == ["failed_retrying", "dead"]

    (run,) = run_rows(sync_engine, opp["id"])
    assert run["status"] == "failed"
    assert {(t["status"], t["error_code"]) for t in task_rows(sync_engine, run["id"]).values()} == {
        ("failed", code)
    }
    assert assessment_rows(sync_engine, opp["id"]) == []
    (job,) = assess_jobs(sync_engine, opp["id"])
    assert (job["status"], job["attempts"]) == ("dead", 2)


def test_bad_findings_and_effort_rows_are_dropped_and_counted(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    bad = assessment_out(
        finding("SAP custom fields", ["R1"]),
        finding("Unknown Requirement", ["R99"]),
        efforts=(effort("R1", 0), effort("R2", 12)),
    )
    install(AgentGateway(replies(engineering_agent=[bad])))
    started(client, headers, opp["id"])

    assert drain(db_url, ASSESS) == ["succeeded"]

    engineering = current(sync_engine, opp["id"], "engineering_agent")
    assert [f["title"] for f in finding_rows(sync_engine, engineering["id"])] == [
        "SAP custom fields"
    ]
    assert [r["hours"] for r in effort_rows(sync_engine, engineering["id"])] == [Decimal("12.0")]
    assert engineering["dropped_count"] == 2
    completed = [
        e["payload"]
        for e in events(sync_engine, opp["id"])
        if e["event_type"] == "assessments.assessment.completed"
        and e["payload"]["agent"] == "engineering_agent"
    ]
    assert [(p["dropped_count"], p["finding_count"], p["effort_count"]) for p in completed] == [
        (2, 1, 1)
    ]


@pytest.mark.parametrize(
    "invalid",
    [
        assessment_out(finding("Only an unknown label", ["R99"])),
        assessment_out(),
        assessment_out(finding("Fine", ["R1"]), recommendation="maybe"),
        assessment_out(finding("Fine", ["R1"]), confidence="certain"),
        assessment_out(finding("Fine", ["R1"]), basis="   "),
    ],
    ids=["no-valid-finding", "no-finding", "recommendation", "confidence", "basis"],
)
def test_an_invalid_reply_twice_fails_the_task_and_keeps_the_previous_assessment(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    invalid: SpecialistOutput,
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    fake = install(AgentGateway(replies()))
    started(client, headers, opp["id"])
    assert drain(db_url, ASSESS) == ["succeeded"]
    fake.replies["security_agent"] = [invalid]
    started(client, headers, opp["id"])

    assert drain(db_url, ASSESS) == ["failed_retrying", "dead"]

    first, second = run_rows(sync_engine, opp["id"])
    assert second["status"] == "partially_failed"
    security = task_rows(sync_engine, second["id"])["security_agent"]
    assert (security["status"], security["error_code"]) == ("failed", "output_invalid")
    assert fake.calls("security_agent") == 3  # one, then two attempts
    kept = current(sync_engine, opp["id"], "security_agent")
    assert (kept["version"], kept["run_id"]) == (1, first["id"])
    assert current(sync_engine, opp["id"], "engineering_agent")["version"] == 2


def test_a_missing_recommendation_makes_the_reply_invalid(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    class Missing(BaseModel):  # the extension without `recommendation`
        confidence: str = "high"
        confidence_basis: str = "x"
        findings: list[dict[str, Any]] = [finding("Fine", ["R1"])]

    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    install(AgentGateway(replies(pm_agent=[Missing()])))
    started(client, headers, opp["id"])

    assert drain(db_url, ASSESS) == ["failed_retrying", "dead"]

    (run,) = run_rows(sync_engine, opp["id"])
    pm = task_rows(sync_engine, run["id"])["pm_agent"]
    assert (pm["status"], pm["error_code"]) == ("failed", "output_invalid")


def test_a_rerun_supersedes_each_agents_assessment(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=5)
    fake = install(AgentGateway(replies()))
    started(client, headers, opp["id"])
    assert drain(db_url, ASSESS) == ["succeeded"]
    fake.replies["pm_agent"] = [
        assessment_out(finding("One phase only", ["R2"]), recommendation="do_not_proceed")
    ]
    started(client, headers, opp["id"])

    assert drain(db_url, ASSESS) == ["succeeded"]

    for agent in AGENTS:
        v1, v2 = assessment_rows(sync_engine, opp["id"], agent)
        assert (v1["version"], v1["status"]) == (1, "superseded")
        assert (v2["version"], v2["status"]) == (2, "current")
    pm_v1, pm_v2 = assessment_rows(sync_engine, opp["id"], "pm_agent")
    assert len(finding_rows(sync_engine, pm_v1["id"])) == 3  # kept, read-only
    assert pm_v2["recommendation"] == "do_not_proceed"
    superseded = [
        e["payload"]["superseded_count"]
        for e in events(sync_engine, opp["id"])
        if e["event_type"] == "assessments.assessment.completed"
    ]
    assert sorted(superseded) == [0, 0, 0, 1, 1, 1]


def test_with_no_active_requirements_nothing_is_asked(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = owner(client, sync_engine)
    fake = install(AgentGateway({agent: [ModelUnavailableError("not called")] for agent in AGENTS}))
    started(client, headers, opp["id"])

    assert drain(db_url, ASSESS) == ["succeeded"]

    assert fake.requests == []
    (run,) = run_rows(sync_engine, opp["id"])
    assert run["status"] == "succeeded"
    assert assessment_rows(sync_engine, opp["id"]) == []


# --- review-style edges ---------------------------------------------------------------------


class _Hanging:
    async def complete_structured(self, request: StructuredRequest[Any]) -> Any:
        await asyncio.sleep(60)
        raise AssertionError("not reached")


@pytest.mark.parametrize(
    ("attempt", "run_status", "task_status", "code"),
    [(2, "failed", "failed", "model_timeout"), (1, "running", "running", None)],
)
def test_a_cancelled_run_is_recorded_as_timed_out_only_on_the_final_attempt(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    attempt: int,
    run_status: str,
    task_status: str,
    code: str | None,
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    started(client, headers, opp["id"])
    (job,) = assess_jobs(sync_engine, opp["id"])
    provider.install(_Hanging())

    async def scenario() -> None:
        engine = create_engine(Settings(database_url=db_url))
        ctx = JobContext(
            job_id=job["id"],
            job_type=ASSESS,
            attempt=attempt,
            max_attempts=2,
            opportunity_id=UUID(opp["id"]),
            engine=engine,
        )
        payload = assessments_assessment.RunAssessment.model_validate(job["payload"])
        try:
            with pytest.raises(TimeoutError):  # the runner's job timeout, made short
                async with asyncio.timeout(1):
                    await assessments_assessment.run_assessment(ctx, payload)
        finally:
            await engine.dispose()

    run_async(scenario())

    (run,) = run_rows(sync_engine, opp["id"])
    assert run["status"] == run_status
    assert {(t["status"], t["error_code"]) for t in task_rows(sync_engine, run["id"]).values()} == {
        (task_status, code)
    }


def test_a_job_whose_run_is_no_longer_in_progress_is_skipped(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    started(client, headers, opp["id"])
    with sync_engine.begin() as conn:  # failed (e.g. as lost) while its job still waits
        conn.execute(
            sa.text("UPDATE assessments_runs SET status = 'failed' WHERE opportunity_id = :o"),
            {"o": opp["id"]},
        )
    fake = install(AgentGateway({agent: [ModelUnavailableError("not called")] for agent in AGENTS}))

    assert drain(db_url, ASSESS) == ["succeeded"]

    assert fake.requests == []
    (run,) = run_rows(sync_engine, opp["id"])
    assert run["status"] == "failed"
    assert {t["status"] for t in task_rows(sync_engine, run["id"]).values()} == {"queued"}


def test_starting_fails_a_lost_run_first(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    started(client, headers, opp["id"])
    with sync_engine.begin() as conn:  # its job died without recording it, long ago
        conn.execute(
            sa.text(
                "UPDATE assessments_runs SET status = 'running', queued_at = now() - :age "
                "WHERE opportunity_id = :o"
            ),
            {"age": assessments_assessment.stale_after() * 2, "o": opp["id"]},
        )

    started(client, headers, opp["id"])

    lost, new = run_rows(sync_engine, opp["id"])
    assert lost["status"] == "failed"
    assert {
        (t["status"], t["error_code"]) for t in task_rows(sync_engine, lost["id"]).values()
    } == {("failed", "model_timeout")}
    assert new["status"] == "queued"


def test_retry_fails_a_lost_run_first(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    body = started(client, headers, opp["id"])
    with sync_engine.begin() as conn:  # its job died without recording it, long ago
        conn.execute(
            sa.text(
                "UPDATE assessments_runs SET status = 'running', queued_at = now() - :age "
                "WHERE opportunity_id = :o"
            ),
            {"age": assessments_assessment.stale_after() * 2, "o": opp["id"]},
        )
        conn.execute(  # the Engineering Agent had started
            sa.text(
                "UPDATE assessments_tasks SET status = 'running', started_at = now() - :age "
                "WHERE agent = 'engineering_agent' AND run_id = :r"
            ),
            {"age": assessments_assessment.stale_after() * 2, "r": body["id"]},
        )

    retried = retry(client, headers, opp["id"], body["id"], "pm_agent")

    assert retried.status_code == 201, retried.text
    (run,) = run_rows(sync_engine, opp["id"])
    assert run["status"] == "queued"
    tasks = task_rows(sync_engine, run["id"])
    assert (tasks["pm_agent"]["status"], tasks["pm_agent"]["error_code"]) == ("queued", None)
    for agent in ("engineering_agent", "security_agent"):
        assert (tasks[agent]["status"], tasks[agent]["error_code"]) == ("failed", "model_timeout")
        assert tasks[agent]["finished_at"] is None  # when it stopped is unknown: no duration
    assert tasks["engineering_agent"]["started_at"] is not None
    assert tasks["security_agent"]["started_at"] is None


def _inputs(engine: Engine, opp_id: str) -> assessments_assessment.AssessmentInputs:
    return assessments_assessment.AssessmentInputs(
        requirements=[
            assessments_assessment.AssessedRequirement(
                label=f"R{n}",
                requirement_id=r["id"],
                version=r["version"],
                classification=r["classification"],
                text=r["text"],
            )
            for n, r in enumerate(requirement_rows(engine, opp_id), start=1)
        ]
    )


def _accept(
    db_url: str,
    run_id: Any,
    agent: AssessmentAgent,
    output: SpecialistOutput,
    inputs: assessments_assessment.AssessmentInputs,
) -> None:
    result = AgentResult(
        confidence=0.5,
        confidence_basis="test",
        needs_human_review=True,
        extensions={agent.value: output},
    )

    async def scenario() -> None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                await assessments_assessment.accept_assessment(
                    uow,
                    run_id=run_id,
                    agent=agent,
                    result=result,
                    inputs=inputs,
                    actor=Actor(type="agent", id=f"{agent.value}@0.1.0"),
                )
        finally:
            await engine.dispose()

    run_async(scenario())


def test_a_requirement_changed_after_the_read_does_not_resolve(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    body = started(client, headers, opp["id"])
    with sync_engine.begin() as conn:  # the run has read the Requirements and is mid-call
        conn.execute(
            sa.text("UPDATE assessments_runs SET status = 'running' WHERE id = :r"),
            {"r": body["id"]},
        )
        conn.execute(
            sa.text("UPDATE assessments_tasks SET status = 'running' WHERE run_id = :r"),
            {"r": body["id"]},
        )
    inputs = _inputs(sync_engine, opp["id"])
    reqs = requirement_rows(sync_engine, opp["id"])
    edited = client.patch(
        f"{BASE}/{opp['id']}/requirements/{reqs[0]['id']}",
        headers={**headers, "If-Match": f'"{reqs[0]["row_version"]}"'},
        json={"text": "Connect to SAP EWM over IDocs."},
    )
    assert edited.status_code == 200, edited.text

    _accept(
        db_url,
        body["id"],
        AssessmentAgent.PM,
        assessment_out(
            finding("SAP", ["R1"]),
            finding("Uptime", ["R2"]),
            efforts=(effort("R1", 8), effort("R2", 4)),
        ),
        inputs,
    )

    pm = current(sync_engine, opp["id"], "pm_agent")
    assert [r["title"] for r in finding_rows(sync_engine, pm["id"])] == ["Uptime"]
    assert [e["requirement_id"] for e in effort_rows(sync_engine, pm["id"])] == [reqs[1]["id"]]
    assert pm["dropped_count"] == 2


def test_an_older_run_accepted_after_a_newer_one_writes_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    older = started(client, headers, opp["id"])
    inputs = _inputs(sync_engine, opp["id"])
    with sync_engine.begin() as conn:  # the older run is lost mid-call
        conn.execute(
            sa.text(
                "UPDATE assessments_runs SET status = 'running', queued_at = now() - :age "
                "WHERE id = :r"
            ),
            {"age": assessments_assessment.stale_after() * 2, "r": older["id"]},
        )
        conn.execute(
            sa.text("UPDATE assessments_tasks SET status = 'running' WHERE run_id = :r"),
            {"r": older["id"]},
        )
    install(AgentGateway(replies()))
    started(client, headers, opp["id"])  # fails the lost run first
    assert set(drain(db_url, ASSESS)) == {"succeeded"}  # the older job is skipped

    _accept(
        db_url, older["id"], AssessmentAgent.PM, assessment_out(finding("Late", ["R1"])), inputs
    )

    (pm,) = assessment_rows(sync_engine, opp["id"], "pm_agent")
    assert pm["run_id"] != UUID(older["id"])
    assert "Late" not in [r["title"] for r in finding_rows(sync_engine, pm["id"])]
    completed = [
        e
        for e in events(sync_engine, opp["id"])
        if e["event_type"] == "assessments.assessment.completed"
    ]
    assert len(completed) == 3


def test_findings_and_effort_are_insert_only_and_nothing_is_deletable_for_psa_app(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    install(
        AgentGateway(
            replies(
                engineering_agent=[
                    assessment_out(finding("SAP custom fields", ["R1"]), efforts=(effort("R1", 4),))
                ]
            )
        )
    )
    started(client, headers, opp["id"])
    assert drain(db_url, ASSESS) == ["succeeded"]
    (run,) = run_rows(sync_engine, opp["id"])
    engineering = current(sync_engine, opp["id"], "engineering_agent")
    (row,) = finding_rows(sync_engine, engineering["id"])
    task = task_rows(sync_engine, run["id"])["pm_agent"]
    denied = [
        ("UPDATE assessments_assessment_findings SET title = 'x' WHERE id = :i", row["id"]),
        ("DELETE FROM assessments_assessment_findings WHERE id = :i", row["id"]),
        (
            "UPDATE assessments_assessment_finding_requirements SET requirement_version = 9 "
            "WHERE finding_id = :i",
            row["id"],
        ),
        (
            "DELETE FROM assessments_assessment_finding_requirements WHERE finding_id = :i",
            row["id"],
        ),
        ("UPDATE assessments_effort SET hours = 1 WHERE assessment_id = :i", engineering["id"]),
        ("DELETE FROM assessments_effort WHERE assessment_id = :i", engineering["id"]),
        (
            "UPDATE assessments_assessments SET recommendation = 'proceed' WHERE id = :i",
            engineering["id"],
        ),
        ("UPDATE assessments_assessments SET version = 9 WHERE id = :i", engineering["id"]),
        ("DELETE FROM assessments_assessments WHERE id = :i", engineering["id"]),
        ("UPDATE assessments_tasks SET agent = 'pm_agent' WHERE id = :i", task["id"]),
        ("DELETE FROM assessments_tasks WHERE id = :i", task["id"]),
        ("UPDATE assessments_runs SET opportunity_id = id WHERE id = :i", run["id"]),
        ("DELETE FROM assessments_runs WHERE id = :i", run["id"]),
    ]
    for sql, value in denied:
        with pytest.raises(sa.exc.ProgrammingError), sync_engine.begin() as conn:
            conn.execute(sa.text(sql), {"i": value})
    # The status columns stay updatable (superseding, run and task states).
    allowed = [
        ("UPDATE assessments_assessments SET status = status WHERE id = :i", engineering["id"]),
        ("UPDATE assessments_tasks SET status = status WHERE id = :i", task["id"]),
        ("UPDATE assessments_runs SET status = status WHERE id = :i", run["id"]),
    ]
    for sql, value in allowed:
        with sync_engine.begin() as conn:
            conn.execute(sa.text(sql), {"i": value})


# --- cancelling (Story 5.5) -----------------------------------------------------------------

ENGINEERING_SMALL = assessment_out(finding("SAP custom fields", ["R1"]), efforts=(effort("R1", 4),))


def _mid_run(engine: Engine, run_id: str) -> None:
    """The run has read its inputs and every agent is mid-call."""
    with engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE assessments_runs SET status = 'running' WHERE id = :r"), {"r": run_id}
        )
        conn.execute(
            sa.text(
                "UPDATE assessments_tasks SET status = 'running', started_at = now() "
                "WHERE run_id = :r"
            ),
            {"r": run_id},
        )


def test_cancelling_a_running_run_skips_the_rest_and_keeps_what_completed(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    body = started(client, headers, opp["id"])
    _mid_run(sync_engine, body["id"])
    inputs = _inputs(sync_engine, opp["id"])
    _accept(db_url, body["id"], AssessmentAgent.ENGINEERING, ENGINEERING_SMALL, inputs)

    response = cancel(client, headers, opp["id"], body["id"])

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    assert {t["agent"]: (t["status"], t["error_code"]) for t in response.json()["tasks"]} == {
        "engineering_agent": ("succeeded", None),
        "pm_agent": ("skipped", None),
        "security_agent": ("skipped", None),
    }
    (run,) = run_rows(sync_engine, opp["id"])
    assert run["status"] == "cancelled"
    assert run["finished_at"] is not None
    tasks = task_rows(sync_engine, run["id"])
    for agent in ("pm_agent", "security_agent"):  # they had started: they keep a duration
        assert tasks[agent]["started_at"] <= tasks[agent]["finished_at"]
    engineering = current(sync_engine, opp["id"], "engineering_agent")
    assert (engineering["version"], engineering["run_id"]) == (1, run["id"])
    assert assessment_rows(sync_engine, opp["id"], "pm_agent") == []
    last = events(sync_engine, opp["id"])[-1]
    assert last["event_type"] == "assessments.assessment_run.cancelled"
    assert last["actor_type"] == "user"
    assert (last["subject_type"], str(last["subject_id"])) == (
        "assessments.assessment_run",
        body["id"],
    )
    assert last["payload"] == {"skipped_count": 2, "succeeded_count": 1}


def test_a_reply_after_the_cancel_is_discarded(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    body = started(client, headers, opp["id"])
    _mid_run(sync_engine, body["id"])
    inputs = _inputs(sync_engine, opp["id"])
    assert cancel(client, headers, opp["id"], body["id"]).status_code == 200

    _accept(db_url, body["id"], AssessmentAgent.PM, assessment_out(finding("Late", ["R1"])), inputs)

    assert assessment_rows(sync_engine, opp["id"]) == []
    (run,) = run_rows(sync_engine, opp["id"])
    assert run["status"] == "cancelled"
    assert {t["status"] for t in task_rows(sync_engine, run["id"]).values()} == {"skipped"}
    assert [
        e for e in events(sync_engine, opp["id"]) if e["event_type"].endswith(".completed")
    ] == []


def test_a_cancelled_queued_run_skips_its_job(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    body = started(client, headers, opp["id"])
    fake = install(AgentGateway({agent: [ModelUnavailableError("not called")] for agent in AGENTS}))

    response = cancel(client, headers, opp["id"], body["id"])

    assert response.status_code == 200, response.text
    assert {t["status"] for t in response.json()["tasks"]} == {"skipped"}
    assert drain(db_url, ASSESS) == ["succeeded"]  # the job finds nothing to do
    assert fake.requests == []
    (run,) = run_rows(sync_engine, opp["id"])
    assert run["status"] == "cancelled"
    tasks = task_rows(sync_engine, run["id"])
    assert {(t["status"], t["started_at"], t["finished_at"]) for t in tasks.values()} == {
        ("skipped", None, None)  # never started: no duration
    }
    assert events(sync_engine, opp["id"])[-1]["payload"] == {
        "skipped_count": 3,
        "succeeded_count": 0,
    }


class _Blocking:
    """Blocks every call until it is cancelled; counts the calls started and cancelled."""

    def __init__(self, expected: int = 3) -> None:
        self.started = 0
        self.cancelled = 0
        self.expected = expected
        self.all_started = asyncio.Event()

    async def complete_structured(self, request: StructuredRequest[Any]) -> Any:
        self.started += 1
        if self.started >= self.expected:
            self.all_started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        raise AssertionError("not reached")


def _context(engine: Any, job: dict[str, Any], opp_id: str, attempt: int) -> JobContext:
    return JobContext(
        job_id=job["id"],
        job_type=ASSESS,
        attempt=attempt,
        max_attempts=2,
        opportunity_id=UUID(opp_id),
        engine=engine,
    )


async def _calls_started(fake: _Blocking) -> None:
    async with asyncio.timeout(10):
        await fake.all_started.wait()


@pytest.mark.parametrize("attempt", [1, 2], ids=["first-attempt", "final-attempt"])
def test_cancel_stops_the_in_flight_calls_and_the_job_ends_without_error(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    attempt: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    body = started(client, headers, opp["id"])
    (job,) = assess_jobs(sync_engine, opp["id"])
    fake = _Blocking()
    provider.install(fake)
    monkeypatch.setattr(assessments_assessment, "CANCEL_POLL_S", 0.2)

    async def scenario() -> float:
        engine = create_engine(Settings(database_url=db_url))
        payload = assessments_assessment.RunAssessment.model_validate(job["payload"])
        try:
            handler = asyncio.create_task(
                assessments_assessment.run_assessment(
                    _context(engine, job, opp["id"], attempt), payload
                )
            )
            await _calls_started(fake)
            response = await asyncio.to_thread(cancel, client, headers, opp["id"], body["id"])
            assert response.status_code == 200, response.text
            cancelled_at = time.monotonic()
            await asyncio.wait_for(handler, 10)  # ends without raising
            return time.monotonic() - cancelled_at
        finally:
            await engine.dispose()

    took = run_async(scenario())

    assert took < 0.2 + 1.5  # within one poll, plus slack
    assert (fake.started, fake.cancelled) == (3, 3)  # every in-flight call let go of its slot
    (run,) = run_rows(sync_engine, opp["id"])
    assert run["status"] == "cancelled"  # never failed, even on the final attempt
    assert {(t["status"], t["error_code"]) for t in task_rows(sync_engine, run["id"]).values()} == {
        ("skipped", None)
    }
    trail = [e["event_type"] for e in events(sync_engine, opp["id"])]
    assert "assessments.assessment_run.completed" not in trail


def test_a_final_attempt_timing_out_after_the_cancel_leaves_the_run_cancelled(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    body = started(client, headers, opp["id"])
    (job,) = assess_jobs(sync_engine, opp["id"])
    fake = _Blocking()
    provider.install(fake)
    monkeypatch.setattr(assessments_assessment, "CANCEL_POLL_S", 60.0)  # the watcher is late

    async def scenario() -> None:
        engine = create_engine(Settings(database_url=db_url))
        payload = assessments_assessment.RunAssessment.model_validate(job["payload"])
        try:
            with pytest.raises(TimeoutError):  # the runner's job timeout, made short
                async with asyncio.timeout(3):
                    work = asyncio.ensure_future(
                        assessments_assessment.run_assessment(
                            _context(engine, job, opp["id"], 2), payload
                        )
                    )
                    await _calls_started(fake)
                    response = await asyncio.to_thread(
                        cancel, client, headers, opp["id"], body["id"]
                    )
                    assert response.status_code == 200, response.text
                    await work
        finally:
            await engine.dispose()

    run_async(scenario())

    (run,) = run_rows(sync_engine, opp["id"])
    assert run["status"] == "cancelled"
    assert {(t["status"], t["error_code"]) for t in task_rows(sync_engine, run["id"]).values()} == {
        ("skipped", None)
    }


class _FailsOnSignal:
    """Each call waits for `release`, then raises `ModelUnavailableError`."""

    def __init__(self, expected: int = 3) -> None:
        self.started = 0
        self.expected = expected
        self.all_started = asyncio.Event()
        self.release = asyncio.Event()

    async def complete_structured(self, request: StructuredRequest[Any]) -> Any:
        self.started += 1
        if self.started >= self.expected:
            self.all_started.set()
        await self.release.wait()
        raise ModelUnavailableError("down", error_code="connection")


@pytest.mark.parametrize("attempt", [1, 2], ids=["first-attempt", "final-attempt"])
def test_a_task_failing_after_the_cancel_neither_retries_nor_fails_the_run(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    attempt: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    body = started(client, headers, opp["id"])
    (job,) = assess_jobs(sync_engine, opp["id"])
    fake = _FailsOnSignal()
    provider.install(fake)
    monkeypatch.setattr(assessments_assessment, "CANCEL_POLL_S", 60.0)  # the watcher is late

    async def scenario() -> None:
        engine = create_engine(Settings(database_url=db_url))
        payload = assessments_assessment.RunAssessment.model_validate(job["payload"])
        try:
            handler = asyncio.create_task(
                assessments_assessment.run_assessment(
                    _context(engine, job, opp["id"], attempt), payload
                )
            )
            async with asyncio.timeout(10):
                await fake.all_started.wait()
            response = await asyncio.to_thread(cancel, client, headers, opp["id"], body["id"])
            assert response.status_code == 200, response.text
            fake.release.set()  # the calls now fail, after the cancel
            await asyncio.wait_for(handler, 10)  # returns without raising
        finally:
            await engine.dispose()

    run_async(scenario())

    (run,) = run_rows(sync_engine, opp["id"])
    assert run["status"] == "cancelled"
    assert {(t["status"], t["error_code"]) for t in task_rows(sync_engine, run["id"]).values()} == {
        ("skipped", None)
    }
