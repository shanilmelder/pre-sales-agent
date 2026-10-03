"""Opportunities and collaborators (Story 1.7) against a real, migrated Postgres as psa_app.

Covers the spec's I/O matrix: create, create denied, invalid fields, read, hidden (404
identical to an unknown id), add and remove collaborators with the next-request effect,
bad members, non-owners, stale `If-Match`, My vs All, and the trace.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.identity.application.public import OPPORTUNITY_RESOURCE
from app.modules.opportunities.adapters import repository
from app.modules.opportunities.application.public import (
    NewOpportunity,
    OpportunityStatus,
    derived_status,
)
from app.modules.opportunities.domain.opportunity import SUBJECT_TYPE
from tests.auth_tokens import auth_app
from tests.conftest import make_client
from tests.test_health import assert_problem
from tests.test_role_admin import _grant, _signed_in

BASE = "/api/v1/opportunities"
PSE = "presales_engineer"


@pytest.fixture
def client(db_url: str) -> Iterator[TestClient]:
    with make_client(auth_app(db_url)) as c:
        yield c


def _today() -> date:
    return datetime.now(UTC).date()


def _user(
    client: TestClient, engine: Engine, name: str, *roles: str
) -> tuple[dict[str, str], UUID]:
    headers, user_id = _signed_in(client, name)
    if roles:
        _grant(engine, user_id, *roles)
    return headers, user_id


def _body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "customer_name": "[CUSTOMER]",
        "products": ["AutoStore", "Pick station"],
        "industry": "Retail",
        "target_proposal_date": (_today() + timedelta(days=30)).isoformat(),
    }
    body.update(overrides)
    return body


def _create(client: TestClient, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
    resp = client.post(BASE, headers=headers, json=_body(**overrides))
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


def _if_match(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


def _events(engine: Engine, opportunity_id: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                sa.text(
                    "SELECT * FROM platform_trace_events WHERE opportunity_id = :o "
                    "ORDER BY occurred_at, id"
                ),
                {"o": opportunity_id},
            ).mappings()
        ]


def _collect(client: TestClient, headers: dict[str, str], scope: str) -> set[str]:
    ids: set[str] = set()
    page = 1
    while True:
        body = client.get(
            BASE, headers=headers, params={"scope": scope, "page": page, "page_size": 200}
        ).json()
        ids.update(item["id"] for item in body["items"])
        if page * 200 >= body["total"]:
            return ids
        page += 1


def _add(client: TestClient, headers: dict[str, str], opp: dict[str, Any], user_id: UUID) -> Any:
    return client.put(
        f"{BASE}/{opp['id']}/collaborators/{user_id}",
        headers={**headers, **_if_match(opp["row_version"])},
    )


# --- domain (no DB) -------------------------------------------------------------------------


def test_policy_resource_type_is_the_opportunity_subject_type() -> None:
    assert SUBJECT_TYPE == OPPORTUNITY_RESOURCE


def test_derived_status_is_intake() -> None:
    assert derived_status() is OpportunityStatus.INTAKE


def test_new_opportunity_normalises_fields() -> None:
    new = NewOpportunity(
        title="   ",
        customer_name="  [CUSTOMER]  ",
        products=[" AutoStore ", "autostore", "Pick station", "AUTOSTORE"],
        industry=" Retail ",
        target_proposal_date=_today(),
    )
    assert new.title is None
    assert new.customer_name == "[CUSTOMER]"
    assert new.products == ["AutoStore", "Pick station"]
    assert new.industry == "Retail"


# --- create ---------------------------------------------------------------------------------


def test_create_sets_owner_status_and_traces(client: TestClient, sync_engine: Engine) -> None:
    headers, owner_id = _user(client, sync_engine, "Owner Person", PSE)

    resp = client.post(BASE, headers=headers, json=_body())

    assert resp.status_code == 201, resp.text
    opp = resp.json()
    assert UUID(opp["id"]).version == 7
    assert opp["owner"] == {"id": str(owner_id), "name": "Owner Person"}
    assert opp["status"] == "intake"
    assert opp["title"] == "[CUSTOMER]"  # defaults to the customer name
    assert opp["products"] == ["AutoStore", "Pick station"]
    assert opp["collaborators"] == []
    assert opp["row_version"] == 1
    assert opp["can_manage_collaborators"] is True
    assert opp["created_at"].endswith("Z")
    assert resp.headers["ETag"] == '"1"'
    assert resp.headers["Location"] == f"{BASE}/{opp['id']}"

    (event,) = _events(sync_engine, opp["id"])
    assert event["event_type"] == "opportunities.opportunity.created"
    assert event["payload"] == {}
    assert (event["actor_type"], event["actor_id"]) == ("user", str(owner_id))
    assert (event["subject_type"], str(event["subject_id"])) == (
        "opportunities.opportunity",
        opp["id"],
    )
    assert str(event["opportunity_id"]) == opp["id"]


def test_create_keeps_an_explicit_title_and_accepts_today(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers, title="  Phase 2  ", target_proposal_date=_today().isoformat())
    assert opp["title"] == "Phase 2"


@pytest.mark.parametrize(
    "role", ["sales_representative", "head_of_delivery", "platform_administrator", None]
)
def test_create_without_presales_engineer_is_403(
    client: TestClient, sync_engine: Engine, role: str | None
) -> None:
    headers, user_id = _user(client, sync_engine, "Not An Engineer", *([role] if role else []))
    resp = client.post(BASE, headers=headers, json=_body())
    assert resp.status_code == 403, resp.text
    assert_problem(resp.json(), 403, "forbidden")
    with sync_engine.connect() as conn:
        count = conn.execute(
            sa.text("SELECT count(*) FROM opportunities_opportunities WHERE owner_id = :u"),
            {"u": user_id},
        ).scalar_one()
    assert count == 0


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        (
            {"target_proposal_date": (date.today() - timedelta(days=2)).isoformat()},
            "body.target_proposal_date",
        ),
        ({"products": []}, "body.products"),
        ({"products": [f"P{i}" for i in range(21)]}, "body.products"),
        ({"products": ["ok", "   "]}, "body.products"),
        ({"products": ["x" * 101]}, "body.products"),
        ({"customer_name": "x" * 201}, "body.customer_name"),
        ({"customer_name": "  "}, "body.customer_name"),
        ({"title": "x" * 201}, "body.title"),
        ({"industry": "x" * 101}, "body.industry"),
        ({"industry": ""}, "body.industry"),
        ({"target_proposal_date": "not-a-date"}, "body.target_proposal_date"),
        ({"owner_id": str(uuid4())}, "body.owner_id"),
    ],
)
def test_invalid_fields_are_422_naming_the_field(
    client: TestClient, sync_engine: Engine, overrides: dict[str, Any], field: str
) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    resp = client.post(BASE, headers=headers, json=_body(**overrides))
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert_problem(body, 422, "validation_error")
    assert field in body["detail"]


def test_twenty_products_and_duplicates_are_accepted(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    products = [f"P{i}" for i in range(19)] + ["p0"]
    opp = _create(client, headers, products=products, customer_name="x" * 200)
    assert opp["products"] == [f"P{i}" for i in range(19)]


def test_422_detail_format_is_stable(client: TestClient, sync_engine: Engine) -> None:
    """The web client parses this exact format to mark the fields."""
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    past = (_today() - timedelta(days=2)).isoformat()
    resp = client.post(BASE, headers=headers, json=_body(products=[], target_proposal_date=past))
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Invalid fields: body.products, body.target_proposal_date"


def test_missing_required_fields_are_422(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    resp = client.post(BASE, headers=headers, json={})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    for field in ("customer_name", "products", "industry", "target_proposal_date"):
        assert f"body.{field}" in detail


# --- read -----------------------------------------------------------------------------------


@pytest.mark.parametrize("reader", ["owner", "collaborator", "head_of_delivery", "admin"])
def test_readers_get_200(client: TestClient, sync_engine: Engine, reader: str) -> None:
    owner_headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    member_headers, member_id = _user(client, sync_engine, "Member Person", "pm_reviewer")
    opp = _create(client, owner_headers)
    assert _add(client, owner_headers, opp, member_id).status_code == 200
    headers = {
        "owner": owner_headers,
        "collaborator": member_headers,
        "head_of_delivery": _user(client, sync_engine, "HoD", "head_of_delivery")[0],
        "admin": _user(client, sync_engine, "Admin", "platform_administrator")[0],
    }[reader]

    resp = client.get(f"{BASE}/{opp['id']}", headers=headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["customer_name"] == "[CUSTOMER]"
    assert resp.json()["can_manage_collaborators"] is (reader == "owner")
    assert resp.headers["ETag"] == '"2"'


@pytest.mark.parametrize("role", ["presales_engineer", "sales_representative", None])
def test_hidden_opportunity_is_404_identical_to_unknown_id(
    client: TestClient, sync_engine: Engine, role: str | None
) -> None:
    owner_headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, owner_headers)
    other, _ = _user(client, sync_engine, "Outsider", *([role] if role else []))

    hidden = client.get(f"{BASE}/{opp['id']}", headers=other)
    unknown_id = str(uuid4())
    unknown = client.get(f"{BASE}/{unknown_id}", headers=other)

    assert hidden.status_code == unknown.status_code == 404
    assert_problem(hidden.json(), 404, "not_found")
    strip = lambda body: {k: v for k, v in body.items() if k != "instance"}  # noqa: E731
    assert strip(hidden.json()) == strip(unknown.json())
    assert hidden.json()["instance"] == f"{BASE}/{opp['id']}"
    # Writes on a hidden Opportunity are 404 too, before any other check.
    for method in ("put", "delete"):
        resp = client.request(method, f"{BASE}/{opp['id']}/collaborators/{uuid4()}", headers=other)
        assert resp.status_code == 404
        assert strip(resp.json()) == strip(unknown.json())


# --- collaborators --------------------------------------------------------------------------


def test_add_collaborator_applies_on_next_request_and_traces(
    client: TestClient, sync_engine: Engine
) -> None:
    owner_headers, owner_id = _user(client, sync_engine, "Owner Person", PSE)
    member_headers, member_id = _user(client, sync_engine, "Member Person", "pm_reviewer")
    opp = _create(client, owner_headers)
    assert client.get(f"{BASE}/{opp['id']}", headers=member_headers).status_code == 404

    resp = _add(client, owner_headers, opp, member_id)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["collaborators"] == [{"id": str(member_id), "name": "Member Person"}]
    assert body["row_version"] == 2
    assert body["last_changed_by"] == "Owner Person"
    assert resp.headers["ETag"] == '"2"'
    assert client.get(f"{BASE}/{opp['id']}", headers=member_headers).status_code == 200
    assert opp["id"] in _collect(client, member_headers, "mine")

    events = _events(sync_engine, opp["id"])
    assert [e["event_type"] for e in events] == [
        "opportunities.opportunity.created",
        "opportunities.collaborator.added",
    ]
    added = events[1]
    assert added["payload"] == {"user_id": str(member_id)}
    assert added["actor_id"] == str(owner_id)
    assert added["subject_version"] == 2
    assert str(added["subject_id"]) == str(added["opportunity_id"]) == opp["id"]
    assert "[CUSTOMER]" not in str(events)


def test_remove_collaborator_hides_it_on_next_request(
    client: TestClient, sync_engine: Engine
) -> None:
    owner_headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    member_headers, member_id = _user(client, sync_engine, "Member Person", "pm_reviewer")
    opp = _create(client, owner_headers)
    added = _add(client, owner_headers, opp, member_id).json()

    resp = client.delete(
        f"{BASE}/{opp['id']}/collaborators/{member_id}",
        headers={**owner_headers, **_if_match(added["row_version"])},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["collaborators"] == []
    assert resp.json()["row_version"] == 3
    hidden = client.get(f"{BASE}/{opp['id']}", headers=member_headers)
    assert hidden.status_code == 404
    assert_problem(hidden.json(), 404, "not_found")
    assert opp["id"] not in _collect(client, member_headers, "mine")
    removed = _events(sync_engine, opp["id"])[-1]
    assert removed["event_type"] == "opportunities.collaborator.removed"
    assert removed["payload"] == {"user_id": str(member_id)}


def test_add_existing_and_remove_missing_are_noops(client: TestClient, sync_engine: Engine) -> None:
    owner_headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    _, member_id = _user(client, sync_engine, "Member Person", "pm_reviewer")
    _, stranger_id = _user(client, sync_engine, "Stranger", "commercial")
    opp = _create(client, owner_headers)
    added = _add(client, owner_headers, opp, member_id).json()

    again = _add(client, owner_headers, added, member_id)
    missing = client.delete(
        f"{BASE}/{opp['id']}/collaborators/{stranger_id}",
        headers={**owner_headers, **_if_match(added["row_version"])},
    )

    for resp in (again, missing):
        assert resp.status_code == 200, resp.text
        assert resp.json()["row_version"] == 2
        assert resp.json()["collaborators"] == [{"id": str(member_id), "name": "Member Person"}]
    assert len(_events(sync_engine, opp["id"])) == 2


def test_bad_members_are_422(client: TestClient, sync_engine: Engine) -> None:
    owner_headers, owner_id = _user(client, sync_engine, "Owner Person", PSE)
    _, roleless_id = _user(client, sync_engine, "No Role")
    opp = _create(client, owner_headers)

    responses = [
        _add(client, owner_headers, opp, owner_id),
        client.delete(
            f"{BASE}/{opp['id']}/collaborators/{owner_id}",
            headers={**owner_headers, **_if_match(1)},
        ),
        _add(client, owner_headers, opp, roleless_id),
        _add(client, owner_headers, opp, uuid4()),  # no such user
    ]

    for resp in responses:
        assert resp.status_code == 422, resp.text
        assert_problem(resp.json(), 422, "invalid_collaborator")
    assert len(_events(sync_engine, opp["id"])) == 1
    assert client.get(f"{BASE}/{opp['id']}", headers=owner_headers).json()["row_version"] == 1


@pytest.mark.parametrize("who", ["collaborator", "head_of_delivery", "admin"])
def test_non_owner_readers_get_403_on_collaborator_changes(
    client: TestClient, sync_engine: Engine, who: str
) -> None:
    owner_headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    member_headers, member_id = _user(client, sync_engine, "Member Person", PSE)
    _, target_id = _user(client, sync_engine, "Target", "commercial")
    opp = _create(client, owner_headers)
    added = _add(client, owner_headers, opp, member_id).json()
    headers = {
        "collaborator": member_headers,
        "head_of_delivery": _user(client, sync_engine, "HoD", "head_of_delivery")[0],
        "admin": _user(client, sync_engine, "Admin", "platform_administrator")[0],
    }[who]
    assert client.get(f"{BASE}/{opp['id']}", headers=headers).status_code == 200

    version = _if_match(added["row_version"])
    responses = [
        client.put(f"{BASE}/{opp['id']}/collaborators/{target_id}", headers={**headers, **version}),
        client.delete(
            f"{BASE}/{opp['id']}/collaborators/{member_id}", headers={**headers, **version}
        ),
        # Authorization comes before the If-Match check.
        client.put(f"{BASE}/{opp['id']}/collaborators/{target_id}", headers=headers),
    ]
    for resp in responses:
        assert resp.status_code == 403, resp.text
        assert_problem(resp.json(), 403, "forbidden")
    assert len(_events(sync_engine, opp["id"])) == 2


def test_stale_if_match_is_412_and_writes_nothing(client: TestClient, sync_engine: Engine) -> None:
    owner_headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    _, a_id = _user(client, sync_engine, "Member A", "pm_reviewer")
    _, b_id = _user(client, sync_engine, "Member B", "pm_reviewer")
    opp = _create(client, owner_headers)
    assert _add(client, owner_headers, opp, a_id).status_code == 200  # now version 2

    stale_add = _add(client, owner_headers, opp, b_id)
    stale_remove = client.delete(
        f"{BASE}/{opp['id']}/collaborators/{a_id}", headers={**owner_headers, **_if_match(1)}
    )
    stale_noop = _add(client, owner_headers, opp, a_id)
    too_big = client.put(
        f"{BASE}/{opp['id']}/collaborators/{b_id}",
        headers={**owner_headers, "If-Match": f'"{2**31}"'},
    )
    # The int4 maximum: bumping it would overflow, so it is stale too (not a 500).
    int4_max = client.put(
        f"{BASE}/{opp['id']}/collaborators/{b_id}",
        headers={**owner_headers, "If-Match": f'"{2**31 - 1}"'},
    )

    for resp in (stale_add, stale_remove, stale_noop, too_big, int4_max):
        assert resp.status_code == 412, resp.text
        assert_problem(resp.json(), 412, "row_version_mismatch")
    current = client.get(f"{BASE}/{opp['id']}", headers=owner_headers).json()
    assert current["collaborators"] == [{"id": str(a_id), "name": "Member A"}]
    assert current["row_version"] == 2
    assert current["last_changed_by"] == "Owner Person"


def test_membership_already_changed_after_the_bump_is_412_and_rolls_back(
    client: TestClient, sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A collaborator row that appears between the membership read and the write (from a
    path that didn't bump the version) makes the caller's view stale: 412, and the bump is
    rolled back."""
    owner_headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    _, member_id = _user(client, sync_engine, "Member", "pm_reviewer")
    opp = _create(client, owner_headers)
    real_bump = repository.bump_row_version

    async def bump_then_sneak_in_member(uow: Any, opportunity_id: UUID, expected: int) -> Any:
        new_version = await real_bump(uow, opportunity_id, expected)
        with sync_engine.begin() as conn:  # committed, without a version bump
            conn.execute(
                sa.text(
                    "INSERT INTO opportunities_collaborators (opportunity_id, user_id) "
                    "VALUES (:o, :u)"
                ),
                {"o": opportunity_id, "u": member_id},
            )
        return new_version

    monkeypatch.setattr(repository, "bump_row_version", bump_then_sneak_in_member)
    resp = _add(client, owner_headers, opp, member_id)

    assert resp.status_code == 412, resp.text
    assert_problem(resp.json(), 412, "row_version_mismatch")
    with sync_engine.connect() as conn:
        version = conn.execute(
            sa.text("SELECT row_version FROM opportunities_opportunities WHERE id = :o"),
            {"o": opp["id"]},
        ).scalar_one()
    assert version == 1
    assert [e["event_type"] for e in _events(sync_engine, opp["id"])] == [
        "opportunities.opportunity.created"
    ]


def test_owner_whose_roles_were_removed_loses_access(
    client: TestClient, sync_engine: Engine
) -> None:
    owner_headers, owner_id = _user(client, sync_engine, "Owner Person", PSE)
    member_headers, member_id = _user(client, sync_engine, "Member", "pm_reviewer")
    _, other_id = _user(client, sync_engine, "Other", "commercial")
    opp = _create(client, owner_headers)
    added = _add(client, owner_headers, opp, member_id).json()
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text("DELETE FROM identity_user_roles WHERE user_id = ANY(:u)"),
            {"u": [owner_id, member_id]},
        )

    for headers in (owner_headers, member_headers):
        resp = client.get(f"{BASE}/{opp['id']}", headers=headers)
        assert resp.status_code == 404
        assert_problem(resp.json(), 404, "not_found")
        assert opp["id"] not in _collect(client, headers, "mine")
    denied = _add(client, owner_headers, added, other_id)
    assert denied.status_code == 404
    assert_problem(denied.json(), 404, "not_found")
    assert len(_events(sync_engine, opp["id"])) == 2


@pytest.mark.parametrize("method", ["put", "delete"])
def test_write_without_if_match_is_428(
    client: TestClient, sync_engine: Engine, method: str
) -> None:
    owner_headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    _, member_id = _user(client, sync_engine, "Member", "pm_reviewer")
    opp = _create(client, owner_headers)
    resp = client.request(
        method, f"{BASE}/{opp['id']}/collaborators/{member_id}", headers=owner_headers
    )
    assert resp.status_code == 428
    assert_problem(resp.json(), 428, "if_match_required")


# --- lists ----------------------------------------------------------------------------------


def test_my_vs_all(client: TestClient, sync_engine: Engine) -> None:
    a_headers, a_id = _user(client, sync_engine, "User A", PSE)
    b_headers, _ = _user(client, sync_engine, "User B", PSE)
    hod_headers, _ = _user(client, sync_engine, "Head Of Delivery", "head_of_delivery", PSE)
    x = _create(client, a_headers, customer_name="[X]")
    y = _create(client, b_headers, customer_name="[Y]")
    z = _create(client, b_headers, customer_name="[Z]")
    own = _create(client, hod_headers, customer_name="[HOD]")
    assert _add(client, b_headers, y, a_id).status_code == 200

    a_mine, a_all = _collect(client, a_headers, "mine"), _collect(client, a_headers, "all")
    assert a_mine == a_all == {x["id"], y["id"]}
    hod_mine, hod_all = _collect(client, hod_headers, "mine"), _collect(client, hod_headers, "all")
    assert hod_mine == {own["id"]}
    assert {x["id"], y["id"], z["id"], own["id"]} <= hod_all
    with sync_engine.connect() as conn:
        total = conn.execute(sa.text("SELECT count(*) FROM opportunities_opportunities")).scalar()
    assert len(hod_all) == total


def test_list_rows_and_pagination(client: TestClient, sync_engine: Engine) -> None:
    headers, owner_id = _user(client, sync_engine, "Lister Person", PSE)
    created = [_create(client, headers, customer_name=f"[C{i}]") for i in range(3)]

    first = client.get(BASE, headers=headers, params={"scope": "mine", "page_size": 2})
    second = client.get(BASE, headers=headers, params={"scope": "mine", "page_size": 2, "page": 2})

    assert first.status_code == 200, first.text
    page1, page2 = first.json(), second.json()
    assert (page1["page"], page1["page_size"], page1["total"]) == (1, 2, 3)
    # Newest first.
    assert [i["id"] for i in page1["items"] + page2["items"]] == [
        c["id"] for c in reversed(created)
    ]
    row = page1["items"][0]
    assert set(row) == {
        "id",
        "title",
        "customer_name",
        "status",
        "owner",
        "target_proposal_date",
        "created_at",
    }
    assert row["status"] == "intake"
    assert row["owner"] == {"id": str(owner_id), "name": "Lister Person"}
    assert client.get(BASE, headers=headers).json()["page_size"] == 50

    for params in (
        {"page": 0},
        {"page": 1_000_001},
        {"page_size": 0},
        {"page_size": 201},
        {"scope": "everything"},
    ):
        assert client.get(BASE, headers=headers, params=params).status_code == 422, params


def test_empty_lists(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "Newcomer", "commercial")
    for scope in ("mine", "all"):
        body = client.get(BASE, headers=headers, params={"scope": scope}).json()
        assert body["items"] == []
        assert body["total"] == 0


def test_unauthenticated_is_401(client: TestClient) -> None:
    for resp in (client.get(BASE), client.post(BASE, json=_body())):
        assert resp.status_code == 401
        assert_problem(resp.json(), 401, "token_missing")
