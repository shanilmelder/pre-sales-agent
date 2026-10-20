"""LLM-assisted Conflict detection (Story 6.2) against a real, migrated Postgres as psa_app,
with the per-agent fake gateway: the `conflicts.semantic_detection` job queued by
`finish_run`, `accept_semantic_conflicts` (every matrix row), the gone pass on a rerun, the
trace actor, the Finding on the position cards, resolving as in 6.3, the live
`conflicts.changed` frame, privacy and the registry seed.

Reuses the fixtures of `test_assessments_specialists.py` (jobs scheduled a day ahead;
`drain` runs only this test's Opportunities' jobs)."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.agents.conflict_agent.schema import ConflictOutput
from app.modules.conflicts.application import semantic as conflicts_semantic
from app.modules.workflows.application import events as stream_events
from app.modules.workflows.application import runs as workflows_runs
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.jobs.runner import run_job
from app.platform.model_gateway.port import ModelUnavailableError, StructuredRequest
from app.platform.uow import unit_of_work
from tests import test_assessments_specialists as specialist_tests
from tests import test_estimates_draft as draft_tests
from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests.conftest import run_async
from tests.test_assessments_specialists import (
    AgentGateway,
    assessment_out,
    effort,
    finding,
    install,
    prepared,
    replies,
    run_rows,
    started,
)
from tests.test_conflicts import conflict_events, conflict_rows, get, position_rows
from tests.test_conflicts_resolution import escalate, resolve
from tests.test_gaps_detection import requirement_rows, rows
from tests.test_intake_extraction import ASSESS, FakeGateway, drain
from tests.test_opportunities import BASE, PSE, _add, _user

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile
_draft_profile = draft_tests._draft_profile
_assessment_profile = specialist_tests._assessment_profile
_no_auto_run = specialist_tests._no_auto_run

SEMANTIC = "conflicts.semantic_detection"
ACTOR = "conflict_agent@0.1.0"
SSO = "SSO runs against the on-prem directory"
REGION = "Hosting in a single region"
GO_LIVE = "Go-live needs the Q3 freeze"
IDP = "Cloud identity provider required"
SUMMARY = "Engineering assumes on-prem SSO; Security requires a cloud IdP."
ENG_STANCE = "SSO authenticates against the customer's on-prem directory."
SEC_STANCE = "Only a cloud identity provider is acceptable."


@pytest.fixture(autouse=True)
def _semantic_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        conflicts_semantic, "semantic_settings", lambda: Settings(model_profile_chat="demo-chat")
    )


# Labels: F1, F2 Engineering; F3 PM; F4 Security. Both size R1 alike, so no rule fires.
def agents(
    *,
    engineering: Any = None,
    pm: Any = None,
    security: Any = None,
    conflict: list[Any] | None = None,
) -> dict[str, list[Any]]:
    out = replies(
        engineering_agent=[
            engineering
            or assessment_out(
                finding(SSO, ["R4"]), finding(REGION, ["R2"]), efforts=(effort("R1", 10),)
            )
        ],
        pm_agent=[pm or assessment_out(finding(GO_LIVE, ["R1"]), efforts=(effort("R1", 10),))],
        security_agent=[security or assessment_out(finding(IDP, ["R4"], kind="constraint"))],
    )
    out["conflict_agent"] = conflict if conflict is not None else [found(clash())]
    return out


def clash(
    *labels: str,
    type_: str = "architecture",
    severity: str = "high",
    summary: str = SUMMARY,
    mandatory: bool = False,
) -> dict[str, Any]:
    cited = list(labels) or ["F1", "F4"]
    stances = {"F1": ENG_STANCE, "F4": SEC_STANCE}
    return {
        "type": type_,
        "severity": severity,
        "finding_labels": cited,
        "summary": summary,
        "stances": [
            {"finding_label": label, "stance": stances.get(label, f"{label} holds otherwise.")}
            for label in cited
        ],
        "mandatory_constraint": mandatory,
    }


def found(*candidates: dict[str, Any]) -> ConflictOutput:
    return ConflictOutput.model_validate({"conflicts": list(candidates)})


def assess(client: TestClient, headers: dict[str, str], opp_id: str, db_url: str) -> None:
    started(client, headers, opp_id)
    assert drain(db_url, ASSESS)[-1] in {"succeeded", "dead"}


def semantic_jobs(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM platform_jobs WHERE opportunity_id = :o AND job_type = :t "
        "ORDER BY created_at, id",
        o=opp_id,
        t=SEMANTIC,
    )


def semantic_rows(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return [c for c in conflict_rows(engine, opp_id) if c["detected_by"] == "semantic"]


def finding_ids(engine: Engine, opp_id: str, agent: str) -> list[Any]:
    return [
        r["id"]
        for r in rows(
            engine,
            "SELECT f.id FROM assessments_assessment_findings f JOIN assessments_assessments a "
            "ON a.id = f.assessment_id WHERE a.opportunity_id = :o AND a.agent = :g "
            "AND a.status = 'current' ORDER BY f.position",
            o=opp_id,
            g=agent,
        )
    ]


def ready(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    fake: dict[str, list[Any]] | None = None,
) -> tuple[dict[str, str], dict[str, Any], AgentGateway]:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    installed = install(AgentGateway(fake or agents(), delay_s=0.01))
    assess(client, headers, opp["id"], db_url)
    return headers, opp, installed


# --- happy path -----------------------------------------------------------------------------


def test_contradicting_findings_become_one_semantic_conflict_with_finding_positions(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        headers, opp, fake = ready(client, sync_engine, db_url, gateway)
        (run_row,) = run_rows(sync_engine, opp["id"])
        (job,) = semantic_jobs(sync_engine, opp["id"])
        assert job["payload"] == {
            "opportunity_id": opp["id"],
            "run_id": str(run_row["id"]),
            "detection_pass": 1,
        }
        assert drain(db_url, SEMANTIC) == ["succeeded"]

    reqs = requirement_rows(sync_engine, opp["id"])
    assert [c["detected_by"] for c in conflict_rows(sync_engine, opp["id"])] == ["semantic"]
    (conflict,) = semantic_rows(sync_engine, opp["id"])
    assert (conflict["type"], conflict["severity"], conflict["status"]) == (
        "architecture",
        "high",
        "open",
    )
    assert (conflict["run_id"], conflict["detection_pass"]) == (run_row["id"], 1)
    sso_id = finding_ids(sync_engine, opp["id"], "engineering_agent")[0]
    (idp_id,) = finding_ids(sync_engine, opp["id"], "security_agent")
    ids = sorted(str(i) for i in (sso_id, idp_id))
    assert conflict["fingerprint"] == f"semantic:architecture:{ids[0]}+{ids[1]}"
    assert conflict["summary"] == SUMMARY
    engineering, security = position_rows(sync_engine, conflict["id"])
    assert (engineering["agent"], engineering["finding_id"], engineering["summary"]) == (
        "engineering_agent",
        sso_id,
        ENG_STANCE,
    )
    assert (security["agent"], security["finding_id"], security["summary"]) == (
        "security_agent",
        idp_id,
        SEC_STANCE,
    )
    for p in (engineering, security):
        assert (p["source"], p["assessment_version"], p["value"]) == ("assessment", 1, None)
        assert (p["requirement_id"], p["requirement_version"]) == (reqs[3]["id"], 1)

    (event,) = conflict_events(sync_engine, opp["id"])
    assert event["event_type"] == "conflicts.conflict.detected"
    assert (event["actor_type"], event["actor_id"]) == ("agent", ACTOR)
    assert event["payload"]["detected_by"] == "semantic"
    assert event["payload"]["position_count"] == 2

    # The prompt fences each Finding with a per-call token and cites Requirement labels.
    (request,) = [r for r in fake.requests if r.caller.agent_id == "conflict_agent"]
    user = request.messages[1].content
    token = user.split("token=", 1)[1].split(">>>", 1)[0]
    assert f"<<<FINDING F1 agent=engineering assessment=v1 token={token}>>>" in user
    assert f"<<<FINDING F4 agent=security assessment=v1 token={token}>>>" in user
    assert "requirements: R4" in user and f"<<<END F4 token={token}>>>" in user
    assert request.priority == "background"

    body = get(client, headers, opp["id"]).json()
    assert body["open_count"] == 1
    (view,) = body["conflicts"]
    assert (view["detected_by"], view["requirement"]["label"]) == ("semantic", "R4")
    assert [(p["agent"], p["summary"], p["finding"]) for p in view["positions"]] == [
        ("engineering_agent", ENG_STANCE, {"id": str(sso_id), "title": SSO, "kind": "risk"}),
        ("security_agent", SEC_STANCE, {"id": str(idp_id), "title": IDP, "kind": "constraint"}),
    ]

    # Resolved as in 6.3.
    decided = resolve(client, headers, opp["id"], view, 2)
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "resolved"
    assert decided.json()["positions"][1]["finding"]["title"] == IDP

    # Privacy: no Finding, stance or summary text in logs or the trace's detection events.
    logged = caplog.text + str([r.__dict__ for r in caplog.records])
    detected = str(
        [e for e in conflict_events(sync_engine, opp["id"]) if "detected" in e["event_type"]]
    )
    for leak in (SSO, IDP, SUMMARY, ENG_STANCE, SEC_STANCE, "on-prem"):
        assert leak not in logged
        assert leak not in detected


def test_a_rule_conflict_view_has_no_finding(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, _ = ready(
        client,
        sync_engine,
        db_url,
        gateway,
        agents(
            engineering=assessment_out(finding(SSO, ["R4"]), efforts=(effort("R4", 24),)),
            conflict=[found()],
        ),
    )
    assert drain(db_url, SEMANTIC) == ["succeeded"]
    views = get(client, headers, opp["id"]).json()["conflicts"]
    assert views and {v["detected_by"] for v in views} == {"rule"}
    assert {p["finding"] is None for v in views for p in v["positions"]} == {True}


# --- dropped candidates ---------------------------------------------------------------------


def test_invalid_candidates_are_dropped_and_the_valid_one_stored(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp, _ = ready(
        client,
        sync_engine,
        db_url,
        gateway,
        agents(
            conflict=[
                found(
                    clash("F1", "F2"),  # the same agent
                    clash("F1", "F99"),  # an unknown label
                    clash("F3", "F4", mandatory=True),
                    clash("F1", "F4", type_="effort"),
                    clash("F1", "F4"),
                )
            ]
        ),
    )
    assert drain(db_url, SEMANTIC) == ["succeeded"]
    (conflict,) = semantic_rows(sync_engine, opp["id"])
    assert conflict["type"] == "architecture"
    assert len(position_rows(sync_engine, conflict["id"])) == 2


def test_a_candidate_duplicating_an_open_rule_conflict_is_dropped(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    # Engineering sizes R4, PM doesn't: rule `scope:R4` is open. The Findings share R2 and R4.
    _, opp, _ = ready(
        client,
        sync_engine,
        db_url,
        gateway,
        agents(
            engineering=assessment_out(
                finding(SSO, ["R2", "R4"]), efforts=(effort("R1", 10), effort("R4", 24))
            ),
            security=assessment_out(finding(IDP, ["R4", "R2"], kind="constraint")),
            conflict=[found(clash("F1", "F3", type_="scope"), clash("F1", "F3"))],
        ),
    )
    assert drain(db_url, SEMANTIC) == ["succeeded"]
    by = {(c["detected_by"], c["type"]) for c in conflict_rows(sync_engine, opp["id"])}
    assert by == {("rule", "scope"), ("semantic", "architecture")}


def test_when_every_candidate_is_invalid_nothing_is_stored_and_the_job_retries_once(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp, fake = ready(
        client,
        sync_engine,
        db_url,
        gateway,
        agents(conflict=[found(clash("F1", "F2"), clash("F1", "F99"))]),
    )
    assert drain(db_url, SEMANTIC) == ["failed_retrying", "dead"]
    assert fake.calls("conflict_agent") == 2
    assert semantic_rows(sync_engine, opp["id"]) == []
    assert conflict_events(sync_engine, opp["id"]) == []


def test_when_every_candidate_is_filtered_the_gone_pass_runs_and_the_job_succeeds(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    fake_replies = agents(conflict=[found(clash()), found(clash(mandatory=True))])
    headers, opp, fake = ready(client, sync_engine, db_url, gateway, fake_replies)
    assert drain(db_url, SEMANTIC) == ["succeeded"]

    assess(client, headers, opp["id"], db_url)
    assert drain(db_url, SEMANTIC) == ["succeeded"]  # no retry
    assert fake.calls("conflict_agent") == 2
    (only,) = semantic_rows(sync_engine, opp["id"])
    assert only["status"] == "resolved"
    assert only["resolution_reason"] == (
        "No longer present in Engineering Assessment v2 and Security Assessment v2"
    )


def test_an_assumption_candidate_is_kept_while_a_recommendation_clash_is_open(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp, _ = ready(
        client,
        sync_engine,
        db_url,
        gateway,
        agents(
            engineering=assessment_out(
                finding(SSO, ["R4"]),
                finding(REGION, ["R2"]),
                efforts=(effort("R1", 10),),
                recommendation="proceed",
            ),
            security=assessment_out(
                finding(IDP, ["R4"], kind="constraint"), recommendation="do_not_proceed"
            ),
            conflict=[found(clash("F2", "F3", type_="assumption"))],
        ),
    )
    assert drain(db_url, SEMANTIC) == ["succeeded"]
    by = {(c["detected_by"], c["type"]) for c in conflict_rows(sync_engine, opp["id"])}
    assert by == {("rule", "assumption"), ("semantic", "assumption")}


def test_no_candidates_store_nothing_and_succeed(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp, fake = ready(client, sync_engine, db_url, gateway, agents(conflict=[found()]))
    assert drain(db_url, SEMANTIC) == ["succeeded"]
    assert fake.calls("conflict_agent") == 1
    assert conflict_rows(sync_engine, opp["id"]) == []


# --- reruns ---------------------------------------------------------------------------------


def test_a_rerun_raises_the_contradiction_again_and_resolves_the_earlier_one(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, _ = ready(client, sync_engine, db_url, gateway)
    assert drain(db_url, SEMANTIC) == ["succeeded"]
    (first,) = semantic_rows(sync_engine, opp["id"])

    assess(client, headers, opp["id"], db_url)
    assert drain(db_url, SEMANTIC) == ["succeeded"]

    earlier, newer = semantic_rows(sync_engine, opp["id"])
    assert earlier["id"] == first["id"] and earlier["status"] == "resolved"
    assert earlier["resolution_reason"] == (
        "No longer present in Engineering Assessment v2 and Security Assessment v2"
    )
    assert newer["status"] == "open" and newer["fingerprint"] != first["fingerprint"]
    assert {p["assessment_version"] for p in position_rows(sync_engine, newer["id"])} == {2}
    resolved = [
        e for e in conflict_events(sync_engine, opp["id"]) if e["subject_id"] == first["id"]
    ][-1]
    assert resolved["event_type"] == "conflicts.conflict.resolved"
    assert resolved["payload"]["reason_kind"] == "no_longer_present"
    assert resolved["actor_type"] == "system"
    listed = get(client, headers, opp["id"]).json()["conflicts"]
    (view,) = [v for v in listed if v["status"] == "open"]
    assert view["id"] == str(newer["id"])
    # The resolved one's cards keep the superseded Findings' titles.
    (gone,) = [v for v in listed if v["id"] == str(first["id"])]
    assert [p["finding"]["title"] for p in gone["positions"]] == [SSO, IDP]


def test_when_the_model_fails_twice_superseded_conflicts_are_still_resolved(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, fake = ready(client, sync_engine, db_url, gateway)
    assert drain(db_url, SEMANTIC) == ["succeeded"]
    (first,) = semantic_rows(sync_engine, opp["id"])
    fake.replies["conflict_agent"] = [ModelUnavailableError("down")]

    assess(client, headers, opp["id"], db_url)
    assert drain(db_url, SEMANTIC) == ["failed_retrying", "dead"]

    assert fake.calls("conflict_agent") == 3
    (only,) = semantic_rows(sync_engine, opp["id"])
    assert only["id"] == first["id"] and only["status"] == "resolved"
    assert only["resolution_reason"] == (
        "No longer present in Engineering Assessment v2 and Security Assessment v2"
    )


def test_when_the_agents_agree_on_a_rerun_the_earlier_conflict_is_resolved_as_gone(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    fake_replies = agents(conflict=[found(clash()), found()])
    headers, opp, _ = ready(client, sync_engine, db_url, gateway, fake_replies)
    assert drain(db_url, SEMANTIC) == ["succeeded"]

    assess(client, headers, opp["id"], db_url)
    assert drain(db_url, SEMANTIC) == ["succeeded"]

    (only,) = semantic_rows(sync_engine, opp["id"])
    assert only["status"] == "resolved"
    assert only["resolution_reason"].startswith("No longer present in Engineering Assessment v2")


def test_a_retry_pass_with_the_same_findings_carries_the_conflict_forward(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, _ = ready(client, sync_engine, db_url, gateway)
    assert drain(db_url, SEMANTIC) == ["succeeded"]
    (run_row,) = run_rows(sync_engine, opp["id"])

    async def again() -> None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            from app.modules.workflows.application import runs as workflows_runs
            from app.platform.uow import unit_of_work

            async with unit_of_work(engine) as uow:
                await workflows_runs.detect_conflicts(uow, UUID(opp["id"]), run_row["id"])
        finally:
            await engine.dispose()

    run_async(again())  # a second pass of the same run, same Assessments
    assert drain(db_url, SEMANTIC) == ["succeeded"]
    first, second = semantic_rows(sync_engine, opp["id"])
    assert second["detection_pass"] == 2 and second["previous_conflict_id"] == first["id"]
    assert first["resolution_reason"] == "Still present: carried forward to a later run."
    assert [v["id"] for v in get(client, headers, opp["id"]).json()["conflicts"]] == [
        str(second["id"])
    ]


def test_an_escalated_semantic_conflict_stands_when_not_raised_again(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, _ = ready(
        client, sync_engine, db_url, gateway, agents(conflict=[found(clash()), found()])
    )
    assert drain(db_url, SEMANTIC) == ["succeeded"]
    (view,) = get(client, headers, opp["id"]).json()["conflicts"]
    full = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    _, reviewer_id = _user(client, sync_engine, "Sam Reviewer", PSE)
    assert _add(client, headers, full, reviewer_id).status_code == 200
    assert escalate(client, headers, opp["id"], view, reviewer_id).status_code == 200

    assess(client, headers, opp["id"], db_url)
    assert drain(db_url, SEMANTIC) == ["succeeded"]
    (only,) = semantic_rows(sync_engine, opp["id"])
    assert only["status"] == "escalated"


# --- stale results and when no job is queued -------------------------------------------------


def test_a_result_accepted_after_a_newer_run_finished_writes_nothing_and_does_not_retry(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    def newer_run_meanwhile(request: StructuredRequest[Any]) -> ConflictOutput:
        with sync_engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO conflicts_detections (run_id, detection_pass, opportunity_id) "
                    "VALUES (:r, 1, :o)"
                ),
                {"r": uuid4(), "o": request.caller.opportunity_id},
            )
        return found(clash())

    _, opp, fake = ready(
        client, sync_engine, db_url, gateway, agents(conflict=[newer_run_meanwhile])
    )
    assert drain(db_url, SEMANTIC) == ["succeeded"]
    assert fake.calls("conflict_agent") == 1
    assert conflict_rows(sync_engine, opp["id"]) == []


def test_a_job_of_an_older_pass_is_skipped_without_a_model_call(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, fake = ready(client, sync_engine, db_url, gateway)
    assess(client, headers, opp["id"], db_url)
    assert len(semantic_jobs(sync_engine, opp["id"])) == 2
    assert drain(db_url, SEMANTIC) == ["succeeded", "succeeded"]
    assert fake.calls("conflict_agent") == 1  # only the newer run's
    (only,) = semantic_rows(sync_engine, opp["id"])
    assert {p["assessment_version"] for p in position_rows(sync_engine, only["id"])} == {2}


def test_without_a_job_open_semantic_conflicts_citing_superseded_assessments_are_resolved(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, _ = ready(client, sync_engine, db_url, gateway)
    assert drain(db_url, SEMANTIC) == ["succeeded"]
    (first,) = semantic_rows(sync_engine, opp["id"])
    # The rerun queues no job (the agent is disabled now), yet the Assessments it cited are
    # superseded: it is resolved in finish_run's Unit of Work.
    set_conflict_agent_status(sync_engine, "disabled")
    try:

        async def rerun(_: Any) -> None:
            await asyncio.to_thread(assess, client, headers, opp["id"], db_url)

        assert _frame_after(db_url, opp["id"], rerun, CONFLICTS_CHANGED_FRAME) == (
            CONFLICTS_CHANGED_FRAME
        )
    finally:
        set_conflict_agent_status(sync_engine, "active")
    assert len(semantic_jobs(sync_engine, opp["id"])) == 1
    (only,) = semantic_rows(sync_engine, opp["id"])
    assert only["id"] == first["id"] and only["status"] == "resolved"
    assert only["resolution_reason"] == (
        "No longer present in Engineering Assessment v2 and Security Assessment v2"
    )
    resolved = [
        e for e in conflict_events(sync_engine, opp["id"]) if e["subject_id"] == first["id"]
    ]
    assert resolved[-1]["payload"]["reason_kind"] == "no_longer_present"
    assert (resolved[-1]["actor_type"], resolved[-1]["actor_id"]) == (
        "system",
        "conflicts.semantic_detection",
    )


def test_without_a_job_a_conflict_citing_current_assessments_stays_open(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp, _ = ready(client, sync_engine, db_url, gateway)
    assert drain(db_url, SEMANTIC) == ["succeeded"]
    (run_row,) = run_rows(sync_engine, opp["id"])
    set_conflict_agent_status(sync_engine, "disabled")
    try:

        async def again() -> None:
            engine = create_engine(Settings(database_url=db_url))
            try:
                async with unit_of_work(engine) as uow:
                    await workflows_runs.detect_conflicts(uow, UUID(opp["id"]), run_row["id"])
            finally:
                await engine.dispose()

        run_async(again())  # the same Assessments, no job
    finally:
        set_conflict_agent_status(sync_engine, "active")
    (only,) = semantic_rows(sync_engine, opp["id"])
    assert only["status"] == "open"


def test_no_job_is_queued_when_only_one_agent_has_findings(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp, _ = ready(
        client,
        sync_engine,
        db_url,
        gateway,
        agents(
            pm=assessment_out(efforts=(effort("R1", 10),)),
            security=assessment_out(),
        ),
    )
    assert semantic_jobs(sync_engine, opp["id"]) == []


def set_conflict_agent_status(engine: Engine, value: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE registry_agents SET status = :s, row_version = row_version + 1 "
                "WHERE agent_id = 'conflict_agent'"
            ),
            {"s": value},
        )


@pytest.fixture
def conflict_agent_disabled(sync_engine: Engine) -> Iterator[None]:
    set_conflict_agent_status(sync_engine, "disabled")
    try:
        yield
    finally:
        set_conflict_agent_status(sync_engine, "active")


def test_no_job_is_queued_while_the_conflict_agent_is_disabled(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    conflict_agent_disabled: None,
) -> None:
    _, opp, _ = ready(client, sync_engine, db_url, gateway)
    assert semantic_jobs(sync_engine, opp["id"]) == []


def test_a_queued_job_is_skipped_once_the_conflict_agent_is_disabled(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp, fake = ready(client, sync_engine, db_url, gateway)
    assert len(semantic_jobs(sync_engine, opp["id"])) == 1
    set_conflict_agent_status(sync_engine, "disabled")
    try:
        assert drain(db_url, SEMANTIC) == ["succeeded"]
    finally:
        set_conflict_agent_status(sync_engine, "active")
    assert fake.calls("conflict_agent") == 0
    assert semantic_rows(sync_engine, opp["id"]) == []


def test_a_job_skipped_at_start_still_resolves_superseded_conflicts(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, fake = ready(client, sync_engine, db_url, gateway)
    assert drain(db_url, SEMANTIC) == ["succeeded"]
    (first,) = semantic_rows(sync_engine, opp["id"])
    assess(client, headers, opp["id"], db_url)  # queues a job: the agent is still active
    set_conflict_agent_status(sync_engine, "disabled")
    try:
        assert drain(db_url, SEMANTIC) == ["succeeded"]
    finally:
        set_conflict_agent_status(sync_engine, "active")
    assert fake.calls("conflict_agent") == 1  # only the first run's
    (only,) = semantic_rows(sync_engine, opp["id"])
    assert only["id"] == first["id"] and only["status"] == "resolved"


def test_the_conflict_agent_is_seeded_active_at_version_one(sync_engine: Engine) -> None:
    (agent,) = rows(sync_engine, "SELECT * FROM registry_agents WHERE agent_id = 'conflict_agent'")
    assert (agent["name"], agent["status"]) == ("Conflict Agent", "active")
    (version,) = rows(
        sync_engine,
        "SELECT * FROM registry_agent_config_versions WHERE agent_id = 'conflict_agent'",
    )
    assert (version["version"], version["semver"], version["model_profile"]) == (
        1,
        "0.1.0",
        "demo-chat",
    )
    assert (version["prompt_version"], version["output_schema_version"]) == (1, 1)
    assert (version["contract_version"], version["tool_permissions"]) == ("1", [])


def test_psa_app_cannot_change_or_delete_detection_passes(sync_engine: Engine) -> None:
    run_id = uuid4()
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO conflicts_detections (run_id, detection_pass, opportunity_id) "
                "VALUES (:r, 1, :o)"
            ),
            {"r": run_id, "o": uuid4()},
        )
    for statement in (
        "UPDATE conflicts_detections SET detection_pass = 2 WHERE run_id = :r",
        "DELETE FROM conflicts_detections WHERE run_id = :r",
    ):
        with pytest.raises(sa.exc.ProgrammingError), sync_engine.begin() as conn:
            conn.execute(sa.text(statement), {"r": run_id})


# --- live updates ---------------------------------------------------------------------------

CONFLICTS_CHANGED_FRAME = 'event: conflicts.changed\ndata: {"source": "conflicts"}\n\n'


def _frame_after(
    db_url: str,
    opp_id: str,
    action: Callable[[Any], Awaitable[None]],
    wanted: str | None = None,
) -> str:
    """The first frame the Opportunity's stream sends after `action(engine)` (with `wanted`,
    the first such frame, skipping progress frames)."""

    async def scenario() -> str:
        engine = create_engine(Settings(database_url=db_url))
        stream = stream_events.event_stream(engine, db_url, UUID(opp_id), None, keepalive_s=0.2)
        try:
            assert await anext(stream) == ": connected\n\n"
            await action(engine)
            deadline = asyncio.get_running_loop().time() + 10.0  # fail, don't hang
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise AssertionError("no matching frame within 10 s")
                chunk = await asyncio.wait_for(anext(stream), remaining)
                if not chunk.startswith(":") and (wanted is None or chunk == wanted):
                    return chunk
        finally:
            await stream.aclose()
            await engine.dispose()

    return run_async(scenario())


def test_storing_a_semantic_conflict_sends_a_conflicts_changed_frame(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp, _ = ready(client, sync_engine, db_url, gateway)

    async def run_semantic(engine: Any) -> None:
        job = await extraction_tests._claim_mine(engine, (SEMANTIC,))
        assert job is not None
        assert await run_job(engine, job, extraction_tests.LEASE) == "succeeded"

    assert _frame_after(db_url, opp["id"], run_semantic) == CONFLICTS_CHANGED_FRAME


def test_resolving_a_conflict_sends_a_conflicts_changed_frame(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, _ = ready(client, sync_engine, db_url, gateway)
    assert drain(db_url, SEMANTIC) == ["succeeded"]
    (view,) = get(client, headers, opp["id"]).json()["conflicts"]

    async def decide(_: Any) -> None:
        assert resolve(client, headers, opp["id"], view, 1).status_code == 200

    assert _frame_after(db_url, opp["id"], decide) == CONFLICTS_CHANGED_FRAME


def test_escalating_a_conflict_sends_a_conflicts_changed_frame(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, _ = ready(client, sync_engine, db_url, gateway)
    assert drain(db_url, SEMANTIC) == ["succeeded"]
    (view,) = get(client, headers, opp["id"]).json()["conflicts"]
    full = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    _, reviewer_id = _user(client, sync_engine, "Sam Reviewer", PSE)
    assert _add(client, headers, full, reviewer_id).status_code == 200

    async def escalated(_: Any) -> None:
        assert escalate(client, headers, opp["id"], view, reviewer_id).status_code == 200

    assert _frame_after(db_url, opp["id"], escalated) == CONFLICTS_CHANGED_FRAME


def test_a_firing_rule_sends_a_conflicts_changed_frame(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    # Engineering sizes R4, PM doesn't: the scope rule fires.
    _, opp, _ = ready(
        client,
        sync_engine,
        db_url,
        gateway,
        agents(
            engineering=assessment_out(finding(SSO, ["R4"]), efforts=(effort("R4", 24),)),
            conflict=[found()],
        ),
    )
    (run_row,) = run_rows(sync_engine, opp["id"])
    # Make the next pass raise afresh: the earlier scope Conflict is resolved by hand.
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE conflicts_conflicts SET status = 'resolved', resolved_at = now(), "
                "resolution_reason = 'test' WHERE opportunity_id = :o"
            ),
            {"o": opp["id"]},
        )

    async def detect(engine: Any) -> None:
        async with unit_of_work(engine) as uow:
            await workflows_runs.detect_conflicts(uow, UUID(opp["id"]), run_row["id"])

    assert _frame_after(db_url, opp["id"], detect) == CONFLICTS_CHANGED_FRAME


def test_a_pass_that_stores_nothing_is_recorded_so_the_next_pass_is_two(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, opp, _ = ready(client, sync_engine, db_url, gateway, agents(conflict=[found()]))
    assert drain(db_url, SEMANTIC) == ["succeeded"]
    assert conflict_rows(sync_engine, opp["id"]) == []  # pass 1 stored nothing
    (run_row,) = run_rows(sync_engine, opp["id"])

    async def again() -> None:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                await workflows_runs.detect_conflicts(uow, UUID(opp["id"]), run_row["id"])
        finally:
            await engine.dispose()

    run_async(again())  # the run finishes again
    passes = rows(
        sync_engine,
        "SELECT detection_pass FROM conflicts_detections WHERE run_id = :r ORDER BY 1",
        r=run_row["id"],
    )
    assert [p["detection_pass"] for p in passes] == [1, 2]
    first, second = semantic_jobs(sync_engine, opp["id"])
    assert (first["payload"]["detection_pass"], second["payload"]["detection_pass"]) == (1, 2)


def test_the_stream_maps_conflicts_notifications_to_their_frame() -> None:
    opp = uuid4()
    payload = f'{{"opportunity_id": "{opp}", "source": "conflicts"}}'
    assert stream_events._notified(payload, opp) == "conflicts"
    assert stream_events._notified(payload, uuid4()) is None
    assert stream_events.CONFLICTS_CHANGED_FRAME == CONFLICTS_CHANGED_FRAME
