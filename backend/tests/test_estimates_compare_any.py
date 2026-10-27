"""Comparing any two Estimate Versions (Story 9.9) against a real, migrated Postgres as
psa_app, with the fake model gateways of `test_intake_extraction.py`: line, total, Assumption
and Risk diffs between two versions three runs apart, the "why it changed" events in the
window (and none outside it), the same version twice (422), an unknown number (404), and who
may compare (a sales representative reads it; a non-member gets 404). Nothing is written.
"""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.platform.model_gateway import provider
from tests import test_assessments_red_team as red_team_tests
from tests import test_assessments_specialists as specialist_tests
from tests import test_estimates_assumptions as assumption_tests
from tests import test_estimates_draft as draft_tests
from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests.test_assessments_specialists import AgentGateway, install
from tests.test_estimates_assumptions import by_title, condition
from tests.test_estimates_lineage import (
    AGREE,
    SAP,
    WMS,
    all_assumptions,
    edit,
    estimate,
    lines_by_title,
    run,
    trace_count,
)
from tests.test_estimates_risks import _convert
from tests.test_gaps_detection import extracted, gap, gaps_out
from tests.test_health import assert_problem
from tests.test_intake_extraction import BASE, DETECT, PROPOSE, FakeGateway, drain
from tests.test_opportunities import PSE, _add, _create, _user
from tests.test_reviews_requests import REP

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile
_draft_profile = draft_tests._draft_profile
_assessment_profile = specialist_tests._assessment_profile
_no_auto_run = specialist_tests._no_auto_run
_proposal_profile = assumption_tests._proposal_profile
_review_profile = red_team_tests._review_profile

PEAK_GAP = "Peak growth unknown"


def compare(client: TestClient, headers: dict[str, str], opp_id: str, start: Any, end: Any) -> Any:
    return client.get(
        f"{BASE}/{opp_id}/estimate-versions/compare?from={start}&to={end}", headers=headers
    )


def three_versions(
    client: TestClient, engine: Engine, db_url: str, gateway: FakeGateway
) -> tuple[dict[str, str], dict[str, Any], str]:
    """R1-R3 with two open Gaps (WMS about R1, peak growth about R3). v1 from a run, with
    the WMS Condition accepted; v2 from a second run, its SAP line edited to 30 h and the
    peak-growth Gap converted to a Risk; v3 from a third run, its Condition reworded. (headers,
    opp, the Risk's id)."""
    headers, opp = extracted(client, engine, db_url, gateway, count=3)
    gateway.replies = [gaps_out(gap(WMS, ["R1"]), gap(PEAK_GAP, ["R3"]))]
    assert drain(db_url, DETECT) == ["succeeded"]
    install(AgentGateway(AGREE))
    run(client, headers, opp["id"], db_url)
    provider.install(gateway)
    # The peak-growth Gap is left without one: the first attempt retries, the second keeps it.
    gateway.replies = [by_title(condition(WMS)), by_title(condition(WMS))]  # type: ignore[list-item]
    assert drain(db_url, PROPOSE)[-1] == "succeeded"
    (wms,) = all_assumptions(estimate(client, headers, opp["id"]))
    accepted = client.post(
        f"{BASE}/{opp['id']}/assumptions/{wms['id']}/accept",
        headers={**headers, "If-Match": f'"{wms["row_version"]}"'},
    )
    assert accepted.status_code == 200, accepted.text

    install(AgentGateway(AGREE))
    run(client, headers, opp["id"], db_url)  # v2 carries the Condition
    edit(client, headers, opp["id"], lines_by_title(estimate(client, headers, opp["id"]))[SAP], 30)
    peak_gap = next(
        g
        for g in client.get(f"{BASE}/{opp['id']}/gaps", headers=headers).json()["items"]
        if g["title"] == PEAK_GAP
    )
    risk = _convert(client, headers, opp["id"], peak_gap["id"], "Peak growth may double.")
    assert risk.status_code == 201, risk.text

    install(AgentGateway(AGREE))
    run(client, headers, opp["id"], db_url)  # v3 carries the edit, Condition and Risk
    (carried,) = all_assumptions(estimate(client, headers, opp["id"]))
    reworded = client.patch(
        f"{BASE}/{opp['id']}/assumptions/{carried['id']}",
        headers={**headers, "If-Match": f'"{carried["row_version"]}"'},
        json={"wording": "The customer confirms the WMS version.", "reason": "Clearer"},
    )
    assert reworded.status_code == 200, reworded.text
    (carried_risk,) = estimate(client, headers, opp["id"])["version"]["risks"]
    raised = client.patch(
        f"{BASE}/{opp['id']}/risks/{carried_risk['id']}",
        headers={**headers, "If-Match": f'"{carried_risk["row_version"]}"'},
        json={"likelihood": "high", "reason": "Peak season confirmed"},
    )
    assert raised.status_code == 200, raised.text
    return headers, opp, str(risk.json()["id"])


def test_any_two_versions_with_lines_totals_assumptions_risks_and_why(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, _ = three_versions(client, sync_engine, db_url, gateway)
    v1 = estimate(client, headers, opp["id"], 1)["version"]
    v3 = estimate(client, headers, opp["id"], 3)["version"]
    before = trace_count(sync_engine, opp["id"])

    resp = compare(client, headers, opp["id"], 1, 3)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["from_version"], body["to_version"]) == (1, 3)
    assert (body["from_version_id"], body["to_version_id"]) == (v1["id"], v3["id"])
    assert body["lines"] == [
        {
            "change": "changed",
            "section": "integration",
            "title": SAP,
            "before_hours": 34.0,
            "after_hours": 30.0,
            "delta_hours": -4.0,
        }
    ]
    assert body["total_before"] == v1["totals"]["total_hours"]
    assert body["total_after"] == v3["totals"]["total_hours"]
    assert body["total_delta"] == round(body["total_after"] - body["total_before"], 1)
    (assumption,) = body["assumptions"]
    assert assumption["change"] == "changed"
    assert assumption["text"] == "The customer confirms the WMS version."
    assert (
        assumption["before"]
        == f"Condition · The estimate assumes the customer settles {WMS.lower()}."
    )
    assert assumption["after"] == "Condition · The customer confirms the WMS version."
    (risk,) = body["risks"]
    assert (risk["change"], risk["text"], risk["before"]) == (
        "added",
        "Peak growth may double.",
        None,
    )

    types = [e["event_type"] for e in body["why"]]
    assert types.count("estimates.estimate_version.created") == 2  # v2 and v3, not v1
    assert "estimates.estimate_line.edited" in types
    assert "estimates.risk.created" in types
    assert "gaps.gap.converted" in types
    assert types.count("assessments.assessment.completed") == 6  # two reruns of three agents
    # v3 is still the latest: edits to it after its creation are in the window too.
    assert "estimates.assumption.edited" in types
    assert "estimates.risk.edited" in types
    times = [e["occurred_at"] for e in body["why"]]
    assert times == sorted(times)
    (edited,) = [e for e in body["why"] if e["event_type"] == "estimates.estimate_line.edited"]
    assert (edited["label"], edited["reason"], edited["actor"]["name"]) == (
        "Estimate line edited",
        "Reuse the existing connector",
        "Owner Person",
    )
    assert edited["subject"]["type"] == "estimates.estimate_line"
    assert trace_count(sync_engine, opp["id"]) == before

    # Reversed: the same window, the deltas negated.
    back = compare(client, headers, opp["id"], 3, 1).json()
    assert [d["delta_hours"] for d in back["lines"]] == [4.0]
    assert back["total_delta"] == -body["total_delta"]
    assert [e["id"] for e in back["why"]] == [e["id"] for e in body["why"]]
    assert back["risks"][0]["change"] == "removed"


def test_a_risk_and_an_assumption_changed_between_versions(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, _ = three_versions(client, sync_engine, db_url, gateway)

    body = compare(client, headers, opp["id"], 2, 3).json()

    (risk,) = body["risks"]
    assert (risk["change"], risk["text"]) == ("changed", "Peak growth may double.")
    assert risk["before"] == "medium likelihood · medium impact · Peak growth may double."
    assert risk["after"] == "high likelihood · medium impact · Peak growth may double."
    (assumption,) = body["assumptions"]
    assert assumption["change"] == "changed"
    # v2 is superseded by v3: the window ends at v3's creation, so v3's edits are left out.
    back = compare(client, headers, opp["id"], 1, 2).json()
    assert "estimates.risk.edited" not in [e["event_type"] for e in back["why"]]


def test_bad_compare_requests(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = extracted(client, sync_engine, db_url, gateway, count=3)
    gateway.replies = [gaps_out(gap(WMS, ["R1"]))]
    assert drain(db_url, DETECT) == ["succeeded"]
    install(AgentGateway(AGREE))
    run(client, headers, opp["id"], db_url)

    assert_problem(compare(client, headers, opp["id"], 1, 1).json(), 422, "validation_error")
    assert_problem(compare(client, headers, opp["id"], 1, 9).json(), 404, "not_found")
    assert compare(client, headers, opp["id"], 0, 1).status_code == 422
    assert compare(client, headers, opp["id"], "x", 1).status_code == 422
    missing = client.get(f"{BASE}/{opp['id']}/estimate-versions/compare?from=1", headers=headers)
    assert missing.status_code == 422


def test_who_may_compare(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = extracted(client, sync_engine, db_url, gateway, count=3)
    gateway.replies = [gaps_out(gap(WMS, ["R1"]))]
    assert drain(db_url, DETECT) == ["succeeded"]
    install(AgentGateway(AGREE))
    run(client, headers, opp["id"], db_url)
    install(AgentGateway(AGREE))
    run(client, headers, opp["id"], db_url)
    rep_h, rep = _user(client, sync_engine, "Rita Rep", REP)
    current = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    assert _add(client, headers, current, rep).status_code == 200
    stranger_h, _ = _user(client, sync_engine, "Sam Stranger", PSE)
    other = _create(client, stranger_h)

    assert compare(client, rep_h, opp["id"], 1, 2).status_code == 200
    assert_problem(compare(client, stranger_h, opp["id"], 1, 2).json(), 404, "not_found")
    assert_problem(compare(client, stranger_h, other["id"], 1, 2).json(), 404, "not_found")
