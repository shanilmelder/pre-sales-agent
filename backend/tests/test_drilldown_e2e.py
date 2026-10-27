"""Drill down from variance to the failed Assumption (Story 10.4; FR-50, UJ-5), end to end
against a real, migrated Postgres as psa_app with the fake model gateways: on the drill-down
world (`tests/fixtures/drilldown.py`: answered Gap -> Condition -> Baseline -> final Actual
citing the Condition), the Head of Delivery, who doesn't collaborate on the Opportunity,
walks the three API calls behind the three navigations:

1. Reports grouped by Integration Type: the Opportunity's row in the line's group;
2. the Actuals tab: the line with its failed Condition (number, acceptance, Evidence),
   read-only (`can_record` false);
3. the Trace filtered to the Condition, with its lineage: the chain holds the Gap, the
   question, the answer, the conversion, the acceptance and the Actual.

The Head of Delivery reads the Actuals, Estimate and Trace tabs, and both writes checked
(Save Actuals and accepting all Assumptions) are 403.
"""

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tests import test_estimates_lineage as lineage_tests
from tests.fixtures.drilldown import CAUSE, WMS, drilled
from tests.test_actuals_api import _save
from tests.test_intake_extraction import BASE, FakeGateway

# The fixtures the lineage flow needs (fake gateways, hidden jobs, agent profiles).
storage_dir = lineage_tests.storage_dir
_hidden_jobs = lineage_tests._hidden_jobs
gateway = lineage_tests.gateway
client = lineage_tests.client
_chat_profile = lineage_tests._chat_profile
_draft_profile = lineage_tests._draft_profile
_assessment_profile = lineage_tests._assessment_profile
_no_auto_run = lineage_tests._no_auto_run
_proposal_profile = lineage_tests._proposal_profile
_review_profile = lineage_tests._review_profile
_matching_settings = lineage_tests._matching_settings

REPORTS = "/api/v1/reports/estimate-vs-actual"


def test_from_a_reports_row_to_the_failed_condition_and_its_chain(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    w = drilled(client, sync_engine, db_url, gateway)
    hod = w.hod

    # 1. Reports, grouped by Integration Type: the line's group holds the Opportunity's row.
    resp = client.get(
        REPORTS,
        headers=hod,
        params={"group_by": "integration_type", "integration_type_id": w.integration_type_id},
    )
    assert resp.status_code == 200, resp.text
    (group,) = resp.json()["groups"]
    assert (group["key"], group["label"]) == (w.integration_type_id, w.integration_type_name)
    assert group["failed_assumptions"] == 1
    (row,) = group["opportunities"]
    assert (row["opportunity_id"], row["estimate_version_id"]) == (w.opp_id, w.baseline_id)
    assert row["is_baseline"] is True
    assert row["main_cause"]["value"] == CAUSE
    assert row["variance"]["direction"] == "over"

    # 2. The Actuals tab (the row's link): the tagged line, over, with its failed Condition.
    actuals = client.get(f"{BASE}/{w.opp_id}/actuals", headers=hod)
    assert actuals.status_code == 200, actuals.text
    view = actuals.json()
    assert (view["can_record"], view["can_close"]) == (False, False)
    line = next(line for line in view["lines"] if line["line_id"] == w.line_id)
    assert [t["id"] for t in line["integration_types"]] == [w.integration_type_id]
    assert line["variance"]["direction"] == "over"
    (failed,) = line["actual"]["failed_assumptions"]
    assert (failed["assumption_id"], failed["kind"], failed["position"]) == (
        w.condition_id,
        "condition",
        1,
    )
    assert failed["accepted_by"]["name"] == "Owner Person"
    assert failed["accepted_at"] is not None
    (chip,) = failed["evidence"]
    assert chip["kind"] == "source_document"
    assert chip["label"].startswith("S")

    # 3. Open in Trace: the Condition's own events and the Actual that recorded the failure.
    trace = client.get(
        f"{BASE}/{w.opp_id}/trace",
        headers=hod,
        params={"subject_type": "estimates.assumption", "subject_id": w.condition_id},
    )
    assert trace.status_code == 200, trace.text
    items = trace.json()["items"]
    assert {i["event_type"] for i in items} >= {
        "estimates.assumption.accepted",
        "actuals.actual.recorded",
    }
    assert all(
        i["subject"]["id"] == w.condition_id or i["event_type"].startswith("actuals.actual.")
        for i in items
    )
    # ... and the chain card above it (the Condition's lineage).
    chain = client.get(f"{BASE}/{w.opp_id}/assumptions/{w.condition_id}/lineage", headers=hod)
    assert chain.status_code == 200, chain.text
    body = chain.json()
    assert (body["position"], body["kind"]) == (1, "condition")
    kinds = [s["kind"] for s in body["steps"]]
    assert kinds == ["gap", "question", "answer", "conversion", "acceptance", "actual"]
    gap, *_, actual = body["steps"]
    assert gap["title"] == WMS
    assert actual["actual"]["line_id"] == w.line_id
    assert actual["actual"]["line_label"] is not None
    assert (actual["actual"]["kind"], actual["actual"]["effort_hours"]) == ("final", 48.0)
    assert (actual["actual"]["variance_cause"], actual["detail"]) == (
        CAUSE,
        "Integration complexity",
    )
    assert actual["actor"]["name"] == "Dana Delivery"
    assert actual["superseded"] is False


def test_a_non_collaborating_head_of_delivery_reads_but_never_writes(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    w = drilled(client, sync_engine, db_url, gateway)
    hod = w.hod

    for tab in ("actuals", "estimate", "trace"):
        resp = client.get(f"{BASE}/{w.opp_id}/{tab}", headers=hod)
        assert resp.status_code == 200, (tab, resp.text)
    assert client.get(f"{BASE}/{w.opp_id}/actuals", headers=hod).json()["can_record"] is False

    item = {"line_id": w.line_id, "effort_hours": 50, "variance_cause": CAUSE}
    resp = _save(client, hod, w.opp_id, [item], reason="Not mine to change")
    assert resp.status_code == 403, resp.text
    resp = client.post(f"{BASE}/{w.opp_id}/assumptions/accept-all", headers=hod)
    assert resp.status_code == 403, resp.text
