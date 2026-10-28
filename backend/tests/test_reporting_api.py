"""Reports > Estimate vs actual (Story 10.3) against a real, migrated Postgres as psa_app:
every row of the I/O matrix, each grouping and filter, the milestone toggle, 403 for every
role without `reporting.report.read`, rows restricted to readable Opportunities, the empty
state, and the 500 ms P95 on 200 delivered Opportunities.

The database is shared with other tests, so each test tags its Opportunities with a product
of its own and filters on it.
"""

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.actuals.domain.actuals import MINUS
from tests import test_opportunities as opportunity_tests
from tests.test_opportunities import _user
from tests.test_reporting_views import Seeded, SeedLine, catalogue_entry, seed_opportunity
from tests.test_role_admin import _signed_in

client = opportunity_tests.client

URL = "/api/v1/reports/estimate-vs-actual"
HOD = "head_of_delivery"
ADMIN = "platform_administrator"
REPORT_READ = "reporting.report.read"


@dataclass
class World:
    product: str
    other_product: str
    ewm: UUID
    sso: UUID
    crm: UUID
    mig: UUID
    wp: UUID
    alpha: Seeded
    beta: Seeded


def _world(engine: Engine) -> World:
    """Alpha (closed, products P and Q): SAP EWM 420 -> 468 h (a failed Condition), SSO 96 ->
    88 h, a line tagged CRM and Migration 100 -> 110 h, Unplanned work 12 h (Work Package
    only) and a milestone on SAP EWM 50 -> 20 h. Beta (open, product P): CRM 200 -> 250 h (a
    failed Contingency)."""
    tag = uuid4().hex[:8]
    product, other = f"Prod-{tag}", f"Other-{tag}"
    ewm = catalogue_entry(engine, f"SAP EWM {tag}")
    sso = catalogue_entry(engine, f"SSO and identity {tag}")
    crm = catalogue_entry(engine, f"CRM data migration {tag}")
    mig = catalogue_entry(engine, f"Migration tooling {tag}")
    wp = catalogue_entry(engine, f"Go-live support {tag}", kind="work_package")
    alpha = seed_opportunity(
        engine,
        title=f"Alpha {tag}",
        products=[product, other],
        assumptions=[("a1", "condition")],
        lines=[
            SeedLine("420.0", "468.0", "integration_complexity", [ewm], failed=["a1"]),
            SeedLine("96.0", "88.0", "estimation_error", [sso]),
            SeedLine("100.0", "110.0", "scope_change", [crm, mig]),
            SeedLine(None, "12.0", "scope_change", work_package=wp),
            SeedLine("50.0", "20.0", None, [ewm], kind="milestone"),
        ],
    )
    beta = seed_opportunity(
        engine,
        title=f"Beta {tag}",
        products=[product],
        closed=False,
        assumptions=[("b1", "contingency")],
        lines=[SeedLine("200.0", "250.0", "scope_change", [crm], failed=["b1"])],
    )
    return World(product, other, ewm, sso, crm, mig, wp, alpha, beta)


def _hod(client: TestClient, engine: Engine) -> dict[str, str]:
    headers, _ = _user(client, engine, "Hana Head", HOD)
    return headers


def _report(client: TestClient, headers: dict[str, str], **params: Any) -> dict[str, Any]:
    resp = client.get(URL, headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _by_key(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {g["key"]: g for g in report["groups"]}


def _figures(group: dict[str, Any]) -> tuple[float, float, str, str]:
    return (
        group["estimate_hours"],
        group["actual_hours"],
        group["variance"]["display"],
        group["variance"]["tone"],
    )


# --- the matrix -----------------------------------------------------------------------------


def test_grouped_by_integration_type(client: TestClient, sync_engine: Engine) -> None:
    w = _world(sync_engine)
    report = _report(client, _hod(client, sync_engine), product=w.product)
    assert report["group_by"] == "integration_type"
    assert report["has_actuals"] is True
    groups = _by_key(report)
    assert set(groups) == {str(w.ewm), str(w.sso), str(w.crm), str(w.mig), "none"}

    # Group: 420 -> 468 h is +11.4%, red, right of centre.
    ewm = groups[str(w.ewm)]
    assert ewm["label"].startswith("SAP EWM")
    assert _figures(ewm) == (420.0, 468.0, "+11.4%", "over")
    assert ewm["variance"]["percent"] == 11.4
    assert (ewm["variance"]["bar_left"], ewm["variance"]["bar_width"]) == (50.0, 6.8)
    assert ewm["variance"]["sr_label"] == "over"
    assert ewm["main_cause"] == {
        "value": "integration_complexity",
        "label": "Integration complexity",
    }
    assert (ewm["opportunity_count"], ewm["failed_assumptions"]) == (1, 1)
    (opp,) = ewm["opportunities"]
    assert opp["opportunity_id"] == str(w.alpha.opp_id)
    assert (opp["estimate_version"], opp["is_baseline"]) == (3, True)
    assert (opp["estimate_hours"], opp["actual_hours"], opp["failed_assumptions"]) == (
        420.0,
        468.0,
        1,
    )

    # Under: 96 -> 88 h is -8.3%, green, left of centre.
    sso = groups[str(w.sso)]
    assert _figures(sso) == (96.0, 88.0, f"{MINUS}8.3%", "under")
    assert (sso["variance"]["bar_left"], sso["variance"]["bar_width"]) == (45.0, 5.0)
    assert sso["variance"]["sr_label"] == "under"

    # Multi-tag: the CRM + Migration line is in both groups.
    crm = groups[str(w.crm)]
    assert _figures(crm) == (300.0, 360.0, "+20.0%", "over")
    assert (crm["opportunity_count"], crm["failed_assumptions"]) == (2, 1)
    assert [o["title"][:4] for o in crm["opportunities"]] == ["Alph", "Beta"]
    # +10.0% exactly is not above +10%: neutral.
    assert _figures(groups[str(w.mig)]) == (100.0, 110.0, "+10.0%", "neutral")

    # Unplanned work with a Work Package only, and a zero estimate: no percent, hours label.
    none = groups["none"]
    assert none["label"] == "No Integration Type"
    assert _figures(none) == (0.0, 12.0, "+12.0 h", "over")
    assert none["variance"]["percent"] is None
    assert report["groups"][-1]["key"] == "none"  # listed last

    # KPIs count each Actual once (the multi-tag line too) and include Unplanned work.
    kpis = report["kpis"]
    assert (kpis["closed_opportunities"], kpis["opportunities"]) == (1, 2)
    assert (kpis["estimate_hours"], kpis["actual_hours"]) == (816.0, 928.0)
    assert kpis["variance"]["display"] == "+13.7%"
    assert kpis["variance"]["hours"] == 112.0
    assert kpis["failed_assumptions"] == 2
    assert kpis["failed_by_kind"] == [
        {"kind": "condition", "label": "Condition", "count": 1},
        {"kind": "contingency", "label": "Contingency", "count": 1},
    ]
    assert report["calibration"]["threshold"] == 5
    assert report["calibration"]["message"] == (
        "Suggestions need at least 5 closed Opportunities per Integration Type. "
        "0 of 4 types have that many."
    )


def test_milestones_only_with_the_toggle(client: TestClient, sync_engine: Engine) -> None:
    w = _world(sync_engine)
    hod = _hod(client, sync_engine)
    default = _by_key(_report(client, hod, product=w.product))[str(w.ewm)]
    assert (default["estimate_hours"], default["actual_hours"]) == (420.0, 468.0)
    report = _report(client, hod, product=w.product, include_milestones="true")
    assert report["filters"]["include_milestones"] is True
    ewm = _by_key(report)[str(w.ewm)]
    assert _figures(ewm) == (470.0, 488.0, "+3.8%", "neutral")
    assert (report["kpis"]["estimate_hours"], report["kpis"]["actual_hours"]) == (866.0, 948.0)


def test_each_grouping(client: TestClient, sync_engine: Engine) -> None:
    w = _world(sync_engine)
    hod = _hod(client, sync_engine)

    by_opp = _by_key(_report(client, hod, product=w.product, group_by="opportunity"))
    alpha, beta = by_opp[str(w.alpha.opp_id)], by_opp[str(w.beta.opp_id)]
    assert alpha["label"].startswith("Alpha")
    assert _figures(alpha) == (616.0, 678.0, "+10.1%", "over")
    assert _figures(beta) == (200.0, 250.0, "+25.0%", "over")
    assert alpha["main_cause"]["value"] == "scope_change"  # 2 of 4 final Actuals

    by_product = _by_key(_report(client, hod, product=w.product, group_by="product"))
    assert set(by_product) == {w.product, w.other_product}  # Alpha is in both
    assert _figures(by_product[w.product])[:2] == (816.0, 928.0)
    assert _figures(by_product[w.other_product])[:2] == (616.0, 678.0)
    assert by_product[w.other_product]["opportunity_count"] == 1

    by_wp = _by_key(_report(client, hod, product=w.product, group_by="work_package"))
    assert set(by_wp) == {str(w.wp), "none"}
    assert by_wp[str(w.wp)]["label"].startswith("Go-live support")
    assert _figures(by_wp[str(w.wp)]) == (0.0, 12.0, "+12.0 h", "over")
    assert by_wp["none"]["label"] == "No Work Package"
    assert _figures(by_wp["none"])[:2] == (816.0, 916.0)

    by_cause = _by_key(_report(client, hod, product=w.product, group_by="cause"))
    assert set(by_cause) == {"integration_complexity", "estimation_error", "scope_change"}
    assert by_cause["scope_change"]["label"] == "Scope change"
    assert _figures(by_cause["scope_change"]) == (300.0, 372.0, "+24.0%", "over")
    assert by_cause["estimation_error"]["main_cause"]["value"] == "estimation_error"


def test_each_filter(client: TestClient, sync_engine: Engine) -> None:
    w = _world(sync_engine)
    hod = _hod(client, sync_engine)

    only_alpha = _report(client, hod, product=f"  {w.other_product.upper()} ")
    assert only_alpha["filters"]["product"] == w.other_product.upper()
    assert only_alpha["kpis"]["opportunities"] == 1
    assert only_alpha["kpis"]["estimate_hours"] == 616.0

    by_wp = _report(client, hod, product=w.product, work_package_id=str(w.wp))
    assert [g["key"] for g in by_wp["groups"]] == ["none"]
    assert by_wp["kpis"]["actual_hours"] == 12.0

    by_cause = _report(client, hod, product=w.product, cause="estimation_error")
    assert [g["key"] for g in by_cause["groups"]] == [str(w.sso)]

    # Story 10.4: one Integration Type (multi-tagged rows keep their other groups).
    by_it = _report(client, hod, product=w.product, integration_type_id=str(w.crm))
    assert by_it["filters"]["integration_type_id"] == str(w.crm)
    assert {g["key"] for g in by_it["groups"]} == {str(w.crm), str(w.mig)}
    assert by_it["kpis"]["estimate_hours"] == 300.0

    today = time.strftime("%Y-%m-%d", time.gmtime())
    closed = _report(client, hod, product=w.product, closed_from=today, closed_to=today)
    assert closed["kpis"]["opportunities"] == 1  # Beta isn't closed
    assert closed["kpis"]["closed_opportunities"] == 1

    none = _report(client, hod, product=w.product, closed_to="2000-01-01")
    assert (none["has_actuals"], none["kpis"], none["groups"]) == (True, None, [])

    # The options list every readable choice, whatever the filters.
    assert w.product in none["options"]["products"]
    assert {"id": str(w.wp), "name": f"Go-live support {w.product[5:]}"} in none["options"][
        "work_packages"
    ]
    assert {"id": str(w.ewm), "name": f"SAP EWM {w.product[5:]}"} in none["options"][
        "integration_types"
    ]
    assert [c["value"] for c in none["options"]["causes"]][:2] == [
        "unknown_requirement",
        "integration_complexity",
    ]


@pytest.mark.parametrize(
    "params",
    [
        {"group_by": "customer"},
        {"cause": "bad_luck"},
        {"work_package_id": "nope"},
        {"integration_type_id": "nope"},
        {"closed_from": "2026-13-01"},
        {"closed_from": "2026-10-02", "closed_to": "2026-10-01"},
    ],
)
def test_invalid_parameters_are_422(
    client: TestClient, sync_engine: Engine, params: dict[str, str]
) -> None:
    resp = client.get(URL, headers=_hod(client, sync_engine), params=params)
    assert resp.status_code == 422, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")


# --- access ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role", ["delivery_manager", "presales_engineer", "pm_reviewer", "sales_representative"]
)
def test_other_roles_are_403(client: TestClient, sync_engine: Engine, role: str) -> None:
    headers, _ = _user(client, sync_engine, "No Reports", role)
    resp = client.get(URL, headers=headers)
    assert resp.status_code == 403, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["code"] == "forbidden"


def test_platform_administrators_may_read(client: TestClient, sync_engine: Engine) -> None:
    w = _world(sync_engine)
    headers, _ = _user(client, sync_engine, "Ada Admin", ADMIN)
    assert _report(client, headers, product=w.product)["kpis"]["opportunities"] == 2


def test_rows_are_restricted_to_readable_opportunities(
    client: TestClient, sync_engine: Engine
) -> None:
    """A user holding the permission but not `opportunities.opportunity.read` sees only the
    Opportunities they own or collaborate on; with none, the empty state."""
    headers, user_id = _signed_in(
        client, "Pat Partial", "presales_engineer", permissions=[REPORT_READ]
    )
    empty = _report(client, headers)
    assert (empty["has_actuals"], empty["kpis"], empty["groups"]) == (False, None, [])
    assert empty["options"]["products"] == []

    tag = uuid4().hex[:8]
    it = catalogue_entry(sync_engine, f"Own type {tag}")
    own = seed_opportunity(
        sync_engine,
        title=f"Own {tag}",
        products=[f"Own-{tag}"],
        owner_id=user_id,
        lines=[SeedLine("10.0", "11.0", "estimation_error", [it])],
    )
    _world(sync_engine)  # someone else's
    report = _report(client, headers)
    assert report["has_actuals"] is True
    assert report["kpis"]["opportunities"] == 1
    assert [g["key"] for g in report["groups"]] == [str(it)]
    assert report["groups"][0]["opportunities"][0]["opportunity_id"] == str(own.opp_id)
    assert report["options"]["products"] == [f"Own-{tag}"]


# --- performance ----------------------------------------------------------------------------


def test_p95_under_500_ms_on_200_delivered_opportunities(
    client: TestClient, sync_engine: Engine
) -> None:
    tag = uuid4().hex[:8]
    types = [catalogue_entry(sync_engine, f"Perf type {tag} {i}") for i in range(6)]
    wp = catalogue_entry(sync_engine, f"Perf package {tag}", kind="work_package")
    causes = ["estimation_error", "integration_complexity", "scope_change", "customer_delay"]
    for n in range(200):
        seed_opportunity(
            sync_engine,
            title=f"Perf {tag} {n:03}",
            products=[f"Perf-{tag}-{n % 4}"],
            assumptions=[("a", "condition")],
            lines=[
                SeedLine(
                    f"{40 + i * 7}.0",
                    f"{38 + i * 8 + n % 5}.0",
                    causes[(n + i) % len(causes)],
                    [types[(n + i) % 6], types[(n + i + 1) % 6]] if i == 0 else [types[i]],
                    failed=["a"] if i == 1 else (),
                )
                for i in range(5)
            ]
            + [SeedLine(None, "6.0", "scope_change", work_package=wp)],
        )
    hod = _hod(client, sync_engine)
    for group_by in ("integration_type", "opportunity", "product", "work_package", "cause"):
        durations = []
        for _ in range(20):
            started = time.perf_counter()
            resp = client.get(URL, headers=hod, params={"group_by": group_by})
            durations.append(time.perf_counter() - started)
            assert resp.status_code == 200, resp.text
        assert resp.json()["kpis"]["closed_opportunities"] >= 200
        p95 = sorted(durations)[int(len(durations) * 0.95) - 1]
        assert p95 < 0.5, (
            f"{group_by}: P95 {p95 * 1000:.0f} ms of {sorted(round(d * 1000) for d in durations)}"
        )
