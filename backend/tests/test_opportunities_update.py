"""Owner edits the title and target proposal date (Story 1.8 Part B), against a real,
migrated Postgres as psa_app.

Covers the spec's I/O matrix: title, both fields, blank title, too long, past date, past
date kept, no change, stale and missing `If-Match`, non-owners, non-readers, and an edit
followed by a collaborator change.
"""

from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.opportunities.application.public import OpportunityChanges
from tests.auth_tokens import auth_app
from tests.conftest import make_client
from tests.test_health import assert_problem
from tests.test_opportunities import BASE, PSE, _add, _create, _events, _if_match, _today, _user

UPDATED = "opportunities.opportunity.updated"


@pytest.fixture
def client(db_url: str) -> Iterator[TestClient]:
    with make_client(auth_app(db_url)) as c:
        yield c


def _patch(
    client: TestClient,
    headers: dict[str, str],
    opp: dict[str, Any],
    version: int | None,
    **body: Any,
) -> Any:
    extra = {} if version is None else _if_match(version)
    return client.patch(f"{BASE}/{opp['id']}", headers={**headers, **extra}, json=body)


def _updates(engine: Engine, opportunity_id: str) -> list[dict[str, Any]]:
    return [e for e in _events(engine, opportunity_id) if e["event_type"] == UPDATED]


def _stored(engine: Engine, opportunity_id: str) -> dict[str, Any]:
    with engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT title, target_proposal_date, row_version "
                "FROM opportunities_opportunities WHERE id = :o"
            ),
            {"o": opportunity_id},
        ).mappings()
        return dict(row.one())


# --- model (no DB) --------------------------------------------------------------------------


def test_changes_model_trims_and_allows_blank() -> None:
    assert OpportunityChanges(title="  New  ").title == "New"
    assert OpportunityChanges(title="   ").title == ""
    assert OpportunityChanges().title is None
    assert OpportunityChanges(title="x" * 200).title == "x" * 200
    with pytest.raises(ValueError):
        OpportunityChanges(title="x" * 201)
    with pytest.raises(ValueError):
        OpportunityChanges.model_validate({"customer_name": "[CUSTOMER]"})


# --- changes --------------------------------------------------------------------------------


def test_owner_edits_title(client: TestClient, sync_engine: Engine) -> None:
    headers, owner_id = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)

    resp = _patch(client, headers, opp, 1, title="  New title  ")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "New title"
    assert body["target_proposal_date"] == opp["target_proposal_date"]
    assert body["row_version"] == 2
    assert body["can_edit"] is True
    assert body["last_changed_by"] == "Owner Person"
    assert resp.headers["ETag"] == '"2"'
    # A reload keeps it.
    assert client.get(f"{BASE}/{opp['id']}", headers=headers).json()["title"] == "New title"

    (event,) = _updates(sync_engine, opp["id"])
    assert event["payload"] == {"fields": ["title"]}
    assert (event["actor_type"], event["actor_id"]) == ("user", str(owner_id))
    assert event["subject_version"] == 2
    assert str(event["subject_id"]) == str(event["opportunity_id"]) == opp["id"]
    assert "New title" not in str(_events(sync_engine, opp["id"]))


def test_owner_edits_both_fields_in_one_bump(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)
    new_date = (_today() + timedelta(days=60)).isoformat()

    resp = _patch(client, headers, opp, 1, title="Phase 2", target_proposal_date=new_date)

    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "Phase 2"
    assert resp.json()["target_proposal_date"] == new_date
    assert resp.json()["row_version"] == 2
    (event,) = _updates(sync_engine, opp["id"])
    assert event["payload"] == {"fields": ["title", "target_proposal_date"]}
    assert new_date not in str(event)


def test_today_is_accepted(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)
    resp = _patch(client, headers, opp, 1, target_proposal_date=_today().isoformat())
    assert resp.status_code == 200, resp.text
    (event,) = _updates(sync_engine, opp["id"])
    assert event["payload"] == {"fields": ["target_proposal_date"]}


def test_blank_title_falls_back_to_the_customer_name(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers, title="Custom")

    blanked = _patch(client, headers, opp, 1, title="   ")

    assert blanked.status_code == 200, blanked.text
    assert blanked.json()["title"] == "[CUSTOMER]"
    assert blanked.json()["row_version"] == 2
    assert [e["payload"] for e in _updates(sync_engine, opp["id"])] == [{"fields": ["title"]}]

    # Already the customer name: a blank title changes nothing.
    again = _patch(client, headers, opp, 2, title="")
    assert again.status_code == 200, again.text
    assert again.json()["row_version"] == 2
    assert len(_updates(sync_engine, opp["id"])) == 1


def test_past_date_kept_while_the_title_changes(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)
    past = (_today() - timedelta(days=10)).isoformat()
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE opportunities_opportunities SET target_proposal_date = :d WHERE id = :o"
            ),
            {"d": past, "o": opp["id"]},
        )

    resp = _patch(client, headers, opp, 1, title="Renamed", target_proposal_date=past)

    assert resp.status_code == 200, resp.text
    assert resp.json()["target_proposal_date"] == past
    assert resp.json()["title"] == "Renamed"
    (event,) = _updates(sync_engine, opp["id"])
    assert event["payload"] == {"fields": ["title"]}


# --- invalid --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ({"title": "x" * 201}, "body.title"),
        ({"target_proposal_date": "not-a-date"}, "body.target_proposal_date"),
        ({"customer_name": "[OTHER]"}, "body.customer_name"),
        ({"products": ["A"]}, "body.products"),
        ({"industry": "Food"}, "body.industry"),
    ],
)
def test_invalid_or_unknown_fields_are_422(
    client: TestClient, sync_engine: Engine, body: dict[str, Any], detail: str
) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)
    resp = _patch(client, headers, opp, 1, **body)
    assert resp.status_code == 422, resp.text
    assert_problem(resp.json(), 422, "validation_error")
    assert detail in resp.json()["detail"]
    assert _stored(sync_engine, opp["id"])["row_version"] == 1
    assert _updates(sync_engine, opp["id"]) == []


def test_past_date_is_422_with_a_readable_reason(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)
    yesterday = (_today() - timedelta(days=1)).isoformat()

    resp = _patch(client, headers, opp, 1, title="Renamed", target_proposal_date=yesterday)

    assert resp.status_code == 422, resp.text
    assert_problem(resp.json(), 422, "validation_error")
    assert resp.json()["detail"] == "The target proposal date can't be in the past."
    stored = _stored(sync_engine, opp["id"])
    assert (stored["title"], stored["row_version"]) == ("[CUSTOMER]", 1)
    assert _updates(sync_engine, opp["id"]) == []


def test_field_rules_come_before_the_if_match_check(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)
    yesterday = (_today() - timedelta(days=1)).isoformat()
    resp = _patch(client, headers, opp, 7, target_proposal_date=yesterday)
    assert resp.status_code == 422, resp.text


# --- no change, concurrency -----------------------------------------------------------------


@pytest.mark.parametrize("body", [{}, {"title": "[CUSTOMER]"}, "same_date", "both_same"])
def test_no_change_writes_nothing(client: TestClient, sync_engine: Engine, body: Any) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)
    if body == "same_date":
        body = {"target_proposal_date": opp["target_proposal_date"]}
    elif body == "both_same":
        body = {"title": " [CUSTOMER] ", "target_proposal_date": opp["target_proposal_date"]}

    resp = _patch(client, headers, opp, 1, **body)

    assert resp.status_code == 200, resp.text
    assert resp.json()["row_version"] == 1
    assert resp.headers["ETag"] == '"1"'
    assert len(_events(sync_engine, opp["id"])) == 1
    # A stale view is still told to reload.
    stale = _patch(client, headers, opp, 0, **body)
    assert stale.status_code == 412, stale.text
    assert_problem(stale.json(), 412, "row_version_mismatch")


def test_stale_if_match_is_412_and_writes_nothing(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)
    assert _patch(client, headers, opp, 1, title="First").status_code == 200

    responses = [
        _patch(client, headers, opp, 1, title="Second"),
        _patch(client, headers, opp, 2**31 - 1, title="Second"),
        _patch(client, headers, opp, 2**31, title="Second"),
    ]

    for resp in responses:
        assert resp.status_code == 412, resp.text
        assert_problem(resp.json(), 412, "row_version_mismatch")
    stored = _stored(sync_engine, opp["id"])
    assert (stored["title"], stored["row_version"]) == ("First", 2)
    assert len(_updates(sync_engine, opp["id"])) == 1


def test_missing_if_match_is_428(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)
    resp = _patch(client, headers, opp, None, title="New")
    assert resp.status_code == 428, resp.text
    assert_problem(resp.json(), 428, "if_match_required")
    assert _stored(sync_engine, opp["id"])["row_version"] == 1


# --- access ---------------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["collaborator", "head_of_delivery", "admin"])
def test_non_owner_readers_get_403_and_no_edit_controls(
    client: TestClient, sync_engine: Engine, who: str
) -> None:
    owner_headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    member_headers, member_id = _user(client, sync_engine, "Member Person", PSE)
    opp = _create(client, owner_headers)
    added = _add(client, owner_headers, opp, member_id).json()
    headers = {
        "collaborator": member_headers,
        "head_of_delivery": _user(client, sync_engine, "HoD", "head_of_delivery")[0],
        "admin": _user(client, sync_engine, "Admin", "platform_administrator")[0],
    }[who]
    assert client.get(f"{BASE}/{opp['id']}", headers=headers).json()["can_edit"] is False

    responses = [
        _patch(client, headers, opp, added["row_version"], title="Hijacked"),
        # Authorization comes before field rules and the If-Match check.
        _patch(client, headers, opp, None, title="Hijacked"),
        _patch(client, headers, opp, 1, target_proposal_date="2000-01-01"),
    ]
    for resp in responses:
        assert resp.status_code == 403, resp.text
        assert_problem(resp.json(), 403, "forbidden")
    assert _stored(sync_engine, opp["id"])["title"] == "[CUSTOMER]"
    assert _updates(sync_engine, opp["id"]) == []


@pytest.mark.parametrize("role", ["presales_engineer", "sales_representative", None])
def test_non_reader_and_unknown_id_get_the_get_404(
    client: TestClient, sync_engine: Engine, role: str | None
) -> None:
    owner_headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, owner_headers)
    other, _ = _user(client, sync_engine, "Outsider", *([role] if role else []))

    hidden = _patch(client, other, opp, 1, title="Hijacked")
    unknown = _patch(client, other, {"id": str(uuid4())}, 1, title="Hijacked")
    got = client.get(f"{BASE}/{uuid4()}", headers=other)

    strip = lambda body: {k: v for k, v in body.items() if k != "instance"}  # noqa: E731
    for resp in (hidden, unknown):
        assert resp.status_code == 404, resp.text
        assert_problem(resp.json(), 404, "not_found")
        assert strip(resp.json()) == strip(got.json())
    assert _stored(sync_engine, opp["id"])["title"] == "[CUSTOMER]"


def test_owner_sees_can_edit(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)
    assert opp["can_edit"] is True
    assert client.get(f"{BASE}/{opp['id']}", headers=headers).json()["can_edit"] is True


# --- then share -----------------------------------------------------------------------------


def test_edit_then_share_uses_the_returned_version(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    _, member_id = _user(client, sync_engine, "Member Person", "pm_reviewer")
    opp = _create(client, headers)

    edited = _patch(client, headers, opp, 1, title="Renamed")
    assert edited.status_code == 200, edited.text
    shared = _add(client, headers, edited.json(), member_id)

    assert shared.status_code == 200, shared.text
    assert shared.json()["row_version"] == 3
    assert shared.json()["title"] == "Renamed"
    assert [e["event_type"] for e in _events(sync_engine, opp["id"])] == [
        "opportunities.opportunity.created",
        UPDATED,
        "opportunities.collaborator.added",
    ]
