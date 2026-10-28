"""The drill-down world (Story 10.4), reusable by Story 9.10's end-to-end fixture: an
Opportunity built through the flow (intake, a Gap answered from a Source, an assessment run
drafting v1, the Gap converted to a Condition and accepted, v1 approved and set as the
Baseline, `test_estimates_lineage.baselined`), then delivery: the "Connect to SAP." line's
Requirement tagged with an Integration Type, and a delivery manager recording that line's
final Actual over the estimate, citing the Condition as failed. The Head of Delivery who reads
it doesn't collaborate on the Opportunity.

Needs the fixtures `test_estimates_lineage` uses (fake gateways, hidden jobs, the profiles),
which the test module re-exports.
"""

from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tests.test_actuals_api import DM, HOD, _collaborate, _save
from tests.test_estimates_lineage import SAP, WMS, all_assumptions, baselined, estimate
from tests.test_intake_extraction import BASE, FakeGateway
from tests.test_opportunities import _user
from tests.test_reviews_challenges import _entry

CAUSE = "integration_complexity"
ACTUAL_HOURS = 48.0


@dataclass
class Drilldown:
    owner: dict[str, str]
    dm: dict[str, str]
    hod: dict[str, str]
    opp_id: str
    title: str
    baseline_id: str
    line_id: str
    line_hours: float
    condition_id: str
    integration_type_id: str
    integration_type_name: str


def _tag_requirement(
    client: TestClient, headers: dict[str, str], opp_id: str, text: str, entry_id: str
) -> None:
    listed = client.get(f"{BASE}/{opp_id}/requirements", headers=headers).json()
    item = next(i for i in listed["items"] if i["text"] == text)
    resp = client.put(
        f"{BASE}/{opp_id}/requirements/{item['id']}/integration-types",
        headers={**headers, "If-Match": f'"{item["row_version"]}"'},
        json={"integration_type_ids": [entry_id]},
    )
    assert resp.status_code == 200, resp.text


def drilled(client: TestClient, engine: Engine, db_url: str, gateway: FakeGateway) -> Drilldown:
    """The drill-down world (module docstring)."""
    owner, opp, baseline_id = baselined(client, engine, db_url, gateway)
    view = estimate(client, owner, opp["id"])
    line = next(
        line for s in view["version"]["sections"] for line in s["lines"] if line["title"] == SAP
    )
    (condition,) = [a for a in all_assumptions(view) if a["wording"] and a["kind"] == "condition"]
    assert condition["accepted_by"] is not None, condition
    name = f"SAP EWM {opp['id'][:8]}"
    entry = str(_entry(engine, name))
    _tag_requirement(client, owner, opp["id"], SAP, entry)

    dm, dm_id = _user(client, engine, "Dana Delivery", DM)
    _collaborate(client, owner, opp["id"], dm_id)
    item: dict[str, Any] = {
        "line_id": line["id"],
        "effort_hours": ACTUAL_HOURS,
        "variance_cause": CAUSE,
        "failed_assumption_ids": [condition["id"]],
    }
    saved = _save(client, dm, opp["id"], [item])
    assert saved.status_code == 200, saved.text
    hod, _ = _user(client, engine, "Hana Head", HOD)
    return Drilldown(
        owner=owner,
        dm=dm,
        hod=hod,
        opp_id=opp["id"],
        title=opp["title"],
        baseline_id=baseline_id,
        line_id=line["id"],
        line_hours=float(line["effort_hours"]),
        condition_id=condition["id"],
        integration_type_id=entry,
        integration_type_name=name,
    )


__all__ = ["CAUSE", "WMS", "Drilldown", "drilled"]
