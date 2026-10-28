"""The Opportunity outcome and retention dates (Story 10.5) against a real, migrated Postgres
as psa_app: every row of the story's I/O matrix, 403 per role, 412/428, the three trace
events, the read-only line for other roles, and the `closed` status agreeing between the
domain and the list's SQL (status filter included).

Estimate Versions and the Baseline row are inserted directly; people sign in through `/me`
with their roles (see `test_reviews_requests`).
"""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.opportunities.application.public import (
    OpportunityStatus,
    Outcome,
    derived_status,
    retention_until,
)
from tests import test_opportunities as opportunity_tests
from tests.test_actuals_api import DM, HOD, _baseline, _collaborate
from tests.test_gaps_detection import rows
from tests.test_opportunities import BASE, PSE, _create, _user
from tests.test_reviews_requests import ENG, PM, REP, _events, _version
from tests.test_role_admin import ADMIN, _reissue

client = opportunity_tests.client

CLOSED = "opportunities.opportunity.closed"
END_UPDATED = "opportunities.contract_end_date.updated"
REOPENED = "opportunities.opportunity.reopened"
FLAGS = ("can_record_outcome", "can_change_contract_end", "can_reopen_outcome")


# --- helpers --------------------------------------------------------------------------------


def _problem(resp: Any, status: int, code: str) -> dict[str, Any]:
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = resp.json()
    assert body["code"] == code
    return body


def _get(client: TestClient, headers: dict[str, str], opp_id: str) -> dict[str, Any]:
    resp = client.get(f"{BASE}/{opp_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _tag(client: TestClient, headers: dict[str, str], opp_id: str) -> dict[str, str]:
    return {"If-Match": f'"{_get(client, headers, opp_id)["row_version"]}"'}


def _record(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    body: dict[str, Any],
    *,
    if_match: dict[str, str] | None = None,
) -> Any:
    tag = _tag(client, headers, opp_id) if if_match is None else if_match
    return client.post(f"{BASE}/{opp_id}/outcome", headers={**headers, **tag}, json=body)


def _lost(client: TestClient, headers: dict[str, str], opp_id: str) -> Any:
    return _record(client, headers, opp_id, {"outcome": "lost", "reason": "Lost on price"})


def _won(client: TestClient, headers: dict[str, str], opp_id: str, end: str = "2028-06-30") -> Any:
    return _record(client, headers, opp_id, {"outcome": "won", "contract_end_date": end})


def _change_end(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    end: str,
    reason: str = "Contract extended",
    *,
    if_match: dict[str, str] | None = None,
) -> Any:
    tag = _tag(client, headers, opp_id) if if_match is None else if_match
    return client.patch(
        f"{BASE}/{opp_id}/contract-end-date",
        headers={**headers, **tag},
        json={"contract_end_date": end, "reason": reason},
    )


def _reopen(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    reason: str = "Customer came back",
    *,
    if_match: dict[str, str] | None = None,
) -> Any:
    tag = _tag(client, headers, opp_id) if if_match is None else if_match
    return client.post(
        f"{BASE}/{opp_id}/outcome/reopen", headers={**headers, **tag}, json={"reason": reason}
    )


def _baselined(client: TestClient, engine: Engine) -> tuple[dict[str, str], UUID, str]:
    """An Opportunity owned by a presales engineer with an approved v1 set as its
    Baseline: (owner headers, owner id, opportunity id)."""
    owner, owner_id = _user(client, engine, "Owner Person", PSE)
    opp = _create(client, owner)
    v1 = _version(engine, opp["id"], 1, status="approved", created_by=owner_id)
    _baseline(engine, opp["id"], v1, owner_id)
    return owner, owner_id, opp["id"]


def _list_status(client: TestClient, headers: dict[str, str], opp_id: str) -> str:
    items = client.get(f"{BASE}?scope=mine&page_size=200", headers=headers).json()["items"]
    return str(next(i for i in items if i["id"] == opp_id)["status"])


def _filtered(client: TestClient, headers: dict[str, str], status: str) -> set[str]:
    resp = client.get(
        BASE, headers=headers, params={"scope": "all", "status": status, "page_size": 200}
    )
    assert resp.status_code == 200, resp.text
    return {item["id"] for item in resp.json()["items"]}


def _plus_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


def _stored(engine: Engine, opp_id: str) -> dict[str, Any]:
    (found,) = rows(
        engine,
        "SELECT outcome, outcome_recorded_at, contract_end_date, row_version "
        "FROM opportunities_opportunities WHERE id = :o",
        o=opp_id,
    )
    return found


# --- the matrix -----------------------------------------------------------------------------


def test_close_as_lost(client: TestClient, sync_engine: Engine) -> None:
    owner, _, opp_id = _baselined(client, sync_engine)
    before = _get(client, owner, opp_id)
    assert before["outcome"] is None
    assert before["retention_until"] is None
    assert before["can_record_outcome"] is True

    resp = _lost(client, owner, opp_id)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert resp.headers["ETag"] == f'"{before["row_version"] + 1}"'
    assert body["outcome"] == "lost"
    assert body["status"] == "closed"
    assert body["contract_end_date"] is None
    recorded = datetime.fromisoformat(body["outcome_recorded_at"])
    expected = retention_until(Outcome.LOST, recorded, None)
    assert expected is not None
    assert body["retention_until"] == expected.isoformat()
    assert body["retention_until"] == _plus_years(recorded.date(), 3).isoformat()
    assert body["can_record_outcome"] is False
    assert body["can_change_contract_end"] is False
    assert body["can_reopen_outcome"] is False  # the owner may not reopen

    (event,) = _events(sync_engine, opp_id, CLOSED)
    assert event["subject_type"] == "opportunities.opportunity"
    assert str(event["subject_id"]) == opp_id
    assert event["subject_version"] == body["row_version"]
    assert event["payload"] == {
        "outcome": "lost",
        "reason": "Lost on price",
        "contract_end_date": None,
        "retention_until": body["retention_until"],
    }


def test_lost_needs_a_reason(client: TestClient, sync_engine: Engine) -> None:
    owner, _, opp_id = _baselined(client, sync_engine)
    for body in ({"outcome": "lost"}, {"outcome": "lost", "reason": "   "}):
        problem = _problem(_record(client, owner, opp_id, body), 422, "outcome_invalid")
        assert [e["field"] for e in problem["errors"]] == ["reason"]
    long = {"outcome": "lost", "reason": "x" * 1001}
    _problem(_record(client, owner, opp_id, long), 422, "outcome_invalid")
    assert _stored(sync_engine, opp_id)["outcome"] is None
    assert _events(sync_engine, opp_id, CLOSED) == []


def test_mark_as_won_by_the_head_of_delivery(client: TestClient, sync_engine: Engine) -> None:
    owner, _, opp_id = _baselined(client, sync_engine)
    hod, _ = _user(client, sync_engine, "Hana Delivery Head", HOD)
    assert _get(client, hod, opp_id)["can_record_outcome"] is True

    resp = _won(client, hod, opp_id, "2028-06-30")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["outcome"] == "won"
    assert body["contract_end_date"] == "2028-06-30"
    assert body["retention_until"] == "2035-06-30"
    assert body["status"] == "baselined"  # won keeps its derived status
    assert body["can_change_contract_end"] is True
    assert body["can_reopen_outcome"] is True
    assert _list_status(client, owner, opp_id) == "baselined"

    (event,) = _events(sync_engine, opp_id, CLOSED)
    assert event["payload"] == {
        "outcome": "won",
        "reason": None,
        "contract_end_date": "2028-06-30",
        "retention_until": "2035-06-30",
    }


def test_won_needs_a_baseline(client: TestClient, sync_engine: Engine) -> None:
    owner, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, owner)
    _problem(_won(client, owner, opp["id"]), 409, "baseline_required")
    assert _stored(sync_engine, opp["id"])["outcome"] is None


def test_won_needs_a_contract_end_date(client: TestClient, sync_engine: Engine) -> None:
    owner, _, opp_id = _baselined(client, sync_engine)
    problem = _problem(_record(client, owner, opp_id, {"outcome": "won"}), 422, "outcome_invalid")
    assert [e["field"] for e in problem["errors"]] == ["contract_end_date"]
    _problem(_won(client, owner, opp_id, "9999-01-01"), 422, "outcome_invalid")
    bad = _record(client, owner, opp_id, {"outcome": "won", "contract_end_date": "soon"})
    _problem(bad, 422, "validation_error")
    _problem(_record(client, owner, opp_id, {"outcome": "drawn"}), 422, "validation_error")
    assert _stored(sync_engine, opp_id)["outcome"] is None


def test_a_second_outcome_is_409(client: TestClient, sync_engine: Engine) -> None:
    owner, _, opp_id = _baselined(client, sync_engine)
    assert _lost(client, owner, opp_id).status_code == 200
    _problem(_lost(client, owner, opp_id), 409, "outcome_already_recorded")
    _problem(_won(client, owner, opp_id), 409, "outcome_already_recorded")
    assert len(_events(sync_engine, opp_id, CLOSED)) == 1


def test_change_contract_end_date(client: TestClient, sync_engine: Engine) -> None:
    owner, _, opp_id = _baselined(client, sync_engine)
    hod, _ = _user(client, sync_engine, "Hana Delivery Head", HOD)
    admin, _ = _user(client, sync_engine, "Ada Admin", ADMIN)
    assert _won(client, owner, opp_id).status_code == 200

    _problem(_change_end(client, owner, opp_id, "2029-12-31"), 403, "forbidden")
    problem = _problem(_change_end(client, hod, opp_id, "2029-12-31", "  "), 422, "outcome_invalid")
    assert [e["field"] for e in problem["errors"]] == ["reason"]

    resp = _change_end(client, hod, opp_id, "2029-12-31")
    assert resp.status_code == 200, resp.text
    assert resp.json()["contract_end_date"] == "2029-12-31"
    assert resp.json()["retention_until"] == "2036-12-31"
    (event,) = _events(sync_engine, opp_id, END_UPDATED)
    assert event["payload"] == {
        "previous_contract_end_date": "2028-06-30",
        "contract_end_date": "2029-12-31",
        "reason": "Contract extended",
        "retention_until": "2036-12-31",
    }

    # The administrator may too; the same date again writes nothing.
    assert _change_end(client, admin, opp_id, "2030-01-31").status_code == 200
    same = _change_end(client, admin, opp_id, "2030-01-31")
    assert same.status_code == 200, same.text
    assert len(_events(sync_engine, opp_id, END_UPDATED)) == 2


def test_contract_end_date_only_when_won(client: TestClient, sync_engine: Engine) -> None:
    owner, _, opp_id = _baselined(client, sync_engine)
    hod, _ = _user(client, sync_engine, "Hana Delivery Head", HOD)
    _problem(_change_end(client, hod, opp_id, "2029-12-31"), 409, "outcome_not_won")
    assert _lost(client, owner, opp_id).status_code == 200
    _problem(_change_end(client, hod, opp_id, "2029-12-31"), 409, "outcome_not_won")


@pytest.mark.parametrize("outcome", ["lost", "won"])
def test_reopen(client: TestClient, sync_engine: Engine, outcome: str) -> None:
    owner, _, opp_id = _baselined(client, sync_engine)
    hod, _ = _user(client, sync_engine, "Hana Delivery Head", HOD)
    admin, _ = _user(client, sync_engine, "Ada Admin", ADMIN)
    recorded = _lost(client, owner, opp_id) if outcome == "lost" else _won(client, owner, opp_id)
    assert recorded.status_code == 200, recorded.text

    _problem(_reopen(client, owner, opp_id), 403, "forbidden")
    _problem(_reopen(client, hod, opp_id, ""), 422, "outcome_invalid")
    resp = _reopen(client, admin if outcome == "lost" else hod, opp_id)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["outcome"] is None
    assert body["outcome_recorded_at"] is None
    assert body["contract_end_date"] is None
    assert body["retention_until"] is None
    assert body["status"] == "baselined"
    # The administrator may reopen but not record; the Head of Delivery may do both.
    assert body["can_record_outcome"] is (outcome == "won")
    assert _get(client, owner, opp_id)["can_record_outcome"] is True
    assert _list_status(client, owner, opp_id) == "baselined"
    stored = _stored(sync_engine, opp_id)
    assert (stored["outcome"], stored["outcome_recorded_at"], stored["contract_end_date"]) == (
        None,
        None,
        None,
    )
    (event,) = _events(sync_engine, opp_id, REOPENED)
    assert event["payload"] == {"previous_outcome": outcome, "reason": "Customer came back"}

    # Reopening again has nothing to reopen; a new outcome can be recorded.
    _problem(_reopen(client, hod, opp_id), 409, "outcome_not_recorded")
    assert _lost(client, owner, opp_id).status_code == 200


def test_stale_and_missing_if_match(client: TestClient, sync_engine: Engine) -> None:
    owner, _, opp_id = _baselined(client, sync_engine)
    hod, _ = _user(client, sync_engine, "Hana Delivery Head", HOD)
    old = _tag(client, owner, opp_id)
    # Someone else changes the Opportunity first.
    edit = client.patch(f"{BASE}/{opp_id}", headers={**owner, **old}, json={"title": "Renamed"})
    assert edit.status_code == 200, edit.text

    body = {"outcome": "lost", "reason": "Lost on price"}
    _problem(_record(client, owner, opp_id, body, if_match=old), 412, "row_version_mismatch")
    _problem(_record(client, owner, opp_id, body, if_match={}), 428, "if_match_required")
    assert _stored(sync_engine, opp_id)["outcome"] is None

    assert _won(client, owner, opp_id).status_code == 200
    _problem(
        _change_end(client, hod, opp_id, "2030-01-01", if_match=old), 412, "row_version_mismatch"
    )
    _problem(_change_end(client, hod, opp_id, "2030-01-01", if_match={}), 428, "if_match_required")
    _problem(_reopen(client, hod, opp_id, if_match=old), 412, "row_version_mismatch")
    _problem(_reopen(client, hod, opp_id, if_match={}), 428, "if_match_required")
    assert _stored(sync_engine, opp_id)["outcome"] == "won"


def test_same_contract_end_date_still_checks_if_match(
    client: TestClient, sync_engine: Engine
) -> None:
    owner, _, opp_id = _baselined(client, sync_engine)
    hod, _ = _user(client, sync_engine, "Hana Delivery Head", HOD)
    assert _won(client, owner, opp_id, "2028-06-30").status_code == 200
    old = _tag(client, owner, opp_id)
    edit = client.patch(f"{BASE}/{opp_id}", headers={**owner, **old}, json={"title": "Renamed"})
    assert edit.status_code == 200, edit.text

    stale = _change_end(client, hod, opp_id, "2028-06-30", if_match=old)
    _problem(stale, 412, "row_version_mismatch")
    missing = _change_end(client, hod, opp_id, "2028-06-30", if_match={})
    _problem(missing, 428, "if_match_required")
    assert _events(sync_engine, opp_id, END_UPDATED) == []


def test_the_other_outcome_field_is_ignored(client: TestClient, sync_engine: Engine) -> None:
    owner, _, lost_id = _baselined(client, sync_engine)
    body = {"outcome": "lost", "reason": "Lost on price", "contract_end_date": "2028-06-30"}
    resp = _record(client, owner, lost_id, body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["contract_end_date"] is None
    (event,) = _events(sync_engine, lost_id, CLOSED)
    assert event["payload"]["contract_end_date"] is None

    won_owner, _, won_id = _baselined(client, sync_engine)
    body = {"outcome": "won", "contract_end_date": "2028-06-30", "reason": "Signed"}
    resp = _record(client, won_owner, won_id, body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["contract_end_date"] == "2028-06-30"
    (event,) = _events(sync_engine, won_id, CLOSED)
    assert event["payload"]["reason"] is None


def test_leap_day_retention(client: TestClient, sync_engine: Engine) -> None:
    owner, _, opp_id = _baselined(client, sync_engine)
    assert _lost(client, owner, opp_id).status_code == 200
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE opportunities_opportunities SET outcome_recorded_at = :at WHERE id = :o"
            ),
            {"at": datetime(2028, 2, 29, 12, tzinfo=UTC), "o": opp_id},
        )
    assert _get(client, owner, opp_id)["retention_until"] == "2031-02-28"


# --- roles ------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", [REP, ENG, PM, DM])
def test_other_collaborators_get_403_and_no_actions(
    client: TestClient, sync_engine: Engine, role: str
) -> None:
    owner, _, opp_id = _baselined(client, sync_engine)
    other, other_id = _user(client, sync_engine, "Other Person", role)
    _collaborate(client, owner, opp_id, other_id)
    assert _won(client, owner, opp_id).status_code == 200

    seen = _get(client, other, opp_id)
    assert seen["outcome"] == "won"
    assert seen["retention_until"] == "2035-06-30"
    assert not any(seen[flag] for flag in FLAGS)
    _problem(_reopen(client, other, opp_id), 403, "forbidden")
    _problem(_change_end(client, other, opp_id, "2030-01-01"), 403, "forbidden")
    assert _reopen(client, _user(client, sync_engine, "Hod", HOD)[0], opp_id).status_code == 200
    _problem(_lost(client, other, opp_id), 403, "forbidden")


def test_a_sales_representative_owner_may_not_record(
    client: TestClient, sync_engine: Engine
) -> None:
    rep_owner, rep_id = _user(client, sync_engine, "Rex Rep", PSE, REP)
    opp = _create(client, rep_owner)
    # Only the sales representative role left: the owner's grant is withheld.
    rep_only = _reissue(rep_id, REP)
    assert _get(client, rep_only, opp["id"])["can_record_outcome"] is False
    _problem(_lost(client, rep_only, opp["id"]), 403, "forbidden")
    # With presales engineer too, the owner may.
    assert _get(client, rep_owner, opp["id"])["can_record_outcome"] is True
    assert _lost(client, rep_owner, opp["id"]).status_code == 200


def test_a_platform_administrator_may_not_record(client: TestClient, sync_engine: Engine) -> None:
    owner, _, opp_id = _baselined(client, sync_engine)
    admin, _ = _user(client, sync_engine, "Ada Admin", ADMIN)
    seen = _get(client, admin, opp_id)
    assert seen["can_record_outcome"] is False
    _problem(_lost(client, admin, opp_id), 403, "forbidden")
    assert _lost(client, owner, opp_id).status_code == 200
    assert _get(client, admin, opp_id)["can_reopen_outcome"] is True


def test_a_stranger_gets_404(client: TestClient, sync_engine: Engine) -> None:
    _, _, opp_id = _baselined(client, sync_engine)
    stranger, _ = _user(client, sync_engine, "Stranger", PSE)
    _problem(
        client.post(
            f"{BASE}/{opp_id}/outcome",
            headers={**stranger, "If-Match": '"1"'},
            json={"outcome": "lost", "reason": "x"},
        ),
        404,
        "not_found",
    )


# --- status: domain and SQL agree ---------------------------------------------------------


def test_lost_appears_under_the_closed_filter(client: TestClient, sync_engine: Engine) -> None:
    owner, _, opp_id = _baselined(client, sync_engine)
    hod, _ = _user(client, sync_engine, "Hana Delivery Head", HOD)
    assert opp_id not in _filtered(client, hod, "closed")
    assert _lost(client, owner, opp_id).status_code == 200
    assert opp_id in _filtered(client, hod, "closed")
    assert opp_id not in _filtered(client, hod, "baselined")
    assert _list_status(client, owner, opp_id) == "closed"
    assert _list_status(client, owner, opp_id) == derived_status(True, outcome=Outcome.LOST).value
    assert derived_status(True, outcome=Outcome.LOST) is OpportunityStatus.CLOSED


def test_lost_without_a_baseline_and_delivered_lost(
    client: TestClient, sync_engine: Engine
) -> None:
    owner, owner_id = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, owner)
    assert _lost(client, owner, opp["id"]).status_code == 200
    assert _list_status(client, owner, opp["id"]) == derived_status(outcome=Outcome.LOST).value

    # A delivered Opportunity that is then lost reads `closed`; won keeps `delivered`.
    _, _, delivered = _baselined(client, sync_engine)
    (version,) = rows(
        sync_engine,
        "SELECT estimate_version_id FROM estimates_baselines WHERE opportunity_id = :o",
        o=delivered,
    )
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO actuals_deliveries (id, opportunity_id, estimate_version_id, "
                "closed_by) VALUES (gen_random_uuid(), :o, :v, :b)"
            ),
            {"o": delivered, "v": version["estimate_version_id"], "b": owner_id},
        )
    hod, _ = _user(client, sync_engine, "Hana Delivery Head", HOD)
    assert _won(client, hod, delivered).status_code == 200
    assert _get(client, hod, delivered)["status"] == "delivered"
    assert _reopen(client, hod, delivered).status_code == 200
    assert _lost(client, hod, delivered).status_code == 200
    assert _get(client, hod, delivered)["status"] == "closed"


def test_the_check_constraints_hold(client: TestClient, sync_engine: Engine) -> None:
    _, _, opp_id = _baselined(client, sync_engine)
    for values in (
        "outcome = 'drawn', outcome_recorded_at = now()",
        "outcome = 'lost'",  # no recorded-at
        "outcome = 'won', outcome_recorded_at = now()",  # no contract end
        "outcome = 'lost', outcome_recorded_at = now(), contract_end_date = '2030-01-01'",
        "contract_end_date = '2030-01-01'",
    ):
        with pytest.raises(sa.exc.IntegrityError), sync_engine.begin() as conn:
            conn.execute(
                sa.text(f"UPDATE opportunities_opportunities SET {values} WHERE id = :o"),
                {"o": opp_id},
            )
