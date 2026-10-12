"""Conflict detection at the end of an assessment run (Story 6.1) against a real, migrated
Postgres as psa_app, with the per-agent fake gateway: `conflicts.detect_for_run` from
`finish_run`, `raise_conflict` idempotency, reruns (resolved / carried forward), the
Estimate rule, `list_open`, `GET …/conflicts`, privacy and the table grants.

Reuses the fixtures of `test_assessments_specialists.py` (jobs scheduled a day ahead;
`drain` runs only this test's Opportunities' jobs)."""

import logging
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.assessments.application import assessment as assessments_assessment
from app.modules.conflicts.adapters import repository as conflicts_repo
from app.modules.conflicts.application import public as conflicts
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.model_gateway import provider
from app.platform.model_gateway.port import ModelUnavailableError
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
    retry,
    run_rows,
    started,
)
from tests.test_gaps_detection import requirement_rows, rows
from tests.test_intake_extraction import ASSESS, BASE, FakeGateway, drain
from tests.test_opportunities import PSE, _add, _user

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile
_draft_profile = draft_tests._draft_profile
_assessment_profile = specialist_tests._assessment_profile
_no_auto_run = specialist_tests._no_auto_run


def agent_out(*efforts: dict[str, Any], recommendation: str = "proceed_with_conditions") -> Any:
    return assessment_out(
        finding("Interface details open", ["R1"]), efforts=efforts, recommendation=recommendation
    )


def conflict_rows(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM conflicts_conflicts WHERE opportunity_id = :o ORDER BY created_at, id",
        o=opp_id,
    )


def position_rows(engine: Engine, conflict_id: Any) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM conflicts_positions WHERE conflict_id = :c ORDER BY position",
        c=conflict_id,
    )


def conflict_events(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM platform_trace_events WHERE opportunity_id = :o "
        "AND event_type LIKE 'conflicts.%' ORDER BY occurred_at, id",
        o=opp_id,
    )


def get(client: TestClient, headers: dict[str, str], opp_id: str) -> Any:
    return client.get(f"{BASE}/{opp_id}/conflicts", headers=headers)


def run(client: TestClient, headers: dict[str, str], opp_id: str, db_url: str) -> None:
    started(client, headers, opp_id)
    assert drain(db_url, ASSESS)[-1] in {"succeeded", "dead"}


# Engineering sizes R4 at 24 h; PM sizes R1 only; Security sizes nothing.
SCOPE = replies(
    engineering_agent=[agent_out(effort("R1", 10), effort("R4", 24))],
    pm_agent=[agent_out(effort("R1", 8))],
    security_agent=[agent_out()],
)


# --- happy path and agreement ---------------------------------------------------------------


def test_a_scope_disagreement_is_one_open_conflict_with_two_positions(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    reqs = requirement_rows(sync_engine, opp["id"])
    install(AgentGateway(SCOPE))

    with caplog.at_level(logging.DEBUG):
        run(client, headers, opp["id"], db_url)

    (run_row,) = run_rows(sync_engine, opp["id"])
    (conflict,) = conflict_rows(sync_engine, opp["id"])
    assert (conflict["type"], conflict["severity"], conflict["status"]) == (
        "scope",
        "medium",
        "open",
    )
    assert (conflict["detected_by"], conflict["run_id"]) == ("rule", run_row["id"])
    assert conflict["fingerprint"] == f"scope:{reqs[3]['id']}:engineering_agent+pm_agent"
    assert conflict["previous_conflict_id"] is None
    assert (conflict["resolved_at"], conflict["resolution_reason"]) == (None, None)
    assert conflict["row_version"] == 1
    engineering, pm = position_rows(sync_engine, conflict["id"])
    assert (engineering["agent"], engineering["summary"], str(engineering["value"])) == (
        "engineering_agent",
        "24 h",
        "24.0",
    )
    assert (pm["agent"], pm["summary"], pm["value"]) == ("pm_agent", "Not sized", None)
    for position in (engineering, pm):
        assert (position["source"], position["assessment_version"]) == ("assessment", 1)
        assert (position["requirement_id"], position["requirement_version"]) == (reqs[3]["id"], 1)
        assert position["estimate_version_id"] is None

    (event,) = conflict_events(sync_engine, opp["id"])
    assert event["event_type"] == "conflicts.conflict.detected"
    assert (event["actor_type"], event["actor_id"]) == ("system", "conflicts.detect_conflicts")
    assert (event["subject_type"], event["subject_id"]) == ("conflicts.conflict", conflict["id"])
    assert event["payload"] == {
        "run_id": str(run_row["id"]),
        "type": "scope",
        "severity": "medium",
        "detected_by": "rule",
        "position_count": 2,
    }

    body = get(client, headers, opp["id"]).json()
    assert body["open_count"] == 1
    (view,) = body["conflicts"]
    assert (view["id"], view["type"], view["severity"], view["status"]) == (
        str(conflict["id"]),
        "scope",
        "medium",
        "open",
    )
    assert view["requirement"] == {
        "id": str(reqs[3]["id"]),
        "version": 1,
        "label": "R4",
        "excerpt": "Single sign-on.",
    }
    assert [
        (p["position"], p["agent"], p["summary"], p["value"], p["assessment_version"])
        for p in view["positions"]
    ] == [
        (1, "engineering_agent", "24 h", 24.0, 1),
        (2, "pm_agent", "Not sized", None, 1),
    ]
    assert view["positions"][0]["requirement"]["label"] == "R4"

    # Privacy: no Requirement or Finding text in logs or the trace.
    logged = caplog.text + str([r.__dict__ for r in caplog.records])
    trace_text = str(conflict_events(sync_engine, opp["id"]))
    for leak in ("Single sign-on", "Interface details", "Nothing shows", "Sized R"):
        assert leak not in logged
        assert leak not in trace_text


def test_agreeing_assessments_raise_no_conflict(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    install(
        AgentGateway(
            replies(
                engineering_agent=[agent_out(effort("R1", 10))],
                pm_agent=[agent_out(effort("R1", 8))],
                security_agent=[agent_out()],
            )
        )
    )
    run(client, headers, opp["id"], db_url)

    assert conflict_rows(sync_engine, opp["id"]) == []
    assert conflict_events(sync_engine, opp["id"]) == []
    assert get(client, headers, opp["id"]).json() == {"conflicts": [], "open_count": 0}


def test_detecting_again_for_the_same_pass_adds_nothing(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    install(AgentGateway(SCOPE))
    run(client, headers, opp["id"], db_url)
    (run_row,) = run_rows(sync_engine, opp["id"])
    before = conflict_rows(sync_engine, opp["id"])
    assert [c["detection_pass"] for c in before] == [1]

    async def same_pass(uow: Any, run_id: UUID) -> int:
        return 0  # the next detection is pass 1 again

    monkeypatch.setattr(conflicts_repo, "latest_pass", same_pass)

    async def again() -> list[UUID]:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                await assessments_assessment.detect_conflicts(uow, UUID(opp["id"]), run_row["id"])
            async with unit_of_work(engine) as uow:
                return [UUID(c.id) for c in await conflicts.list_open(uow, UUID(opp["id"]))]
        finally:
            await engine.dispose()

    listed = run_async(again())

    assert conflict_rows(sync_engine, opp["id"]) == before
    assert len(conflict_events(sync_engine, opp["id"])) == 1
    assert listed == [before[0]["id"]]


# --- partial runs and task retries ----------------------------------------------------------


def test_a_partial_run_uses_the_failed_agents_earlier_assessment_and_a_retry_is_a_new_pass(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    fake = install(
        AgentGateway(
            replies(
                engineering_agent=[agent_out(effort("R1", 10), recommendation="proceed")],
                pm_agent=[agent_out(effort("R1", 8))],
                security_agent=[agent_out(recommendation="do_not_proceed")],
            )
        )
    )
    run(client, headers, opp["id"], db_url)
    (first,) = conflict_rows(sync_engine, opp["id"])
    assert (first["type"], first["severity"], first["fingerprint"]) == (
        "assumption",
        "high",
        "recommendation_clash",
    )

    # Run 2: Security fails on both attempts; its v1 still says do not proceed.
    fake.replies["security_agent"] = [ModelUnavailableError("down", error_code="connection")]
    body = started(client, headers, opp["id"])
    assert drain(db_url, ASSESS) == ["failed_retrying", "dead"]
    second_run = run_rows(sync_engine, opp["id"])[-1]
    assert second_run["status"] == "partially_failed"

    old, new = conflict_rows(sync_engine, opp["id"])
    assert (old["id"], old["status"]) == (first["id"], "resolved")
    assert (new["status"], new["previous_conflict_id"]) == ("open", first["id"])
    assert {
        (p["agent"], p["assessment_version"]) for p in position_rows(sync_engine, new["id"])
    } == {
        ("engineering_agent", 2),
        ("pm_agent", 2),
        ("security_agent", 1),
    }
    assert new["detection_pass"] == 1

    # Retry Security with the same view: the run finishes again as pass 2, which carries the
    # clash forward with Security's new Assessment.
    fake.replies["security_agent"] = [agent_out(recommendation="do_not_proceed")]
    assert retry(client, headers, opp["id"], body["id"], "security_agent").status_code == 201
    assert drain(db_url, ASSESS) == ["succeeded"]

    _, pass_1, pass_2 = conflict_rows(sync_engine, opp["id"])
    assert (pass_1["id"], pass_1["status"]) == (new["id"], "resolved")
    assert (pass_2["run_id"], pass_2["detection_pass"]) == (new["run_id"], 2)
    assert (pass_2["status"], pass_2["previous_conflict_id"]) == ("open", new["id"])
    assert ("security_agent", 2) in {
        (p["agent"], p["assessment_version"]) for p in position_rows(sync_engine, pass_2["id"])
    }
    # Run 1's and pass 1's Conflicts were carried forward: only pass 2's is listed.
    assert [c["id"] for c in get(client, headers, opp["id"]).json()["conflicts"]] == [
        str(pass_2["id"])
    ]


def test_a_retried_task_adds_its_position_in_a_new_detection_pass(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    fake = install(
        AgentGateway(
            replies(
                engineering_agent=[agent_out(effort("R1", 10), recommendation="proceed")],
                pm_agent=[agent_out(effort("R1", 8), recommendation="do_not_proceed")],
                security_agent=[ModelUnavailableError("down", error_code="connection")],
            )
        )
    )
    body = started(client, headers, opp["id"])
    assert drain(db_url, ASSESS) == ["failed_retrying", "dead"]
    (first,) = conflict_rows(sync_engine, opp["id"])
    assert (first["fingerprint"], first["detection_pass"]) == ("recommendation_clash", 1)
    assert [p["agent"] for p in position_rows(sync_engine, first["id"])] == [
        "engineering_agent",
        "pm_agent",
    ]

    fake.replies["security_agent"] = [agent_out(recommendation="do_not_proceed")]
    assert retry(client, headers, opp["id"], body["id"], "security_agent").status_code == 201
    assert drain(db_url, ASSESS) == ["succeeded"]

    old, again = conflict_rows(sync_engine, opp["id"])
    assert (old["id"], old["status"]) == (first["id"], "resolved")
    assert (again["run_id"], again["detection_pass"]) == (first["run_id"], 2)
    assert (again["status"], again["previous_conflict_id"]) == ("open", first["id"])
    assert [(p["agent"], p["summary"]) for p in position_rows(sync_engine, again["id"])] == [
        ("engineering_agent", "Proceed"),
        ("pm_agent", "Do not proceed"),
        ("security_agent", "Do not proceed"),
    ]
    view = get(client, headers, opp["id"]).json()
    assert [c["id"] for c in view["conflicts"]] == [str(again["id"])]
    assert view["open_count"] == 1


# --- reruns ---------------------------------------------------------------------------------


def test_a_conflict_gone_on_a_rerun_is_resolved_naming_the_assessment(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    fake = install(AgentGateway(SCOPE))
    run(client, headers, opp["id"], db_url)
    (conflict,) = conflict_rows(sync_engine, opp["id"])

    fake.replies["pm_agent"] = [agent_out(effort("R1", 8), effort("R4", 6))]
    run(client, headers, opp["id"], db_url)

    (resolved,) = conflict_rows(sync_engine, opp["id"])
    assert (resolved["id"], resolved["status"]) == (conflict["id"], "resolved")
    assert resolved["resolution_reason"] == "No longer present in PM Assessment v2"
    assert resolved["resolved_at"] is not None
    assert resolved["row_version"] == 2
    _, gone = conflict_events(sync_engine, opp["id"])
    assert gone["event_type"] == "conflicts.conflict.resolved"
    assert gone["actor_type"] == "system"
    assert (gone["subject_id"], gone["subject_version"]) == (conflict["id"], None)
    assert gone["payload"] == {
        "run_id": str(run_rows(sync_engine, opp["id"])[-1]["id"]),
        "reason_kind": "no_longer_present",
    }

    body = get(client, headers, opp["id"]).json()
    assert body["open_count"] == 0
    (view,) = body["conflicts"]
    assert (view["status"], view["resolution_reason"]) == (
        "resolved",
        "No longer present in PM Assessment v2",
    )
    assert view["resolved_at"] is not None


def test_a_conflict_that_comes_back_is_raised_again_unlinked(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    fake = install(AgentGateway(SCOPE))
    run(client, headers, opp["id"], db_url)  # run 1: scope on R4
    fake.replies["pm_agent"] = [agent_out(effort("R1", 8), effort("R4", 6))]
    run(client, headers, opp["id"], db_url)  # run 2: PM sizes R4, the Conflict is gone
    fake.replies["pm_agent"] = [agent_out(effort("R1", 8))]
    run(client, headers, opp["id"], db_url)  # run 3: PM drops R4 again

    gone, back = conflict_rows(sync_engine, opp["id"])
    assert gone["fingerprint"] == back["fingerprint"]
    assert (gone["status"], gone["resolution_reason"]) == (
        "resolved",
        "No longer present in PM Assessment v2",
    )
    assert (back["status"], back["previous_conflict_id"]) == ("open", None)
    assert back["run_id"] == run_rows(sync_engine, opp["id"])[-1]["id"]

    view = get(client, headers, opp["id"]).json()
    assert [(c["id"], c["status"]) for c in view["conflicts"]] == [
        (str(back["id"]), "open"),
        (str(gone["id"]), "resolved"),
    ]
    assert view["open_count"] == 1


def test_a_conflict_still_there_on_a_rerun_links_the_previous_one(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    install(AgentGateway(SCOPE))
    run(client, headers, opp["id"], db_url)
    run(client, headers, opp["id"], db_url)

    old, new = conflict_rows(sync_engine, opp["id"])
    assert old["fingerprint"] == new["fingerprint"]
    assert (old["status"], new["status"]) == ("resolved", "open")
    assert new["previous_conflict_id"] == old["id"]
    assert new["run_id"] != old["run_id"]
    assert [p["assessment_version"] for p in position_rows(sync_engine, new["id"])] == [2, 2]
    kinds = [
        (e["event_type"], e["payload"].get("reason_kind"))
        for e in conflict_events(sync_engine, opp["id"])
    ]
    assert kinds == [
        ("conflicts.conflict.detected", None),
        ("conflicts.conflict.detected", None),
        ("conflicts.conflict.resolved", "carried_forward"),
    ]

    body = get(client, headers, opp["id"]).json()
    assert body["open_count"] == 1
    assert [(c["id"], c["previous_conflict_id"]) for c in body["conflicts"]] == [
        (str(new["id"]), str(old["id"]))
    ]


# --- the recommendation clash ---------------------------------------------------------------


def test_proceed_against_do_not_proceed_is_an_opportunity_level_conflict(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    install(
        AgentGateway(
            replies(
                engineering_agent=[agent_out(effort("R1", 10), recommendation="proceed")],
                pm_agent=[agent_out(effort("R1", 8))],
                security_agent=[agent_out(recommendation="do_not_proceed")],
            )
        )
    )
    run(client, headers, opp["id"], db_url)

    (view,) = get(client, headers, opp["id"]).json()["conflicts"]
    assert (view["type"], view["severity"], view["requirement"]) == ("assumption", "high", None)
    assert [(p["agent"], p["summary"], p["requirement"]) for p in view["positions"]] == [
        ("engineering_agent", "Proceed", None),
        ("pm_agent", "Proceed with conditions", None),
        ("security_agent", "Do not proceed", None),
    ]


# --- agents vs Estimate ---------------------------------------------------------------------


def _edit_line(
    client: TestClient, headers: dict[str, str], opp_id: str, requirement: str, hours: float
) -> None:
    """A person sets the hours of the current Estimate's line covering `requirement` (R<n>)."""
    estimate = client.get(f"{BASE}/{opp_id}/estimate", headers=headers).json()
    (line,) = [
        line
        for section in estimate["version"]["sections"]
        for line in section["lines"]
        if [r["label"] for r in line["requirements"]] == [requirement]
    ]
    edited = client.patch(
        f"{BASE}/{opp_id}/estimate-lines/{line['id']}",
        headers={**headers, "If-Match": f'"{line["row_version"]}"'},
        json={"effort_hours": hours, "reason": "Our own figure"},
    )
    assert edited.status_code == 200, edited.text


def _edited(
    client: TestClient, engine: Engine, db_url: str, gateway: FakeGateway, hours: float
) -> tuple[dict[str, str], dict[str, Any]]:
    """An Opportunity whose Estimate v1, built from a first run of the EFFORT agents (R1 6 h,
    R2 100 h), has R2's line edited to `hours`. Story 8.3: the next run builds v2 from the
    agents and carries the edit, so it differs from the agents only by that edit."""
    headers, opp = prepared(client, engine, db_url, gateway)
    install(AgentGateway(EFFORT))
    run(client, headers, opp["id"], db_url)
    assert conflict_rows(engine, opp["id"]) == []  # v1 is the agents' own hours
    _edit_line(client, headers, opp["id"], "R2", hours)
    return headers, opp


EFFORT = replies(
    engineering_agent=[agent_out(effort("R1", 4), effort("R2", 60))],
    pm_agent=[agent_out(effort("R1", 2), effort("R2", 40))],
    security_agent=[agent_out()],
)


def test_the_estimate_30_percent_above_the_agents_is_no_conflict(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = _edited(client, sync_engine, db_url, gateway, 130)
    run(client, headers, opp["id"], db_url)

    assert conflict_rows(sync_engine, opp["id"]) == []


def test_the_estimate_more_than_30_percent_above_is_an_effort_conflict(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = _edited(client, sync_engine, db_url, gateway, 131)
    reqs = requirement_rows(sync_engine, opp["id"])
    run(client, headers, opp["id"], db_url)
    version = rows(
        sync_engine,
        "SELECT * FROM estimates_estimate_versions WHERE opportunity_id = :o AND version = 2",
        o=opp["id"],
    )[0]

    (conflict,) = conflict_rows(sync_engine, opp["id"])
    assert (conflict["type"], conflict["severity"], conflict["fingerprint"]) == (
        "effort",
        "medium",
        f"effort:{reqs[1]['id']}",
    )
    positions = position_rows(sync_engine, conflict["id"])
    assert [(p["source"], p["agent"], str(p["value"])) for p in positions] == [
        ("assessment", "engineering_agent", "60.0"),
        ("assessment", "pm_agent", "40.0"),
        ("estimate", None, "131.0"),
    ]
    estimate = positions[-1]
    assert (estimate["estimate_version_id"], estimate["estimate_version"]) == (version["id"], 2)
    assert (estimate["assessment_id"], estimate["assessment_version"]) == (None, None)

    (view,) = get(client, headers, opp["id"]).json()["conflicts"]
    assert view["positions"][-1]["estimate_version"] == 2
    assert view["positions"][-1]["requirement"]["label"] == "R2"


# --- reads and access -----------------------------------------------------------------------


def test_open_conflicts_come_first_then_by_severity(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    fake = install(AgentGateway(SCOPE))
    run(client, headers, opp["id"], db_url)  # scope on R4 (resolved by run 2)
    fake.replies["engineering_agent"] = [
        agent_out(effort("R1", 10), effort("R3", 5), recommendation="proceed")
    ]
    fake.replies["security_agent"] = [agent_out(recommendation="do_not_proceed")]
    run(client, headers, opp["id"], db_url)  # scope on R3 and the clash

    body = get(client, headers, opp["id"]).json()

    assert [(c["type"], c["severity"], c["status"]) for c in body["conflicts"]] == [
        ("assumption", "high", "open"),
        ("scope", "medium", "open"),
        ("scope", "medium", "resolved"),
    ]
    assert body["open_count"] == 2


def test_same_severity_conflicts_list_newest_first_then_in_requirement_order(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    fake = install(AgentGateway(SCOPE))  # run 1: scope on R4; Estimate v1 R1 18 h
    run(client, headers, opp["id"], db_url)
    _edit_line(client, headers, opp["id"], "R1", 5)  # carried on: an effort Conflict on R1
    fake.replies["engineering_agent"] = [agent_out(effort("R1", 10), effort("R3", 5))]
    run(client, headers, opp["id"], db_url)  # run 2: scope on R3, effort on R1; R4 resolved
    fake.replies["engineering_agent"] = [
        agent_out(effort("R1", 10), effort("R2", 10), effort("R5", 5))
    ]
    run(client, headers, opp["id"], db_url)  # run 3: scope on R2 and R5; R3 resolved

    listed = [
        (c["type"], c["status"], c["requirement"]["label"])
        for c in get(client, headers, opp["id"]).json()["conflicts"]
    ]

    # One run's Conflicts in Requirement order (its R1 effort Conflict was raised last); the
    # resolved ones from different runs newest first.
    assert listed == [
        ("effort", "open", "R1"),
        ("scope", "open", "R2"),
        ("scope", "open", "R5"),
        ("scope", "resolved", "R3"),
        ("scope", "resolved", "R4"),
    ]


def test_a_requirement_no_longer_active_reads_as_superseded(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    install(
        AgentGateway(
            replies(
                engineering_agent=[agent_out(effort("R1", 10), effort("R2", 6))],
                pm_agent=[agent_out(effort("R1", 8))],
                security_agent=[agent_out()],
            )
        )
    )
    run(client, headers, opp["id"], db_url)  # scope on R2 ("Runs 24/7.")
    extraction_tests._requeue(db_url, opp["id"])  # a re-extraction supersedes R1 and R2
    provider.install(gateway)
    gateway.replies = [
        extraction_tests.out(("Runs 24/7.", "non_functional", [("S1", "The site runs 24/7")]))
    ]
    assert drain(db_url, extraction_tests.EXTRACT) == ["succeeded"]

    (view,) = get(client, headers, opp["id"]).json()["conflicts"]

    assert (view["requirement"]["label"], view["requirement"]["excerpt"]) == (
        "Superseded",
        "Runs 24/7.",
    )
    chips = {(p["requirement"]["label"], p["requirement"]["excerpt"]) for p in view["positions"]}
    assert chips == {("Superseded", "Runs 24/7.")}


def test_who_may_read_the_conflicts(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway, count=2)
    opp = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    rep, rep_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    assert _add(client, headers, opp, rep_id).status_code == 200
    outsider, _ = _user(client, sync_engine, "Outsider", PSE)

    assert get(client, rep, opp["id"]).status_code == 200
    hidden = get(client, outsider, opp["id"])
    assert hidden.status_code == 404
    assert hidden.json()["code"] == "not_found"
    assert client.get(f"{BASE}/not-a-uuid/conflicts", headers=headers).status_code == 422
    assert client.get(f"{BASE}/{opp['id']}/conflicts").status_code == 401


def test_conflicts_are_insert_only_but_their_status_and_nothing_is_deletable(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    install(AgentGateway(SCOPE))
    run(client, headers, opp["id"], db_url)
    (conflict,) = conflict_rows(sync_engine, opp["id"])
    denied = [
        "UPDATE conflicts_conflicts SET summary = 'x' WHERE id = :i",
        "UPDATE conflicts_conflicts SET severity = 'low' WHERE id = :i",
        "UPDATE conflicts_conflicts SET fingerprint = 'x' WHERE id = :i",
        "DELETE FROM conflicts_conflicts WHERE id = :i",
        "UPDATE conflicts_positions SET summary = 'x' WHERE conflict_id = :i",
        "UPDATE conflicts_positions SET value = 1 WHERE conflict_id = :i",
        "DELETE FROM conflicts_positions WHERE conflict_id = :i",
    ]
    for sql in denied:
        with pytest.raises(sa.exc.ProgrammingError), sync_engine.begin() as conn:
            conn.execute(sa.text(sql), {"i": conflict["id"]})
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE conflicts_conflicts SET status = status, resolution_reason = "
                "resolution_reason, resolved_at = resolved_at, row_version = row_version "
                "WHERE id = :i"
            ),
            {"i": conflict["id"]},
        )
