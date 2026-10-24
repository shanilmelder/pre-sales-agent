"""Blocking Findings and overrides (Story 6.6) against a real, migrated Postgres as psa_app,
with the fake ModelGateway and hidden jobs of `test_intake_extraction.py`: Red Team Findings'
status, `get_blocking_findings`, Supply Evidence, Mark resolved, Override (R1) and its
carry-over, `If-Match` (428/412), 409, 422, who may, the Evidence picker, privacy and the
grants. (The Critic's security-discipline Findings are covered in `test_assessments_critic.py`.)
"""

import json
import logging
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.assessments.application import public as assessments
from app.modules.assessments.domain.findings import fingerprint, line_key
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.uow import unit_of_work
from tests import test_assessments_red_team as red_team_tests
from tests import test_estimates_draft as draft_tests
from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests.conftest import run_async
from tests.test_assessments_red_team import drafted, finding, findings_out
from tests.test_estimates_draft import est_line, lines_out
from tests.test_gaps_detection import rows
from tests.test_gaps_mandatory import publish
from tests.test_health import assert_problem
from tests.test_intake_extraction import BASE, DRAFT, RED_TEAM, FakeGateway, drain
from tests.test_knowledge_checklists import _author, _item
from tests.test_opportunities import PSE, _add, _user
from tests.test_role_admin import _admin

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile
_draft_profile = draft_tests._draft_profile
_review_profile = red_team_tests._review_profile

REASON = "Customer confirmed the seasonal profile on the call."
RESOLVED = "assessments.finding.resolved"
OVERRIDDEN = "assessments.finding.overridden"

# Two critical, one high and one more critical (to be overridden): the matrix's blocking case.
FOUR = (
    finding("Peak 900 orders/hour — no seasonal profile", ["R3"], severity="critical"),
    finding("SAP custom fields — IDoc mapping unknown", ["R1"], severity="critical"),
    finding("24/7 support — no on-call model priced", ["R2"], severity="high"),
    finding(
        "Single sign-on — identity provider not named",
        ["R4"],
        category="hidden_dependency",
        severity="critical",
    ),
)


# --- helpers --------------------------------------------------------------------------------


def reviewed(
    client: TestClient,
    engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    *items: dict[str, Any],
) -> tuple[dict[str, str], dict[str, Any]]:
    """An Opportunity with a Red Team Review of these Findings (FOUR by default)."""
    headers, opp = drafted(client, engine, db_url, gateway)
    gateway.replies = [findings_out(*(items or FOUR))]
    assert drain(db_url, RED_TEAM) == ["succeeded"]
    return headers, client.get(f"{BASE}/{opp['id']}", headers=headers).json()


def red_team(client: TestClient, headers: dict[str, str], opp_id: str) -> dict[str, Any]:
    response = client.get(f"{BASE}/{opp_id}/red-team", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def by_title(view: dict[str, Any], title: str) -> dict[str, Any]:
    return next(f for f in view["review"]["findings"] if f["title"].startswith(title))


def _post(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    found: dict[str, Any],
    verb: str,
    body: dict[str, Any],
    *,
    version: int | None = None,
) -> Any:
    v = found["row_version"] if version is None else version
    return client.post(
        f"{BASE}/{opp_id}/findings/{found['id']}/{verb}",
        headers={**headers, "If-Match": f'"{v}"'},
        json=body,
    )


def override(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    found: dict[str, Any],
    reason: str = REASON,
    **kw: Any,
) -> Any:
    return _post(client, headers, opp_id, found, "override", {"reason": reason}, **kw)


def resolve(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    found: dict[str, Any],
    reason: Any = REASON,
) -> Any:
    return _post(client, headers, opp_id, found, "resolution", {"reason": reason})


def supply(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    found: dict[str, Any],
    refs: list[dict[str, Any]],
    note: str = REASON,
) -> Any:
    return _post(client, headers, opp_id, found, "evidence", {"refs": refs, "note": note})


def finding_events(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM platform_trace_events WHERE opportunity_id = :o "
        "AND event_type LIKE 'assessments.finding.%' ORDER BY occurred_at, id",
        o=opp_id,
    )


def blocking(db_url: str, opp_id: str) -> list[assessments.BlockingFinding]:
    async def scenario() -> list[assessments.BlockingFinding]:
        engine = create_engine(Settings(database_url=db_url))
        try:
            async with unit_of_work(engine) as uow:
                return await assessments.get_blocking_findings(uow, UUID(opp_id))
        finally:
            await engine.dispose()

    return run_async(scenario())


def requirement_ref(client: TestClient, headers: dict[str, str], opp_id: str) -> dict[str, Any]:
    reqs = client.get(f"{BASE}/{opp_id}/requirements", headers=headers).json()["items"]
    return {"kind": "requirement", "id": reqs[0]["id"], "version": reqs[0]["version"]}


def member(
    client: TestClient,
    engine: Engine,
    headers: dict[str, str],
    opp: dict[str, Any],
    name: str,
    role: str,
) -> tuple[dict[str, str], dict[str, Any]]:
    """A new collaborator with `role`; returns their headers and the Opportunity as now."""
    user, user_id = _user(client, engine, name, role)
    added = _add(client, headers, opp, user_id)
    assert added.status_code == 200, added.text
    return user, added.json()


# --- blocking -------------------------------------------------------------------------------


def test_open_critical_findings_block_and_an_override_stops_one_blocking(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = reviewed(client, sync_engine, db_url, gateway)
    view = red_team(client, headers, opp["id"])
    assert view["blocking_count"] == 3
    sso = by_title(view, "Single sign-on")
    assert (sso["status"], sso["overridable"], sso["can_resolve"], sso["can_override"]) == (
        "open",
        True,
        True,
        True,
    )
    assert (sso["resolution"], sso["override"], sso["previous_override"], sso["row_version"]) == (
        None,
        None,
        None,
        1,
    )

    assert override(client, headers, opp["id"], sso).status_code == 200

    found = blocking(db_url, opp["id"])
    assert len(found) == 2
    assert {b.review_kind for b in found} == {"red_team"}
    assert {b.review_version for b in found} == {1}
    titles = {by_title(view, t)["id"] for t in ("Peak 900", "SAP custom")}
    assert {str(b.finding_id) for b in found} == titles
    assert red_team(client, headers, opp["id"])["blocking_count"] == 2


# --- Supply Evidence ------------------------------------------------------------------------


def test_the_owner_supplies_evidence_and_the_finding_is_resolved(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    headers, opp = reviewed(client, sync_engine, db_url, gateway)
    peak = by_title(red_team(client, headers, opp["id"]), "Peak 900")
    ref = requirement_ref(client, headers, opp["id"])
    (source,) = client.get(f"{BASE}/{opp['id']}/sources", headers=headers).json()["items"]
    source_ref = {"kind": "source_document", "id": source["id"], "version": source["version"]}
    me = client.get("/api/v1/me", headers=headers).json()

    with caplog.at_level(logging.DEBUG):
        answer = supply(client, headers, opp["id"], peak, [ref, source_ref])

    assert answer.status_code == 200, answer.text
    assert answer.headers["ETag"] == '"2"'
    state = answer.json()
    assert (state["status"], state["row_version"], state["can_resolve"]) == ("resolved", 2, False)
    resolution = state["resolution"]
    assert (resolution["kind"], resolution["reason"]) == ("evidence_supplied", REASON)
    assert resolution["by"] == {"id": me["id"], "name": me["name"]}
    assert [(e["kind"], e["label"]) for e in resolution["evidence"]] == [
        ("requirement", "R1"),
        ("source_document", f"S1 · {source['filename']}"),
    ]
    (event,) = finding_events(sync_engine, opp["id"])
    assert (event["event_type"], str(event["subject_id"]), event["subject_version"]) == (
        RESOLVED,
        peak["id"],
        2,
    )
    assert event["subject_type"] == "assessments.finding"
    assert event["payload"]["kind"] == "evidence_supplied"
    assert event["payload"]["reason"] == REASON
    assert event["payload"]["review_kind"] == "red_team"
    assert [e["kind"] for e in event["payload"]["evidence"]] == [
        "requirement",
        "source_document",
    ]
    assert red_team(client, headers, opp["id"])["blocking_count"] == 2
    assert REASON not in caplog.text
    assert "Peak 900" not in caplog.text


def test_unresolvable_or_foreign_evidence_is_422_and_changes_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = reviewed(client, sync_engine, db_url, gateway)
    peak = by_title(red_team(client, headers, opp["id"]), "Peak 900")
    other_headers, other = reviewed(client, sync_engine, db_url, gateway, FOUR[0])
    foreign = requirement_ref(client, other_headers, other["id"])
    (other_source,) = client.get(f"{BASE}/{other['id']}/sources", headers=other_headers).json()[
        "items"
    ]
    foreign_source = {
        "kind": "source_document",
        "id": other_source["id"],
        "version": other_source["version"],
    }
    mine = requirement_ref(client, headers, opp["id"])

    for refs in (
        [{"kind": "requirement", "id": str(uuid4()), "version": 1}],
        [{**mine, "version": 9}],
        [foreign],
        [foreign_source],
    ):
        answer = supply(client, headers, opp["id"], peak, refs)
        assert answer.status_code == 422, answer.text
        assert_problem(answer.json(), 422, "evidence_unresolvable")
    # Only Requirements and Sources may be cited (not, e.g., a Knowledge chunk).
    for refs in (
        [{"kind": "knowledge_chunk", "id": str(uuid4()), "version": 1}],
        [{**mine, "version": 2**31}],
    ):
        answer = supply(client, headers, opp["id"], peak, refs)
        assert answer.status_code == 422, answer.text
        assert_problem(answer.json(), 422, "validation_error")
    assert supply(client, headers, opp["id"], peak, [mine], note="x" * 4001).status_code == 422
    assert supply(client, headers, opp["id"], peak, []).status_code == 422
    assert supply(client, headers, opp["id"], peak, [mine], note=" ").status_code == 422

    assert by_title(red_team(client, headers, opp["id"]), "Peak 900")["status"] == "open"
    assert finding_events(sync_engine, opp["id"]) == []


def test_the_evidence_picker_lists_requirements_then_sources(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = reviewed(client, sync_engine, db_url, gateway, FOUR[0])
    rep, _ = member(client, sync_engine, headers, opp, "Rep Person", "sales_representative")

    answer = client.get(f"{BASE}/{opp['id']}/evidence-options", headers=rep)

    assert answer.status_code == 200, answer.text
    items = answer.json()["items"]
    kinds = [i["kind"] for i in items]
    assert kinds == ["requirement"] * 5 + ["source_document"]
    assert [i["label"] for i in items[:5]] == ["R1", "R2", "R3", "R4", "R5"]
    assert items[2]["excerpt"] == "Peak 900 orders/hour."
    assert items[5]["label"].startswith("S1 · ")
    outsider, _ = _user(client, sync_engine, "Outsider", PSE)
    assert client.get(f"{BASE}/{opp['id']}/evidence-options", headers=outsider).status_code == 404


# --- Mark resolved --------------------------------------------------------------------------


def test_mark_resolved_needs_a_reason(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = reviewed(client, sync_engine, db_url, gateway)
    peak = by_title(red_team(client, headers, opp["id"]), "Peak 900")

    for reason in ("", "   ", "x" * 1001):
        answer = resolve(client, headers, opp["id"], peak, reason)
        assert answer.status_code == 422, answer.text
        assert_problem(answer.json(), 422, "validation_error")
    missing = _post(client, headers, opp["id"], peak, "resolution", {})
    assert missing.status_code == 422
    assert finding_events(sync_engine, opp["id"]) == []

    answer = resolve(client, headers, opp["id"], peak)

    assert answer.status_code == 200, answer.text
    assert answer.json()["resolution"]["kind"] == "addressed"
    assert answer.json()["resolution"]["evidence"] == []
    (event,) = finding_events(sync_engine, opp["id"])
    assert (event["event_type"], event["payload"]["kind"]) == (RESOLVED, "addressed")


def test_a_collaborator_resolves_but_may_not_override(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = reviewed(client, sync_engine, db_url, gateway)
    colleague, _ = member(client, sync_engine, headers, opp, "Colleague", PSE)
    view = red_team(client, colleague, opp["id"])
    peak, sap = by_title(view, "Peak 900"), by_title(view, "SAP custom")
    assert (peak["can_resolve"], peak["can_override"]) == (True, False)

    denied = override(client, colleague, opp["id"], sap)
    assert denied.status_code == 403, denied.text
    assert_problem(denied.json(), 403, "forbidden")
    assert resolve(client, colleague, opp["id"], peak).status_code == 200


# --- Override (R1) --------------------------------------------------------------------------


def test_a_head_of_delivery_overrides_with_a_reason(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    headers, opp = reviewed(client, sync_engine, db_url, gateway)
    head, head_id = _user(client, sync_engine, "Head Person", "head_of_delivery")
    view = red_team(client, head, opp["id"])  # reads every Opportunity
    sap = by_title(view, "SAP custom")
    assert (sap["can_resolve"], sap["can_override"]) == (False, True)

    with caplog.at_level(logging.DEBUG):
        answer = override(client, head, opp["id"], sap)

    assert answer.status_code == 200, answer.text
    assert answer.headers["ETag"] == '"2"'
    state = answer.json()
    assert (state["status"], state["can_override"], state["resolution"]) == (
        "overridden",
        False,
        None,
    )
    assert state["override"]["reason"] == REASON
    assert state["override"]["by"] == {"id": str(head_id), "name": "Head Person"}
    assert (state["override"]["policy_basis"], state["override"]["review_version"]) == (
        "head_of_delivery",
        1,
    )
    (row,) = rows(
        sync_engine,
        "SELECT * FROM assessments_finding_overrides WHERE finding_id = :f",
        f=sap["id"],
    )
    assert (row["review_kind"], row["review_version"], row["overridden_by"]) == (
        "red_team",
        1,
        head_id,
    )
    assert (row["reason"], row["policy_basis"]) == (REASON, "head_of_delivery")
    (event,) = finding_events(sync_engine, opp["id"])
    assert event["event_type"] == OVERRIDDEN
    assert event["payload"]["person_id"] == str(head_id)
    assert event["payload"]["reason"] == REASON
    assert event["payload"]["override_id"] == str(row["id"])
    assert event["payload"]["previous_override_id"] is None
    assert REASON not in caplog.text

    again = override(client, head, opp["id"], state)
    assert again.status_code == 409, again.text
    assert_problem(again.json(), 409, "finding_not_open")
    assert resolve(client, headers, opp["id"], {**sap, "row_version": 2}).status_code == 409


def test_the_owner_overrides_and_the_view_shows_who_and_why(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = reviewed(client, sync_engine, db_url, gateway)
    sso = by_title(red_team(client, headers, opp["id"]), "Single sign-on")

    assert override(client, headers, opp["id"], sso).status_code == 200

    shown = by_title(red_team(client, headers, opp["id"]), "Single sign-on")
    assert shown["status"] == "overridden"
    assert (shown["override"]["by"]["name"], shown["override"]["reason"]) == (
        "Owner Person",
        REASON,
    )
    assert shown["override"]["policy_basis"] == "owner"


def test_a_security_reviewer_may_not_override_a_non_security_finding(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = reviewed(client, sync_engine, db_url, gateway)
    reviewer, _ = member(client, sync_engine, headers, opp, "Sec Person", "security_reviewer")
    sap = by_title(red_team(client, reviewer, opp["id"]), "SAP custom")
    assert sap["can_override"] is False

    answer = override(client, reviewer, opp["id"], sap)

    assert answer.status_code == 403, answer.text
    assert_problem(answer.json(), 403, "forbidden")
    assert by_title(red_team(client, headers, opp["id"]), "SAP custom")["status"] == "open"


def test_a_sales_rep_may_do_nothing_and_sees_no_actions(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = reviewed(client, sync_engine, db_url, gateway)
    rep, _ = member(client, sync_engine, headers, opp, "Rep Person", "sales_representative")
    view = red_team(client, rep, opp["id"])
    sap = by_title(view, "SAP custom")
    assert {(f["can_resolve"], f["can_override"]) for f in view["review"]["findings"]} == {
        (False, False)
    }
    ref = requirement_ref(client, headers, opp["id"])

    for answer in (
        override(client, rep, opp["id"], sap),
        resolve(client, rep, opp["id"], sap),
        supply(client, rep, opp["id"], sap, [ref]),
    ):
        assert answer.status_code == 403, answer.text
        assert_problem(answer.json(), 403, "forbidden")
    assert finding_events(sync_engine, opp["id"]) == []
    outsider, _ = _user(client, sync_engine, "Outsider", PSE)
    assert override(client, outsider, opp["id"], sap).status_code == 404


@pytest.mark.parametrize("domain", ["security", "delivery"])
def test_only_a_mandatory_security_item_makes_a_finding_not_overridable_by_anyone(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway, domain: str
) -> None:
    headers, opp = drafted(client, sync_engine, db_url, gateway)
    author = _author(client)
    checklist = publish(
        client,
        author,
        items=[_item(text="Is a pen test required?", mandatory=True)],
        domain=domain,
        products=[f"Product {uuid4().hex[:10]}"],  # applies to no Opportunity
    )
    item_id = checklist["items"][0]["id"]
    reqs = client.get(f"{BASE}/{opp['id']}/requirements", headers=headers).json()["items"]
    gap_id = uuid4()
    trigger = {
        "kind": "checklist_item",
        "checklist_id": checklist["id"],
        "version": checklist["current_version"],
        "item_id": item_id,
        "checklist_name": checklist["name"],
    }
    with sync_engine.begin() as conn:  # a mandatory security Gap linked to R3
        conn.execute(
            sa.text(
                "INSERT INTO gaps_gaps (id, opportunity_id, title, category, trigger, "
                "why_it_matters, impact, impact_basis, origin, status, row_version) VALUES "
                "(:i, :o, 'Is a pen test required?', 'security_and_compliance', "
                "CAST(:t AS jsonb), 'Why.', 'high', 'Default.', 'mandatory_checklist', 'open', 1)"
            ),
            {"i": gap_id, "o": opp["id"], "t": json.dumps(trigger)},
        )
        conn.execute(
            sa.text(
                "INSERT INTO gaps_gap_requirements (gap_id, requirement_id, requirement_version) "
                "VALUES (:g, :r, :v)"
            ),
            {"g": gap_id, "r": reqs[2]["id"], "v": reqs[2]["version"]},
        )
    gateway.replies = [findings_out(*FOUR)]
    assert drain(db_url, RED_TEAM) == ["succeeded"]
    admin, _ = _admin(client)
    view = red_team(client, headers, opp["id"])
    peak = by_title(view, "Peak 900")
    if domain != "security":  # a mandatory item of another domain doesn't tie it
        assert (peak["policy_ref"], peak["overridable"], peak["can_override"]) == (
            None,
            True,
            True,
        )
        assert override(client, admin, opp["id"], peak).status_code == 403  # no grant
        assert override(client, headers, opp["id"], peak).status_code == 200
        return
    assert peak["policy_ref"] == {
        "kind": "checklist_item",
        "checklist_id": checklist["id"],
        "version": checklist["current_version"],
        "item_id": item_id,
    }
    assert (peak["overridable"], peak["can_override"], peak["can_resolve"]) == (False, False, True)
    assert by_title(view, "SAP custom")["policy_ref"] is None

    for who in (admin, headers):
        answer = override(client, who, opp["id"], peak)
        assert answer.status_code == 422, answer.text
        assert_problem(answer.json(), 422, "finding_not_overridable")
    assert by_title(red_team(client, headers, opp["id"]), "Peak 900")["status"] == "open"
    assert resolve(client, headers, opp["id"], peak).status_code == 200  # still resolvable


# --- If-Match -------------------------------------------------------------------------------


def test_a_stale_or_missing_if_match_changes_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = reviewed(client, sync_engine, db_url, gateway)
    colleague, _ = member(client, sync_engine, headers, opp, "Colleague Person", PSE)
    peak = by_title(red_team(client, headers, opp["id"]), "Peak 900")
    assert resolve(client, colleague, opp["id"], peak).status_code == 200

    stale = override(client, headers, opp["id"], peak)
    assert stale.status_code == 412, stale.text
    assert_problem(stale.json(), 412, "row_version_mismatch")
    assert stale.json()["detail"] == "Changed by Colleague Person since you opened it."

    sap = by_title(red_team(client, headers, opp["id"]), "SAP custom")
    missing = client.post(
        f"{BASE}/{opp['id']}/findings/{sap['id']}/override",
        headers=headers,
        json={"reason": REASON},
    )
    assert missing.status_code == 428, missing.text
    assert_problem(missing.json(), 428, "if_match_required")
    unknown = override(client, headers, opp["id"], {**sap, "id": str(uuid4())})
    assert unknown.status_code == 404
    assert len(finding_events(sync_engine, opp["id"])) == 1


# --- carry-over -----------------------------------------------------------------------------


def test_a_rerun_raising_the_same_fingerprint_shows_the_previous_override(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = reviewed(client, sync_engine, db_url, gateway, FOUR[1], FOUR[2])
    sap = by_title(red_team(client, headers, opp["id"]), "SAP custom")
    assert override(client, headers, opp["id"], sap).status_code == 200
    assert client.post(f"{BASE}/{opp['id']}/estimate-drafts", headers=headers).status_code == 201
    gateway.replies = [lines_out(est_line("Everything", ["R1", "R2", "R3", "R4", "R5"]))]
    assert drain(db_url, DRAFT) == ["succeeded"]
    reworded = {**FOUR[1], "title": "SAP custom fields — still unmapped"}
    gateway.replies = [findings_out(reworded, FOUR[2])]
    assert drain(db_url, RED_TEAM) == ["succeeded"]

    view = red_team(client, headers, opp["id"])

    assert view["review"]["version"] == 2
    newer = by_title(view, "SAP custom")
    assert newer["id"] != sap["id"]
    assert (newer["status"], newer["override"]) == ("open", None)  # nothing carried over
    previous = newer["previous_override"]
    assert (previous["reason"], previous["by"]["name"], previous["review_version"]) == (
        REASON,
        "Owner Person",
        1,
    )
    assert by_title(view, "24/7 support")["previous_override"] is None
    assert view["blocking_count"] == 1
    # Only the current Review's Findings block: none of the superseded v1's.
    (only,) = blocking(db_url, opp["id"])
    assert (str(only.finding_id), only.review_version) == (newer["id"], 2)
    # The superseded Finding can no longer be acted on.
    old = resolve(client, headers, opp["id"], {**sap, "row_version": 2})
    assert old.status_code == 409
    assert_problem(old.json(), 409, "finding_not_open")

    reapplied = override(client, headers, opp["id"], newer, previous["reason"])

    assert reapplied.status_code == 200, reapplied.text
    assert red_team(client, headers, opp["id"])["blocking_count"] == 0
    *_, event = finding_events(sync_engine, opp["id"])
    assert event["payload"]["previous_override_id"] == previous["id"]


# --- fingerprint, grants --------------------------------------------------------------------


def test_red_team_fingerprints_use_requirements_and_line_keys(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    item = finding("SAP fields", ["R1", "R2"], lines=["SAP order interface"])
    _, opp = reviewed(client, sync_engine, db_url, gateway, item)
    (row,) = rows(
        sync_engine,
        "SELECT f.* FROM assessments_findings f JOIN assessments_reviews r ON r.id = f.review_id "
        "WHERE r.opportunity_id = :o",
        o=opp["id"],
    )
    links = rows(
        sync_engine,
        "SELECT requirement_id FROM assessments_finding_requirements WHERE finding_id = :f",
        f=row["id"],
    )
    (line,) = rows(
        sync_engine,
        "SELECT l.section, l.title FROM assessments_finding_lines fl "
        "JOIN estimates_estimate_lines l ON l.id = fl.line_id WHERE fl.finding_id = :f",
        f=row["id"],
    )
    assert row["fingerprint"] == fingerprint(
        "red_team",
        "integration_harder",
        [link["requirement_id"] for link in links],
        [line_key(line["section"], line["title"])],
    )
    assert (row["security_discipline"], row["policy_ref"], row["previous_override_id"]) == (
        False,
        None,
        None,
    )


def test_the_migration_fingerprint_is_the_apps() -> None:
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20261024_0042_blocking_findings.py"
    )
    spec = importlib.util.spec_from_file_location("m0042", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ids = [uuid4(), uuid4()]
    assert module.fingerprint("critic", "coverage", ids, ["b", "a"]) == fingerprint(
        "critic", "coverage", reversed(ids), ["a", "b"]
    )
    assert module.line_key(" Functional ", "SAP  order") == line_key("functional", "sap order")


def test_only_status_resolution_and_row_version_are_updatable_for_psa_app(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = reviewed(client, sync_engine, db_url, gateway, FOUR[1])
    sap = by_title(red_team(client, headers, opp["id"]), "SAP custom")
    assert override(client, headers, opp["id"], sap).status_code == 200
    peak_headers, peak_opp = reviewed(client, sync_engine, db_url, gateway, FOUR[0])
    peak = by_title(red_team(client, peak_headers, peak_opp["id"]), "Peak 900")
    ref = requirement_ref(client, peak_headers, peak_opp["id"])
    assert supply(client, peak_headers, peak_opp["id"], peak, [ref]).status_code == 200
    denied = [
        ("UPDATE assessments_findings SET fingerprint = 'x' WHERE id = :i", sap["id"]),
        ("UPDATE assessments_findings SET policy_ref = NULL WHERE id = :i", sap["id"]),
        ("UPDATE assessments_findings SET severity = 'low' WHERE id = :i", sap["id"]),
        ("DELETE FROM assessments_findings WHERE id = :i", sap["id"]),
        ("UPDATE assessments_finding_overrides SET reason = 'x' WHERE finding_id = :i", sap["id"]),
        ("DELETE FROM assessments_finding_overrides WHERE finding_id = :i", sap["id"]),
        (
            "UPDATE assessments_finding_evidence SET ref_version = 9 WHERE finding_id = :i",
            peak["id"],
        ),
        ("DELETE FROM assessments_finding_evidence WHERE finding_id = :i", peak["id"]),
    ]
    for sql, value in denied:
        with pytest.raises(sa.exc.ProgrammingError), sync_engine.begin() as conn:
            conn.execute(sa.text(sql), {"i": value})
    with sync_engine.begin() as conn:  # the status columns are psa_app's to update
        conn.execute(
            sa.text("UPDATE assessments_findings SET row_version = row_version WHERE id = :i"),
            {"i": sap["id"]},
        )
