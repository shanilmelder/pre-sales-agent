"""Actuals (Story 10.1) against a real, migrated Postgres as psa_app: every row of the story's
I/O matrix, Save Actuals with a record and a correction in one Unit of Work, corrections and
their history, 403 per role, 412, trace events, version mismatch, Close delivery and the
`delivered` status (domain and SQL agree), and the append-only grants.

Estimate Versions, lines, Assumptions and the Baseline row are inserted directly; people sign
in through `/me` with their roles (see `test_reviews_requests`).
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.actuals.domain.actuals import MINUS
from app.modules.opportunities.application.public import OpportunityStatus, derived_status
from tests import test_opportunities as opportunity_tests
from tests.test_gaps_detection import rows
from tests.test_intake_parse_job import _alembic
from tests.test_opportunities import BASE, PSE, _create, _user
from tests.test_reviews_challenges import _entry, _requirement
from tests.test_reviews_requests import ENG, REP, _events, _version
from tests.test_role_admin import _signed_in

client = opportunity_tests.client

DM = "delivery_manager"
HOD = "head_of_delivery"
RECORDED = "actuals.actual.recorded"
CORRECTED = "actuals.actual.corrected"
CLOSED = "actuals.delivery.closed"


# --- helpers --------------------------------------------------------------------------------


def _problem(resp: Any, status: int, code: str) -> None:
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["code"] == code


def _line(engine: Engine, version_id: str, position: int, title: str, hours: str) -> str:
    line_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO estimates_estimate_lines (id, version_id, position, section, title, "
                "effort_hours, role_mix, basis) VALUES (:i, :v, :p, 'integration', :t, :h, "
                "CAST(:m AS jsonb), 'Basis')"
            ),
            {
                "i": line_id,
                "v": version_id,
                "p": position,
                "t": title,
                "h": hours,
                "m": '{"engineer": 100, "project_manager": 0, "qa": 0}',
            },
        )
    return str(line_id)


def _cover(engine: Engine, line_id: str, requirement_id: UUID) -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO estimates_line_requirements (line_id, requirement_id, "
                "requirement_version) VALUES (:l, :r, 1)"
            ),
            {"l": line_id, "r": requirement_id},
        )


def _assumption(engine: Engine, version_id: str, position: int) -> str:
    assumption_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO estimates_assumptions (id, version_id, position, kind, wording, "
                "origin_ref, row_version) VALUES (:i, :v, :p, 'condition', 'Volumes as stated', "
                "CAST(:o AS jsonb), 2)"
            ),
            {"i": assumption_id, "v": version_id, "p": position, "o": '{"kind": "gap"}'},
        )
    return str(assumption_id)


def _baseline(engine: Engine, opp_id: str, version_id: str, by: UUID) -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO estimates_baselines (id, opportunity_id, estimate_version_id, "
                "set_at, set_by) VALUES (:i, :o, :v, clock_timestamp(), :b)"
            ),
            {"i": uuid4(), "o": opp_id, "v": version_id, "b": by},
        )


def _collaborate(client: TestClient, owner: dict[str, str], opp_id: str, user_id: UUID) -> None:
    opp = client.get(f"{BASE}/{opp_id}", headers=owner).json()
    resp = client.put(
        f"{BASE}/{opp_id}/collaborators/{user_id}",
        headers={**owner, "If-Match": f'"{opp["row_version"]}"'},
    )
    assert resp.status_code in (200, 201), resp.text


@dataclass
class Scene:
    owner: dict[str, str]
    owner_id: UUID
    dm: dict[str, str]
    dm_id: UUID
    opp_id: str
    v3: str
    l1: str
    l2: str
    assumption: str
    entry: UUID


def _scene(client: TestClient, engine: Engine, *, baseline: bool = True) -> Scene:
    """An Opportunity owned by a presales engineer with a delivery manager collaborator, an
    approved v3 with L1 (36 h, its Requirement tagged with an Integration Type) and L2 (20 h),
    one Assumption, and (by default) v3 as the Baseline."""
    owner, owner_id = _user(client, engine, "Owner Person", PSE)
    dm, dm_id = _user(client, engine, "Dana Delivery", DM)
    opp = _create(client, owner)
    _collaborate(client, owner, opp["id"], dm_id)
    v3 = _version(engine, opp["id"], 3, status="approved", created_by=owner_id)
    l1 = _line(engine, v3, 1, "WMS to SAP EWM interface", "36.0")
    l2 = _line(engine, v3, 2, "CRM data migration", "20.0")
    entry = _entry(engine, "ERP integration")
    _cover(engine, l1, _requirement(engine, opp["id"], 1, entry))
    assumption = _assumption(engine, v3, 1)
    if baseline:
        _baseline(engine, opp["id"], v3, owner_id)
    return Scene(owner, owner_id, dm, dm_id, opp["id"], v3, l1, l2, assumption, entry)


def _view(client: TestClient, headers: dict[str, str], opp_id: str) -> dict[str, Any]:
    resp = client.get(f"{BASE}/{opp_id}/actuals", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["ETag"] == f'"{resp.json()["row_version"]}"'
    return resp.json()  # type: ignore[no-any-return]


def _save(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    items: list[dict[str, Any]],
    *,
    reason: str | None = None,
    row_version: int | None = None,
) -> Any:
    if row_version is None:
        row_version = _view(client, headers, opp_id)["row_version"]
    body: dict[str, Any] = {"items": items}
    if reason is not None:
        body["reason"] = reason
    return client.post(
        f"{BASE}/{opp_id}/actuals",
        headers={**headers, "If-Match": f'"{row_version}"'},
        json=body,
    )


def _close(client: TestClient, headers: dict[str, str], opp_id: str) -> Any:
    row_version = _view(client, headers, opp_id)["row_version"]
    return client.post(
        f"{BASE}/{opp_id}/actuals/delivery/close",
        headers={**headers, "If-Match": f'"{row_version}"'},
    )


def _actuals(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM actuals_actuals WHERE opportunity_id = :o ORDER BY recorded_at, version",
        o=opp_id,
    )


def _fields(resp: Any) -> set[str]:
    return {e["field"] for e in resp.json()["errors"]}


def _line_view(view: dict[str, Any], line_id: str) -> dict[str, Any]:
    return next(line for line in view["lines"] if line["line_id"] == line_id)


def _list_status(client: TestClient, headers: dict[str, str], opp_id: str) -> str:
    items = client.get(f"{BASE}?scope=mine&page_size=200", headers=headers).json()["items"]
    return str(next(i for i in items if i["id"] == opp_id)["status"])


# --- the matrix -----------------------------------------------------------------------------


def test_record_over(client: TestClient, sync_engine: Engine) -> None:
    s = _scene(client, sync_engine)
    resp = _save(
        client,
        s.dm,
        s.opp_id,
        [{"line_id": s.l1, "effort_hours": 41, "variance_cause": "estimation_error"}],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["recorded"], body["corrected"]) == (1, 0)
    line = _line_view(body["view"], s.l1)
    assert line["label"] == "L1"
    assert line["estimate_hours"] == 36.0
    assert line["integration_types"] == [
        {"id": str(s.entry), "kind": "integration_type", "name": "ERP integration"}
    ]
    variance = line["variance"]
    assert variance["label"] == "+5.0 h (13.9%)"
    assert (variance["hours"], variance["percent"], variance["direction"]) == (5.0, 13.9, "over")
    assert variance["direction_label"] == "Over estimate"
    assert line["cost_variance"] is None
    assert line["actual"]["recorded_by_name"] == "Dana Delivery"
    assert _line_view(body["view"], s.l2)["actual"] is None
    totals = body["view"]["totals"]
    assert (totals["estimate_hours"], totals["actual_hours"]) == (36.0, 41.0)  # L2 excluded
    assert totals["variance"]["label"] == "+5.0 h (13.9%)"
    assert body["view"]["open_line_count"] == 1  # L1 final, L2 not recorded

    (row,) = _actuals(sync_engine, s.opp_id)
    assert (row["version"], row["is_current"], row["kind"]) == (1, True, "final")
    assert str(row["estimate_version_id"]) == s.v3
    assert row["integration_type_ids"] == [s.entry]  # derived from the line's Requirements
    assert row["work_package_id"] is None
    (event,) = _events(sync_engine, s.opp_id, RECORDED)
    payload = event["payload"]
    assert payload["effort_hours"] == "41.0"
    assert (payload["line_id"], payload["estimate_version"]) == (s.l1, 3)
    assert (event["actor_type"], event["actor_id"]) == ("user", str(s.dm_id))
    assert (event["subject_type"], str(event["subject_id"])) == ("actuals.actual", str(row["id"]))


def test_missing_cause_is_422_on_the_cause(client: TestClient, sync_engine: Engine) -> None:
    s = _scene(client, sync_engine)
    resp = _save(client, s.dm, s.opp_id, [{"line_id": s.l1, "effort_hours": 41}])
    _problem(resp, 422, "actual_invalid")
    assert resp.json()["errors"] == [
        {
            "item": 0,
            "field": "variance_cause",
            "message": "A final Actual that differs from the estimate needs a variance cause.",
        }
    ]
    assert _actuals(sync_engine, s.opp_id) == []
    assert _events(sync_engine, s.opp_id, RECORDED) == []


def test_other_without_a_note_is_422_on_the_note(client: TestClient, sync_engine: Engine) -> None:
    s = _scene(client, sync_engine)
    item = {"line_id": s.l1, "effort_hours": 41, "variance_cause": "other", "note": "  "}
    resp = _save(client, s.dm, s.opp_id, [item])
    _problem(resp, 422, "actual_invalid")
    assert _fields(resp) == {"note"}
    assert _actuals(sync_engine, s.opp_id) == []


def test_a_milestone_needs_no_cause(client: TestClient, sync_engine: Engine) -> None:
    s = _scene(client, sync_engine)
    item = {"line_id": s.l1, "kind": "milestone", "milestone_label": "Design", "effort_hours": 12}
    resp = _save(client, s.dm, s.opp_id, [item])
    assert resp.status_code == 200, resp.text
    line = _line_view(resp.json()["view"], s.l1)
    assert (line["actual"]["kind"], line["actual"]["milestone_label"]) == ("milestone", "Design")
    assert line["actual"]["variance_cause"] is None
    assert resp.json()["view"]["open_line_count"] == 2  # a milestone isn't final


def test_failed_assumptions_come_from_the_actuals_own_version(
    client: TestClient, sync_engine: Engine
) -> None:
    s = _scene(client, sync_engine)
    v2 = _version(sync_engine, s.opp_id, 2, status="superseded", created_by=s.owner_id)
    foreign = _assumption(sync_engine, v2, 1)
    base = {"line_id": s.l1, "effort_hours": 41, "variance_cause": "unknown_requirement"}

    resp = _save(client, s.dm, s.opp_id, [{**base, "failed_assumption_ids": [foreign]}])
    _problem(resp, 422, "actual_invalid")
    assert _fields(resp) == {"failed_assumption_ids"}
    assert _actuals(sync_engine, s.opp_id) == []

    resp = _save(client, s.dm, s.opp_id, [{**base, "failed_assumption_ids": [s.assumption]}])
    assert resp.status_code == 200, resp.text
    (row,) = _actuals(sync_engine, s.opp_id)
    assert row["failed_assumptions"] == [{"assumption_id": s.assumption, "version": 2}]
    actual = _line_view(resp.json()["view"], s.l1)["actual"]
    assert actual["failed_assumptions"] == [
        {
            "assumption_id": s.assumption,
            "version": 2,
            "kind": "condition",
            "wording": "Volumes as stated",
            "position": 1,
            "amount_hours": None,
            "accepted_by": None,
            "accepted_at": None,
            "evidence": [],
        }
    ]
    (event,) = _events(sync_engine, s.opp_id, RECORDED)
    assert event["payload"]["failed_assumptions"] == [{"assumption_id": s.assumption, "version": 2}]
    assert [a["id"] for a in resp.json()["view"]["assumptions"]] == [s.assumption]


def test_failed_assumptions_carry_their_number_hours_and_acceptance(
    client: TestClient, sync_engine: Engine
) -> None:
    """Story 10.4: the Inspector's read-only list gets each failed Assumption's register number,
    a Contingency's hours and who accepted it and when, for every reader (here the Head of
    Delivery, who doesn't collaborate) and in the correction history too."""
    s = _scene(client, sync_engine)
    contingency = uuid4()
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO estimates_assumptions (id, version_id, position, kind, wording, "
                "amount_hours, line_id, origin_ref, accepted_by, accepted_at, row_version) "
                "VALUES (:i, :v, 2, 'contingency', 'Interface spec arrives late', 12.0, :l, "
                "CAST(:o AS jsonb), :b, '2026-10-05T09:00:00Z', 3)"
            ),
            {"i": contingency, "v": s.v3, "l": s.l1, "o": '{"kind": "gap"}', "b": s.owner_id},
        )
    item = {
        "line_id": s.l1,
        "effort_hours": 50,
        "variance_cause": "integration_complexity",
        "failed_assumption_ids": [str(contingency), s.assumption],
    }
    assert _save(client, s.dm, s.opp_id, [item]).status_code == 200
    hod, _ = _user(client, sync_engine, "Hana Head", HOD)

    actual = _line_view(_view(client, hod, s.opp_id), s.l1)["actual"]

    by_id = {f["assumption_id"]: f for f in actual["failed_assumptions"]}
    got = by_id[str(contingency)]
    assert (got["kind"], got["position"], got["amount_hours"], got["version"]) == (
        "contingency",
        2,
        12.0,
        3,
    )
    assert got["accepted_by"] == {"id": str(s.owner_id), "name": "Owner Person"}
    assert got["accepted_at"].startswith("2026-10-05T09:00:00")
    assert (by_id[s.assumption]["position"], by_id[s.assumption]["accepted_by"]) == (1, None)

    resp = _save(client, s.dm, s.opp_id, [{**item, "effort_hours": 52}], reason="Late timesheets")
    assert resp.status_code == 200, resp.text
    corrected = _line_view(_view(client, hod, s.opp_id), s.l1)["actual"]
    (past,) = corrected["history"]
    assert {f["position"] for f in past["failed_assumptions"]} == {1, 2}


def test_unplanned_work(client: TestClient, sync_engine: Engine) -> None:
    s = _scene(client, sync_engine)
    bad = {"effort_hours": 8, "variance_cause": "customer_delay"}
    resp = _save(client, s.dm, s.opp_id, [bad])
    _problem(resp, 422, "actual_invalid")
    assert _fields(resp) == {"variance_cause", "integration_type_id"}

    wrong_kind = {
        "effort_hours": 8,
        "variance_cause": "scope_change",
        "work_package_id": str(s.entry),
    }
    assert _fields(_save(client, s.dm, s.opp_id, [wrong_kind])) == {"work_package_id"}
    assert _actuals(sync_engine, s.opp_id) == []

    good = {
        "effort_hours": 8,
        "variance_cause": "scope_change",
        "integration_type_id": str(s.entry),
    }
    planned = {"line_id": s.l2, "effort_hours": 18, "variance_cause": "estimation_error"}
    resp = _save(client, s.dm, s.opp_id, [good, planned])
    assert resp.status_code == 200, resp.text
    view = resp.json()["view"]
    (unplanned,) = view["unplanned"]
    assert unplanned["line_id"] is None
    assert unplanned["integration_types"][0]["name"] == "ERP integration"
    assert unplanned["variance"]["label"] == "+8.0 h"
    assert unplanned["variance"]["percent"] is None
    # Unplanned work counts in the total: 20 h estimated, 18 + 8 h actual.
    assert view["totals"]["variance"]["label"] == "+6.0 h (30.0%)"
    assert view["totals"]["unplanned_count"] == 1
    # The line under its estimate is green: a minus sign and "Under estimate".
    under = _line_view(view, s.l2)["variance"]
    assert (under["label"], under["direction"]) == (f"{MINUS}2.0 h ({MINUS}10.0%)", "under")


def test_stale_if_match_is_412_and_writes_nothing(client: TestClient, sync_engine: Engine) -> None:
    s = _scene(client, sync_engine)
    stale = _view(client, s.dm, s.opp_id)["row_version"]
    item = {"line_id": s.l1, "effort_hours": 36}
    assert _save(client, s.dm, s.opp_id, [item], row_version=stale).status_code == 200
    resp = _save(client, s.dm, s.opp_id, [{"line_id": s.l2, "effort_hours": 20}], row_version=stale)
    _problem(resp, 412, "row_version_mismatch")
    assert len(_actuals(sync_engine, s.opp_id)) == 1
    missing = client.post(f"{BASE}/{s.opp_id}/actuals", headers=s.dm, json={"items": [item]})
    _problem(missing, 428, "if_match_required")


@pytest.mark.parametrize("role", [PSE, ENG, REP, HOD])
def test_other_roles_read_only_and_403_on_writes(
    client: TestClient, sync_engine: Engine, role: str
) -> None:
    s = _scene(client, sync_engine)
    other, other_id = _user(client, sync_engine, "Other Person", role)
    _collaborate(client, s.owner, s.opp_id, other_id)
    view = _view(client, other, s.opp_id)
    assert (view["can_record"], view["can_close"]) == (False, False)
    item = {"line_id": s.l1, "effort_hours": 36}
    _problem(_save(client, other, s.opp_id, [item]), 403, "forbidden")
    _problem(_close(client, other, s.opp_id), 403, "forbidden")
    assert _actuals(sync_engine, s.opp_id) == []


def test_the_owner_presales_engineer_is_403(client: TestClient, sync_engine: Engine) -> None:
    s = _scene(client, sync_engine)
    assert _view(client, s.owner, s.opp_id)["can_record"] is False
    resp = _save(client, s.owner, s.opp_id, [{"line_id": s.l1, "effort_hours": 36}])
    _problem(resp, 403, "forbidden")


def test_a_delivery_manager_needs_read_access(client: TestClient, sync_engine: Engine) -> None:
    s = _scene(client, sync_engine)
    stranger, _ = _user(client, sync_engine, "Stranger DM", DM)
    resp = _save(client, stranger, s.opp_id, [{"line_id": s.l1, "effort_hours": 36}], row_version=0)
    _problem(resp, 404, "not_found")


def test_the_role_alone_grants_a_collaborator_without_the_permission(
    client: TestClient, sync_engine: Engine
) -> None:
    """The relation grant needs the delivery manager role, whatever the token's permissions."""
    s = _scene(client, sync_engine)
    bare, bare_id = _signed_in(client, "Bare DM", DM, permissions=[])
    _collaborate(client, s.owner, s.opp_id, bare_id)
    assert _view(client, bare, s.opp_id)["can_record"] is True
    resp = _save(client, bare, s.opp_id, [{"line_id": s.l1, "effort_hours": 36}])
    assert resp.status_code == 200, resp.text


def test_no_baseline(client: TestClient, sync_engine: Engine) -> None:
    s = _scene(client, sync_engine, baseline=False)
    view = _view(client, s.dm, s.opp_id)
    assert view["baseline"] is None
    assert view["lines"] == []
    assert view["can_record"] is False  # nothing to record against yet
    resp = _save(client, s.dm, s.opp_id, [{"line_id": s.l1, "effort_hours": 36}])
    _problem(resp, 409, "actuals_no_baseline")


def test_no_actuals(client: TestClient, sync_engine: Engine) -> None:
    s = _scene(client, sync_engine)
    view = _view(client, s.dm, s.opp_id)
    assert view["baseline"]["version"] == 3
    assert [(line["label"], line["actual"], line["variance"]) for line in view["lines"]] == [
        ("L1", None, None),
        ("L2", None, None),
    ]
    assert view["totals"]["variance"] is None
    assert view["can_record"] is True
    assert (view["can_close"], view["close_blocked_reason"]) == (
        False,
        "2 lines have no final Actual",
    )
    assert [c["value"] for c in view["causes"]] == [
        "unknown_requirement",
        "integration_complexity",
        "customer_delay",
        "scope_change",
        "estimation_error",
        "other",
    ]


# --- acceptance: one save, a record and a correction -----------------------------------------


def test_save_records_and_corrects_in_one_unit_of_work(
    client: TestClient, sync_engine: Engine
) -> None:
    s = _scene(client, sync_engine)
    first = _save(client, s.dm, s.opp_id, [{"line_id": s.l1, "effort_hours": 36}])
    assert first.status_code == 200, first.text
    edits = [
        {"line_id": s.l1, "effort_hours": 41, "variance_cause": "integration_complexity"},
        {"line_id": s.l2, "effort_hours": 20},
    ]
    no_reason = _save(client, s.dm, s.opp_id, edits)
    _problem(no_reason, 422, "actual_invalid")
    assert resp_fields(no_reason) == [(None, "reason")]
    assert len(_actuals(sync_engine, s.opp_id)) == 1

    resp = _save(client, s.dm, s.opp_id, edits, reason="Timesheets closed")
    assert resp.status_code == 200, resp.text
    assert (resp.json()["recorded"], resp.json()["corrected"]) == (1, 1)
    stored = _actuals(sync_engine, s.opp_id)
    l1_rows = [r for r in stored if str(r["estimate_line_id"]) == s.l1]
    assert [(r["version"], r["is_current"]) for r in l1_rows] == [(1, False), (2, True)]
    assert l1_rows[1]["actual_group_id"] == l1_rows[0]["actual_group_id"]
    assert l1_rows[1]["correction_reason"] == "Timesheets closed"
    assert len(_events(sync_engine, s.opp_id, RECORDED)) == 2  # the first save, then L2
    (corrected,) = _events(sync_engine, s.opp_id, CORRECTED)
    assert corrected["payload"]["reason"] == "Timesheets closed"
    assert corrected["payload"]["previous_version"] == 1
    actual = _line_view(resp.json()["view"], s.l1)["actual"]
    assert actual["version"] == 2
    assert [(h["version"], h["effort_hours"]) for h in actual["history"]] == [(1, 36.0)]


def resp_fields(resp: Any) -> list[tuple[int | None, str]]:
    return [(e["item"], e["field"]) for e in resp.json()["errors"]]


def test_correct_one_actual(client: TestClient, sync_engine: Engine) -> None:
    s = _scene(client, sync_engine)
    saved = _save(client, s.dm, s.opp_id, [{"line_id": s.l1, "effort_hours": 36}]).json()
    actual = _line_view(saved["view"], s.l1)["actual"]
    url = f"{BASE}/{s.opp_id}/actuals/{actual['id']}/corrections"
    body = {"effort_hours": 40, "variance_cause": "customer_delay", "reason": "Late invoice"}

    _problem(client.post(url, headers=s.dm, json=body), 428, "if_match_required")
    blank = client.post(url, headers={**s.dm, "If-Match": '"1"'}, json={**body, "reason": "  "})
    _problem(blank, 422, "actual_invalid")
    resp = client.post(url, headers={**s.dm, "If-Match": '"1"'}, json=body)
    assert resp.status_code == 201, resp.text
    again = client.post(url, headers={**s.dm, "If-Match": '"1"'}, json=body)
    _problem(again, 412, "row_version_mismatch")  # no longer current
    (event,) = _events(sync_engine, s.opp_id, CORRECTED)
    assert (event["payload"]["version"], event["payload"]["reason"]) == (2, "Late invoice")
    assert _line_view(resp.json()["view"], s.l1)["variance"]["label"] == "+4.0 h (11.1%)"


def test_rows_are_never_changed_or_deleted(client: TestClient, sync_engine: Engine) -> None:
    s = _scene(client, sync_engine)
    assert _save(client, s.dm, s.opp_id, [{"line_id": s.l1, "effort_hours": 36}]).status_code == 200
    for statement in (
        "UPDATE actuals_actuals SET effort_hours = 1 WHERE opportunity_id = :o",
        "DELETE FROM actuals_actuals WHERE opportunity_id = :o",
        "DELETE FROM actuals_deliveries WHERE opportunity_id = :o",
    ):
        with pytest.raises(sa.exc.ProgrammingError, match="permission denied"):
            with sync_engine.begin() as conn:
                conn.execute(sa.text(statement), {"o": s.opp_id})


# --- version mismatch -----------------------------------------------------------------------


def test_actuals_stay_tied_to_their_version(client: TestClient, sync_engine: Engine) -> None:
    s = _scene(client, sync_engine)
    item = {
        "effort_hours": 8,
        "variance_cause": "scope_change",
        "integration_type_id": str(s.entry),
    }
    first = _save(client, s.dm, s.opp_id, [item, {"line_id": s.l1, "effort_hours": 36}])
    assert first.status_code == 200, first.text
    v5 = _version(sync_engine, s.opp_id, 5, status="approved", created_by=s.owner_id)
    l1_v5 = _line(sync_engine, v5, 1, "WMS to SAP EWM interface", "40.0")
    _baseline(sync_engine, s.opp_id, v5, s.owner_id)

    view = _view(client, s.dm, s.opp_id)
    assert view["baseline"]["version"] == 5
    assert view["version_mismatch"]["message"] == (
        "Actuals recorded against v3; the current Baseline is v5"
    )
    assert view["version_mismatch"]["actual_count"] == 2
    assert _line_view(view, l1_v5)["actual"] is None
    assert view["unplanned"] == []
    assert {str(r["estimate_version_id"]) for r in _actuals(sync_engine, s.opp_id)} == {s.v3}


# --- Close delivery -------------------------------------------------------------------------


def test_close_delivery(client: TestClient, sync_engine: Engine) -> None:
    s = _scene(client, sync_engine)
    _save(client, s.dm, s.opp_id, [{"line_id": s.l1, "effort_hours": 36}])
    blocked = _close(client, s.dm, s.opp_id)
    _problem(blocked, 409, "delivery_not_ready")
    assert blocked.json()["detail"] == "1 line has no final Actual"
    assert blocked.json()["open_line_count"] == 1
    assert _list_status(client, s.owner, s.opp_id) == "baselined"

    _save(client, s.dm, s.opp_id, [{"line_id": s.l2, "effort_hours": 20}])
    ready = _view(client, s.dm, s.opp_id)
    assert (ready["can_close"], ready["close_blocked_reason"]) == (True, None)
    resp = _close(client, s.dm, s.opp_id)
    assert resp.status_code == 200, resp.text
    assert resp.json()["delivery"]["closed_by_name"] == "Dana Delivery"
    assert (resp.json()["can_record"], resp.json()["can_close"]) == (False, False)
    (event,) = _events(sync_engine, s.opp_id, CLOSED)
    assert (event["payload"]["line_count"], event["payload"]["estimate_version"]) == (2, 3)

    # The list and the domain agree: `delivered`.
    assert derived_status(True, delivered=True) is OpportunityStatus.DELIVERED
    assert _list_status(client, s.owner, s.opp_id) == "delivered"
    filtered = client.get(
        f"{BASE}?scope=all&status=delivered&page_size=200", headers=s.owner
    ).json()["items"]
    assert s.opp_id in {i["id"] for i in filtered}
    baselined = client.get(
        f"{BASE}?scope=all&status=baselined&page_size=200", headers=s.owner
    ).json()["items"]
    assert s.opp_id not in {i["id"] for i in baselined}
    assert client.get(f"{BASE}/{s.opp_id}", headers=s.owner).json()["status"] == "delivered"

    _problem(_close(client, s.dm, s.opp_id), 409, "delivery_closed")
    late = _save(client, s.dm, s.opp_id, [{"line_id": s.l1, "effort_hours": 37}], reason="Late")
    _problem(late, 409, "delivery_closed")


def test_the_migration_goes_down_and_up(client: TestClient, sync_engine: Engine) -> None:
    s = _scene(client, sync_engine)
    assert _save(client, s.dm, s.opp_id, [{"line_id": s.l1, "effort_hours": 36}]).status_code == 200

    _alembic("downgrade", "0052_estimates_baselines")
    try:
        tables = rows(
            sync_engine,
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name IN ('actuals_actuals', 'actuals_deliveries')",
        )
        assert tables == []
    finally:
        _alembic("upgrade", "head")
    assert _actuals(sync_engine, s.opp_id) == []
    assert _save(client, s.dm, s.opp_id, [{"line_id": s.l1, "effort_hours": 36}]).status_code == 200


# --- review follow-ups ----------------------------------------------------------------------


def test_close_delivery_needs_a_current_if_match(client: TestClient, sync_engine: Engine) -> None:
    s = _scene(client, sync_engine)
    stale = _view(client, s.dm, s.opp_id)["row_version"]
    items = [{"line_id": s.l1, "effort_hours": 36}, {"line_id": s.l2, "effort_hours": 20}]
    assert _save(client, s.dm, s.opp_id, items).status_code == 200
    url = f"{BASE}/{s.opp_id}/actuals/delivery/close"
    _problem(
        client.post(url, headers={**s.dm, "If-Match": f'"{stale}"'}), 412, "row_version_mismatch"
    )
    _problem(client.post(url, headers=s.dm), 428, "if_match_required")
    assert (
        rows(sync_engine, "SELECT id FROM actuals_deliveries WHERE opportunity_id = :o", o=s.opp_id)
        == []
    )


def test_correct_unplanned_work_through_save(client: TestClient, sync_engine: Engine) -> None:
    s = _scene(client, sync_engine)
    item = {
        "effort_hours": 8,
        "variance_cause": "scope_change",
        "integration_type_id": str(s.entry),
    }
    first = _save(client, s.dm, s.opp_id, [item, {"line_id": s.l1, "effort_hours": 36}]).json()
    (unplanned,) = first["view"]["unplanned"]
    line_actual = _line_view(first["view"], s.l1)["actual"]

    fix = {**item, "actual_id": unplanned["id"], "effort_hours": 10}
    resp = _save(client, s.dm, s.opp_id, [fix], reason="Late timesheet")
    assert resp.status_code == 200, resp.text
    (corrected,) = resp.json()["view"]["unplanned"]
    assert (corrected["version"], corrected["group_id"]) == (2, unplanned["group_id"])
    (event,) = _events(sync_engine, s.opp_id, CORRECTED)
    assert (event["payload"]["line_id"], event["payload"]["previous_version"]) == (None, 1)
    assert event["payload"]["integration_type_ids"] == [str(s.entry)]

    _problem(_save(client, s.dm, s.opp_id, [fix], reason="Again"), 412, "row_version_mismatch")
    wrong = {**item, "actual_id": line_actual["id"]}
    resp = _save(client, s.dm, s.opp_id, [wrong], reason="x")
    _problem(resp, 422, "actual_invalid")
    assert resp_fields(resp) == [(0, "actual_id")]
    twice = {**item, "actual_id": corrected["id"]}
    resp = _save(client, s.dm, s.opp_id, [twice, twice], reason="x")
    _problem(resp, 422, "actual_invalid")
    assert resp_fields(resp) == [(1, "actual_id")]
    assert len(_events(sync_engine, s.opp_id, CORRECTED)) == 1


def test_a_cost_correction_is_traced(client: TestClient, sync_engine: Engine) -> None:
    s = _scene(client, sync_engine)
    saved = _save(client, s.dm, s.opp_id, [{"line_id": s.l1, "effort_hours": 36}]).json()
    actual = _line_view(saved["view"], s.l1)["actual"]
    body = {
        "effort_hours": 36,
        "cost_minor": 480000,
        "currency": "EUR",
        "duration_days": 4.5,
        "reason": "Invoice in",
    }
    resp = client.post(
        f"{BASE}/{s.opp_id}/actuals/{actual['id']}/corrections",
        headers={**s.dm, "If-Match": '"1"'},
        json=body,
    )
    assert resp.status_code == 201, resp.text
    (event,) = _events(sync_engine, s.opp_id, CORRECTED)
    payload = event["payload"]
    assert (payload["cost_minor"], payload["currency"], payload["duration_days"]) == (
        480000,
        "EUR",
        "4.5",
    )
    assert payload["integration_type_ids"] == [str(s.entry)]
    assert payload["work_package_id"] is None


def test_correct_a_v3_actual_after_the_baseline_moves(
    client: TestClient, sync_engine: Engine
) -> None:
    s = _scene(client, sync_engine)
    saved = _save(client, s.dm, s.opp_id, [{"line_id": s.l1, "effort_hours": 36}]).json()
    actual = _line_view(saved["view"], s.l1)["actual"]
    v5 = _version(sync_engine, s.opp_id, 5, status="approved", created_by=s.owner_id)
    _line(sync_engine, v5, 1, "WMS to SAP EWM interface", "40.0")
    v5_assumption = _assumption(sync_engine, v5, 1)
    _baseline(sync_engine, s.opp_id, v5, s.owner_id)
    url = f"{BASE}/{s.opp_id}/actuals/{actual['id']}/corrections"
    body = {"effort_hours": 41, "variance_cause": "unknown_requirement", "reason": "Volumes"}

    foreign = client.post(
        url,
        headers={**s.dm, "If-Match": '"1"'},
        json={**body, "failed_assumption_ids": [v5_assumption]},
    )
    _problem(foreign, 422, "actual_invalid")
    assert resp_fields(foreign) == [(None, "failed_assumption_ids")]
    resp = client.post(
        url,
        headers={**s.dm, "If-Match": '"1"'},
        json={**body, "failed_assumption_ids": [s.assumption]},
    )
    assert resp.status_code == 201, resp.text
    (event,) = _events(sync_engine, s.opp_id, CORRECTED)
    assert (event["payload"]["estimate_version_id"], event["payload"]["estimate_version"]) == (
        s.v3,
        3,
    )
    assert {str(r["estimate_version_id"]) for r in _actuals(sync_engine, s.opp_id)} == {s.v3}


def test_closed_delivery_keeps_showing_its_version(client: TestClient, sync_engine: Engine) -> None:
    s = _scene(client, sync_engine)
    items = [{"line_id": s.l1, "effort_hours": 36}, {"line_id": s.l2, "effort_hours": 20}]
    assert _save(client, s.dm, s.opp_id, items).status_code == 200
    assert _close(client, s.dm, s.opp_id).status_code == 200
    v5 = _version(sync_engine, s.opp_id, 5, status="approved", created_by=s.owner_id)
    _line(sync_engine, v5, 1, "WMS to SAP EWM interface", "40.0")
    _baseline(sync_engine, s.opp_id, v5, s.owner_id)

    view = _view(client, s.dm, s.opp_id)
    assert [line["line_id"] for line in view["lines"]] == [s.l1, s.l2]
    assert all(line["actual"] is not None for line in view["lines"])
    assert view["baseline"]["version"] == 3
    assert view["open_line_count"] == 0
    assert view["totals"]["actual_hours"] == 56.0
    assert view["version_mismatch"] is None
