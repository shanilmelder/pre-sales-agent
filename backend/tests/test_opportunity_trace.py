"""The Decision Trace read API (Story 9.8): `GET /opportunities/{id}/trace`, against a real,
migrated Postgres as psa_app.

Covers the spec's matrix: the timeline (newest first, readable actors), other Opportunities'
and Opportunity-less events left out, filters, an unknown filter value, paging, and who may
read it. Agent and system events are inserted directly (psa_app may INSERT trace rows), with
explicit times so the order is certain.
"""

import json
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.opportunities.application.trace import agent_name, ordered_payload
from app.platform.ids import new_id
from tests.test_health import assert_problem
from tests.test_opportunities import BASE, PSE, _add, _create, _user, client

__all__ = ["client"]

RED_TEAM = "red_team_agent@1.2.0"
ESTIMATING = "estimating_agent@0.3.1"
CREATED = "estimates.estimate_version.created"
RED_TEAM_DONE = "assessments.red_team_review.completed"
PARSED = "intake.source.parsed"

_RED_TEAM_PAYLOAD = {
    "version": 1,
    "finding_count": 3,
    "critical_count": 0,
    "high_count": 1,
    "medium_count": 1,
    "low_count": 1,
    "dropped_count": 0,
    "requirement_count": 5,
    "gap_count": 2,
    "line_count": 7,
    "superseded_count": 0,
}
_CREATED_PAYLOAD = {
    "version": 1,
    "template_version": "t1",
    "line_count": 7,
    "dropped_count": 0,
    "uncovered_count": 1,
    "requirement_count": 5,
    "superseded_count": 0,
    "carried_assumption_count": 0,
}


def _insert(
    engine: Engine,
    *,
    opportunity_id: str | None,
    actor_type: str,
    actor_id: str,
    event_type: str,
    subject_type: str,
    payload: dict[str, Any],
    at: datetime,
    subject_version: int | None = None,
) -> str:
    event_id = new_id()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO platform_trace_events (id, opportunity_id, actor_type, actor_id,"
                " event_type, subject_type, subject_id, subject_version, payload, occurred_at)"
                " VALUES (:id, :opp, :at_type, :actor, :event, :subject, :subject_id, :version,"
                " CAST(:payload AS jsonb), :occurred)"
            ),
            {
                "id": event_id,
                "opp": opportunity_id,
                "at_type": actor_type,
                "actor": actor_id,
                "event": event_type,
                "subject": subject_type,
                "subject_id": uuid4(),
                "version": subject_version,
                "payload": json.dumps(payload),
                "occurred": at,
            },
        )
    return str(event_id)


def _agent_and_system(engine: Engine, opp_id: str) -> None:
    """After the Opportunity's own `created` event: the Estimating Agent drafts, a system
    parse runs, then the Red Team reviews (newest)."""
    now = datetime.now(UTC)
    _insert(
        engine,
        opportunity_id=opp_id,
        actor_type="agent",
        actor_id=ESTIMATING,
        event_type=CREATED,
        subject_type="estimates.estimate_version",
        payload=_CREATED_PAYLOAD,
        at=now + timedelta(seconds=10),
        subject_version=1,
    )
    _insert(
        engine,
        opportunity_id=opp_id,
        actor_type="system",
        actor_id="intake.parse_source",
        event_type=PARSED,
        subject_type="intake.source",
        payload={"version": 1, "char_count": 120},
        at=now + timedelta(seconds=20),
        subject_version=1,
    )
    _insert(
        engine,
        opportunity_id=opp_id,
        actor_type="agent",
        actor_id=RED_TEAM,
        event_type=RED_TEAM_DONE,
        subject_type="assessments.review",
        payload=_RED_TEAM_PAYLOAD,
        at=now + timedelta(seconds=30),
        subject_version=1,
    )


def _trace(client: TestClient, headers: dict[str, str], opp_id: str, **query: Any) -> Any:
    return client.get(f"{BASE}/{opp_id}/trace", headers=headers, params=query)


# --- pure helpers ------------------------------------------------------------------------------


def test_agent_names_are_roles_in_words_with_the_version_kept() -> None:
    assert agent_name("red_team_agent@1.2.0") == ("Red Team Agent", "1.2.0")
    assert agent_name("intake_agent@0.1.0") == ("Intake Agent", "0.1.0")
    assert agent_name("pm@2.0.0") == ("Pm Agent", "2.0.0")
    assert agent_name("estimating_agent") == ("Estimating Agent", None)


def test_payload_fields_follow_catalogue_order() -> None:
    stored = {"size_bytes": 10, "kind": "pdf", "version": 2, "extra": True}
    assert list(ordered_payload("intake.source.added", stored)) == [
        "version",
        "kind",
        "size_bytes",
        "extra",
    ]
    assert ordered_payload("nope.nope.nopped", {"b": 1, "a": 2}) == {"b": 1, "a": 2}


# --- against Postgres --------------------------------------------------------------------------


def test_timeline_is_newest_first_with_readable_actors(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, owner_id = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)
    _agent_and_system(sync_engine, opp["id"])

    resp = _trace(client, headers, opp["id"])

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["page"], body["page_size"], body["total"]) == (1, 50, 4)
    assert [i["event_type"] for i in body["items"]] == [
        RED_TEAM_DONE,
        PARSED,
        CREATED,
        "opportunities.opportunity.created",
    ]
    assert [i["actor"] for i in body["items"]] == [
        {"type": "agent", "id": RED_TEAM, "name": "Red Team Agent", "version": "1.2.0"},
        {"type": "system", "id": "intake.parse_source", "name": "System", "version": None},
        {"type": "agent", "id": ESTIMATING, "name": "Estimating Agent", "version": "0.3.1"},
        {"type": "user", "id": str(owner_id), "name": "Owner Person", "version": None},
    ]
    red_team = body["items"][0]
    assert red_team["subject"]["type"] == "assessments.review"
    assert red_team["subject"]["version"] == 1
    UUID(red_team["subject"]["id"])
    # Stored payload, in catalogue order (JSONB itself doesn't keep key order).
    assert list(red_team["payload"].items()) == list(_RED_TEAM_PAYLOAD.items())
    created = body["items"][-1]
    assert created["subject"] == {
        "type": "opportunities.opportunity",
        "id": opp["id"],
        "version": 1,
    }
    assert created["payload"] == {"from_import": False}
    assert datetime.fromisoformat(red_team["occurred_at"]) > datetime.fromisoformat(
        created["occurred_at"]
    )
    assert body["options"] == {
        "subject_types": [
            "assessments.review",
            "estimates.estimate_version",
            "intake.source",
            "opportunities.opportunity",
        ],
        "actor_types": ["agent", "system", "user"],
        "event_types": sorted(
            [RED_TEAM_DONE, PARSED, CREATED, "opportunities.opportunity.created"]
        ),
    }


def test_other_opportunities_and_opportunity_less_events_are_left_out(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)
    other = _create(client, headers)
    _agent_and_system(sync_engine, other["id"])
    _insert(
        sync_engine,
        opportunity_id=None,
        actor_type="system",
        actor_id="x",
        event_type=PARSED,
        subject_type="intake.source",
        payload={"version": 1, "char_count": 1},
        at=datetime.now(UTC) + timedelta(seconds=40),
    )

    body = _trace(client, headers, opp["id"]).json()

    assert body["total"] == 1
    assert [i["event_type"] for i in body["items"]] == ["opportunities.opportunity.created"]
    assert body["options"]["actor_types"] == ["user"]


def test_filters_narrow_the_page_but_not_the_options(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)
    _agent_and_system(sync_engine, opp["id"])
    everything = _trace(client, headers, opp["id"]).json()

    agents = _trace(client, headers, opp["id"], actor_type="agent").json()
    drafted = _trace(client, headers, opp["id"], actor_type="agent", event_type=CREATED).json()
    sources = _trace(client, headers, opp["id"], subject_type="intake.source").json()

    assert [i["actor"]["id"] for i in agents["items"]] == [RED_TEAM, ESTIMATING]
    assert agents["total"] == 2
    assert [i["event_type"] for i in drafted["items"]] == [CREATED]
    assert drafted["total"] == 1
    assert [i["event_type"] for i in sources["items"]] == [PARSED]
    assert agents["options"] == drafted["options"] == sources["options"] == everything["options"]


def test_an_unknown_filter_value_is_an_empty_page(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)

    for query in ({"subject_type": "nope"}, {"actor_type": "robot"}, {"event_type": "x.y.z"}):
        resp = _trace(client, headers, opp["id"], **query)
        assert resp.status_code == 200, resp.text
        assert (resp.json()["items"], resp.json()["total"]) == ([], 0)
        assert resp.json()["options"]["event_types"] == ["opportunities.opportunity.created"]


def test_an_empty_filter_value_is_no_filter(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)
    _agent_and_system(sync_engine, opp["id"])

    resp = _trace(client, headers, opp["id"], subject_type="", actor_type="", event_type="")

    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 4


def test_a_filter_value_over_200_characters_is_422(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)

    for name in ("subject_type", "actor_type", "event_type"):
        too_long = _trace(client, headers, opp["id"], **{name: "x" * 201})
        assert too_long.status_code == 422, (name, too_long.text)
        assert_problem(too_long.json(), 422, "validation_error")
        at_limit = _trace(client, headers, opp["id"], **{name: "x" * 200})
        assert at_limit.status_code == 200, (name, at_limit.text)


def test_paging_is_offset_based_and_page_size_is_capped(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)
    start = datetime.now(UTC) + timedelta(seconds=5)
    rows = [
        {
            "id": new_id(),
            "opp": opp["id"],
            "event": PARSED,
            "subject_id": uuid4(),
            "payload": json.dumps({"version": 1, "char_count": n}),
            # Pairs share a time, so the id breaks the tie.
            "occurred": start + timedelta(seconds=n // 2),
        }
        for n in range(119)
    ]
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO platform_trace_events (id, opportunity_id, actor_type, actor_id,"
                " event_type, subject_type, subject_id, payload, occurred_at) VALUES (:id, :opp,"
                " 'system', 'intake.parse_source', :event, 'intake.source', :subject_id,"
                " CAST(:payload AS jsonb), :occurred)"
            ),
            rows,
        )

    pages = [_trace(client, headers, opp["id"], page=n, page_size=50).json() for n in (1, 2, 3)]

    assert [len(p["items"]) for p in pages] == [50, 50, 20]
    assert {p["total"] for p in pages} == {120}
    ids = [i["id"] for p in pages for i in p["items"]]
    assert len(set(ids)) == 120
    keys = [(i["occurred_at"], i["id"]) for p in pages for i in p["items"]]
    assert [datetime.fromisoformat(t) for t, _ in keys] == sorted(
        (datetime.fromisoformat(t) for t, _ in keys), reverse=True
    )
    for (t1, id1), (t2, id2) in pairwise(keys):
        if t1 == t2:
            assert id1 > id2
    assert pages[2]["items"][-1]["event_type"] == "opportunities.opportunity.created"
    assert _trace(client, headers, opp["id"], page=4, page_size=50).json()["items"] == []
    assert _trace(client, headers, opp["id"]).json()["page_size"] == 50

    too_big = _trace(client, headers, opp["id"], page_size=500)
    assert too_big.status_code == 422
    assert_problem(too_big.json(), 422, "validation_error")
    assert _trace(client, headers, opp["id"], page_size=100).status_code == 200
    assert _trace(client, headers, opp["id"], page=0).status_code == 422


def test_readers_including_sales_reps_see_it_and_others_get_404(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)
    rep, rep_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    assert _add(client, headers, opp, rep_id).status_code == 200
    outsider, _ = _user(client, sync_engine, "Outsider", PSE)
    head, _ = _user(client, sync_engine, "Head Person", "head_of_delivery")

    seen = _trace(client, rep, opp["id"])
    assert seen.status_code == 200, seen.text
    assert [i["event_type"] for i in seen.json()["items"]] == [
        "opportunities.collaborator.added",
        "opportunities.opportunity.created",
    ]
    assert _trace(client, head, opp["id"]).status_code == 200

    hidden = _trace(client, outsider, opp["id"])
    unknown = _trace(client, outsider, str(uuid4()))
    assert hidden.status_code == unknown.status_code == 404
    assert_problem(hidden.json(), 404, "not_found")
    assert client.get(f"{BASE}/{opp['id']}/trace").status_code == 401


def test_there_is_no_write_path(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)
    for method in ("post", "put", "patch", "delete"):
        resp = client.request(method, f"{BASE}/{opp['id']}/trace", headers=headers)
        assert resp.status_code == 405, (method, resp.status_code)
