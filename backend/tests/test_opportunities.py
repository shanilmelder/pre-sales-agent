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
from tests.test_role_admin import _reissue, _signed_in

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
    """A signed-in user whose token carries `roles` and their Auth0 permissions. `engine`
    is unused (roles come from the token) but kept for the many callers."""
    return _signed_in(client, name, *roles)


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


def test_derived_status_is_intake_until_a_baseline() -> None:
    assert derived_status() is OpportunityStatus.INTAKE
    assert derived_status(False) is OpportunityStatus.INTAKE
    assert derived_status(True) is OpportunityStatus.BASELINED
    # Story 10.1: closing delivery wins.
    assert derived_status(True, delivered=True) is OpportunityStatus.DELIVERED


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
    assert event["payload"] == {"from_import": False}
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
    assert added["payload"] == {"user_id": str(member_id), "role": "collaborator"}
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
    assert removed["payload"] == {"user_id": str(member_id), "role": "collaborator"}


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
    opp = _create(client, owner_headers)

    responses = [
        _add(client, owner_headers, opp, owner_id),
        client.delete(
            f"{BASE}/{opp['id']}/collaborators/{owner_id}",
            headers={**owner_headers, **_if_match(1)},
        ),
        _add(client, owner_headers, opp, uuid4()),  # no such user
    ]

    for resp in responses:
        assert resp.status_code == 422, resp.text
        assert_problem(resp.json(), 422, "invalid_collaborator")
    assert len(_events(sync_engine, opp["id"])) == 1
    assert client.get(f"{BASE}/{opp['id']}", headers=owner_headers).json()["row_version"] == 1


def test_owner_finds_and_adds_a_user_with_no_roles(client: TestClient, sync_engine: Engine) -> None:
    """Any provisioned user can be found and added; roles decide what they can then do."""
    owner_headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    tag = uuid4().hex[:10]
    _, roleless_id = _user(client, sync_engine, f"No Role {tag}")
    opp = _create(client, owner_headers)

    found = client.get("/api/v1/users/search", headers=owner_headers, params={"q": tag})
    assert [u["id"] for u in found.json()["items"]] == [str(roleless_id)]
    resp = _add(client, owner_headers, opp, roleless_id)

    assert resp.status_code == 200, resp.text
    assert [c["id"] for c in resp.json()["collaborators"]] == [str(roleless_id)]


def test_role_without_create_permission_is_403_but_owner_access_stays(
    client: TestClient, sync_engine: Engine
) -> None:
    owner_headers, owner_id = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, owner_headers)
    no_permissions = _reissue(owner_id, PSE, permissions=[])

    denied = client.post(BASE, headers=no_permissions, json=_body())
    assert denied.status_code == 403
    assert_problem(denied.json(), 403, "forbidden")
    assert client.get(f"{BASE}/{opp['id']}", headers=no_permissions).status_code == 200


def test_create_permission_decides_not_the_role(client: TestClient, sync_engine: Engine) -> None:
    """Auth0 may give any role the create permission. (Owner access still needs a role.)"""
    headers, _ = _signed_in(
        client, "Commercial Creator", "commercial", permissions=["opportunities.opportunity.create"]
    )
    assert client.post(BASE, headers=headers, json=_body()).status_code == 201


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
    # Their roles are removed in Auth0; their next tokens carry none.
    owner_headers, member_headers = _reissue(owner_id), _reissue(member_id)

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
        "open_gaps",
        "open_conflicts",
        "blocker_count",
        "estimate",
    }
    assert (row["open_gaps"], row["open_conflicts"], row["estimate"]) == (0, 0, None)
    assert row["blocker_count"] == 0
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


# --- list row counts and Estimate (Opportunity list redesign) ------------------------------


def _gap(engine: Engine, opportunity_id: str, status: str = "open") -> None:
    dismissed = status == "dismissed"
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO gaps_gaps (id, opportunity_id, title, category, trigger, "
                "why_it_matters, impact, impact_basis, origin, status, row_version, "
                "dismiss_reason_kind, dismissed_by, dismissed_at) VALUES (:id, :o, 'A gap', "
                "'other', CAST('{}' AS jsonb), 'Why', 'low', 'Basis', 'detected', :s, 1, "
                ":kind, :by, :at)"
            ),
            {
                "id": uuid4(),
                "o": opportunity_id,
                "s": status,
                "kind": "not_relevant" if dismissed else None,
                "by": uuid4() if dismissed else None,
                "at": datetime.now(UTC) if dismissed else None,
            },
        )


def _conflict(engine: Engine, opportunity_id: str, status: str = "open") -> None:
    escalated = status == "escalated"
    resolved = status == "resolved"
    now = datetime.now(UTC)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO conflicts_conflicts (id, opportunity_id, run_id, type, severity, "
                "status, detected_by, fingerprint, summary, detection_pass, resolved_at, "
                "resolution_reason, escalated_to, escalated_by, escalated_at, "
                "escalation_reason) VALUES (:id, :o, :run, 'effort', 'high', :s, 'rule', "
                ":fp, 'A conflict', 1, :rat, :reason, :to, :by, :eat, :ereason)"
            ),
            {
                "id": uuid4(),
                "o": opportunity_id,
                "run": uuid4(),
                "s": status,
                "fp": str(uuid4()),
                "rat": now if resolved else None,
                "reason": "Resolved" if resolved else None,
                "to": uuid4() if escalated else None,
                "by": uuid4() if escalated else None,
                "eat": now if escalated else None,
                "ereason": "Needs a reviewer" if escalated else None,
            },
        )


def _estimate_version(
    engine: Engine,
    opportunity_id: str,
    version: int,
    *,
    status: str = "draft",
    lines: tuple[float, ...] = (),
    contingencies: tuple[tuple[float, int | None], ...] = (),
) -> None:
    """An Estimate Version with lines of these hours, and Contingencies of these hours
    linked to the line at that index (or to none)."""
    version_id = uuid4()
    line_ids = [uuid4() for _ in lines]
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO estimates_estimate_versions (id, opportunity_id, version, status, "
                "template_version, uncovered_count, dropped_count, row_version, submitted_at) "
                "VALUES (:id, :o, :v, :s, 'v1', 0, 0, 1, :at)"
            ),
            {
                "id": version_id,
                "o": opportunity_id,
                "v": version,
                "s": status,
                "at": datetime.now(UTC) if status == "submitted" else None,
            },
        )
        for position, (line_id, hours) in enumerate(zip(line_ids, lines, strict=True), 1):
            conn.execute(
                sa.text(
                    "INSERT INTO estimates_estimate_lines (id, version_id, position, section, "
                    "title, effort_hours, role_mix, basis) VALUES (:id, :v, :p, 'functional', "
                    "'A line', :h, CAST(:mix AS jsonb), 'Basis')"
                ),
                {
                    "id": line_id,
                    "v": version_id,
                    "p": position,
                    "h": hours,
                    "mix": '{"engineer": 70, "project_manager": 10, "qa": 20}',
                },
            )
        for position, (hours, index) in enumerate(contingencies, 1):
            conn.execute(
                sa.text(
                    "INSERT INTO estimates_assumptions (id, version_id, position, kind, "
                    "wording, amount_hours, line_id, origin_ref, row_version) VALUES (:id, "
                    ":v, :p, 'contingency', 'A contingency', :h, :line, "
                    "CAST(:ref AS jsonb), 1)"
                ),
                {
                    "id": uuid4(),
                    "v": version_id,
                    "p": position,
                    "h": hours,
                    "line": None if index is None else line_ids[index],
                    "ref": f'{{"kind": "gap", "id": "{uuid4()}", "row_version": 1}}',
                },
            )


def _row(client: TestClient, headers: dict[str, str], opportunity_id: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for scope in ("mine", "all"):
        items = client.get(BASE, headers=headers, params={"scope": scope}).json()["items"]
        rows.extend(i for i in items if i["id"] == opportunity_id)
    mine, everything = rows  # both lists return the row, and the same one
    assert mine == everything
    return mine


def test_list_row_counts_open_gaps_and_blocking_conflicts(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _ = _user(client, sync_engine, "Counter Person", PSE)
    opp = _create(client, headers)
    other = _create(client, headers)
    for status in ("open", "open", "open", "dismissed"):
        _gap(sync_engine, opp["id"], status)
    for status in ("open", "escalated", "resolved"):
        _conflict(sync_engine, opp["id"], status)
    _gap(sync_engine, other["id"])

    row = _row(client, headers, opp["id"])

    assert (row["open_gaps"], row["open_conflicts"]) == (3, 2)
    assert (_row(client, headers, other["id"])["open_gaps"]) == 1


def test_list_row_estimate_is_the_draft_total_with_contingency(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _ = _user(client, sync_engine, "Estimate Person", PSE)
    opp = _create(client, headers)
    _estimate_version(sync_engine, opp["id"], 2, status="superseded", lines=(999.0,))
    # Lines total 270 h; 5 h of Contingency on a line plus 3 h unallocated.
    _estimate_version(
        sync_engine, opp["id"], 3, lines=(200.0, 70.0), contingencies=((5.0, 0), (3.0, None))
    )

    row = _row(client, headers, opp["id"])

    assert row["estimate"] == {
        "version": 3,
        "status": "draft",
        "total_hours": 278.0,
        "is_baseline": False,
    }
    estimate = client.get(f"{BASE}/{opp['id']}/estimate", headers=headers)
    assert estimate.status_code == 200, estimate.text
    assert estimate.json()["version"]["totals"]["total_hours"] == 278.0


def test_list_row_estimate_is_null_without_a_draft(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "No Draft Person", PSE)
    opp = _create(client, headers)
    _estimate_version(sync_engine, opp["id"], 1, status="superseded", lines=(10.0,))

    assert _row(client, headers, opp["id"])["estimate"] is None


def _list_queries(client: TestClient, headers: dict[str, str]) -> tuple[int, int]:
    engine = client.app.state.engine.sync_engine  # type: ignore[attr-defined]
    statements: list[str] = []

    def count(*args: Any) -> None:
        statements.append(args[2])

    sa.event.listen(engine, "before_cursor_execute", count)
    try:
        body = client.get(BASE, headers=headers, params={"scope": "mine"}).json()
    finally:
        sa.event.remove(engine, "before_cursor_execute", count)
    return len(body["items"]), len(statements)


def test_list_rows_read_counts_and_estimates_in_batches(
    client: TestClient, sync_engine: Engine
) -> None:
    def arrange(headers: dict[str, str], n: int) -> None:
        for _ in range(n):
            opp = _create(client, headers)
            _gap(sync_engine, opp["id"])
            _conflict(sync_engine, opp["id"])
            _estimate_version(sync_engine, opp["id"], 1, lines=(10.0,), contingencies=((1.0, 0),))

    one, _ = _user(client, sync_engine, "One Row", PSE)
    many, _ = _user(client, sync_engine, "Many Rows", PSE)
    arrange(one, 1)
    arrange(many, 25)
    _list_queries(client, one)  # warm up (first-request work, if any)
    _list_queries(client, many)

    rows_one, queries_one = _list_queries(client, one)
    rows_many, queries_many = _list_queries(client, many)

    assert (rows_one, rows_many) == (1, 25)
    assert queries_one == queries_many


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
