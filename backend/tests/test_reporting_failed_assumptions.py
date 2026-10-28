"""Reports > a group's failed Assumptions (Story 10.4) against a real, migrated Postgres as
psa_app: the list behind a group's "N failed Assumptions" for each grouping, the report's
filters, one item per distinct Assumption, 403 for every role without
`reporting.report.read`, and rows restricted to readable Opportunities.

The database is shared with other tests, so each test tags its Opportunities with a product
of its own and filters on it (`_world` from `test_reporting_api`).
"""

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tests import test_opportunities as opportunity_tests
from tests.test_opportunities import _user
from tests.test_reporting_api import REPORT_READ, World, _hod, _report, _world
from tests.test_reporting_views import SeedLine, catalogue_entry, seed_opportunity
from tests.test_role_admin import _signed_in

client = opportunity_tests.client

URL = "/api/v1/reports/failed-assumptions"


def _list(client: TestClient, headers: dict[str, str], **params: Any) -> dict[str, Any]:
    resp = client.get(URL, headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _ids(body: dict[str, Any]) -> list[str]:
    return [i["assumption_id"] for i in body["items"]]


def _a1(w: World) -> str:
    return str(w.alpha.assumptions["a1"])


def _b1(w: World) -> str:
    return str(w.beta.assumptions["b1"])


def test_an_integration_type_group_lists_its_failed_assumptions(
    client: TestClient, sync_engine: Engine
) -> None:
    w = _world(sync_engine)
    hod = _hod(client, sync_engine)

    ewm = _list(client, hod, product=w.product, group_key=str(w.ewm))

    assert (ewm["group_by"], ewm["group_key"]) == ("integration_type", str(w.ewm))
    (item,) = ewm["items"]
    assert item == {
        "opportunity_id": str(w.alpha.opp_id),
        "opportunity_title": f"Alpha {w.product[5:]}",
        "line_label": "L1",
        "kind": "condition",
        "position": 1,
        "label": "A1",
        "wording": "Wording",
        "amount_hours": None,
        "assumption_id": _a1(w),
        "assumption_version": 2,
        "actual_id": str(w.alpha.actual_ids[0]),
    }
    crm = _list(client, hod, product=w.product, group_key=str(w.crm))
    (contingency,) = crm["items"]
    assert (contingency["kind"], contingency["amount_hours"], contingency["label"]) == (
        "contingency",
        4.0,
        "A1",
    )
    assert contingency["opportunity_id"] == str(w.beta.opp_id)
    assert _list(client, hod, product=w.product, group_key=str(w.sso))["items"] == []
    assert _list(client, hod, product=w.product, group_key="none")["items"] == []
    assert _list(client, hod, product=w.product, group_key=str(uuid4()))["items"] == []


def test_the_list_matches_the_groups_count(client: TestClient, sync_engine: Engine) -> None:
    """Grouped by product, the shared product's group counts "2 failed Assumptions": the list
    has those 2, ordered by Opportunity."""
    w = _world(sync_engine)
    hod = _hod(client, sync_engine)
    report = _report(client, hod, product=w.product, group_by="product")
    group = next(g for g in report["groups"] if g["key"] == w.product)
    assert group["failed_assumptions"] == 2

    body = _list(client, hod, product=w.product, group_by="product", group_key=w.product)

    assert _ids(body) == [_a1(w), _b1(w)]


def test_each_grouping(client: TestClient, sync_engine: Engine) -> None:
    w = _world(sync_engine)
    hod = _hod(client, sync_engine)

    def ids(group_by: str, key: str) -> list[str]:
        return _ids(_list(client, hod, product=w.product, group_by=group_by, group_key=key))

    assert ids("opportunity", str(w.alpha.opp_id)) == [_a1(w)]
    assert ids("opportunity", str(w.beta.opp_id)) == [_b1(w)]
    assert ids("product", w.other_product) == [_a1(w)]
    assert ids("work_package", "none") == [_a1(w), _b1(w)]
    assert ids("work_package", str(w.wp)) == []
    assert ids("cause", "integration_complexity") == [_a1(w)]
    assert ids("cause", "scope_change") == [_b1(w)]
    assert ids("cause", "none") == []


def test_the_reports_filters_apply(client: TestClient, sync_engine: Engine) -> None:
    w = _world(sync_engine)
    hod = _hod(client, sync_engine)

    def ids(**params: Any) -> list[str]:
        return _ids(
            _list(client, hod, product=w.product, group_by="product", group_key=w.product, **params)
        )

    assert ids(integration_type_id=str(w.crm)) == [_b1(w)]
    assert ids(cause="integration_complexity") == [_a1(w)]
    assert ids(closed_to="2000-01-01") == []
    body = _list(
        client,
        hod,
        product=w.product,
        group_key=w.product,
        group_by="product",
        integration_type_id=str(w.crm),
    )
    assert body["filters"]["integration_type_id"] == str(w.crm)


def test_an_assumption_named_by_two_actuals_is_listed_once(
    client: TestClient, sync_engine: Engine
) -> None:
    tag = uuid4().hex[:8]
    it = catalogue_entry(sync_engine, f"Twice {tag}")
    s = seed_opportunity(
        sync_engine,
        title=f"Twice {tag}",
        products=[f"Twice-{tag}"],
        assumptions=[("a1", "condition"), ("a2", "condition")],
        lines=[
            SeedLine("10.0", "14.0", "estimation_error", [it], failed=["a2", "a1"]),
            SeedLine("10.0", "15.0", "estimation_error", [it], failed=["a1"]),
        ],
    )
    hod = _hod(client, sync_engine)
    report = _report(client, hod, product=f"Twice-{tag}")
    assert report["groups"][0]["failed_assumptions"] == 2

    body = _list(client, hod, product=f"Twice-{tag}", group_key=str(it))

    assert _ids(body) == [str(s.assumptions["a1"]), str(s.assumptions["a2"])]  # by A{n}
    assert [i["line_label"] for i in body["items"]] == ["L1", "L1"]  # the first line naming it


def test_a_missing_group_key_is_422(client: TestClient, sync_engine: Engine) -> None:
    resp = client.get(URL, headers=_hod(client, sync_engine))
    assert resp.status_code == 422, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")


# --- access ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role", ["delivery_manager", "presales_engineer", "pm_reviewer", "sales_representative"]
)
def test_other_roles_are_403(client: TestClient, sync_engine: Engine, role: str) -> None:
    headers, _ = _user(client, sync_engine, "No Reports", role)
    resp = client.get(URL, headers=headers, params={"group_key": "none"})
    assert resp.status_code == 403, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["code"] == "forbidden"


def test_rows_are_restricted_to_readable_opportunities(
    client: TestClient, sync_engine: Engine
) -> None:
    """Visibility is applied before the group is picked: a user holding the permission but
    not `opportunities.opportunity.read` lists only their own Opportunities' Assumptions."""
    headers, user_id = _signed_in(
        client, "Pat Partial", "presales_engineer", permissions=[REPORT_READ]
    )
    w = _world(sync_engine)  # someone else's
    assert _list(client, headers, group_by="product", group_key=w.product)["items"] == []

    own = seed_opportunity(
        sync_engine,
        title=f"Own {w.product}",
        products=[w.product],
        owner_id=user_id,
        assumptions=[("o1", "condition")],
        lines=[SeedLine("10.0", "12.0", "estimation_error", [w.ewm], failed=["o1"])],
    )
    body = _list(client, headers, group_by="product", group_key=w.product)
    assert _ids(body) == [str(own.assumptions["o1"])]
    assert _ids(_list(client, headers, group_key=str(w.ewm))) == [str(own.assumptions["o1"])]
