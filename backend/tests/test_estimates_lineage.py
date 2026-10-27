"""Lineage (Story 9.9) against a real, migrated Postgres as psa_app, with the fake model
gateways and hidden jobs of `test_intake_extraction.py`: an Estimate line's lineage (an
assessed line, an edited and carried line, a Conflict decision, a superseded Requirement, a
model-drafted version, a Red Team Finding's override), an Assumption's chain from an answered
Gap, who may read them (a sales representative, a non-member, another Opportunity's line),
nothing written, and the Baseline lineage test: on a Baseline built through the flow (intake,
Gap answered, assessment run, Assumption accepted, review approved, Baseline set), every
Baseline line has a Finding or effort entry with Evidence, or an edit with a reason, and
every Assumption has its origin and the person who accepted it.
"""

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.platform.model_gateway import provider
from tests import test_assessments_red_team as red_team_tests
from tests import test_assessments_specialists as specialist_tests
from tests import test_estimates_assumptions as assumption_tests
from tests import test_estimates_draft as draft_tests
from tests import test_gaps_answers as answer_tests
from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests.test_assessments_critic import critic_finding, critic_out
from tests.test_assessments_findings_decisions import override, resolve
from tests.test_assessments_red_team import finding as red_team_finding
from tests.test_assessments_red_team import findings_out
from tests.test_assessments_specialists import (
    AgentGateway,
    assessment_out,
    effort,
    finding,
    install,
    replies,
    started,
)
from tests.test_estimates_assumptions import by_title, condition, contingency
from tests.test_estimates_draft import est_line, lines_out
from tests.test_estimates_from_assessments import prepared
from tests.test_gaps_answers import _answer
from tests.test_gaps_detection import requirement_rows, rows
from tests.test_gaps_questions import _approve
from tests.test_gaps_send import _mark_sent, _questions
from tests.test_health import assert_problem
from tests.test_intake_extraction import ASSESS, BASE, DRAFT, PROPOSE, RED_TEAM, FakeGateway, drain
from tests.test_intake_requirement_edits import _patch
from tests.test_opportunities import _add, _create, _user
from tests.test_reviews_challenges import _decline, _raise
from tests.test_reviews_decisions import _decide
from tests.test_reviews_requests import ENG, PSE, REP, _row_version, _send

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
_matching_settings = answer_tests._matching_settings

WMS = "WMS version unknown"
SAP = "Connect to SAP."
UPTIME = "Runs 24/7."
PEAK = "Peak 900 orders/hour."
EDIT_REASON = "Reuse the existing connector"


def agent_out(*efforts: dict[str, Any]) -> Any:
    return assessment_out(finding("Interface details open", ["R1"]), efforts=efforts)


# Every agent sizes R1-R3, so nothing is uncovered and no scope Conflict opens.
AGREE = replies(
    engineering_agent=[
        agent_out(
            effort("R1", 20, "Two interfaces."),
            effort("R2", 6, "Monitoring."),
            effort("R3", 8, "One screen."),
        )
    ],
    pm_agent=[
        agent_out(
            effort("R1", 10, "Vendor meetings."),
            effort("R2", 2, "Runbook."),
            effort("R3", 2, "Sign-off."),
        )
    ],
    security_agent=[
        agent_out(
            effort("R1", 4, "Credential review."),
            effort("R2", 1, "Hardening."),
            effort("R3", 1, "Access review."),
        )
    ],
)


# --- helpers --------------------------------------------------------------------------------


def estimate(
    client: TestClient, headers: dict[str, str], opp_id: str, version: int | None = None
) -> dict[str, Any]:
    query = "" if version is None else f"?version={version}"
    resp = client.get(f"{BASE}/{opp_id}/estimate{query}", headers=headers)
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


def lines_by_title(view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {line["title"]: line for s in view["version"]["sections"] for line in s["lines"]}


def all_assumptions(view: dict[str, Any]) -> list[dict[str, Any]]:
    groups = view["version"]["assumptions"]
    return [*groups["conditions"], *groups["contingencies"]]


def lineage(client: TestClient, headers: dict[str, str], opp_id: str, line_id: str) -> Any:
    return client.get(f"{BASE}/{opp_id}/estimate-lines/{line_id}/lineage", headers=headers)


def line_lineage(
    client: TestClient, headers: dict[str, str], opp_id: str, line_id: str
) -> dict[str, Any]:
    resp = lineage(client, headers, opp_id, line_id)
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


def chain(client: TestClient, headers: dict[str, str], opp_id: str, assumption_id: str) -> Any:
    return client.get(f"{BASE}/{opp_id}/assumptions/{assumption_id}/lineage", headers=headers)


def edit(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    line: dict[str, Any],
    hours: float,
    reason: str = EDIT_REASON,
) -> None:
    resp = client.patch(
        f"{BASE}/{opp_id}/estimate-lines/{line['id']}",
        headers={**headers, "If-Match": f'"{line["row_version"]}"'},
        json={"effort_hours": hours, "reason": reason},
    )
    assert resp.status_code == 200, resp.text


def run(client: TestClient, headers: dict[str, str], opp_id: str, db_url: str) -> dict[str, Any]:
    body = started(client, headers, opp_id)
    assert drain(db_url, ASSESS)[-1] == "succeeded"
    return body


def answered(
    client: TestClient, engine: Engine, db_url: str, gateway: FakeGateway
) -> tuple[dict[str, str], dict[str, Any]]:
    """`prepared` (R1-R3 and the open Gap "WMS version unknown" about R1) with its question
    approved, sent and answered by the customer without settling the Gap."""
    headers, opp = prepared(client, engine, db_url, gateway)
    question = _questions(client, headers, opp["id"])[WMS]
    assert _approve(client, headers, opp["id"], question).status_code == 200
    question = _questions(client, headers, opp["id"])[WMS]
    assert _mark_sent(client, headers, opp["id"], [question]).status_code == 200
    question = _questions(client, headers, opp["id"])[WMS]
    resp = _answer(client, headers, opp["id"], question, settles_gap=False)
    assert resp.status_code == 200, resp.text
    return headers, opp


def assessed(
    client: TestClient, engine: Engine, db_url: str, gateway: FakeGateway
) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
    """`answered`, then an assessment run (`AGREE`) builds draft v1 from the Assessments, and
    its Assumption proposals make the Gap a Condition, which the owner accepts. (headers,
    opp, the run)."""
    headers, opp = answered(client, engine, db_url, gateway)
    install(AgentGateway(AGREE))
    body = run(client, headers, opp["id"], db_url)
    provider.install(gateway)
    gateway.replies = [by_title(condition(WMS))]  # type: ignore[list-item]
    assert drain(db_url, PROPOSE) == ["succeeded"]
    accepted = client.post(f"{BASE}/{opp['id']}/assumptions/accept-all", headers=headers)
    assert accepted.status_code == 200, accepted.text
    return headers, opp, body


def baselined(
    client: TestClient, engine: Engine, db_url: str, gateway: FakeGateway
) -> tuple[dict[str, str], dict[str, Any], str]:
    """`assessed` with the R3 line edited (with a reason), v1 submitted, approved by an
    engineering reviewer and set as the Baseline. (headers, opp, v1's id)."""
    headers, opp, _ = assessed(client, engine, db_url, gateway)
    edit(client, headers, opp["id"], lines_by_title(estimate(client, headers, opp["id"]))[PEAK], 9)
    view = estimate(client, headers, opp["id"])
    assert view["blockers"]["to_submit"] == [], view["blockers"]
    version = view["version"]
    submitted = client.post(
        f"{BASE}/{opp['id']}/estimate/versions/{version['id']}/submit",
        headers={**headers, "If-Match": f'"{version["row_version"]}"'},
    )
    assert submitted.status_code == 200, submitted.text
    ana_h, ana = _user(client, engine, "Ana Reviewer", ENG)
    sent = _send(
        client, headers, opp["id"], version["id"], _row_version(engine, version["id"]), [ana]
    )
    assert sent.status_code == 201, sent.text
    (request,) = sent.json()["items"]
    approved = _decide(client, ana_h, opp["id"], request, "approved", reason=None)
    assert approved.status_code == 201, approved.text
    baseline = client.post(
        f"{BASE}/{opp['id']}/estimate-versions/{version['id']}/baseline",
        headers={**headers, "If-Match": f'"{_row_version(engine, version["id"])}"'},
    )
    assert baseline.status_code == 201, baseline.text
    return headers, opp, version["id"]


def trace_count(engine: Engine, opp_id: str) -> int:
    (found,) = rows(
        engine,
        "SELECT count(*) AS n FROM platform_trace_events WHERE opportunity_id = :o",
        o=opp_id,
    )
    return int(found["n"])


# --- the Baseline lineage test --------------------------------------------------------------


def test_every_baseline_line_and_assumption_traces_back(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, baseline_id = baselined(client, sync_engine, db_url, gateway)
    view = estimate(client, headers, opp["id"])
    assert view["baseline"]["version_id"] == baseline_id
    lines = [line for s in view["version"]["sections"] for line in s["lines"]]
    assert len(lines) == 3

    for line in lines:
        found = line_lineage(client, headers, opp["id"], line["id"])
        assert found["version_id"] == baseline_id
        evidenced = [
            f
            for f in found["findings"]
            if f["entry"] in ("finding", "effort") and f["evidence"] and not f["superseded"]
        ]
        reasoned = [e for e in found["edits"] if e["reason"]]
        assert evidenced or reasoned, line["title"]
        assert all(e["kind"] == "requirement" for f in evidenced for e in f["evidence"])
        assert found["requirements"], line["title"]
        # The review decision on the Baseline version is in its reviews.
        assert [r["label"] for r in found["reviews"] if r["kind"] == "review_decision"] == [
            "Approved"
        ]

    assumptions = all_assumptions(view)
    assert assumptions
    for a in assumptions:
        resp = chain(client, headers, opp["id"], a["id"])
        assert resp.status_code == 200, resp.text
        steps = resp.json()["steps"]
        assert steps[0]["kind"] in ("gap", "unknown", "finding")
        (accepted,) = [s for s in steps if s["kind"] == "acceptance"]
        assert accepted["actor"]["name"] == "Owner Person"
        assert accepted["at"] is not None


# --- a line ---------------------------------------------------------------------------------


def test_an_assessed_line_lists_its_requirements_and_findings_with_evidence(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, body = assessed(client, sync_engine, db_url, gateway)
    reqs = requirement_rows(sync_engine, opp["id"])
    sap = lines_by_title(estimate(client, headers, opp["id"]))[SAP]
    before = trace_count(sync_engine, opp["id"])

    found = line_lineage(client, headers, opp["id"], sap["id"])

    assert (found["title"], found["version"], found["source"]) == (SAP, 1, "assessments")
    (requirement,) = found["requirements"]
    assert (requirement["id"], requirement["version"], requirement["label"]) == (
        str(reqs[0]["id"]),
        1,
        "R1",
    )
    assert requirement["text"] == SAP
    assert (requirement["superseded"], requirement["active_version"]) == (False, 1)
    assert requirement["evidence"] == [
        {
            "kind": "requirement",
            "id": str(reqs[0]["id"]),
            "version": 1,
            "label": "R1",
            "superseded": False,
            "passage_id": None,
            "excerpt": SAP,
        }
    ]
    findings = [f for f in found["findings"] if f["entry"] == "finding"]
    efforts = [f for f in found["findings"] if f["entry"] == "effort"]
    assert [f["agent_label"] for f in findings] == [
        "Engineering Agent",
        "PM Agent",
        "Security Agent",
    ]
    assert {f["title"] for f in findings} == {"Interface details open"}
    assert all(f["version"] == 1 and not f["superseded"] for f in found["findings"])
    assert all([e["label"] for e in f["evidence"]] == ["R1"] for f in found["findings"])
    assert sorted(f["hours"] for f in efforts) == [4, 10, 20]
    assert {f["detail"] for f in efforts} == {
        "Two interfaces.",
        "Vendor meetings.",
        "Credential review.",
    }
    assert found["edits"] == []
    assert found["decisions"] == []
    assert found["assumptions"] == []
    # Read only: nothing traced.
    assert trace_count(sync_engine, opp["id"]) == before
    assert body["id"]


def test_an_edited_line_carried_twice_lists_every_edit_with_its_reason(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, _ = assessed(client, sync_engine, db_url, gateway)
    edit(client, headers, opp["id"], lines_by_title(estimate(client, headers, opp["id"]))[SAP], 30)
    install(AgentGateway(AGREE))
    run(client, headers, opp["id"], db_url)  # v2 carries the edit
    v2 = estimate(client, headers, opp["id"])
    assert v2["version"]["version"] == 2
    edit(client, headers, opp["id"], lines_by_title(v2)[SAP], 28, reason="Fewer interfaces")
    install(AgentGateway(AGREE))
    run(client, headers, opp["id"], db_url)  # v3 carries it again
    v3 = estimate(client, headers, opp["id"])
    sap = lines_by_title(v3)[SAP]
    assert (v3["version"]["version"], sap["effort_hours"]) == (3, 28.0)

    found = line_lineage(client, headers, opp["id"], sap["id"])

    assert [
        (e["version"], e["before_hours"], e["after_hours"], e["reason"]) for e in found["edits"]
    ] == [
        (1, 34.0, 30.0, EDIT_REASON),
        (2, 30.0, 28.0, "Fewer interfaces"),
    ]
    assert [e["superseded"] for e in found["edits"]] == [True, False]
    assert all(e["actor"]["name"] == "Owner Person" for e in found["edits"])
    assert all(e["line_id"] != sap["id"] for e in found["edits"])
    # The run behind v3 is the third one: its Assessments are current, the earlier ones not
    # listed.
    assert found["findings"] and all(not f["superseded"] for f in found["findings"])
    assert {f["version"] for f in found["findings"] if f["entry"] != "critic"} == {3}


def test_a_conflict_decision_on_the_line_is_listed_with_its_reason(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, _ = assessed(client, sync_engine, db_url, gateway)
    sap = lines_by_title(estimate(client, headers, opp["id"]))[SAP]
    conflict_id = uuid4()
    # A Conflict decision that set the line's hours, as `conflicts.decide` traces it.
    with sync_engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO platform_trace_events (id, opportunity_id, actor_type, actor_id, "
            "event_type, subject_type, subject_id, payload, occurred_at) VALUES "
            "(%(id)s, %(o)s, 'user', %(a)s, 'conflicts.conflict.resolved', "
            "'conflicts.conflict', %(c)s, %(p)s::jsonb, now())",
            {
                "id": uuid4(),
                "o": opp["id"],
                "a": opp["owner"]["id"],
                "c": conflict_id,
                "p": '{"reason_kind": "decided", "reason": "Engineering is right", '
                f'"line_id": "{sap["id"]}", "applied_hours": 20.0}}',
            },
        )

    found = line_lineage(client, headers, opp["id"], sap["id"])

    (decision,) = found["decisions"]
    assert (decision["kind"], decision["subject_id"], decision["reason"]) == (
        "conflict_resolved",
        str(conflict_id),
        "Engineering is right",
    )
    assert (decision["actor"]["name"], decision["version"], decision["superseded"]) == (
        "Owner Person",
        1,
        False,
    )


def test_a_requirement_edited_after_it_was_cited_is_superseded(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, _ = assessed(client, sync_engine, db_url, gateway)
    sap = lines_by_title(estimate(client, headers, opp["id"]))[SAP]
    reqs = requirement_rows(sync_engine, opp["id"])
    edited = _patch(
        client, headers, opp["id"], reqs[0], {"text": "Connect to SAP S/4HANA."}, version=1
    )
    assert edited.status_code == 200, edited.text

    found = line_lineage(client, headers, opp["id"], sap["id"])

    (requirement,) = found["requirements"]
    assert (requirement["version"], requirement["active_version"]) == (1, 2)
    assert requirement["superseded"] is True
    assert requirement["text"] == SAP  # the cited version's text
    assert requirement["evidence"][0]["superseded"] is True


def test_a_model_drafted_version_has_no_findings(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    draft_tests.requeue(db_url, opp["id"])
    gateway.replies = [lines_out(est_line(SAP, ["R1"], effort=40.0))]
    assert drain(db_url, DRAFT) == ["succeeded"]
    sap = lines_by_title(estimate(client, headers, opp["id"]))[SAP]
    edit(client, headers, opp["id"], sap, 35)

    found = line_lineage(client, headers, opp["id"], sap["id"])

    assert found["source"] == "model"
    assert [r["label"] for r in found["requirements"]] == ["R1"]
    assert found["findings"] == []
    assert [(e["after_hours"], e["reason"]) for e in found["edits"]] == [(35.0, EDIT_REASON)]


def test_red_team_findings_and_their_override_and_resolution_are_listed(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, _ = assessed(client, sync_engine, db_url, gateway)
    gateway.replies = [
        findings_out(
            red_team_finding("SAP sizing looks thin", ["R1"]),
            red_team_finding("SAP mapping unknown", ["R1"], severity="medium"),
        )
    ]
    assert drain(db_url, RED_TEAM) == ["succeeded"]
    sap = lines_by_title(estimate(client, headers, opp["id"]))[SAP]
    review = client.get(f"{BASE}/{opp['id']}/red-team", headers=headers).json()["review"]
    thin, mapping = review["findings"]
    assert override(client, headers, opp["id"], thin, "Covered by the vendor").status_code == 200
    resolved = resolve(client, headers, opp["id"], mapping, "Mapping agreed on the call")
    assert resolved.status_code == 200, resolved.text

    found = line_lineage(client, headers, opp["id"], sap["id"])

    listed = {f["id"]: f for f in found["findings"] if f["entry"] == "red_team"}
    assert (listed[thin["id"]]["title"], listed[thin["id"]]["status"]) == (
        "SAP sizing looks thin",
        "overridden",
    )
    assert listed[mapping["id"]]["status"] == "resolved"
    (overridden,) = [d for d in found["decisions"] if d["kind"] == "finding_overridden"]
    assert (overridden["subject_id"], overridden["reason"], overridden["actor"]["name"]) == (
        thin["id"],
        "Covered by the vendor",
        "Owner Person",
    )
    (settled,) = [d for d in found["decisions"] if d["kind"] == "finding_resolved"]
    assert (settled["subject_id"], settled["reason"], settled["actor"]["name"]) == (
        mapping["id"],
        "Mapping agreed on the call",
        "Owner Person",
    )


def test_critic_and_line_only_red_team_findings_are_listed(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = answered(client, sync_engine, db_url, gateway)
    critic = critic_out(
        critic_finding("unsupported_claim", "SAP hours have no source", requirements=["R1"])
    )
    install(AgentGateway({**AGREE, "critic_agent": [critic]}))
    run(client, headers, opp["id"], db_url)
    provider.install(gateway)
    # The Red Team must cite a Requirement: R2 (24/7), which the peak line doesn't cover, so the
    # peak line finds it through its line link only.
    gateway.replies = [
        findings_out(red_team_finding("Peak line looks light", ["R2"], lines=[PEAK]))
    ]
    assert drain(db_url, RED_TEAM)[-1] == "succeeded"
    lines = lines_by_title(estimate(client, headers, opp["id"]))

    sap = line_lineage(client, headers, opp["id"], lines[SAP]["id"])
    peak = line_lineage(client, headers, opp["id"], lines[PEAK]["id"])

    (critic_entry,) = [f for f in sap["findings"] if f["entry"] == "critic"]
    assert (critic_entry["title"], critic_entry["agent_label"]) == (
        "SAP hours have no source",
        "Critic",
    )
    assert [e["label"] for e in critic_entry["evidence"]] == ["R1"]
    assert [f for f in sap["findings"] if f["entry"] == "red_team"] == []
    (red_team_entry,) = [f for f in peak["findings"] if f["entry"] == "red_team"]
    assert red_team_entry["title"] == "Peak line looks light"
    assert [e["label"] for e in red_team_entry["evidence"]] == ["R2"]
    assert [f for f in peak["findings"] if f["entry"] == "critic"] == []


def test_a_contingency_linked_to_the_line_is_listed(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = answered(client, sync_engine, db_url, gateway)
    install(AgentGateway(AGREE))
    run(client, headers, opp["id"], db_url)
    provider.install(gateway)
    gateway.replies = [by_title(contingency(WMS, 8, line=SAP))]  # type: ignore[list-item]
    assert drain(db_url, PROPOSE) == ["succeeded"]
    view = estimate(client, headers, opp["id"])
    (a,) = all_assumptions(view)
    assert a["line"]["title"] == SAP
    accepted = client.post(
        f"{BASE}/{opp['id']}/assumptions/{a['id']}/accept",
        headers={**headers, "If-Match": f'"{a["row_version"]}"'},
    )
    assert accepted.status_code == 200, accepted.text

    found = line_lineage(client, headers, opp["id"], lines_by_title(view)[SAP]["id"])
    other = line_lineage(client, headers, opp["id"], lines_by_title(view)[PEAK]["id"])

    (listed,) = found["assumptions"]
    assert (listed["id"], listed["amount_hours"], listed["accepted_by_name"]) == (
        a["id"],
        8.0,
        "Owner Person",
    )
    assert listed["accepted_at"] is not None
    assert (listed["version"], listed["superseded"]) == (1, False)
    assert other["assumptions"] == []


def test_a_declined_challenge_on_the_version_is_listed_with_both_reasons(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, version_id = baselined(client, sync_engine, db_url, gateway)
    raised = _raise(
        client, headers, opp["id"], "estimate_version", version_id, reason="SAP looks light"
    )
    assert raised.status_code == 201, raised.text
    declined = _decline(client, headers, opp["id"], raised.json(), reason="Covered by the buffer")
    assert declined.status_code == 200, declined.text
    sap = lines_by_title(estimate(client, headers, opp["id"]))[SAP]

    found = line_lineage(client, headers, opp["id"], sap["id"])

    (challenge,) = [r for r in found["reviews"] if r["kind"] == "challenge"]
    assert (challenge["id"], challenge["label"]) == (raised.json()["id"], "Challenge declined")
    assert (challenge["reason"], challenge["decline_reason"]) == (
        "SAP looks light",
        "Covered by the buffer",
    )
    assert challenge["actor"]["name"] == "Owner Person"
    assert (challenge["target_kind"], challenge["target_id"]) == ("estimate_version", version_id)


# --- an Assumption --------------------------------------------------------------------------


def test_an_assumption_from_an_answered_gap_traces_its_whole_chain(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, _ = assessed(client, sync_engine, db_url, gateway)
    (a,) = all_assumptions(estimate(client, headers, opp["id"]))

    resp = chain(client, headers, opp["id"], a["id"])

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["kind"], body["version"]) == ("condition", 1)
    kinds = [s["kind"] for s in body["steps"]]
    assert kinds == ["gap", "question", "answer", "conversion", "acceptance"]
    origin, question, answer, conversion, acceptance = body["steps"]
    assert origin["title"] == WMS
    assert origin["actor"]["type"] == "agent"
    assert origin["superseded"] is False
    assert question["title"] == f"Could you tell us about {WMS.lower()}?"
    assert question["actor"]["name"] == "Owner Person"
    assert answer["actor"]["name"] == "Owner Person"
    assert answer["passage"] is not None
    (chip,) = answer["evidence"]
    assert chip["kind"] == "source_document"
    assert chip["passage_id"] == answer["passage"]["passage_id"]
    assert chip["label"].startswith("S")
    assert conversion["title"] == "Converted to a Condition"
    assert conversion["actor"]["name"] == "Owner Person"
    assert (acceptance["actor"]["name"], acceptance["version"]) == ("Owner Person", 1)


def test_a_sales_representative_reads_lineage_without_unapproved_questions(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = prepared(client, sync_engine, db_url, gateway)
    install(AgentGateway(AGREE))
    run(client, headers, opp["id"], db_url)
    provider.install(gateway)
    gateway.replies = [by_title(condition(WMS))]  # type: ignore[list-item]
    assert drain(db_url, PROPOSE) == ["succeeded"]
    view = estimate(client, headers, opp["id"])
    (a,) = all_assumptions(view)
    rep_h, rep = _user(client, sync_engine, "Rita Rep", REP)
    current = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    assert _add(client, headers, current, rep).status_code == 200

    line = line_lineage(client, rep_h, opp["id"], lines_by_title(view)[SAP]["id"])
    resp = chain(client, rep_h, opp["id"], a["id"])

    assert line["requirements"]
    assert resp.status_code == 200, resp.text
    # The question is only drafted: the sales representative doesn't see it; the owner does.
    assert [s["kind"] for s in resp.json()["steps"]] == ["gap"]
    owner = chain(client, headers, opp["id"], a["id"]).json()
    assert [s["kind"] for s in owner["steps"]] == ["gap", "question"]


def test_others_and_other_opportunities_get_404(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp, _ = assessed(client, sync_engine, db_url, gateway)
    view = estimate(client, headers, opp["id"])
    sap = lines_by_title(view)[SAP]
    (a,) = all_assumptions(view)
    stranger_h, _ = _user(client, sync_engine, "Sam Stranger", PSE)
    other = _create(client, stranger_h)

    for resp in (
        lineage(client, stranger_h, opp["id"], sap["id"]),
        chain(client, stranger_h, opp["id"], a["id"]),
        lineage(client, stranger_h, other["id"], sap["id"]),
        chain(client, stranger_h, other["id"], a["id"]),
        lineage(client, headers, opp["id"], str(uuid4())),
        chain(client, headers, opp["id"], str(uuid4())),
    ):
        assert_problem(resp.json(), 404, "not_found")
    assert lineage(client, headers, opp["id"], "not-a-uuid").status_code == 422


@pytest.mark.parametrize("path", ["estimate-lines", "assumptions"])
def test_unknown_ids_are_404(client: TestClient, sync_engine: Engine, path: str) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)
    resp = client.get(f"{BASE}/{opp['id']}/{path}/{uuid4()}/lineage", headers=headers)
    assert_problem(resp.json(), 404, "not_found")
