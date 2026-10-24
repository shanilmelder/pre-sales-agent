"""Risks (Story 8.5) against a real, migrated Postgres as psa_app: converting an open Gap to a
Risk (`POST …/risks`: the Gap converts, the draft's unaccepted proposal for it goes, both
events, 409 `gap_not_open` / `no_draft_estimate`, who may), editing a Risk (If-Match, not
draft, no-op, order), the Risks in the Estimate, and carrying them to a re-draft.

Reuses the fixtures and helpers of `test_estimates_assumptions.py`.
"""

import logging
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tests import test_estimates_assumptions as base
from tests.test_estimates_assumptions import (
    HAPPY,
    _accept,
    _all,
    _labels,
    _register,
    assumption_rows,
    by_title,
    events,
    gap_rows,
    proposed,
    redraft,
)
from tests.test_estimates_draft import versions
from tests.test_gaps_detection import extracted, gaps_out, rows
from tests.test_health import assert_problem
from tests.test_intake_extraction import BASE, DETECT, PROPOSE, FakeGateway, drain
from tests.test_intake_parse_job import _alembic
from tests.test_opportunities import _add, _user

storage_dir = base.storage_dir
_hidden_jobs = base._hidden_jobs
gateway = base.gateway
client = base.client
_chat_profile = base._chat_profile
_draft_profile = base._draft_profile
_proposal_profile = base._proposal_profile

CREATED = "estimates.risk.created"
EDITED = "estimates.risk.edited"
DESCRIPTION = "Peak volumes may exceed what the interface was sized for."
REASON = "The customer expects a sale-day spike."


def risk_rows(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT r.* FROM estimates_risks r JOIN estimates_estimate_versions v "
        "ON v.id = r.version_id WHERE v.opportunity_id = :o ORDER BY v.version, r.position",
        o=opp_id,
    )


def _convert(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    gap_id: str,
    description: str = DESCRIPTION,
    likelihood: str = "medium",
    impact: str = "medium",
) -> Any:
    return client.post(
        f"{BASE}/{opp_id}/risks",
        headers=headers,
        json={
            "gap_id": gap_id,
            "description": description,
            "likelihood": likelihood,
            "impact": impact,
        },
    )


def _edit(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    risk: dict[str, Any],
    row_version: int | None = None,
    **fields: Any,
) -> Any:
    rv = risk["row_version"] if row_version is None else row_version
    extra = {} if rv == 0 else {"If-Match": f'"{rv}"'}
    return client.patch(
        f"{BASE}/{opp_id}/risks/{risk['id']}",
        headers={**headers, **extra},
        json={"reason": REASON, **fields},
    )


def _gap_id(engine: Engine, opp_id: str, title: str) -> str:
    return str(gap_rows(engine, opp_id)[title]["id"])


# --- converting -----------------------------------------------------------------------------


def test_converting_a_gap_makes_a_risk_and_removes_its_proposal(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    before = _register(client, headers, opp["id"])
    peak = _all(before)["Peak order volume"]  # unaccepted, 8 h on "24/7 operations"
    gap_id = peak["origin"]["id"]

    with caplog.at_level(logging.DEBUG):
        resp = _convert(client, headers, opp["id"], gap_id, f"  {DESCRIPTION} ", "high", "medium")

    assert resp.status_code == 201, resp.text
    assert resp.headers["ETag"] == '"1"'
    risk = resp.json()
    assert (risk["position"], risk["description"]) == (1, DESCRIPTION)
    assert (risk["likelihood"], risk["impact"]) == ("high", "medium")
    assert risk["origin"]["id"] == gap_id
    assert risk["origin"]["status"] == "converted"
    assert risk["origin_superseded"] is False
    assert risk["carried_from_version"] is None

    gaps = gap_rows(sync_engine, opp["id"])
    assert (gaps["Peak order volume"]["status"], gaps["Peak order volume"]["converted_to"]) == (
        "converted",
        "risk",
    )
    remaining = {str(a["id"]) for a in assumption_rows(sync_engine, opp["id"])}
    assert peak["id"] not in remaining
    assert len(remaining) == 3
    (stored,) = risk_rows(sync_engine, opp["id"])
    assert stored["origin_ref"] == {"kind": "gap", "id": gap_id, "row_version": 1}
    assert stored["created_by"] == stored["changed_by"]

    after = _register(client, headers, opp["id"])
    assert after["risks"] == [risk]
    assert after["counts"] == {"total": 3, "accepted": 0, "not_accepted": 3}
    assert after["totals"]["contingency_hours"] == before["totals"]["contingency_hours"] - 8.0
    assert after["unconverted_gaps"] == []

    (created,) = events(sync_engine, opp["id"], CREATED)
    assert (created["subject_type"], str(created["subject_id"])) == ("estimates.risk", risk["id"])
    assert created["actor_type"] == "user"
    assert created["payload"] == {
        "version_id": before["id"],
        "gap_id": gap_id,
        "likelihood": "high",
        "impact": "medium",
        "description_length": len(DESCRIPTION),
        "removed_assumption_count": 1,
    }
    (converted,) = events(sync_engine, opp["id"], "gaps.gap.converted")
    assert converted["payload"] == {"assumption_kind": "risk", "row_version": 2}

    # The Gaps tab lists it converted to a Risk.
    listed = client.get(f"{BASE}/{opp['id']}/gaps", headers=headers).json()["items"]
    assert [(g["title"], g["converted_to"]) for g in listed][-1] == ("Peak order volume", "risk")

    # Privacy: never the description.
    logged = caplog.text + str([r.__dict__ for r in caplog.records])
    for leak in ("Peak volumes", "sale-day"):
        assert leak not in logged
        assert leak not in str(created)


def test_a_gap_no_longer_open_is_refused_and_nothing_commits(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    wms = _all(_register(client, headers, opp["id"]))["WMS version unknown"]
    assert _accept(client, headers, opp["id"], wms["id"]).status_code == 200
    before = assumption_rows(sync_engine, opp["id"])

    resp = _convert(client, headers, opp["id"], wms["origin"]["id"])

    assert_problem(resp.json(), 409, "gap_not_open")
    assert risk_rows(sync_engine, opp["id"]) == []
    assert assumption_rows(sync_engine, opp["id"]) == before
    assert gap_rows(sync_engine, opp["id"])["WMS version unknown"]["converted_to"] == "condition"
    assert events(sync_engine, opp["id"], CREATED) == []

    # Converting twice: the second is not open either.
    sso = _gap_id(sync_engine, opp["id"], "SSO provider")
    assert _convert(client, headers, opp["id"], sso).status_code == 201
    assert_problem(_convert(client, headers, opp["id"], sso).json(), 409, "gap_not_open")
    assert len(risk_rows(sync_engine, opp["id"])) == 1


def test_converting_needs_a_draft_estimate(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = extracted(client, sync_engine, db_url, gateway)
    gateway.replies = [gaps_out(*base.FOUR)]
    assert drain(db_url, DETECT) == ["succeeded"]
    gap_id = _gap_id(sync_engine, opp["id"], "SSO provider")

    resp = _convert(client, headers, opp["id"], gap_id)

    assert_problem(resp.json(), 409, "no_draft_estimate")
    assert gap_rows(sync_engine, opp["id"])["SSO provider"]["status"] == "open"
    estimate = client.get(f"{BASE}/{opp['id']}/estimate", headers=headers).json()
    assert (estimate["version"], estimate["can_create_risks"]) == (None, True)


def test_an_unknown_gap_or_a_bad_body_is_refused(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    gap_id = _gap_id(sync_engine, opp["id"], "SSO provider")
    unknown = "01a10891-875d-7f80-9921-65c3fbf28ecb"

    assert_problem(_convert(client, headers, opp["id"], unknown).json(), 404, "not_found")
    blank = _convert(client, headers, opp["id"], gap_id, description="   ")
    assert_problem(blank.json(), 422, "validation_error")
    assert blank.json()["detail"] == "The description must be 1 to 500 characters."
    long = _convert(client, headers, opp["id"], gap_id, description="x" * 501)
    assert long.json()["detail"] == "The description must be 1 to 500 characters."
    assert _convert(client, headers, opp["id"], gap_id, impact="severe").status_code == 422
    assert risk_rows(sync_engine, opp["id"]) == []
    assert gap_rows(sync_engine, opp["id"])["SSO provider"]["status"] == "open"


def test_who_may_convert_and_edit(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    rep, rep_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    current = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    assert _add(client, headers, current, rep_id).status_code == 200
    reader, _ = _user(client, sync_engine, "Head Person", "head_of_delivery")
    outsider, _ = _user(client, sync_engine, "Outsider", "presales_engineer")
    gap_id = _gap_id(sync_engine, opp["id"], "SSO provider")

    seen = client.get(f"{BASE}/{opp['id']}/estimate", headers=rep).json()
    assert (seen["can_create_risks"], seen["can_edit_risks"]) == (False, False)
    assert_problem(_convert(client, rep, opp["id"], gap_id).json(), 403, "forbidden")
    assert_problem(_convert(client, reader, opp["id"], gap_id).json(), 403, "forbidden")
    assert_problem(_convert(client, outsider, opp["id"], gap_id).json(), 404, "not_found")

    risk = _convert(client, headers, opp["id"], gap_id).json()
    assert_problem(_edit(client, rep, opp["id"], risk, impact="high").json(), 403, "forbidden")
    assert_problem(_edit(client, outsider, opp["id"], risk, impact="high").json(), 404, "not_found")
    assert [r["row_version"] for r in risk_rows(sync_engine, opp["id"])] == [1]


def test_psa_app_cannot_delete_risks(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    risk = _convert(client, headers, opp["id"], _gap_id(sync_engine, opp["id"], "SSO provider"))
    with pytest.raises(sa.exc.ProgrammingError), sync_engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM estimates_risks WHERE id = :i"), {"i": risk.json()["id"]})


# --- editing --------------------------------------------------------------------------------


def test_editing_a_risk_re_sorts_and_traces(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    first = _convert(
        client,
        headers,
        opp["id"],
        _gap_id(sync_engine, opp["id"], "SSO provider"),
        "Low one",
        "low",
        "medium",
    ).json()
    second = _convert(
        client,
        headers,
        opp["id"],
        _gap_id(sync_engine, opp["id"], "Test data owner"),
        "Likely one",
        "high",
        "medium",
    ).json()
    order = [r["position"] for r in _register(client, headers, opp["id"])["risks"]]
    assert order == [2, 1]  # same impact: the likelier first

    resp = _edit(client, headers, opp["id"], first, impact="high")

    assert resp.status_code == 200, resp.text
    risks = resp.json()["version"]["risks"]
    assert [(r["position"], r["impact"], r["row_version"]) for r in risks] == [
        (1, "high", 2),
        (2, "medium", 1),
    ]
    (event,) = events(sync_engine, opp["id"], EDITED)
    assert (event["subject_type"], str(event["subject_id"])) == ("estimates.risk", first["id"])
    assert event["payload"] == {
        "version_id": resp.json()["version"]["id"],
        "before_likelihood": "low",
        "after_likelihood": "low",
        "before_impact": "medium",
        "after_impact": "high",
        "before_description_length": len("Low one"),
        "after_description_length": len("Low one"),
        "reason_length": len(REASON),
    }
    assert "sale-day" not in str(event)

    # The same values: nothing changes.
    edited = risks[0]
    same = _edit(client, headers, opp["id"], edited, impact="high", description=" Low one ")
    assert same.status_code == 200
    assert same.json()["version"]["risks"][0]["row_version"] == 2
    assert len(events(sync_engine, opp["id"], EDITED)) == 1

    # A stale If-Match names who changed it; a missing one is refused.
    stale = _edit(client, headers, opp["id"], first, row_version=1, likelihood="high")
    assert_problem(stale.json(), 412, "row_version_mismatch")
    assert stale.json()["detail"] == "Changed by Owner Person since you opened it."
    missing = _edit(client, headers, opp["id"], edited, row_version=0, likelihood="high")
    assert_problem(missing.json(), 428, "if_match_required")
    blank = _edit(client, headers, opp["id"], edited, reason=" ", likelihood="high")
    assert blank.json()["detail"] == "Give a reason of 1 to 300 characters."
    assert second["position"] == 2


# --- carrying -------------------------------------------------------------------------------


def test_a_redraft_carries_every_risk(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    v1_risks = [
        _convert(client, headers, opp["id"], _gap_id(sync_engine, opp["id"], title)).json()
        for title in ("SSO provider", "Test data owner")
    ]

    redraft(client, headers, opp["id"], db_url, gateway)

    first, second = versions(sync_engine, opp["id"])
    stored = risk_rows(sync_engine, opp["id"])
    copies = [r for r in stored if r["version_id"] == second["id"]]
    assert len(copies) == 2
    for source, copy in zip(v1_risks, copies, strict=True):
        assert str(copy["carried_from"]) == source["id"]
        assert copy["row_version"] == 1
        assert copy["description"] == source["description"]
    created = events(sync_engine, opp["id"], "estimates.estimate_version.created")
    assert created[-1]["payload"]["carried_risk_count"] == 2

    # The new draft's proposals skip the Gaps that became Risks.
    gateway.replies = [by_title(HAPPY[0], HAPPY[1])]  # type: ignore[list-item]
    assert drain(db_url, PROPOSE) == ["succeeded"]
    assert set(_labels(gateway.requests[-1], "GAP")) == {"WMS version unknown", "Peak order volume"}
    body = _register(client, headers, opp["id"])
    assert {r["carried_from_version"] for r in body["risks"]} == {1}
    assert {r["origin"]["status"] for r in body["risks"]} == {"converted"}
    assert body["unconverted_gaps"] == []

    # The old version's Risk is not the draft's any more.
    old = _edit(client, headers, opp["id"], v1_risks[0], impact="high")
    assert_problem(old.json(), 409, "estimate_version_not_draft")
    assert first["status"] == "superseded"


def test_converting_removes_only_the_drafts_proposal(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    redraft(client, headers, opp["id"], db_url, gateway)
    gateway.replies = [by_title(*HAPPY)]  # type: ignore[list-item]
    assert drain(db_url, PROPOSE) == ["succeeded"]
    first, second = versions(sync_engine, opp["id"])
    gap_id = _gap_id(sync_engine, opp["id"], "Peak order volume")

    def for_gap(version_id: Any) -> list[dict[str, Any]]:
        return [
            a
            for a in assumption_rows(sync_engine, opp["id"])
            if a["version_id"] == version_id and a["origin_ref"]["id"] == gap_id
        ]

    old = for_gap(first["id"])
    assert len(old) == 1 and len(for_gap(second["id"])) == 1

    assert _convert(client, headers, opp["id"], gap_id).status_code == 201

    assert for_gap(second["id"]) == []
    assert for_gap(first["id"]) == old  # the superseded version keeps its row
    (created,) = events(sync_engine, opp["id"], CREATED)
    assert created["payload"]["removed_assumption_count"] == 1


def test_the_downgrade_reopens_risk_gaps_and_drops_the_risks(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = proposed(client, sync_engine, db_url, gateway)
    gap_id = _gap_id(sync_engine, opp["id"], "SSO provider")
    assert _convert(client, headers, opp["id"], gap_id).status_code == 201

    _alembic("downgrade", "0040_workflows_decisions")
    try:
        (row,) = rows(
            sync_engine, "SELECT status, converted_to FROM gaps_gaps WHERE id = :g", g=gap_id
        )
        assert (row["status"], row["converted_to"]) == ("open", None)
        (table,) = rows(sync_engine, "SELECT to_regclass('estimates_risks') AS t")
        assert table["t"] is None
        columns = rows(
            sync_engine,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'estimates_assumptions' AND column_name = 'changed_by'",
        )
        assert columns == []
    finally:
        _alembic("upgrade", "head")

    assert gap_rows(sync_engine, opp["id"])["SSO provider"]["status"] == "open"
