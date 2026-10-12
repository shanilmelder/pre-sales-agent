"""A person resolves or escalates a Conflict (Story 6.3) against a real, migrated Postgres as
psa_app, with the per-agent fake gateway: choosing or entering a position with a reason,
applying an `effort` decision to the Estimate line, the decision standing on reruns,
escalating to a reviewer who then resolves it, `If-Match` (428/412), 409, 422, who may, and
the table grants.

Reuses the fixtures of `test_conflicts.py` (and through it `test_assessments_specialists.py`)."""

import logging
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.platform.model_gateway import provider
from tests import test_conflicts as conflict_tests
from tests.test_assessments_specialists import AgentGateway, effort, install, prepared
from tests.test_conflicts import (
    EFFORT,
    SCOPE,
    _edit_line,
    _edited,
    agent_out,
    conflict_events,
    conflict_rows,
    get,
    run,
)
from tests.test_gaps_detection import requirement_rows, rows
from tests.test_intake_extraction import BASE, FakeGateway
from tests.test_opportunities import PSE, _add, _user

storage_dir = conflict_tests.storage_dir
_hidden_jobs = conflict_tests._hidden_jobs
gateway = conflict_tests.gateway
client = conflict_tests.client
_chat_profile = conflict_tests._chat_profile
_draft_profile = conflict_tests._draft_profile
_assessment_profile = conflict_tests._assessment_profile
_no_auto_run = conflict_tests._no_auto_run

REASON = "Engineering's breakdown matches the interface list."


def resolve(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    conflict: dict[str, Any],
    choice: Any,
    reason: str = REASON,
    *,
    version: int | None = None,
) -> Any:
    v = conflict["row_version"] if version is None else version
    return client.post(
        f"{BASE}/{opp_id}/conflicts/{conflict['id']}/resolution",
        headers={**headers, "If-Match": f'"{v}"'},
        json={"choice": choice, "reason": reason},
    )


def escalate(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    conflict: dict[str, Any],
    reviewer_id: Any,
    reason: str = "Needs the delivery lead's call.",
) -> Any:
    return client.post(
        f"{BASE}/{opp_id}/conflicts/{conflict['id']}/escalation",
        headers={**headers, "If-Match": f'"{conflict["row_version"]}"'},
        json={"reviewer_id": str(reviewer_id), "reason": reason},
    )


def views(client: TestClient, headers: dict[str, str], opp_id: str) -> list[dict[str, Any]]:
    body = get(client, headers, opp_id).json()
    return list(body["conflicts"])


def one_view(client: TestClient, headers: dict[str, str], opp_id: str) -> dict[str, Any]:
    (view,) = views(client, headers, opp_id)
    return view


def line_for(client: TestClient, headers: dict[str, str], opp_id: str, label: str) -> Any:
    estimate = client.get(f"{BASE}/{opp_id}/estimate", headers=headers).json()
    (line,) = [
        line
        for section in estimate["version"]["sections"]
        for line in section["lines"]
        if label in [r["label"] for r in line["requirements"]]
    ]
    return line


def effort_conflict(
    client: TestClient, engine: Engine, db_url: str, gateway: FakeGateway
) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
    """An open `effort` Conflict on R2: Engineering 60 h, PM 40 h, Estimate 131 h."""
    headers, opp = _edited(client, engine, db_url, gateway, 131)
    run(client, headers, opp["id"], db_url)
    view = one_view(client, headers, opp["id"])
    assert view["type"] == "effort"
    assert [p["summary"] for p in view["positions"]] == ["60 h", "40 h", "131 h"]
    return headers, opp, view


def resolved_events(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return [
        e
        for e in conflict_events(engine, opp_id)
        if e["event_type"] == "conflicts.conflict.resolved"
        and e["payload"]["reason_kind"] == "decided"
    ]


# --- resolving an effort Conflict -----------------------------------------------------------


def test_choosing_an_agents_position_sets_the_line_to_the_agents_total(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    headers, opp, view = effort_conflict(client, sync_engine, db_url, gateway)
    me = client.get("/api/v1/me", headers=headers).json()

    with caplog.at_level(logging.DEBUG):
        answer = resolve(client, headers, opp["id"], view, 1)

    assert answer.status_code == 200, answer.text
    assert answer.headers["ETag"] == '"2"'
    body = answer.json()
    assert (body["status"], body["chosen_position"], body["entered_position"]) == (
        "resolved",
        1,
        None,
    )
    assert (body["applied_hours"], body["not_applied"]) == (100.0, None)
    assert body["resolution_reason"] == REASON
    assert body["resolved_by_name"] == me["name"]
    assert (body["can_resolve"], body["can_escalate"]) == (False, False)
    assert len(body["positions"]) == 3  # every original position is kept

    (row,) = conflict_rows(sync_engine, opp["id"])
    assert (row["status"], str(row["resolved_by"]), str(row["applied_hours"])) == (
        "resolved",
        me["id"],
        "100.0",
    )

    line = line_for(client, headers, opp["id"], "R2")
    assert (line["effort_hours"], line["edited"], line["edit_reason"]) == (100.0, True, REASON)
    assert line["edited_by_name"] == me["name"]
    assert line["conflicts"] == []  # the Open Conflict marker is gone

    (event,) = resolved_events(sync_engine, opp["id"])
    assert (event["actor_type"], event["actor_id"], event["subject_version"]) == (
        "user",
        me["id"],
        2,
    )
    payload = event["payload"]
    assert (payload["reason"], payload["chosen_position"], payload["applied_hours"]) == (
        REASON,
        1,
        100.0,
    )
    assert payload["line_id"] == line["id"]
    assert payload["run_id"] is None
    assert [
        (p["position"], p["source"], p["agent"], p["summary"]) for p in payload["positions"]
    ] == [
        (1, "assessment", "engineering_agent", "60 h"),
        (2, "assessment", "pm_agent", "40 h"),
        (3, "estimate", None, "131 h"),
    ]
    edits = rows(
        sync_engine,
        "SELECT * FROM platform_trace_events WHERE subject_id = :l "
        "AND event_type = 'estimates.estimate_line.edited' ORDER BY occurred_at",
        l=line["id"],
    )
    assert (edits[-1]["payload"]["after_hours"], edits[-1]["payload"]["reason"]) == (100.0, REASON)

    body = get(client, headers, opp["id"]).json()
    assert body["open_count"] == 0
    # Privacy: no reason in the logs.
    assert "breakdown matches" not in caplog.text + str([r.__dict__ for r in caplog.records])


def test_entering_hours_sets_the_line_and_words_are_refused(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, view = effort_conflict(client, sync_engine, db_url, gateway)

    refused = resolve(client, headers, opp["id"], view, {"entered": "about two days"})
    assert refused.status_code == 422
    assert refused.headers["content-type"].startswith("application/problem+json")
    assert "hours" in refused.json()["detail"]
    assert conflict_rows(sync_engine, opp["id"])[0]["status"] == "open"
    assert line_for(client, headers, opp["id"], "R2")["effort_hours"] == 131.0
    for bad in ("2001", "48.25", "-4"):
        assert resolve(client, headers, opp["id"], view, {"entered": bad}).status_code == 422

    answer = resolve(client, headers, opp["id"], view, {"entered": "48"})
    assert answer.status_code == 200, answer.text
    assert (answer.json()["entered_position"], answer.json()["applied_hours"]) == ("48", 48.0)
    assert answer.json()["chosen_position"] is None
    assert line_for(client, headers, opp["id"], "R2")["effort_hours"] == 48.0


def test_keeping_the_estimates_position_leaves_the_line(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, view = effort_conflict(client, sync_engine, db_url, gateway)
    before = line_for(client, headers, opp["id"], "R2")

    answer = resolve(client, headers, opp["id"], view, 3)

    assert answer.status_code == 200, answer.text
    assert (answer.json()["applied_hours"], answer.json()["not_applied"]) == (None, None)
    after = line_for(client, headers, opp["id"], "R2")
    assert (after["effort_hours"], after["row_version"]) == (131.0, before["row_version"])
    assert resolved_events(sync_engine, opp["id"])[0]["payload"]["line_id"] is None


def test_a_line_covering_several_requirements_is_not_applied(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, view = effort_conflict(client, sync_engine, db_url, gateway)
    reqs = requirement_rows(sync_engine, opp["id"])
    line = line_for(client, headers, opp["id"], "R2")
    with sync_engine.begin() as conn:  # the R2 line now covers R3 too
        conn.execute(
            sa.text(
                "INSERT INTO estimates_line_requirements (line_id, requirement_id, "
                "requirement_version) VALUES (:l, :r, 1)"
            ),
            {"l": line["id"], "r": reqs[2]["id"]},
        )

    answer = resolve(client, headers, opp["id"], view, 1)

    assert answer.status_code == 200, answer.text
    assert (answer.json()["status"], answer.json()["applied_hours"]) == ("resolved", None)
    assert answer.json()["not_applied"] == "shared_line"
    assert one_view(client, headers, opp["id"])["not_applied"] == "shared_line"
    assert line_for(client, headers, opp["id"], "R2")["effort_hours"] == 131.0
    assert resolved_events(sync_engine, opp["id"])[0]["payload"]["not_applied"] == "shared_line"


def test_a_requirement_two_lines_cover_is_not_applied(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, view = effort_conflict(client, sync_engine, db_url, gateway)
    reqs = requirement_rows(sync_engine, opp["id"])
    r1_line = line_for(client, headers, opp["id"], "R1")
    with sync_engine.begin() as conn:  # the R1 line now covers R2 too: two lines cover R2
        conn.execute(
            sa.text(
                "INSERT INTO estimates_line_requirements (line_id, requirement_id, "
                "requirement_version) VALUES (:l, :r, 1)"
            ),
            {"l": r1_line["id"], "r": reqs[1]["id"]},
        )
    before = _estimate_lines(sync_engine, opp["id"])

    answer = resolve(client, headers, opp["id"], view, 1)

    assert answer.status_code == 200, answer.text
    assert (answer.json()["applied_hours"], answer.json()["not_applied"]) == (
        None,
        "several_lines",
    )
    assert _estimate_lines(sync_engine, opp["id"]) == before


def test_no_draft_estimate_line_is_not_applied(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, view = effort_conflict(client, sync_engine, db_url, gateway)
    with sync_engine.begin() as conn:  # no current draft: no line covers the Requirement
        conn.execute(
            sa.text(
                "UPDATE estimates_estimate_versions SET status = 'superseded' "
                "WHERE opportunity_id = :o"
            ),
            {"o": opp["id"]},
        )
    before = _estimate_lines(sync_engine, opp["id"])

    answer = resolve(client, headers, opp["id"], view, {"entered": "48"})

    assert answer.status_code == 200, answer.text
    assert (answer.json()["applied_hours"], answer.json()["not_applied"]) == (None, "no_line")
    assert one_view(client, headers, opp["id"])["not_applied"] == "no_line"
    assert _estimate_lines(sync_engine, opp["id"]) == before


def test_a_long_reason_is_cut_to_300_characters_on_the_line(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, view = effort_conflict(client, sync_engine, db_url, gateway)
    reason = "word " * 200  # 1,000 characters

    answer = resolve(client, headers, opp["id"], view, 1, reason)

    assert answer.status_code == 200, answer.text
    assert answer.json()["resolution_reason"] == reason.strip()  # the Conflict keeps it all
    edit_reason = line_for(client, headers, opp["id"], "R2")["edit_reason"]
    assert len(edit_reason) <= 300
    assert edit_reason.endswith("…")
    assert reason.startswith(edit_reason[:-1])


# --- scope and recommendation decisions -----------------------------------------------------


def _estimate_lines(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT l.id, l.effort_hours, l.row_version FROM estimates_estimate_lines l "
        "JOIN estimates_estimate_versions v ON v.id = l.version_id "
        "WHERE v.opportunity_id = :o ORDER BY l.id",
        o=opp_id,
    )


def test_entering_a_scope_position_stores_it_and_leaves_the_estimate(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    install(AgentGateway(SCOPE))
    run(client, headers, opp["id"], db_url)
    view = one_view(client, headers, opp["id"])
    before = _estimate_lines(sync_engine, opp["id"])
    assert resolve(client, headers, opp["id"], view, 9).status_code == 422  # no position 9

    answer = resolve(
        client, headers, opp["id"], view, {"entered": "In scope: PM to size in v2"}, "PM agrees."
    )

    assert answer.status_code == 200, answer.text
    assert answer.json()["entered_position"] == "In scope: PM to size in v2"
    assert (answer.json()["applied_hours"], answer.json()["not_applied"]) == (None, None)
    assert _estimate_lines(sync_engine, opp["id"]) == before
    assert one_view(client, headers, opp["id"])["entered_position"] == (
        "In scope: PM to size in v2"
    )


# --- reruns after a decision ----------------------------------------------------------------


def test_the_decision_stands_until_an_assessment_position_changes(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, view = effort_conflict(client, sync_engine, db_url, gateway)
    me = client.get("/api/v1/me", headers=headers).json()
    assert resolve(client, headers, opp["id"], view, 3).status_code == 200  # keep 131 h

    run(client, headers, opp["id"], db_url)  # same agent figures: the decision stands
    (decided,) = conflict_rows(sync_engine, opp["id"])
    assert decided["status"] == "resolved"
    assert get(client, headers, opp["id"]).json()["open_count"] == 0

    fake = install(AgentGateway(EFFORT))
    fake.replies["engineering_agent"] = [agent_out(effort("R1", 4), effort("R2", 30))]
    run(client, headers, opp["id"], db_url)  # Engineering now says 30 h

    old, new = conflict_rows(sync_engine, opp["id"])
    assert old["id"] == decided["id"]
    assert (new["status"], new["previous_conflict_id"]) == ("open", decided["id"])
    listed = views(client, headers, opp["id"])
    assert [(c["id"], c["status"]) for c in listed] == [
        (str(new["id"]), "open"),
        (str(decided["id"]), "resolved"),  # the decision stays listed
    ]
    assert listed[0]["previous_decision"]["name"] == me["name"]
    assert listed[1]["previous_decision"] is None

    run(client, headers, opp["id"], db_url)  # the same changed figures: carried forward
    _, middle, newest = conflict_rows(sync_engine, opp["id"])
    assert (middle["id"], middle["status"]) == (new["id"], "resolved")
    assert newest["previous_conflict_id"] == new["id"]
    listed = views(client, headers, opp["id"])
    assert [c["id"] for c in listed] == [str(newest["id"]), str(decided["id"])]
    assert listed[0]["previous_decision"]["name"] == me["name"]  # through the carried one

    resolved_now = resolve(client, headers, opp["id"], listed[0], 3)
    assert resolved_now.status_code == 200, resolved_now.text
    assert resolved_now.json()["previous_decision"] is None  # its own decision now


def test_an_estimate_only_change_leaves_a_decision_or_an_escalation_standing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, view = effort_conflict(client, sync_engine, db_url, gateway)
    assert resolve(client, headers, opp["id"], view, 3).status_code == 200  # keep 131 h
    _edit_line(client, headers, opp["id"], "R2", 200)  # still far from the agents' 100 h
    run(client, headers, opp["id"], db_url)

    (decided,) = conflict_rows(sync_engine, opp["id"])
    assert decided["status"] == "resolved"
    assert get(client, headers, opp["id"]).json()["open_count"] == 0

    provider.install(gateway)  # the extraction and Gap fakes for the second Opportunity
    headers, opp, view = effort_conflict(client, sync_engine, db_url, gateway)
    full = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    _, reviewer_id = _user(client, sync_engine, "Sam Reviewer", PSE)
    assert _add(client, headers, full, reviewer_id).status_code == 200
    assert escalate(client, headers, opp["id"], view, reviewer_id).status_code == 200
    _edit_line(client, headers, opp["id"], "R2", 200)
    run(client, headers, opp["id"], db_url)

    (escalated,) = conflict_rows(sync_engine, opp["id"])
    assert escalated["status"] == "escalated"
    assert get(client, headers, opp["id"]).json()["open_count"] == 1


# --- errors ---------------------------------------------------------------------------------


def test_reason_if_match_stale_and_already_resolved(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, view = effort_conflict(client, sync_engine, db_url, gateway)
    url = f"{BASE}/{opp['id']}/conflicts/{view['id']}/resolution"

    for reason in ("", "   ", "x" * 1001):
        blank = resolve(client, headers, opp["id"], view, 1, reason)
        assert blank.status_code == 422
        assert blank.json()["detail"] == "Give a reason of 1 to 1,000 characters."
    missing = client.post(url, headers=headers, json={"choice": 1, "reason": REASON})
    assert missing.status_code == 428
    assert (
        client.post(url, headers=headers | {"If-Match": '"1"'}, json={"choice": 1}).status_code
        == 422
    )
    assert conflict_rows(sync_engine, opp["id"])[0]["status"] == "open"

    me = client.get("/api/v1/me", headers=headers).json()
    assert resolve(client, headers, opp["id"], view, 3).status_code == 200
    stale = resolve(client, headers, opp["id"], view, 1)  # still holds row version 1
    assert stale.status_code == 412
    assert stale.json()["detail"] == f"Changed by {me['name']} since you opened it."
    again = resolve(client, headers, opp["id"], view, 1, version=2)
    assert again.status_code == 409
    assert again.json()["code"] == "conflict_already_resolved"
    # The version and status are checked before the body.
    assert resolve(client, headers, opp["id"], view, 1, " ").status_code == 412
    assert resolve(client, headers, opp["id"], view, 1, " ", version=2).status_code == 409
    resolved_view = {**view, "row_version": 2}
    assert escalate(client, headers, opp["id"], view, view["id"], " ").status_code == 412
    blocked = escalate(client, headers, opp["id"], resolved_view, view["id"], " ")
    assert (blocked.status_code, blocked.json()["code"]) == (409, "conflict_already_resolved")
    (row,) = conflict_rows(sync_engine, opp["id"])
    assert (row["chosen_position"], row["row_version"]) == (3, 2)


# --- escalating -----------------------------------------------------------------------------


def test_escalating_to_a_collaborator_who_then_resolves_it(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, view = effort_conflict(client, sync_engine, db_url, gateway)
    assert view["can_escalate"] is False  # nobody to escalate to yet
    full = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    reviewer, reviewer_id = _user(client, sync_engine, "Sam Reviewer", PSE)
    assert _add(client, headers, full, reviewer_id).status_code == 200
    assert one_view(client, headers, opp["id"])["can_escalate"] is True
    outsider, outsider_id = _user(client, sync_engine, "Outsider", PSE)
    me = client.get("/api/v1/me", headers=headers).json()

    body = get(client, headers, opp["id"]).json()
    assert body["reviewers"] == [{"id": str(reviewer_id), "name": "Sam Reviewer"}]
    for bad in (outsider_id, me["id"]):
        refused = escalate(client, headers, opp["id"], view, bad)
        assert refused.status_code == 422
        assert "reviewer" in refused.json()["detail"]
    assert escalate(client, headers, opp["id"], view, reviewer_id, " ").status_code == 422

    answer = escalate(client, headers, opp["id"], view, reviewer_id)

    assert answer.status_code == 200, answer.text
    assert answer.headers["ETag"] == '"2"'
    escalated = answer.json()
    assert escalated["status"] == "escalated"
    assert escalated["escalated_to"] == {"id": str(reviewer_id), "name": "Sam Reviewer"}
    assert escalated["escalated_by"]["name"] == me["name"]
    assert escalated["escalation_reason"] == "Needs the delivery lead's call."
    assert escalated["escalated_at"] is not None
    assert (escalated["can_resolve"], escalated["can_escalate"]) == (True, False)
    assert get(client, headers, opp["id"]).json()["open_count"] == 1
    assert line_for(client, headers, opp["id"], "R2")["conflicts"] != []  # still marked
    (event,) = [
        e
        for e in conflict_events(sync_engine, opp["id"])
        if e["event_type"] == "conflicts.conflict.escalated"
    ]
    assert event["payload"] == {
        "run_id": None,
        "reviewer_id": str(reviewer_id),
        "reason": "Needs the delivery lead's call.",
    }
    assert (event["actor_id"], event["subject_version"]) == (me["id"], 2)

    twice = escalate(client, headers, opp["id"], escalated, reviewer_id)
    assert (twice.status_code, twice.json()["code"]) == (409, "conflict_not_open")

    done = resolve(client, reviewer, opp["id"], escalated, 1, "Agreed with Engineering.")
    assert done.status_code == 200, done.text
    assert (done.json()["status"], done.json()["resolved_by_name"]) == ("resolved", "Sam Reviewer")
    assert done.json()["escalated_to"]["name"] == "Sam Reviewer"  # the escalation is kept
    (row,) = conflict_rows(sync_engine, opp["id"])
    assert row["resolved_by"] == reviewer_id
    assert hidden_from(client, outsider, opp["id"]) == 404


def hidden_from(client: TestClient, headers: dict[str, str], opp_id: str) -> int:
    return int(get(client, headers, opp_id).status_code)


def test_an_escalated_sales_rep_reviewer_may_resolve_but_not_escalate(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, view = effort_conflict(client, sync_engine, db_url, gateway)
    full = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    rep, rep_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    assert _add(client, headers, full, rep_id).status_code == 200

    rep_view = one_view(client, rep, opp["id"])
    assert (rep_view["can_resolve"], rep_view["can_escalate"]) == (False, False)
    assert resolve(client, rep, opp["id"], view, 1).status_code == 403
    assert escalate(client, rep, opp["id"], view, rep_id).status_code == 403
    assert conflict_rows(sync_engine, opp["id"])[0]["status"] == "open"

    escalated = escalate(client, headers, opp["id"], view, rep_id).json()
    assert one_view(client, rep, opp["id"])["can_resolve"] is True
    before = line_for(client, headers, opp["id"], "R2")

    done = resolve(client, rep, opp["id"], escalated, 1)  # an agent's position

    assert done.status_code == 200, done.text
    assert (done.json()["status"], done.json()["applied_hours"]) == ("resolved", None)
    assert done.json()["not_applied"] == "not_permitted"  # FR-64: no Estimate edit
    after = line_for(client, headers, opp["id"], "R2")
    assert (after["effort_hours"], after["row_version"]) == (131.0, before["row_version"])


# --- reruns of an escalated Conflict --------------------------------------------------------


def test_an_escalated_conflict_stays_escalated_on_a_rerun_and_is_resolved_when_gone(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    fake = install(AgentGateway(SCOPE))
    run(client, headers, opp["id"], db_url)
    view = one_view(client, headers, opp["id"])
    full = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    _, reviewer_id = _user(client, sync_engine, "Sam Reviewer", PSE)
    assert _add(client, headers, full, reviewer_id).status_code == 200
    assert escalate(client, headers, opp["id"], view, reviewer_id).status_code == 200

    run(client, headers, opp["id"], db_url)  # still raised: no duplicate
    (row,) = conflict_rows(sync_engine, opp["id"])
    assert (row["status"], str(row["escalated_to"])) == ("escalated", str(reviewer_id))

    fake.replies["pm_agent"] = [agent_out(effort("R1", 8), effort("R4", 6))]
    run(client, headers, opp["id"], db_url)  # gone: resolved by the system
    (row,) = conflict_rows(sync_engine, opp["id"])
    assert row["status"] == "resolved"
    assert row["resolution_reason"] == "No longer present in PM Assessment v3"
    assert row["resolved_by"] is None
    assert row["escalated_to"] == reviewer_id


# --- grants ---------------------------------------------------------------------------------


def test_the_decision_columns_are_updatable_and_nothing_is_deletable(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    install(AgentGateway(SCOPE))
    run(client, headers, opp["id"], db_url)
    (conflict,) = conflict_rows(sync_engine, opp["id"])
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE conflicts_conflicts SET resolved_by = resolved_by, chosen_position = "
                "chosen_position, entered_position = entered_position, applied_hours = "
                "applied_hours, escalated_to = escalated_to, escalated_by = escalated_by, "
                "escalated_at = escalated_at, escalation_reason = escalation_reason "
                "WHERE id = :i"
            ),
            {"i": conflict["id"]},
        )
    with pytest.raises(sa.exc.ProgrammingError), sync_engine.begin() as conn:
        conn.execute(
            sa.text("DELETE FROM conflicts_conflicts WHERE id = :i"), {"i": conflict["id"]}
        )
    with pytest.raises(sa.exc.IntegrityError), sync_engine.begin() as conn:  # half an escalation
        conn.execute(
            sa.text("UPDATE conflicts_conflicts SET escalation_reason = 'x' WHERE id = :i"),
            {"i": conflict["id"]},
        )
    with pytest.raises(sa.exc.IntegrityError), sync_engine.begin() as conn:  # both choices
        conn.execute(
            sa.text(
                "UPDATE conflicts_conflicts SET chosen_position = 1, entered_position = 'x' "
                "WHERE id = :i"
            ),
            {"i": conflict["id"]},
        )


# --- ids from elsewhere ---------------------------------------------------------------------


def test_a_conflict_of_another_opportunity_or_an_unknown_id_is_not_found(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, view = effort_conflict(client, sync_engine, db_url, gateway)
    me = client.get("/api/v1/me", headers=headers).json()
    provider.install(gateway)  # the extraction and Gap fakes for the second Opportunity
    other_headers, other = prepared(client, sync_engine, db_url, gateway)
    install(AgentGateway(SCOPE))
    run(client, other_headers, other["id"], db_url)
    other_full = client.get(f"{BASE}/{other['id']}", headers=other_headers).json()
    assert _add(client, other_headers, other_full, me["id"]).status_code == 200
    foreign = one_view(client, headers, other["id"])  # the caller is a member there
    before = conflict_rows(sync_engine, other["id"])

    for conflict in (foreign, {**view, "id": str(uuid4())}):
        assert resolve(client, headers, opp["id"], conflict, 1).status_code == 404
        refused = escalate(client, headers, opp["id"], conflict, uuid4())
        assert (refused.status_code, refused.json()["code"]) == (404, "not_found")
    assert conflict_rows(sync_engine, other["id"]) == before


# --- an escalated Conflict whose figures change ---------------------------------------------


def test_an_escalated_conflict_with_changed_figures_is_raised_again_still_escalated(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, view = effort_conflict(client, sync_engine, db_url, gateway)
    full = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    _, reviewer_id = _user(client, sync_engine, "Sam Reviewer", PSE)
    assert _add(client, headers, full, reviewer_id).status_code == 200
    assert escalate(client, headers, opp["id"], view, reviewer_id).status_code == 200
    (escalated,) = conflict_rows(sync_engine, opp["id"])

    fake = install(AgentGateway(EFFORT))
    fake.replies["engineering_agent"] = [agent_out(effort("R1", 4), effort("R2", 30))]
    run(client, headers, opp["id"], db_url)  # Engineering now says 30 h

    old, new = conflict_rows(sync_engine, opp["id"])
    assert (old["id"], old["status"]) == (escalated["id"], "resolved")
    assert old["resolved_by"] is None
    assert (new["status"], new["previous_conflict_id"]) == ("escalated", escalated["id"])
    for column in ("escalated_to", "escalated_by", "escalated_at", "escalation_reason"):
        assert new[column] == escalated[column]
    listed = one_view(client, headers, opp["id"])  # the old one is no longer listed
    assert (listed["id"], listed["status"]) == (str(new["id"]), "escalated")
    assert [p["summary"] for p in listed["positions"]] == ["30 h", "40 h", "131 h"]
    assert listed["escalated_to"] == {"id": str(reviewer_id), "name": "Sam Reviewer"}
    assert get(client, headers, opp["id"]).json()["open_count"] == 1
