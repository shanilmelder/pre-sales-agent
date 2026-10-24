"""Editing Assumptions (Story 8.5) against a real, migrated Postgres as psa_app: the
`PATCH …/assumptions/{id}` command (validation, If-Match, not-draft, who may, no-op), the
acceptance it clears, the Gap's `converted_to` on a kind change, accepting again, the
Register's new fields (`position`, `origin_superseded`, `origin_is_unknown`), and carrying an
edited (unaccepted) Assumption to a re-draft.

Reuses the fixtures and helpers of `test_estimates_assumptions.py`.
"""

import logging
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tests import test_estimates_assumptions as base
from tests.test_estimates_assumptions import (
    FOUR,
    HAPPY,
    _accept,
    _all,
    _register,
    assumption_rows,
    by_title,
    drafted,
    events,
    gap_rows,
    proposed,
    redraft,
)
from tests.test_estimates_draft import versions
from tests.test_gaps_detection import gap
from tests.test_health import assert_problem
from tests.test_intake_extraction import BASE, PROPOSE, FakeGateway, drain
from tests.test_opportunities import _add, _user

storage_dir = base.storage_dir
_hidden_jobs = base._hidden_jobs
gateway = base.gateway
client = base.client
_chat_profile = base._chat_profile
_draft_profile = base._draft_profile
_proposal_profile = base._proposal_profile

EDITED = "estimates.assumption.edited"
REASON = "The customer confirmed this on the call."


def _edit(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    assumption: dict[str, Any],
    row_version: int | None = None,
    **fields: Any,
) -> Any:
    rv = assumption["row_version"] if row_version is None else row_version
    extra = {} if rv == 0 else {"If-Match": f'"{rv}"'}
    return client.patch(
        f"{BASE}/{opp_id}/assumptions/{assumption['id']}",
        headers={**headers, **extra},
        json={"reason": REASON, **fields},
    )


def _lines(version: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {line["title"]: line for s in version["sections"] for line in s["lines"]}


def _accepted(client: TestClient, headers: dict[str, str], opp_id: str, title: str) -> Any:
    assumption = _all(_register(client, headers, opp_id))[title]
    resp = _accept(client, headers, opp_id, assumption["id"], assumption["row_version"])
    assert resp.status_code == 200, resp.text
    return _all(_register(client, headers, opp_id))[title]


# --- the Register's new fields --------------------------------------------------------------


def test_rows_carry_their_number_and_origin_state(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    body = _register(client, headers, opp["id"])
    view = _all(body)

    stored = {str(a["id"]): a["position"] for a in assumption_rows(sync_engine, opp["id"])}
    assert {a["id"]: a["position"] for a in view.values()} == stored
    assert sorted(stored.values()) == [1, 2, 3, 4]
    assert {a["origin_superseded"] for a in view.values()} == {False}
    assert {a["origin_is_unknown"] for a in view.values()} == {False}
    estimate = client.get(f"{BASE}/{opp['id']}/estimate", headers=headers).json()
    assert estimate["can_edit_assumptions"] is True
    assert body["risks"] == []

    # A Gap changed since (its row version bumped) is superseded; so is a re-detected one.
    peak = gap_rows(sync_engine, opp["id"])["Peak order volume"]
    with sync_engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE gaps_gaps SET impact = 'high', row_version = row_version + 1 WHERE id = %s",
            (peak["id"],),
        )
        conn.exec_driver_sql(
            "UPDATE gaps_gaps SET status = 'superseded', row_version = row_version + 1 "
            "WHERE id = %s",
            (gap_rows(sync_engine, opp["id"])["SSO provider"]["id"],),
        )
    view = _all(_register(client, headers, opp["id"]))
    assert view["Peak order volume"]["origin_superseded"] is True
    assert view["SSO provider"]["origin_superseded"] is True
    assert view["WMS version unknown"]["origin_superseded"] is False

    # Accepting converts the Gap (bumping its row version): still the current origin.
    _accepted(client, headers, opp["id"], "WMS version unknown")
    view = _all(_register(client, headers, opp["id"]))
    assert view["WMS version unknown"]["origin"]["status"] == "converted"
    assert view["WMS version unknown"]["origin_superseded"] is False


def test_an_unknown_origin_is_flagged(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    found = (*FOUR[:3], gap("Test data owner", ["R3"], customer_can_answer=False))
    headers, opp = drafted(client, sync_engine, db_url, gateway, found)
    gateway.replies = [by_title(*HAPPY)]  # type: ignore[list-item]
    assert drain(db_url, PROPOSE) == ["succeeded"]

    view = _all(_register(client, headers, opp["id"]))

    assert view["Test data owner"]["origin"]["why_it_matters"].startswith(
        "Unknown to the customer:"
    )
    assert view["Test data owner"]["origin_is_unknown"] is True
    assert view["WMS version unknown"]["origin_is_unknown"] is False


# --- editing ----------------------------------------------------------------------------------


def test_editing_an_accepted_condition_clears_its_acceptance(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    wms = _accepted(client, headers, opp["id"], "WMS version unknown")
    assert wms["row_version"] == 2
    wording = "The estimate assumes the customer runs WMS 9.2 or later."

    with caplog.at_level(logging.DEBUG):
        resp = _edit(client, headers, opp["id"], wms, wording=f"  {wording}  ")

    assert resp.status_code == 200, resp.text
    edited = _all(resp.json()["version"])["WMS version unknown"]
    assert edited["wording"] == wording
    assert edited["row_version"] == 3
    assert (edited["accepted_by"], edited["accepted_at"]) == (None, None)
    assert resp.json()["version"]["counts"] == {"total": 4, "accepted": 0, "not_accepted": 4}
    stored = {str(a["id"]): a for a in assumption_rows(sync_engine, opp["id"])}[wms["id"]]
    assert (stored["accepted_by"], stored["accepted_at"]) == (None, None)
    assert stored["changed_by"] is not None
    # The Gap stays converted to a Condition.
    gaps = gap_rows(sync_engine, opp["id"])
    assert (gaps["WMS version unknown"]["status"], gaps["WMS version unknown"]["converted_to"]) == (
        "converted",
        "condition",
    )

    (event,) = events(sync_engine, opp["id"], EDITED)
    assert (event["subject_type"], str(event["subject_id"])) == ("estimates.assumption", wms["id"])
    assert event["subject_version"] == 3
    assert event["actor_type"] == "user"
    assert event["payload"] == {
        "version_id": resp.json()["version"]["id"],
        "gap_id": wms["origin"]["id"],
        "before_kind": "condition",
        "after_kind": "condition",
        "before_hours": None,
        "after_hours": None,
        "before_line_id": None,
        "after_line_id": None,
        "before_wording_length": len(wms["wording"]),
        "after_wording_length": len(wording),
        "was_accepted": True,
        "reason_length": len(REASON),
    }
    # Privacy: never the wording or the reason.
    logged = caplog.text + str([r.__dict__ for r in caplog.records])
    for leak in ("WMS 9.2", "confirmed this"):
        assert leak not in logged
        assert leak not in str(event)

    # Accepting it again is allowed: the Gap is this Assumption's own conversion.
    again = _accept(client, headers, opp["id"], wms["id"], 3)
    assert again.status_code == 200, again.text
    assert again.json()["accepted_by"]["name"] == "Owner Person"
    assert len(events(sync_engine, opp["id"], "gaps.gap.converted")) == 1


def test_editing_the_hours_of_an_accepted_contingency_changes_the_totals(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    peak = _accepted(client, headers, opp["id"], "Peak order volume")
    before = _register(client, headers, opp["id"])
    assert _lines(before)["24/7 operations"]["contingency_hours"] == 8.0

    resp = _edit(client, headers, opp["id"], peak, amount_hours=10.04)

    assert resp.status_code == 200, resp.text
    version = resp.json()["version"]
    edited = _all(version)["Peak order volume"]
    assert edited["amount_hours"] == 10.0
    assert edited["accepted_at"] is None  # a blocker row again
    assert _lines(version)["24/7 operations"]["contingency_hours"] == 10.0
    assert version["assumptions"]["contingency_hours"] == 22.0
    assert version["totals"]["contingency_hours"] == 22.0
    assert version["totals"]["total_hours"] == before["totals"]["total_hours"] + 2.0
    (event,) = events(sync_engine, opp["id"], EDITED)
    assert (event["payload"]["before_hours"], event["payload"]["after_hours"]) == (8.0, 10.0)


def test_a_kind_flip_moves_the_hours_and_the_gaps_conversion(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    sso = _accepted(client, headers, opp["id"], "SSO provider")
    before = _register(client, headers, opp["id"])
    target = _lines(before)["24/7 operations"]

    resp = _edit(
        client,
        headers,
        opp["id"],
        sso,
        kind="contingency",
        amount_hours=12,
        line_id=target["id"],
    )

    assert resp.status_code == 200, resp.text
    version = resp.json()["version"]
    flipped = _all(version)["SSO provider"]
    assert (flipped["kind"], flipped["amount_hours"]) == ("contingency", 12.0)
    assert flipped["line"] == {"id": target["id"], "title": "24/7 operations"}
    assert _lines(version)["24/7 operations"]["contingency_hours"] == 20.0
    assert version["totals"]["contingency_hours"] == 32.0
    assert flipped in version["assumptions"]["contingencies"]
    gaps = gap_rows(sync_engine, opp["id"])
    assert gaps["SSO provider"]["converted_to"] == "contingency"
    (event,) = events(sync_engine, opp["id"], EDITED)
    assert event["payload"]["before_kind"] == "condition"
    assert event["payload"]["after_kind"] == "contingency"
    assert event["payload"]["after_line_id"] == target["id"]

    # And back to a Condition: hours and line must go too.
    flipped_back = _edit(
        client,
        headers,
        opp["id"],
        flipped,
        kind="condition",
        amount_hours=None,
        line_id=None,
    )
    assert flipped_back.status_code == 200, flipped_back.text
    assert gap_rows(sync_engine, opp["id"])["SSO provider"]["converted_to"] == "condition"
    assert flipped_back.json()["version"]["totals"] == before["totals"]


def test_editing_an_unaccepted_one_leaves_its_open_gap_alone(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    owner = _all(_register(client, headers, opp["id"]))["Test data owner"]

    resp = _edit(client, headers, opp["id"], owner, kind="condition", amount_hours=None)

    assert resp.status_code == 200, resp.text
    gaps = gap_rows(sync_engine, opp["id"])
    assert (gaps["Test data owner"]["status"], gaps["Test data owner"]["converted_to"]) == (
        "open",
        None,
    )
    assert resp.json()["version"]["unallocated_contingency_hours"] == 0.0
    # Accepting it converts the Gap to the new kind.
    edited = _all(resp.json()["version"])["Test data owner"]
    assert (
        _accept(client, headers, opp["id"], edited["id"], edited["row_version"]).status_code == 200
    )
    assert gap_rows(sync_engine, opp["id"])["Test data owner"]["converted_to"] == "condition"


@pytest.mark.parametrize(
    ("title", "fields", "detail"),
    [
        ("Peak order volume", {"amount_hours": None}, "A Contingency needs 0.5 to 1,000 hours."),
        ("Peak order volume", {"amount_hours": 0.4}, "A Contingency needs 0.5 to 1,000 hours."),
        ("Peak order volume", {"amount_hours": 1000.1}, "A Contingency needs 0.5 to 1,000 hours."),
        ("WMS version unknown", {"amount_hours": 4}, "A Condition has no hours."),
        ("WMS version unknown", {"line_id": "LINE"}, "A Condition is not linked to a line."),
        (
            "Peak order volume",
            {"line_id": "01a10891-875d-7f80-9921-65c3fbf28ecb"},
            "The line must be a line of this Estimate Version.",
        ),
        ("WMS version unknown", {"wording": "   "}, "The wording must be 1 to 500 characters."),
        ("WMS version unknown", {"wording": "x" * 501}, "The wording must be 1 to 500 characters."),
        ("WMS version unknown", {"reason": "  "}, "Give a reason of 1 to 300 characters."),
        ("WMS version unknown", {"reason": "r" * 301}, "Give a reason of 1 to 300 characters."),
    ],
)
def test_an_edit_breaking_a_rule_is_refused(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    title: str,
    fields: dict[str, Any],
    detail: str,
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    version = _register(client, headers, opp["id"])
    if fields.get("line_id") == "LINE":
        fields = {"line_id": _lines(version)["24/7 operations"]["id"]}
    before = assumption_rows(sync_engine, opp["id"])

    resp = _edit(client, headers, opp["id"], _all(version)[title], **fields)

    assert resp.status_code == 422, resp.text
    assert_problem(resp.json(), 422, "validation_error")
    assert resp.json()["detail"] == detail
    assert assumption_rows(sync_engine, opp["id"]) == before
    assert events(sync_engine, opp["id"], EDITED) == []


def test_unknown_fields_and_kinds_are_refused(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    wms = _all(_register(client, headers, opp["id"]))["WMS version unknown"]
    assert _edit(client, headers, opp["id"], wms, kind="risk").status_code == 422
    assert _edit(client, headers, opp["id"], wms, accepted_by="me").status_code == 422


def test_the_same_values_change_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    peak = _accepted(client, headers, opp["id"], "Peak order volume")

    resp = _edit(
        client,
        headers,
        opp["id"],
        peak,
        kind="contingency",
        wording=f" {peak['wording']} ",
        amount_hours=8.0,
        line_id=peak["line"]["id"],
    )

    assert resp.status_code == 200, resp.text
    same = _all(resp.json()["version"])["Peak order volume"]
    assert same["row_version"] == peak["row_version"]
    assert same["accepted_at"] == peak["accepted_at"]  # the acceptance is kept
    assert events(sync_engine, opp["id"], EDITED) == []


def test_a_stale_or_missing_if_match_is_refused(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    wms = _all(_register(client, headers, opp["id"]))["WMS version unknown"]
    _accepted(client, headers, opp["id"], "WMS version unknown")  # row version 2 now

    stale = _edit(client, headers, opp["id"], wms, row_version=1, wording="New wording.")
    missing = _edit(client, headers, opp["id"], wms, row_version=0, wording="New wording.")

    assert_problem(stale.json(), 412, "row_version_mismatch")
    assert stale.json()["detail"] == "Changed by Owner Person since you opened it."
    assert_problem(missing.json(), 428, "if_match_required")
    assert events(sync_engine, opp["id"], EDITED) == []


def test_another_versions_assumption_is_not_draft(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    v1 = _all(_register(client, headers, opp["id"]))
    redraft(client, headers, opp["id"], db_url, gateway)

    resp = _edit(client, headers, opp["id"], v1["WMS version unknown"], wording="New wording.")

    assert_problem(resp.json(), 409, "estimate_version_not_draft")
    assert events(sync_engine, opp["id"], EDITED) == []


def test_who_may_edit(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    rep, rep_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    current = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    assert _add(client, headers, current, rep_id).status_code == 200
    reader, _ = _user(client, sync_engine, "Head Person", "head_of_delivery")
    outsider, _ = _user(client, sync_engine, "Outsider", "presales_engineer")
    wms = _all(_register(client, headers, opp["id"]))["WMS version unknown"]

    seen = client.get(f"{BASE}/{opp['id']}/estimate", headers=rep).json()
    assert seen["can_edit_assumptions"] is False
    assert_problem(_edit(client, rep, opp["id"], wms, wording="x").json(), 403, "forbidden")
    assert_problem(_edit(client, reader, opp["id"], wms, wording="x").json(), 403, "forbidden")
    assert_problem(_edit(client, outsider, opp["id"], wms, wording="x").json(), 404, "not_found")
    unknown = {**wms, "id": "01a10891-875d-7f80-9921-65c3fbf28ecb"}
    assert_problem(_edit(client, headers, opp["id"], unknown, wording="x").json(), 404, "not_found")
    assert events(sync_engine, opp["id"], EDITED) == []


# --- carrying -------------------------------------------------------------------------------


def test_an_edited_assumption_is_carried_unaccepted(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    wms = _accepted(client, headers, opp["id"], "WMS version unknown")
    _accepted(client, headers, opp["id"], "Peak order volume")
    edited = _edit(client, headers, opp["id"], wms, wording="The estimate assumes WMS 9.2.")
    assert edited.status_code == 200, edited.text

    redraft(client, headers, opp["id"], db_url, gateway)

    _, second = versions(sync_engine, opp["id"])
    carried = [
        a for a in assumption_rows(sync_engine, opp["id"]) if a["version_id"] == second["id"]
    ]
    assert [(a["wording"], a["accepted_at"] is None) for a in carried] == [
        ("The estimate assumes WMS 9.2.", True),
        (_all(edited.json()["version"])["Peak order volume"]["wording"], False),
    ]
    # Proposals then cover only the two Gaps still open.
    gateway.replies = [by_title(HAPPY[2], HAPPY[3])]  # type: ignore[list-item]
    assert drain(db_url, PROPOSE) == ["succeeded"]
    body = _register(client, headers, opp["id"])
    assert body["counts"] == {"total": 4, "accepted": 1, "not_accepted": 3}
    view = _all(body)["WMS version unknown"]
    assert view["carried_from_version"] == 1
    assert view["accepted_at"] is None
    # It can be accepted on the new draft: its Gap is still its own conversion.
    accepted = _accept(client, headers, opp["id"], view["id"], view["row_version"])
    assert accepted.status_code == 200, accepted.text
    assert gap_rows(sync_engine, opp["id"])["WMS version unknown"]["converted_to"] == "condition"


def test_an_unaccepted_proposal_with_an_open_gap_is_not_carried(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    owner = _all(_register(client, headers, opp["id"]))["Test data owner"]
    assert _edit(client, headers, opp["id"], owner, amount_hours=20).status_code == 200

    redraft(client, headers, opp["id"], db_url, gateway)

    _, second = versions(sync_engine, opp["id"])
    assert [
        a for a in assumption_rows(sync_engine, opp["id"]) if a["version_id"] == second["id"]
    ] == []
    assert UUID(owner["origin"]["id"]) in {
        g["id"] for g in gap_rows(sync_engine, opp["id"]).values()
    }
