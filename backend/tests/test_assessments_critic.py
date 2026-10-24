"""Critic Review (Story 6.4) against a real, migrated Postgres as psa_app: the `critic_agent`
task every assessment run plans after its specialist tasks, `accept_critic_review` (coverage,
validation, backstop, target links, versions, trace), the contradictions raised as Conflicts,
`GET …/critic`, the `assessments.run.read` tool, privacy and the grants.

Reuses the per-agent fake gateway and fixtures of `test_assessments_specialists.py`.
"""

import logging
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.engine import Engine

from app.agents.critic_agent.agent import prompt as critic_prompt
from app.agents.critic_agent.schema import CriticOutput
from app.modules.assessments.application import public as assessments_public
from app.modules.registry.domain.registry import seed_config_version_id
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.model_gateway.port import ModelOutputInvalidError, ModelUnavailableError
from app.platform.tool_gateway import ToolContext, ToolDenied, ToolGateway, ToolResult
from app.platform.tool_gateway.catalogue import RUN_ASSESSMENT_READ
from app.platform.uow import unit_of_work
from tests import test_assessments_specialists as specialist_tests
from tests import test_estimates_draft as draft_tests
from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests.conftest import run_async
from tests.test_assessments_specialists import (
    AGENTS,
    SECURITY,
    AgentGateway,
    assessment_out,
    current,
    effort,
    finding,
    finding_rows,
    install,
    prepared,
    replies,
    retry,
    run_rows,
    started,
    task_rows,
)
from tests.test_gaps_detection import requirement_rows, rows
from tests.test_intake_extraction import ASSESS, BASE, FakeGateway, drain
from tests.test_opportunities import _add, _user

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile
_draft_profile = draft_tests._draft_profile
_assessment_profile = specialist_tests._assessment_profile
_no_auto_run = specialist_tests._no_auto_run

CRITIC = "critic_agent"
DONE = "assessments.critic_review.completed"


def critic_finding(
    category: str,
    title: str,
    *,
    severity: str = "medium",
    findings: list[str] | None = None,
    requirements: list[str] | None = None,
    argument: str | None = None,
) -> dict[str, Any]:
    return {
        "category": category,
        "severity": severity,
        "title": title,
        "argument": argument or f"Secret argument about {title.lower()}.",
        "findings": findings or [],
        "requirements": requirements or [],
    }


def critic_out(
    *findings: dict[str, Any], contradictions: list[dict[str, Any]] | None = None
) -> CriticOutput:
    return CriticOutput.model_validate(
        {"findings": list(findings), "contradictions": contradictions or []}
    )


# The specialists' Findings in label order (agent order, then position): Engineering F1-F3,
# PM F4-F6, Security F7-F9 (see `test_assessments_specialists.py`).
HAPPY = critic_out(
    critic_finding(
        "unsupported_claim",
        "Engineering Agent's peak of 900 orders/hour has no source",
        severity="high",
        findings=["F2"],
    ),
    critic_finding(
        "timeline",
        "PM Agent's 24/7 go-live ignores Engineering Agent's redundant controls",
        severity="critical",
        findings=["F5", "F3"],
        requirements=["R2"],
    ),
    critic_finding(
        "dependency",
        "No Assessment lists the identity provider's owner",
        requirements=["R4"],
    ),
    critic_finding(
        "risk_coverage",
        "Security Agent's credentials risk is not sized by anyone",
        severity="low",
        findings=["F9"],
        requirements=["R1"],
    ),
    contradictions=[
        {
            "type": "architecture",
            "severity": "high",
            "summary": "Engineering Agent and Security Agent disagree on remote access.",
            "positions": [
                {"finding": "F3", "stance": "Redundant controls stay on site."},
                {"finding": "F8", "stance": "Controls need remote access around the clock."},
            ],
        }
    ],
)


def reviews(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM assessments_reviews WHERE opportunity_id = :o AND kind = 'critic' "
        "ORDER BY version",
        o=opp_id,
    )


def review_findings(engine: Engine, review_id: Any) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM assessments_findings WHERE review_id = :r ORDER BY position",
        r=review_id,
    )


def targets(engine: Engine, finding_id: Any) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM assessments_finding_targets WHERE finding_id = :f",
        f=finding_id,
    )


def requirement_links(engine: Engine, finding_id: Any) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM assessments_finding_requirements WHERE finding_id = :f",
        f=finding_id,
    )


def critic_events(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM platform_trace_events WHERE opportunity_id = :o AND event_type = :e "
        "ORDER BY occurred_at, id",
        o=opp_id,
        e=DONE,
    )


def conflicts(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM conflicts_conflicts WHERE opportunity_id = :o AND detected_by = 'critic' "
        "ORDER BY created_at, id",
        o=opp_id,
    )


def get_critic(client: TestClient, headers: dict[str, str], opp_id: str) -> Any:
    return client.get(f"{BASE}/{opp_id}/critic", headers=headers)


def _specialist_finding(engine: Engine, opp_id: str, agent: str, position: int) -> dict[str, Any]:
    return finding_rows(engine, current(engine, opp_id, agent)["id"])[position - 1]


# --- the plan -------------------------------------------------------------------------------


def test_every_run_plans_the_critic_after_the_three_specialists(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)

    body = started(client, headers, opp["id"])

    assert [(t["agent"], t["status"]) for t in body["tasks"]] == [
        *((agent, "queued") for agent in AGENTS),
        (CRITIC, "queued"),
    ]
    (run,) = run_rows(sync_engine, opp["id"])
    tasks = task_rows(sync_engine, run["id"])
    critic = tasks[CRITIC]
    assert sorted(critic["after"]) == sorted(tasks[a]["id"] for a in AGENTS)
    assert critic["requires"] == []
    assert all(tasks[a]["after"] == [] for a in AGENTS)
    assert critic["config_version_id"] == seed_config_version_id(CRITIC)
    (plan,) = rows(
        sync_engine, "SELECT * FROM workflows_plan_versions WHERE run_id = :r", r=run["id"]
    )
    planned = {t["agent"]: t for t in plan["tasks"]}
    assert sorted(planned[CRITIC]["after"]) == sorted(str(tasks[a]["id"]) for a in AGENTS)
    assert planned[CRITIC]["config_version_id"] == str(seed_config_version_id(CRITIC))
    assert body["plan_versions"][0]["tasks"][-1]["agent"] == CRITIC


# --- the happy path -------------------------------------------------------------------------


def test_the_critic_reviews_the_runs_assessments_and_raises_its_contradictions(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    reqs = requirement_rows(sync_engine, opp["id"])
    fake = install(AgentGateway(replies(critic_agent=[HAPPY])))
    started(client, headers, opp["id"])

    with caplog.at_level(logging.DEBUG):
        assert drain(db_url, ASSESS) == ["succeeded"]

    (run,) = run_rows(sync_engine, opp["id"])
    assert run["status"] == "succeeded"
    tasks = task_rows(sync_engine, run["id"])
    assert tasks[CRITIC]["status"] == "succeeded"
    # The Critic started only once every specialist task had ended.
    assert tasks[CRITIC]["started_at"] >= max(tasks[a]["finished_at"] for a in AGENTS)
    assert fake.calls(CRITIC) == 1

    (review,) = reviews(sync_engine, opp["id"])
    assert (review["version"], review["status"], review["run_id"]) == (1, "current", run["id"])
    assert review["dropped_count"] == 0
    stored = review_findings(sync_engine, review["id"])
    assert [(f["position"], f["category"], f["severity"]) for f in stored] == [
        (1, "unsupported_claim", "high"),
        (2, "timeline", "critical"),
        (3, "dependency", "medium"),
        (4, "risk_coverage", "low"),
    ]
    # Target links at the cited Finding's Assessment version.
    engineering = current(sync_engine, opp["id"], "engineering_agent")
    peak = _specialist_finding(sync_engine, opp["id"], "engineering_agent", 2)
    assert [
        (t["assessment_finding_id"], t["assessment_id"], t["assessment_version"])
        for t in targets(sync_engine, stored[0]["id"])
    ] == [(peak["id"], engineering["id"], 1)]
    assert requirement_links(sync_engine, stored[0]["id"]) == []
    hypercare = _specialist_finding(sync_engine, opp["id"], "pm_agent", 2)
    controls = _specialist_finding(sync_engine, opp["id"], "engineering_agent", 3)
    assert {t["assessment_finding_id"] for t in targets(sync_engine, stored[1]["id"])} == {
        hypercare["id"],
        controls["id"],
    }
    assert [
        (r["requirement_id"], r["requirement_version"])
        for r in requirement_links(sync_engine, stored[1]["id"])
    ] == [(reqs[1]["id"], 1)]
    assert targets(sync_engine, stored[2]["id"]) == []

    # The contradiction is a Conflict, not a Finding.
    (conflict,) = conflicts(sync_engine, opp["id"])
    assert (conflict["detected_by"], conflict["type"], conflict["severity"]) == (
        "critic",
        "architecture",
        "high",
    )
    assert conflict["fingerprint"].startswith("critic:architecture:")
    assert conflict["run_id"] == run["id"]
    positions = rows(
        sync_engine, "SELECT * FROM conflicts_positions WHERE conflict_id = :c", c=conflict["id"]
    )
    assert {(p["agent"], p["assessment_version"]) for p in positions} == {
        ("engineering_agent", 1),
        ("security_agent", 1),
    }
    detected = rows(
        sync_engine,
        "SELECT * FROM platform_trace_events WHERE subject_id = :c",
        c=conflict["id"],
    )
    assert [(e["actor_type"], e["actor_id"]) for e in detected] == [("agent", "critic_agent@0.1.0")]
    assert detected[0]["payload"]["detected_by"] == "critic"

    (event,) = critic_events(sync_engine, opp["id"])
    assert (event["actor_type"], event["actor_id"]) == ("agent", "critic_agent@0.1.0")
    assert (event["subject_type"], event["subject_id"], event["subject_version"]) == (
        "assessments.review",
        review["id"],
        1,
    )
    assert event["workflow_run_id"] == run["id"]
    assert event["payload"] == {
        "version": 1,
        "finding_count": 4,
        "critical_count": 1,
        "high_count": 1,
        "medium_count": 1,
        "low_count": 1,
        "dropped_count": 0,
        "backstopped_count": 0,
        "conflict_count": 1,
        "superseded_count": 0,
    }

    # The prompt: its own instructions, then the data blocks only.
    (request,) = [r for r in fake.requests if r.caller.agent_id == CRITIC]
    system, user = request.messages
    assert system.content == critic_prompt(1)
    assert request.output_model is CriticOutput
    assert (request.caller.run_id, request.profile) == (run["id"], "demo-chat")
    assert "<<<REQUIREMENT R1 classification=integration token=" in user.content
    assert "<<<FINDING F1 agent=engineering_agent assessment=v1 token=" in user.content
    assert "<<<FINDING F9 agent=security_agent assessment=v1 token=" in user.content
    assert "<<<EFFORT engineering_agent assessment=v1 token=" in user.content
    assert "R3: 24.3 h" in user.content
    assert "<<<UNCOVERED requirements token=" in user.content
    assert "SAP IDoc custom fields not specified" in user.content

    # Privacy: no Requirement, Finding or argument text in logs or the trace.
    logged = caplog.text + str([r.__dict__ for r in caplog.records])
    trace_text = str(critic_events(sync_engine, opp["id"])) + str(detected)
    for leak in ("Secret argument", "900 orders/hour", "Prices in EUR", "remote access"):
        assert leak not in logged
        assert leak not in trace_text


def test_get_critic_shows_ranked_findings_with_their_chips_to_any_reader(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    rep, rep_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    assert _add(client, headers, opp, rep_id).status_code == 200
    assert get_critic(client, headers, opp["id"]).json() == {"review": None}
    install(AgentGateway(replies(critic_agent=[HAPPY])))
    started(client, headers, opp["id"])
    assert drain(db_url, ASSESS) == ["succeeded"]

    response = get_critic(client, rep, opp["id"])  # a sales representative may read it

    assert response.status_code == 200, response.text
    review = response.json()["review"]
    (run,) = run_rows(sync_engine, opp["id"])
    assert (review["version"], review["status"], review["run_id"]) == (1, "current", str(run["id"]))
    assert review["counts"] == {"critical": 1, "high": 1, "medium": 1, "low": 1}
    assert [(f["severity"], f["category"]) for f in review["findings"]] == [
        ("critical", "timeline"),
        ("high", "unsupported_claim"),
        ("medium", "dependency"),
        ("low", "risk_coverage"),
    ]
    timeline = review["findings"][0]
    assert [(r["label"], r["version"]) for r in timeline["requirements"]] == [("R2", 1)]
    assert [
        (c["agent"], c["role"], c["assessment_version"], c["title"]) for c in timeline["findings"]
    ] == [
        ("engineering_agent", "Engineering Agent", 1, "Uptime target needs redundant controls"),
        ("pm_agent", "PM Agent", 1, "24/7 go-live needs a hypercare rota"),
    ]
    assert timeline["argument"].startswith("Secret argument")
    other, _ = _user(client, sync_engine, "Stranger Person", "presales_engineer")
    assert get_critic(client, other, opp["id"]).status_code == 404


# --- coverage --------------------------------------------------------------------------------


def test_an_uncovered_requirement_the_agent_misses_is_backstopped_by_code(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    reqs = requirement_rows(sync_engine, opp["id"])
    # Nobody cites R5 (PM sized and discussed it in the default replies).
    pm = assessment_out(
        finding("Customer IT not named as interface counterpart", ["R1"], kind="dependency"),
        efforts=(effort("R1", 16),),
    )
    fake = install(
        AgentGateway(
            replies(
                pm_agent=[pm],
                critic_agent=[
                    critic_out(
                        critic_finding(
                            "dependency",
                            "No Assessment lists the identity provider's owner",
                            requirements=["R4"],
                        )
                    )
                ],
            )
        )
    )
    started(client, headers, opp["id"])

    assert drain(db_url, ASSESS) == ["succeeded"]

    (request,) = [r for r in fake.requests if r.caller.agent_id == CRITIC]
    assert "R5\n<<<END requirements" in request.messages[1].content
    (review,) = reviews(sync_engine, opp["id"])
    stored = review_findings(sync_engine, review["id"])
    assert [(f["category"], f["severity"], f["title"]) for f in stored] == [
        ("dependency", "medium", "No Assessment lists the identity provider's owner"),
        ("coverage", "medium", "No specialist Assessment covers R5"),
    ]
    assert [
        (r["requirement_id"], r["requirement_version"])
        for r in requirement_links(sync_engine, stored[1]["id"])
    ] == [(reqs[4]["id"], 1)]
    (event,) = critic_events(sync_engine, opp["id"])
    assert (event["payload"]["backstopped_count"], event["payload"]["finding_count"]) == (1, 2)


def test_a_reported_uncovered_requirement_is_not_backstopped_again(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    pm = assessment_out(finding("Customer IT not named", ["R1"], kind="dependency"))
    reported = critic_out(
        critic_finding(
            "coverage", "Nobody sized the EUR pricing Requirement R5", requirements=["R5"]
        )
    )
    install(AgentGateway(replies(pm_agent=[pm], critic_agent=[reported])))
    started(client, headers, opp["id"])

    assert drain(db_url, ASSESS) == ["succeeded"]

    (review,) = reviews(sync_engine, opp["id"])
    assert [f["title"] for f in review_findings(sync_engine, review["id"])] == [
        "Nobody sized the EUR pricing Requirement R5"
    ]
    assert critic_events(sync_engine, opp["id"])[0]["payload"]["backstopped_count"] == 0


def test_bad_references_and_coverage_on_a_covered_requirement_are_dropped(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    reply = critic_out(
        critic_finding("unsupported_claim", "Cites only unknown labels", findings=["F99"]),
        critic_finding("dependency", "Cites an unknown Requirement", requirements=["R99"]),
        critic_finding("coverage", "R1 is not covered", requirements=["R1"]),  # it is
        critic_finding("timeline", "No citation at all"),
        critic_finding("velocity", "Unknown category", requirements=["R1"]),
        critic_finding("timeline", "Kept: cites a real Finding", findings=["F99", "F1"]),
    )
    install(AgentGateway(replies(critic_agent=[reply])))
    started(client, headers, opp["id"])

    assert drain(db_url, ASSESS) == ["succeeded"]

    (review,) = reviews(sync_engine, opp["id"])
    assert review["dropped_count"] == 5
    (kept,) = review_findings(sync_engine, review["id"])
    assert kept["title"] == "Kept: cites a real Finding"
    assert len(targets(sync_engine, kept["id"])) == 1
    assert critic_events(sync_engine, opp["id"])[0]["payload"]["dropped_count"] == 5


# --- specialists failing ---------------------------------------------------------------------


def test_with_a_specialist_failed_the_critic_reviews_the_others(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    fake = install(
        AgentGateway(
            replies(security_agent=[ModelUnavailableError("down", error_code="connection")])
        )
    )
    started(client, headers, opp["id"])

    assert drain(db_url, ASSESS) == ["failed_retrying", "dead"]

    (run,) = run_rows(sync_engine, opp["id"])
    assert run["status"] == "partially_failed"
    tasks = task_rows(sync_engine, run["id"])
    assert tasks["security_agent"]["status"] == "failed"
    assert tasks[CRITIC]["status"] == "succeeded"
    (request,) = [r for r in fake.requests if r.caller.agent_id == CRITIC]
    content = request.messages[1].content
    assert "agent=engineering_agent" in content and "agent=pm_agent" in content
    assert "agent=security_agent" not in content
    assert "<<<FINDING F6 " in content and "<<<FINDING F7 " not in content
    # R4 was only cited by Security: uncovered now, and backstopped.
    (review,) = reviews(sync_engine, opp["id"])
    assert [f["title"] for f in review_findings(sync_engine, review["id"])] == [
        "No specialist Assessment covers R4"
    ]


def test_with_no_assessment_accepted_the_critic_succeeds_without_a_call(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    error = ModelOutputInvalidError("cut", error_code="truncated")
    fake = install(AgentGateway({agent: [error] for agent in AGENTS}))
    started(client, headers, opp["id"])

    assert drain(db_url, ASSESS) == ["failed_retrying", "dead"]

    (run,) = run_rows(sync_engine, opp["id"])
    assert run["status"] == "failed"
    tasks = task_rows(sync_engine, run["id"])
    assert {tasks[a]["status"] for a in AGENTS} == {"failed"}
    assert tasks[CRITIC]["status"] == "succeeded"
    assert fake.calls(CRITIC) == 0
    assert reviews(sync_engine, opp["id"]) == []
    assert critic_events(sync_engine, opp["id"]) == []


def test_an_unparseable_reply_fails_the_critic_task_through_the_retry(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    class Malformed(BaseModel):  # `findings` is not a list
        findings: str = "none"

    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    fake = install(AgentGateway(replies(critic_agent=[Malformed()])))
    started(client, headers, opp["id"])

    assert drain(db_url, ASSESS) == ["failed_retrying", "dead"]

    (run,) = run_rows(sync_engine, opp["id"])
    assert run["status"] == "partially_failed"
    critic = task_rows(sync_engine, run["id"])[CRITIC]
    assert (critic["status"], critic["error_code"]) == ("failed", "output_invalid")
    assert fake.calls(CRITIC) == 2
    assert fake.calls("engineering_agent") == 1  # finished specialists are not run again
    assert reviews(sync_engine, opp["id"]) == []


def _count(engine: Engine, sql: str, opp_id: str) -> int:
    return len(rows(engine, sql, o=opp_id))


def test_retrying_the_critic_task_reviews_again_without_a_new_estimate(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    class Malformed(BaseModel):  # `findings` is not a list
        findings: str = "none"

    headers, opp = prepared(client, sync_engine, db_url, gateway)
    fake = install(AgentGateway(replies(critic_agent=[Malformed()])))
    body = started(client, headers, opp["id"])
    assert drain(db_url, ASSESS) == ["failed_retrying", "dead"]
    assert run_rows(sync_engine, opp["id"])[0]["status"] == "partially_failed"
    versions_sql = "SELECT id FROM estimates_estimate_versions WHERE opportunity_id = :o"
    jobs_sql = "SELECT id FROM platform_jobs WHERE opportunity_id = :o"
    estimate_versions = _count(sync_engine, versions_sql, opp["id"])
    jobs = _count(sync_engine, jobs_sql, opp["id"])
    fake.replies[CRITIC] = [critic_out()]

    response = retry(client, headers, opp["id"], body["id"], CRITIC)

    assert response.status_code == 201, response.text
    assert {t["agent"]: t["status"] for t in response.json()["tasks"]}[CRITIC] == "queued"
    assert drain(db_url, ASSESS) == ["succeeded"]
    (run,) = run_rows(sync_engine, opp["id"])
    assert run["status"] == "succeeded"
    (review,) = reviews(sync_engine, opp["id"])
    assert (review["version"], review["status"], review["run_id"]) == (1, "current", run["id"])
    assert fake.calls("engineering_agent") == 1  # the specialists are not run again
    # A Critic-only finish builds no Estimate Version (and so queues no Red Team review).
    assert _count(sync_engine, versions_sql, opp["id"]) == estimate_versions
    assert _count(sync_engine, jobs_sql, opp["id"]) == jobs + 1  # only the retry's own job


def test_retrying_a_specialist_reviews_the_run_again(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    fake = install(
        AgentGateway(
            replies(security_agent=[ModelUnavailableError("down", error_code="connection")])
        )
    )
    body = started(client, headers, opp["id"])
    assert drain(db_url, ASSESS) == ["failed_retrying", "dead"]
    (first,) = reviews(sync_engine, opp["id"])
    assert [f["title"] for f in review_findings(sync_engine, first["id"])] == [
        "No specialist Assessment covers R4"
    ]
    fake.replies["security_agent"] = [SECURITY]

    response = retry(client, headers, opp["id"], body["id"], "security_agent")

    assert response.status_code == 201, response.text
    queued = {t["agent"]: t["status"] for t in response.json()["tasks"]}
    assert (queued["security_agent"], queued[CRITIC]) == ("queued", "queued")
    assert drain(db_url, ASSESS) == ["succeeded"]
    (run,) = run_rows(sync_engine, opp["id"])
    assert run["status"] == "succeeded"
    v1, v2 = reviews(sync_engine, opp["id"])
    assert (v1["status"], v2["version"], v2["status"], v2["run_id"]) == (
        "superseded",
        2,
        "current",
        run["id"],
    )
    assert review_findings(sync_engine, v2["id"]) == []  # R4 is covered now
    second = [r for r in fake.requests if r.caller.agent_id == CRITIC][-1]
    assert "agent=security_agent assessment=v1" in second.messages[1].content


def test_a_requirement_changed_during_the_critic_call_is_not_linked_or_backstopped(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    reqs = requirement_rows(sync_engine, opp["id"])
    pm = assessment_out(finding("Customer IT not named", ["R1"], kind="dependency"))

    def edits_r5(request: Any) -> CriticOutput:
        (r5,) = [r for r in requirement_rows(sync_engine, opp["id"]) if r["id"] == reqs[4]["id"]]
        edited = client.patch(
            f"{BASE}/{opp['id']}/requirements/{r5['id']}",
            headers={**headers, "If-Match": '"' + str(r5["row_version"]) + '"'},
            json={"text": "Prices in EUR and GBP."},
        )
        assert edited.status_code == 200, edited.text
        return critic_out(
            critic_finding("coverage", "Nobody sized R5", requirements=["R5"]),
            critic_finding(
                "dependency", "Pricing depends on hardware quotes", requirements=["R5", "R4"]
            ),
        )

    install(AgentGateway(replies(pm_agent=[pm], critic_agent=[edits_r5])))
    started(client, headers, opp["id"])

    assert drain(db_url, ASSESS) == ["succeeded"]

    (review,) = reviews(sync_engine, opp["id"])
    assert review["dropped_count"] == 1  # the coverage Finding: R5 no longer resolves
    (kept,) = review_findings(sync_engine, review["id"])
    assert kept["title"] == "Pricing depends on hardware quotes"
    assert [
        (r["requirement_id"], r["requirement_version"])
        for r in requirement_links(sync_engine, kept["id"])
    ] == [(reqs[3]["id"], 1)]
    assert critic_events(sync_engine, opp["id"])[0]["payload"]["backstopped_count"] == 0


# --- versions ---------------------------------------------------------------------------------


def test_a_second_run_supersedes_the_critic_review(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    fake = install(AgentGateway(replies(critic_agent=[HAPPY])))
    started(client, headers, opp["id"])
    assert drain(db_url, ASSESS) == ["succeeded"]
    fake.replies[CRITIC] = [
        critic_out(
            critic_finding(
                "timeline", "Engineering Agent's v2 sizing still ignores R2", findings=["F1"]
            )
        )
    ]
    started(client, headers, opp["id"])

    assert drain(db_url, ASSESS) == ["succeeded"]

    first_run, second_run = run_rows(sync_engine, opp["id"])
    v1, v2 = reviews(sync_engine, opp["id"])
    assert (v1["version"], v1["status"], v1["run_id"]) == (1, "superseded", first_run["id"])
    assert (v2["version"], v2["status"], v2["run_id"]) == (2, "current", second_run["id"])
    (kept,) = review_findings(sync_engine, v2["id"])
    (target,) = targets(sync_engine, kept["id"])
    assert target["assessment_version"] == 2  # the second run's Engineering Assessment
    assert [e["payload"]["superseded_count"] for e in critic_events(sync_engine, opp["id"])] == [
        0,
        1,
    ]
    body = get_critic(client, headers, opp["id"]).json()["review"]
    assert (body["version"], len(body["findings"])) == (2, 1)
    assert body["findings"][0]["findings"][0]["assessment_version"] == 2


def test_a_contradiction_not_raised_again_is_resolved_as_gone(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    fake = install(AgentGateway(replies(critic_agent=[HAPPY])))
    started(client, headers, opp["id"])
    assert drain(db_url, ASSESS) == ["succeeded"]
    (raised,) = conflicts(sync_engine, opp["id"])
    assert raised["status"] == "open"
    fake.replies[CRITIC] = [critic_out()]  # no contradiction this time
    started(client, headers, opp["id"])

    assert drain(db_url, ASSESS) == ["succeeded"]

    (gone,) = conflicts(sync_engine, opp["id"])
    assert gone["id"] == raised["id"] and gone["status"] == "resolved"
    assert gone["resolution_reason"] == (
        "No longer present in Engineering Assessment v2 and Security Assessment v2"
    )
    events = rows(
        sync_engine,
        "SELECT * FROM platform_trace_events WHERE subject_id = :c "
        "AND event_type = 'conflicts.conflict.resolved'",
        c=raised["id"],
    )
    assert [(e["actor_id"], e["payload"]["reason_kind"]) for e in events] == [
        ("critic_agent@0.1.0", "no_longer_present")
    ]


# --- the tool and the grants ------------------------------------------------------------------


def test_the_run_read_tool_returns_the_runs_assessments_and_is_scoped_to_the_task(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    install(AgentGateway(replies()))
    started(client, headers, opp["id"])
    assert drain(db_url, ASSESS) == ["succeeded"]
    (run,) = run_rows(sync_engine, opp["id"])
    critic = task_rows(sync_engine, run["id"])[CRITIC]

    def context(run_id: UUID | None, tools: frozenset[str]) -> ToolContext:
        return ToolContext(
            agent_id=CRITIC,
            semver="0.1.0",
            config_version_id=seed_config_version_id(CRITIC),
            tool_permissions=tools,
            opportunity_id=UUID(opp["id"]),
            run_id=run_id,
            task_id=critic["id"],
        )

    async def call(ctx: ToolContext, args: dict[str, Any] | None = None) -> Any:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                return await ToolGateway(Settings()).call(ctx, RUN_ASSESSMENT_READ, args, uow=uow)
        finally:
            await engine.dispose()

    granted = frozenset({RUN_ASSESSMENT_READ})
    result = run_async(call(context(run["id"], granted)))
    assert isinstance(result, ToolResult)
    assert [(r.assessment.agent, r.assessment.version, len(r.findings)) for r in result.items] == [
        ("engineering_agent", 1, 3),
        ("pm_agent", 1, 3),
        ("security_agent", 1, 3),
    ]
    assert isinstance(run_async(call(context(None, granted))), ToolDenied)
    other = run_async(call(context(run["id"], granted), {"run_id": str(UUID(int=7))}))
    assert other == ToolDenied("out_of_scope")
    assert run_async(call(context(run["id"], frozenset()))) == ToolDenied("tool_not_permitted")


def test_the_seeded_critic_config_grants_only_the_run_read_tool(sync_engine: Engine) -> None:
    (version,) = rows(
        sync_engine,
        "SELECT * FROM registry_agent_config_versions WHERE agent_id = :a",
        a=CRITIC,
    )
    assert version["id"] == seed_config_version_id(CRITIC)
    assert version["tool_permissions"] == ["assessments.run.read"]
    (agent,) = rows(sync_engine, "SELECT * FROM registry_agents WHERE agent_id = :a", a=CRITIC)
    assert (agent["name"], agent["status"]) == ("Critic Agent", "active")


def test_critic_findings_and_targets_are_insert_only_for_psa_app(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    install(AgentGateway(replies(critic_agent=[HAPPY])))
    started(client, headers, opp["id"])
    assert drain(db_url, ASSESS) == ["succeeded"]
    (review,) = reviews(sync_engine, opp["id"])
    first = review_findings(sync_engine, review["id"])[0]
    denied = [
        ("UPDATE assessments_finding_targets SET assessment_version = 9 WHERE finding_id = :i"),
        ("DELETE FROM assessments_finding_targets WHERE finding_id = :i"),
        ("UPDATE assessments_findings SET title = 'x' WHERE id = :i"),
        ("DELETE FROM assessments_findings WHERE id = :i"),
    ]
    for sql in denied:
        with pytest.raises(sa.exc.ProgrammingError), sync_engine.begin() as conn:
            conn.execute(sa.text(sql), {"i": first["id"]})
    with pytest.raises(sa.exc.ProgrammingError), sync_engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM assessments_reviews WHERE id = :i"), {"i": review["id"]})


def test_the_critic_is_not_an_assessment_agent() -> None:
    assert CRITIC not in {a.value for a in assessments_public.AGENTS}
    assert assessments_public.CRITIC_AGENT == CRITIC
