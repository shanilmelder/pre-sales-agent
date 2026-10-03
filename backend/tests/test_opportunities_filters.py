"""All Opportunities filters and facets (Story 1.7 Part B) against a real, migrated
Postgres as psa_app.

Covers the spec's I/O matrix: status, owner, product (trimmed, ignoring case), inclusive
date range, combined filters, invalid parameters (422 naming them), visibility (filters
never widen it), facets scoped to what the caller can read, and `scope=mine` ignoring the
filters. The database is shared across tests, so each test uses fresh users and product
names and asserts within them.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.opportunities.application.public import OpportunityFilters
from tests.auth_tokens import auth_app
from tests.conftest import make_client
from tests.test_health import assert_problem
from tests.test_opportunities import BASE, PSE, _add, _create, _user

HOD = "head_of_delivery"
ADMIN = "platform_administrator"


@pytest.fixture
def client(db_url: str) -> Iterator[TestClient]:
    with make_client(auth_app(db_url)) as c:
        yield c


def _day(offset: int) -> str:
    return (datetime.now(UTC).date() + timedelta(days=offset)).isoformat()


def _tag() -> str:
    """A product name no other test uses."""
    return f"P-{uuid4().hex[:10]}"


def _ids(
    client: TestClient, headers: dict[str, str], scope: str = "all", **params: Any
) -> set[str]:
    resp = client.get(BASE, headers=headers, params={"scope": scope, "page_size": 200, **params})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] <= 200, "the test expects one page"
    assert body["total"] == len(body["items"])
    return {item["id"] for item in body["items"]}


# --- application model (no DB) --------------------------------------------------------------


def test_filters_trim_the_product_and_ignore_a_blank_one() -> None:
    assert OpportunityFilters(product="  CRM ").product == "CRM"
    assert OpportunityFilters(product="   ").product is None


def test_filters_reject_a_reversed_range() -> None:
    with pytest.raises(ValueError, match="from"):
        OpportunityFilters(date_from=date(2026, 12, 1), date_to=date(2026, 11, 1))


# --- status ---------------------------------------------------------------------------------


def test_status_intake_is_everything_readable_and_any_other_status_is_nothing(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _ = _user(client, sync_engine, "Owner", PSE)
    mine = {_create(client, headers)["id"], _create(client, headers)["id"]}

    assert _ids(client, headers, status="intake") == _ids(client, headers) == mine
    for status in ("gaps_open", "closed", "baselined"):
        assert _ids(client, headers, status=status) == set()
    # An everything-reader, within this test's own tagged rows.
    tag = _tag()
    tagged = {_create(client, headers, products=[tag])["id"] for _ in range(2)}
    hod, _ = _user(client, sync_engine, "HoD", HOD)
    assert _ids(client, hod, product=tag, status="intake") == _ids(client, hod, product=tag)
    assert _ids(client, hod, product=tag) == tagged
    assert _ids(client, hod, product=tag, status="delivered") == set()


# --- owner ----------------------------------------------------------------------------------


def test_owner_filter_lists_only_that_owners(client: TestClient, sync_engine: Engine) -> None:
    a, a_id = _user(client, sync_engine, "Owner A", PSE)
    b, b_id = _user(client, sync_engine, "Owner B", PSE)
    hod, _ = _user(client, sync_engine, "HoD", HOD)
    a_opps = {_create(client, a)["id"], _create(client, a)["id"]}
    b_opps = {_create(client, b)["id"]}

    assert _ids(client, hod, owner=str(a_id)) == a_opps
    assert _ids(client, hod, owner=str(b_id)) == b_opps
    assert _ids(client, hod, owner=str(uuid4())) == set()  # unknown id: empty page


# --- product --------------------------------------------------------------------------------


def test_product_matches_trimmed_and_ignoring_case(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "Owner", PSE)
    tag = _tag()
    # Stored with a trailing space: the API trims on create, so write it directly.
    crm = _create(client, headers, products=[tag, "Other"])
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE opportunities_opportunities SET products = :p WHERE id = :o"),
            {"p": [f"{tag.upper()} ", "Other"], "o": crm["id"]},
        )
    elsewhere = _create(client, headers, products=[f"{tag}-not-quite"])

    for query in (tag.lower(), tag.upper(), f"  {tag}  "):
        assert _ids(client, headers, product=query) == {crm["id"]}, query
    assert _ids(client, headers, product=f"{tag}-not-quite") == {elsewhere["id"]}
    # No partial matches, and a blank product is no filter.
    assert _ids(client, headers, product=tag[:-2]) == set()
    assert _ids(client, headers, product="   ") == {crm["id"], elsewhere["id"]}


# --- dates ----------------------------------------------------------------------------------


def test_date_range_is_inclusive(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "Owner", PSE)
    by_day = {
        offset: _create(client, headers, target_proposal_date=_day(offset))["id"]
        for offset in (10, 11, 20, 30, 31)
    }

    assert _ids(client, headers, **{"from": _day(11), "to": _day(30)}) == {
        by_day[11],
        by_day[20],
        by_day[30],
    }
    assert _ids(client, headers, **{"from": _day(20)}) == {by_day[20], by_day[30], by_day[31]}
    assert _ids(client, headers, to=_day(11)) == {by_day[10], by_day[11]}
    assert _ids(client, headers, **{"from": _day(20), "to": _day(20)}) == {by_day[20]}


def test_reversed_range_is_422_naming_both(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "Owner", PSE)
    resp = client.get(BASE, headers=headers, params={"from": _day(30), "to": _day(1)})
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert_problem(body, 422, "validation_error")
    assert body["detail"] == "Invalid fields: query.from, query.to"


# --- combined -------------------------------------------------------------------------------


def test_owner_product_and_range_combine_with_and(client: TestClient, sync_engine: Engine) -> None:
    a, a_id = _user(client, sync_engine, "Owner A", PSE)
    b, _ = _user(client, sync_engine, "Owner B", PSE)
    admin, _ = _user(client, sync_engine, "Admin", ADMIN)
    tag = _tag()
    match = _create(client, a, products=[tag], target_proposal_date=_day(15))["id"]
    _create(client, a, products=[tag], target_proposal_date=_day(40))  # out of range
    _create(client, a, products=["Something else"], target_proposal_date=_day(15))
    _create(client, b, products=[tag], target_proposal_date=_day(15))  # other owner

    params = {"owner": str(a_id), "product": tag, "from": _day(10), "to": _day(20)}
    assert _ids(client, admin, **params) == {match}
    assert _ids(client, admin, **params, status="intake") == {match}
    assert _ids(client, admin, **params, status="closed") == set()


# --- invalid --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"status": "open"}, "query.status"),
        ({"status": "Intake"}, "query.status"),
        ({"owner": "not-a-uuid"}, "query.owner"),
        ({"from": "2026-13-01"}, "query.from"),
        ({"to": "tomorrow"}, "query.to"),
        ({"product": "x" * 101}, "query.product"),
    ],
)
def test_invalid_filters_are_422_naming_the_parameter(
    client: TestClient, sync_engine: Engine, params: dict[str, str], field: str
) -> None:
    headers, _ = _user(client, sync_engine, "Owner", PSE)
    resp = client.get(BASE, headers=headers, params=params)
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert_problem(body, 422, "validation_error")
    assert body["detail"] == f"Invalid fields: {field}"


# --- visibility -----------------------------------------------------------------------------


def test_filters_never_widen_visibility(client: TestClient, sync_engine: Engine) -> None:
    a, a_id = _user(client, sync_engine, "User A", PSE)
    b, b_id = _user(client, sync_engine, "User B", PSE)
    tag = _tag()
    hidden = _create(client, b, products=[tag])
    shared = _create(client, b, products=[tag])
    assert _add(client, b, shared, a_id).status_code == 200
    own = _create(client, a, products=[tag])

    assert _ids(client, a, owner=str(b_id)) == {shared["id"]}
    assert _ids(client, a, product=tag) == {shared["id"], own["id"]}
    assert hidden["id"] not in _ids(client, a, owner=str(b_id), product=tag)
    # A user with no roles reads nothing, filtered or not.
    roleless, _ = _user(client, sync_engine, "No Role")
    assert _ids(client, roleless, owner=str(b_id)) == set()


def test_mine_ignores_filters(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "Owner", PSE)
    mine = {_create(client, headers)["id"], _create(client, headers)["id"]}
    params = {
        "status": "closed",
        "owner": str(uuid4()),
        "product": _tag(),
        "from": _day(1),
        "to": _day(2),
    }
    assert _ids(client, headers, scope="mine", **params) == mine
    assert _ids(client, headers, scope="all", **params) == set()


@pytest.mark.parametrize(
    "params",
    [
        {"status": "open"},
        {"owner": "not-a-uuid"},
        {"from": "2026-13-01"},
        {"to": "tomorrow"},
        {"from": "2026-12-01", "to": "2026-11-01"},
        {"product": "x" * 101},
    ],
)
def test_mine_ignores_invalid_filters_too(
    client: TestClient, sync_engine: Engine, params: dict[str, str]
) -> None:
    headers, _ = _user(client, sync_engine, "Owner", PSE)
    mine = {_create(client, headers)["id"]}
    assert _ids(client, headers, scope="mine", **params) == mine


def test_product_length_is_checked_after_trimming(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "Owner", PSE)
    name = _tag().ljust(100, "x")
    opp = _create(client, headers, products=[name])
    assert _ids(client, headers, scope="all", product=f"   {name}   ") == {opp["id"]}


# --- facets ---------------------------------------------------------------------------------


def test_facets_cover_only_readable_opportunities(client: TestClient, sync_engine: Engine) -> None:
    a, a_id = _user(client, sync_engine, "zed Reader", PSE)
    b, b_id = _user(client, sync_engine, "Bea Owner", PSE)
    c, _ = _user(client, sync_engine, "Cy Hidden", PSE)
    tag = _tag()
    # A can read 2 of these 5: one of B's (shared) and their own.
    shared = _create(client, b, products=[f"{tag}-beta", f"{tag}-Alpha "])
    assert _add(client, b, shared, a_id).status_code == 200
    _create(client, a, products=[f"{tag}-alpha", f"{tag}-gamma"])
    _create(client, b, products=[f"{tag}-hidden-b"])
    _create(client, c, products=[f"{tag}-hidden-c1"])
    _create(client, c, products=[f"{tag}-hidden-c2"])

    resp = client.get(f"{BASE}/facets", headers=a)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["owners"] == [
        {"id": str(b_id), "name": "Bea Owner"},
        {"id": str(a_id), "name": "zed Reader"},
    ]
    # De-duplicated and sorted ignoring case; one spelling of "alpha" survives.
    assert [p.lower() for p in body["products"]] == [
        f"{tag}-alpha".lower(),
        f"{tag}-beta".lower(),
        f"{tag}-gamma".lower(),
    ]
    assert all(p == p.strip() for p in body["products"])


def test_facets_for_everything_readers_and_users_without_roles(
    client: TestClient, sync_engine: Engine
) -> None:
    owner, owner_id = _user(client, sync_engine, "Facet Owner", PSE)
    tag = _tag()
    _create(client, owner, products=[tag])
    hod, _ = _user(client, sync_engine, "HoD", HOD)

    body = client.get(f"{BASE}/facets", headers=hod).json()
    assert {"id": str(owner_id), "name": "Facet Owner"} in body["owners"]
    assert tag in body["products"]

    roleless, _ = _user(client, sync_engine, "No Role")
    assert client.get(f"{BASE}/facets", headers=roleless).json() == {
        "owners": [],
        "products": [],
    }
    newcomer, _ = _user(client, sync_engine, "Newcomer", "commercial")
    assert client.get(f"{BASE}/facets", headers=newcomer).json() == {
        "owners": [],
        "products": [],
    }


def test_facets_leave_out_blank_products(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "Blank Products", PSE)
    tag = _tag()
    opp = _create(client, headers, products=[tag])
    # The API never stores a blank product, so write the edge case directly.
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE opportunities_opportunities SET products = :p WHERE id = :o"),
            {"p": ["", "   ", f" {tag} ", "	"], "o": opp["id"]},
        )

    body = client.get(f"{BASE}/facets", headers=headers).json()

    assert body["products"] == [tag]


def test_facets_order_owners_with_the_same_name_by_id(
    client: TestClient, sync_engine: Engine
) -> None:
    name = f"Same {uuid4().hex[:8]}"
    first, first_id = _user(client, sync_engine, name, PSE)
    second, second_id = _user(client, sync_engine, name, PSE)
    reader, reader_id = _user(client, sync_engine, "Shared Reader", PSE)
    for headers in (first, second):
        opp = _create(client, headers)
        assert _add(client, headers, opp, reader_id).status_code == 200

    owners = client.get(f"{BASE}/facets", headers=reader).json()["owners"]

    same = [o["id"] for o in owners if o["name"] == name]
    assert same == sorted([str(first_id), str(second_id)])
    hod, _ = _user(client, sync_engine, "HoD", HOD)
    everyone = [o["id"] for o in client.get(f"{BASE}/facets", headers=hod).json()["owners"]]
    assert [i for i in everyone if i in same] == same


def test_facets_need_sign_in(client: TestClient) -> None:
    resp = client.get(f"{BASE}/facets")
    assert resp.status_code == 401
    assert_problem(resp.json(), 401, "token_missing")


def test_owner_from_facets_round_trips_as_a_filter(client: TestClient, sync_engine: Engine) -> None:
    owner, owner_id = _user(client, sync_engine, "Round Trip", PSE)
    tag = _tag()
    opp = _create(client, owner, products=[f" {tag} "])
    hod, _ = _user(client, sync_engine, "HoD", HOD)
    facets = client.get(f"{BASE}/facets", headers=hod).json()
    chosen_owner = next(o["id"] for o in facets["owners"] if o["id"] == str(owner_id))
    chosen_product = next(p for p in facets["products"] if p.lower() == tag.lower())
    assert _ids(client, hod, owner=chosen_owner, product=chosen_product) == {opp["id"]}
    assert UUID(chosen_owner) == owner_id
