"""Review outcomes, replies and superseded requests (Story 9.4) against a real, migrated
Postgres as psa_app: the reply rules (no DB), then every row of the story's matrix (one outcome
item when the owner sent the request, one each otherwise; an Evidence reply; replies that
aren't allowed; an alternative linked on submit; submitting v4 over a pending and an approved
request; New version; an escalation in the author's panel), no reminders after superseding,
the Inbox subject of outcome and superseded items, append-only replies and the migration's
down/up.

Estimate Versions, lines, Assumptions, Risks and Requirements are inserted directly; people
sign in through `/me` with their roles (see `test_reviews_requests`).
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.notifications.domain.notifications import KIND_GROUP, InboxGroup, NotificationKind
from app.modules.reviews.domain.decisions import Decision, outcome_summary
from app.modules.reviews.domain.replies import (
    REPLY_MAX,
    clean_reply_message,
    may_link_alternative,
    may_reply,
)
from tests import test_opportunities as opportunity_tests
from tests.test_gaps_detection import rows
from tests.test_health import assert_problem
from tests.test_intake_parse_job import _alembic
from tests.test_notifications_inbox import _age, _items, _remind
from tests.test_opportunities import BASE, PSE, _add, _create, _user
from tests.test_reviews_decisions import REASON, _decide, _panel, _sent
from tests.test_reviews_requests import (
    ENG,
    _collaborator_rows,
    _events,
    _requests,
    _send,
    _setup,
    _status,
    _version,
)

client = opportunity_tests.client

INBOX = "/api/v1/inbox"
REPLIED = "reviews.review_request.replied"
SUPERSEDED = "reviews.review_request.superseded"
ANSWER = "R4 says the WMS adapter reuses the existing API."


# --- the rules (no DB) ----------------------------------------------------------------------


def test_only_requests_for_evidence_or_an_alternative_take_a_reply() -> None:
    assert may_reply(Decision.EVIDENCE_REQUESTED)
    assert may_reply(Decision.ALTERNATIVE_REQUESTED)
    for other in set(Decision) - {Decision.EVIDENCE_REQUESTED, Decision.ALTERNATIVE_REQUESTED}:
        assert not may_reply(other)
    assert not may_reply(None)
    assert may_link_alternative(Decision.ALTERNATIVE_REQUESTED)
    assert not may_link_alternative(Decision.EVIDENCE_REQUESTED)


def test_the_reply_message_rule() -> None:
    assert clean_reply_message("  See R4  ") == "See R4"
    assert clean_reply_message("x" * REPLY_MAX) == "x" * REPLY_MAX
    for bad in ("", "   ", "x" * (REPLY_MAX + 1)):
        with pytest.raises(ValueError):
            clean_reply_message(bad)


def test_outcome_summaries_and_kinds() -> None:
    assert (
        outcome_summary("Ana Ruiz", Decision.REJECTED, "Estimate v3", "Too high")
        == "Ana Ruiz rejected Estimate v3: Too high"
    )
    assert outcome_summary("Ana Ruiz", Decision.APPROVED, "Estimate v3", None) == (
        "Ana Ruiz approved Estimate v3"
    )
    assert KIND_GROUP[NotificationKind.REVIEW_OUTCOME] == InboxGroup.REVIEWS
    assert KIND_GROUP[NotificationKind.REVIEW_REPLIED] == InboxGroup.REVIEWS


# --- helpers --------------------------------------------------------------------------------


def _reply(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    request: dict[str, Any],
    message: str = ANSWER,
    evidence: list[dict[str, Any]] | None = None,
    alternative: str | None = None,
    row_version: int | None = None,
) -> Any:
    rv = request["row_version"] if row_version is None else row_version
    body: dict[str, Any] = {"message": message, "evidence": evidence or []}
    if alternative is not None:
        body["alternative_version_id"] = alternative
    return client.post(
        f"{BASE}/{opp_id}/review-requests/{request['id']}/replies",
        headers={**headers, "If-Match": f'"{rv}"'},
        json=body,
    )


def _inbox(client: TestClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    resp = client.get(INBOX, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]  # type: ignore[no-any-return]


def _of_kind(items: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [i for i in items if i["kind"] == kind]


def _requirement(engine: Engine, opp_id: str, number: int) -> dict[str, Any]:
    """An active Requirement `R<number>` at version 1, as an Evidence reference."""
    requirement_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO intake_requirements (id, opportunity_id, text, classification, "
                "origin, locked_by_human, status, version, row_version, number) VALUES "
                "(:i, :o, 'The WMS adapter reuses the API.', 'integration', 'extracted', false, "
                "'active', 1, 1, :n)"
            ),
            {"i": requirement_id, "o": opp_id, "n": number},
        )
        conn.execute(
            sa.text(
                "INSERT INTO intake_requirement_versions (requirement_id, version, text, "
                "classification, created_by) VALUES (:i, 1, 'The WMS adapter reuses the API.', "
                "'integration', 'test')"
            ),
            {"i": requirement_id},
        )
    return {"kind": "requirement", "id": str(requirement_id), "version": 1}


def _submit(
    client: TestClient, engine: Engine, headers: dict[str, str], opp_id: str, version_id: str
) -> Any:
    (found,) = rows(
        engine, "SELECT row_version FROM estimates_estimate_versions WHERE id = :i", i=version_id
    )
    return client.post(
        f"{BASE}/{opp_id}/estimate/versions/{version_id}/submit",
        headers={**headers, "If-Match": f'"{found["row_version"]}"'},
    )


def _new_version(
    client: TestClient, headers: dict[str, str], opp_id: str, version_id: str, reason: str | None
) -> Any:
    return client.post(
        f"{BASE}/{opp_id}/estimate-versions/{version_id}/new-version",
        headers=headers,
        json={} if reason is None else {"reason": reason},
    )


# --- outcomes -------------------------------------------------------------------------------


def test_the_owner_who_sent_it_gets_one_outcome_item(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, owner_id, opp, v3, [(ana_h, ana)], [request] = _sent(
        client, sync_engine, "Ana Reviewer"
    )

    resp = _decide(client, ana_h, opp["id"], request, "rejected")

    assert resp.status_code == 201, resp.text
    decision_id = resp.json()["decision"]["id"]
    (item,) = [i for i in _items(sync_engine, owner_id) if i["kind"] == "review_outcome"]
    assert item["summary"] == f"Ana Reviewer rejected Estimate v3: {REASON}"
    assert item["dedupe_key"] == f"review:{request['id']}:outcome:{decision_id}:{owner_id}"
    assert not [i for i in _items(sync_engine, ana) if i["kind"] == "review_outcome"]
    (listed,) = _of_kind(_inbox(client, headers), "review_outcome")
    assert listed["group"] == "reviews"
    assert (listed["subject_status"], listed["subject_open"], listed["href"]) == (
        "rejected",
        False,
        None,
    )

    panel = _panel(client, headers, opp["id"], request["id"]).json()
    assert (panel["is_author"], panel["can_decide"], panel["can_reply"]) == (True, False, False)
    assert panel["can_create_version"] is True
    assert panel["decisions"][0]["reason"] == REASON
    estimate = client.get(f"{BASE}/{opp['id']}/estimate", headers=headers).json()
    assert estimate["can_create_version"] is True
    assert _status(sync_engine, v3) == "rejected"


def test_the_owner_and_another_sender_each_get_one(client: TestClient, sync_engine: Engine) -> None:
    headers, owner_id, opp, v3 = _setup(client, sync_engine)
    ben_h, ben = _user(client, sync_engine, "Ben Presales", PSE)
    assert _add(client, headers, opp, ben).status_code == 200
    ana_h, ana = _user(client, sync_engine, "Ana Reviewer", ENG)
    (request,) = _send(client, ben_h, opp["id"], v3, 1, [ana]).json()["items"]

    assert _decide(client, ana_h, opp["id"], request, "approved", reason=None).status_code == 201

    for who in (owner_id, ben):
        (item,) = [i for i in _items(sync_engine, who) if i["kind"] == "review_outcome"]
        assert item["summary"] == "Ana Reviewer approved Estimate v3"
    panel = _panel(client, ben_h, opp["id"], request["id"]).json()
    assert panel["is_author"] is True
    assert panel["version_status"] == "approved"


# --- replies --------------------------------------------------------------------------------


def test_an_evidence_reply_keeps_the_request_pending(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, owner_id, opp, _, [(ana_h, ana)], [request] = _sent(
        client, sync_engine, "Ana Reviewer"
    )
    r4 = _requirement(sync_engine, opp["id"], 4)
    asked = _decide(client, ana_h, opp["id"], request, "evidence_requested").json()["request"]
    panel = _panel(client, headers, opp["id"], request["id"]).json()
    assert (panel["can_reply"], panel["can_link_alternative"]) == (True, False)
    (outcome,) = _of_kind(_inbox(client, headers), "review_outcome")
    # Open while the request is pending, never "Escalated".
    assert (outcome["subject_status"], outcome["subject_open"]) == ("pending", True)
    assert outcome["href"] == f"/opportunities/{opp['id']}/estimate?review={request['id']}"

    resp = _reply(client, headers, opp["id"], asked, evidence=[r4])

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["request"]["status"] == "pending"
    assert body["request"]["row_version"] == asked["row_version"] + 1
    assert resp.headers["ETag"] == f'"{body["request"]["row_version"]}"'
    assert body["reply"]["message"] == ANSWER
    assert body["reply"]["evidence"] == [{**r4, "label": "R4"}]
    assert body["reply"]["replied_by"] == {"id": str(owner_id), "name": "Owner Person"}
    (event,) = _events(sync_engine, opp["id"], REPLIED)
    assert event["payload"] == {
        "request_id": request["id"],
        "reply_id": body["reply"]["id"],
        "evidence": [r4],
        "has_alternative": False,
        "alternative_version_id": None,
        "message_length": len(ANSWER),
    }
    assert ANSWER not in str(event["payload"])
    (item,) = [i for i in _items(sync_engine, ana) if i["kind"] == "review_replied"]
    assert item["summary"] == "Reply on Estimate v3"
    (listed,) = _of_kind(_inbox(client, ana_h), "review_replied")
    assert listed["subject_open"] is True

    panel = _panel(client, ana_h, opp["id"], request["id"]).json()
    assert panel["can_decide"] is True
    assert [r["evidence"][0]["label"] for r in panel["replies"]] == ["R4"]


def test_a_reply_needs_a_message_resolving_evidence_and_a_fresh_row_version(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _, opp, _, [(ana_h, _)], [request] = _sent(client, sync_engine, "Ana Reviewer")
    asked = _decide(client, ana_h, opp["id"], request, "evidence_requested").json()["request"]
    unknown = {"kind": "requirement", "id": str(uuid4()), "version": 1}
    other_headers, _ = _user(client, sync_engine, "Other Owner", PSE)
    other = _create(client, other_headers)
    foreign = _requirement(sync_engine, other["id"], 1)

    resp = _reply(client, headers, opp["id"], asked, evidence=[unknown])
    assert_problem(resp.json(), 422, "evidence_unresolvable")
    assert unknown["id"] in resp.json()["detail"]
    resp = _reply(client, headers, opp["id"], asked, evidence=[foreign])
    assert_problem(resp.json(), 422, "evidence_unresolvable")
    assert_problem(
        _reply(client, headers, opp["id"], asked, message="  ").json(), 422, "validation_error"
    )
    stale = _reply(client, headers, opp["id"], asked, row_version=asked["row_version"] - 1)
    assert_problem(stale.json(), 412, "row_version_mismatch")
    assert stale.json()["detail"] == "Changed by Ana Reviewer since you opened it."
    assert _events(sync_engine, opp["id"], REPLIED) == []
    assert (
        rows(
            sync_engine,
            "SELECT id FROM reviews_review_replies WHERE review_request_id = :r",
            r=request["id"],
        )
        == []
    )


def test_a_reply_is_only_for_the_author_on_a_request_for_more(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _, opp, _, [(ana_h, _), (ben_h, _)], [ana_req, ben_req] = _sent(
        client, sync_engine, "Ana Reviewer", "Ben Reviewer"
    )
    # Nothing asked yet.
    assert_problem(
        _reply(client, headers, opp["id"], ana_req).json(), 409, "review_reply_not_expected"
    )
    asked = _decide(client, ana_h, opp["id"], ana_req, "evidence_requested").json()["request"]
    # The reviewer can't reply to themselves.
    assert_problem(_reply(client, ana_h, opp["id"], asked).json(), 403, "forbidden")
    # Approved: no longer pending.
    approved = _decide(client, ben_h, opp["id"], ben_req, "approved", reason=None).json()
    assert_problem(
        _reply(client, headers, opp["id"], approved["request"]).json(),
        409,
        "review_request_not_pending",
    )
    assert _events(sync_engine, opp["id"], REPLIED) == []


# --- alternatives and superseding -----------------------------------------------------------


def test_an_alternative_is_linked_when_its_draft_is_submitted(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, owner_id, opp, v3, [(ana_h, ana)], [request] = _sent(
        client, sync_engine, "Ana Reviewer"
    )
    asked = _decide(client, ana_h, opp["id"], request, "alternative_requested").json()["request"]
    panel = _panel(client, headers, opp["id"], request["id"]).json()
    assert (panel["can_reply"], panel["can_link_alternative"]) == (True, False)  # no draft yet
    v4 = _version(sync_engine, opp["id"], 4, status="draft", created_by=owner_id)
    panel = _panel(client, headers, opp["id"], request["id"]).json()
    assert panel["can_link_alternative"] is True
    assert panel["alternative_draft"] == {"id": v4, "version": 4}

    # Not a newer draft: v3 itself, and an evidence reply can't link one.
    assert_problem(
        _reply(client, headers, opp["id"], asked, alternative=v3).json(), 422, "validation_error"
    )
    resp = _reply(client, headers, opp["id"], asked, alternative=v4)
    assert resp.status_code == 201, resp.text
    assert resp.json()["reply"]["alternative"] == {"id": v4, "version": 4}
    (replied,) = _events(sync_engine, opp["id"], REPLIED)
    assert (
        replied["payload"]["has_alternative"],
        replied["payload"]["alternative_version_id"],
    ) == (
        True,
        v4,
    )

    submitted = _submit(client, sync_engine, headers, opp["id"], v4)

    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "in_review"
    stored = {str(r["id"]): r for r in _requests(sync_engine, opp["id"])}
    assert stored[request["id"]]["status"] == "superseded"
    (linked,) = [r for r in stored.values() if r["linked_request_id"] is not None]
    assert str(linked["linked_request_id"]) == request["id"]
    assert (linked["reviewer_id"], linked["status"], str(linked["estimate_version_id"])) == (
        ana,
        "pending",
        v4,
    )
    assert (linked["target_kind"], str(linked["target_id"]), linked["target_version"]) == (
        "estimate_version",
        v4,
        4,
    )
    assert _status(sync_engine, v3) == "superseded"
    assert _status(sync_engine, v4) == "in_review"
    assert _collaborator_rows(sync_engine, opp["id"]) == {str(ana): "reviewer"}
    (event,) = _events(sync_engine, opp["id"], SUPERSEDED)
    assert event["payload"] == {
        "request_id": request["id"],
        "from_status": "pending",
        "estimate_version_id": v3,
        "superseded_by_version_id": v4,
        "superseded_by_version": 4,
        "reviewer_id": str(ana),
        "linked_request_id": str(linked["id"]),
    }
    created = [
        e
        for e in _events(sync_engine, opp["id"], "reviews.review_request.created")
        if e["payload"]["linked_request_id"] is not None
    ]
    assert [e["payload"]["request_id"] for e in created] == [str(linked["id"])]
    keys = {i["dedupe_key"] for i in _items(sync_engine, ana) if i["kind"] == "review_requested"}
    assert f"review:{linked['id']}:requested" in keys

    panel = _panel(client, ana_h, opp["id"], str(linked["id"])).json()
    assert panel["linked_request"] == {"id": request["id"], "version_number": 3}
    assert panel["can_decide"] is True
    old = _panel(client, ana_h, opp["id"], request["id"]).json()
    assert (old["request"]["status"], old["superseded_by"]) == ("superseded", 4)
    # Ana's earlier item reads "Superseded by v4", closed.
    items = {i["subject_id"]: i for i in _of_kind(_inbox(client, ana_h), "review_requested")}
    assert items[request["id"]]["subject_status_label"] == "Superseded by v4"
    assert items[request["id"]]["subject_open"] is False
    assert items[str(linked["id"])]["subject_open"] is True


def test_an_alternative_must_follow_a_request_for_one(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, owner_id, opp, _, [(ana_h, _)], [request] = _sent(client, sync_engine, "Ana Reviewer")
    asked = _decide(client, ana_h, opp["id"], request, "evidence_requested").json()["request"]
    v4 = _version(sync_engine, opp["id"], 4, status="draft", created_by=owner_id)
    assert_problem(
        _reply(client, headers, opp["id"], asked, alternative=v4).json(), 422, "validation_error"
    )


def test_submitting_v4_supersedes_pending_requests_but_not_approvals(
    client: TestClient, sync_engine: Engine, db_url: str
) -> None:
    headers, owner_id, opp, v3, [(ana_h, _), (_, ben)], [ana_req, ben_req] = _sent(
        client, sync_engine, "Ana Reviewer", "Ben Reviewer"
    )
    assert _decide(client, ana_h, opp["id"], ana_req, "approved", reason=None).status_code == 201
    v4 = _version(sync_engine, opp["id"], 4, status="draft", created_by=owner_id)

    submitted = _submit(client, sync_engine, headers, opp["id"], v4)

    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "submitted"
    stored = {str(r["id"]): r["status"] for r in _requests(sync_engine, opp["id"])}
    assert stored == {ana_req["id"]: "approved", ben_req["id"]: "superseded"}
    assert _collaborator_rows(sync_engine, opp["id"]) == {}
    (event,) = _events(sync_engine, opp["id"], SUPERSEDED)
    assert (event["payload"]["request_id"], event["payload"]["reviewer_id"]) == (
        ben_req["id"],
        str(ben),
    )
    # Ana's approval of v3 doesn't count for v4.
    assert _status(sync_engine, v4) == "submitted"
    listed = client.get(f"{BASE}/{opp['id']}/review-requests", headers=headers).json()
    assert (listed["version"], listed["items"]) == (4, [])
    # No reminders for the superseded request.
    _age(sync_engine, ben_req["id"], 7)
    _remind(db_url)
    assert not [i for i in _items(sync_engine, ben) if i["kind"] == "review_reminder"]
    assert _status(sync_engine, v3) == "superseded"


# --- New version ----------------------------------------------------------------------------


def _fill(engine: Engine, version_id: str, owner_id: UUID, covers: dict[str, Any]) -> None:
    """One line (covering `covers`), one accepted Assumption and one Risk on the version."""
    line_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO estimates_estimate_lines (id, version_id, position, section, title, "
                "effort_hours, role_mix, basis) VALUES (:id, :v, 1, 'integration', "
                "'WMS adapter', :h, CAST(:mix AS jsonb), 'Basis')"
            ),
            {
                "id": line_id,
                "v": version_id,
                "h": Decimal("16"),
                "mix": '{"engineer": 80, "project_manager": 10, "qa": 10}',
            },
        )
        conn.execute(
            sa.text(
                "INSERT INTO estimates_line_requirements (line_id, requirement_id, "
                "requirement_version) VALUES (:l, :r, :v)"
            ),
            {"l": line_id, "r": covers["id"], "v": covers["version"]},
        )
        conn.execute(
            sa.text(
                "INSERT INTO estimates_assumptions (id, version_id, position, kind, wording, "
                "amount_hours, line_id, origin_ref, row_version, accepted_by, accepted_at) VALUES "
                "(:id, :v, 1, 'condition', 'The customer hosts the WMS.', NULL, NULL, "
                "CAST(:ref AS jsonb), 1, :by, :at)"
            ),
            {
                "id": uuid4(),
                "v": version_id,
                "ref": f'{{"kind": "gap", "id": "{uuid4()}", "row_version": 1}}',
                "by": owner_id,
                "at": datetime.now(UTC),
            },
        )
        conn.execute(
            sa.text(
                "INSERT INTO estimates_risks (id, version_id, position, description, likelihood, "
                "impact, origin_ref, created_by, row_version) VALUES (:id, :v, 1, "
                "'Legacy interfaces.', 'medium', 'high', CAST(:ref AS jsonb), :by, 1)"
            ),
            {
                "id": uuid4(),
                "v": version_id,
                "ref": f'{{"kind": "gap", "id": "{uuid4()}", "row_version": 1}}',
                "by": owner_id,
            },
        )


def test_new_version_copies_a_rejected_version(client: TestClient, sync_engine: Engine) -> None:
    headers, owner_id, opp, v3, [(ana_h, _)], [request] = _sent(client, sync_engine, "Ana Reviewer")
    _fill(sync_engine, v3, owner_id, _requirement(sync_engine, opp["id"], 1))
    assert _decide(client, ana_h, opp["id"], request, "rejected").status_code == 201

    resp = _new_version(client, headers, opp["id"], v3, "Answers Ana's rejection.")

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert (body["version"], body["status"], body["base_version_id"], body["base_version"]) == (
        4,
        "draft",
        v3,
        3,
    )
    assert resp.headers["ETag"] == f'"{body["row_version"]}"'
    assert _status(sync_engine, v3) == "rejected"
    estimate = client.get(f"{BASE}/{opp['id']}/estimate", headers=headers).json()
    version = estimate["version"]
    assert (version["version"], version["status"]) == (4, "draft")
    lines = [line for section in version["sections"] for line in section["lines"]]
    assert [(line["title"], line["effort_hours"]) for line in lines] == [("WMS adapter", 16)]
    assert [r["label"] for r in lines[0]["requirements"]] == ["R1"]
    assumptions = version["assumptions"]["conditions"]
    assert [a["wording"] for a in assumptions] == ["The customer hosts the WMS."]
    assert [r["description"] for r in version["risks"]] == ["Legacy interfaces."]
    assert estimate["can_create_version"] is False
    (event,) = [
        e
        for e in _events(sync_engine, opp["id"], "estimates.estimate_version.created")
        if e["payload"]["base_version_id"] is not None
    ]
    assert event["payload"]["base_version_id"] == v3
    assert event["payload"]["base_version"] == 3
    assert event["payload"]["reason"] == "Answers Ana's rejection."
    assert (
        event["payload"]["carried_assumption_count"],
        event["payload"]["carried_risk_count"],
    ) == (
        1,
        1,
    )
    assert (event["actor_type"], event["actor_id"]) == ("user", str(owner_id))
    created_by = rows(
        sync_engine,
        "SELECT created_by FROM estimates_estimate_versions WHERE id = :i",
        i=body["id"],
    )[0]["created_by"]
    assert created_by == owner_id

    # A draft exists now.
    assert_problem(
        _new_version(client, headers, opp["id"], v3, None).json(), 409, "estimate_draft_exists"
    )
    # v3's request keeps its decision; the author can't start another.
    panel = _panel(client, headers, opp["id"], request["id"]).json()
    assert (panel["version_status"], panel["can_create_version"]) == ("rejected", False)


def test_new_version_needs_a_rejected_or_approved_base(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _, opp, v3, [(ana_h, _)], _ = _sent(client, sync_engine, "Ana Reviewer")
    assert _status(sync_engine, v3) == "in_review"
    assert_problem(
        _new_version(client, headers, opp["id"], v3, None).json(),
        409,
        "estimate_version_not_decided",
    )
    assert_problem(
        _new_version(client, headers, opp["id"], str(uuid4()), None).json(), 404, "not_found"
    )
    assert_problem(_new_version(client, ana_h, opp["id"], v3, None).json(), 403, "forbidden")
    assert_problem(
        _new_version(client, headers, opp["id"], v3, "x" * 1001).json(), 422, "validation_error"
    )


# --- escalation -----------------------------------------------------------------------------


def test_the_author_panel_shows_who_it_was_escalated_to(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _, opp, _, [(ana_h, _)], [request] = _sent(client, sync_engine, "Ana Reviewer")
    _, cy = _user(client, sync_engine, "Cy Reviewer", ENG)

    resp = _decide(client, ana_h, opp["id"], request, "escalated", "Needs a WMS expert.", cy)
    assert resp.status_code == 201, resp.text

    panel = _panel(client, headers, opp["id"], request["id"]).json()
    assert panel["escalated_to"] == {"id": str(cy), "name": "Cy Reviewer"}
    assert panel["decisions"][0]["reason"] == "Needs a WMS expert."
    assert (panel["is_author"], panel["can_reply"], panel["can_decide"]) == (True, False, False)
    (outcome,) = _of_kind(_inbox(client, headers), "review_outcome")
    assert (outcome["subject_status"], outcome["subject_open"]) == ("pending", True)
    assert outcome["summary"] == "Ana Reviewer escalated Estimate v3: Needs a WMS expert."


# --- grants and the migration ---------------------------------------------------------------


def _replied(client: TestClient, engine: Engine) -> tuple[dict[str, Any], str, UUID]:
    headers, owner_id, opp, _, [(ana_h, _)], [request] = _sent(client, engine, "Ana Reviewer")
    asked = _decide(client, ana_h, opp["id"], request, "evidence_requested").json()["request"]
    resp = _reply(client, headers, opp["id"], asked)
    assert resp.status_code == 201, resp.text
    return opp, resp.json()["reply"]["id"], owner_id


def test_replies_are_append_only(client: TestClient, sync_engine: Engine) -> None:
    _, reply_id, _ = _replied(client, sync_engine)
    for statement in (
        "UPDATE reviews_review_replies SET message = 'x' WHERE id = :i",
        "DELETE FROM reviews_review_replies WHERE id = :i",
    ):
        with pytest.raises(sa.exc.ProgrammingError), sync_engine.begin() as conn:
            conn.execute(sa.text(statement), {"i": reply_id})


def test_the_migration_goes_down_and_up(client: TestClient, sync_engine: Engine) -> None:
    _, reply_id, owner_id = _replied(client, sync_engine)
    assert [i for i in _items(sync_engine, owner_id) if i["kind"] == "review_outcome"]

    _alembic("downgrade", "0049_reviews_review_decisions")
    try:
        assert not [i for i in _items(sync_engine, owner_id) if i["kind"] == "review_outcome"]
        columns = rows(
            sync_engine,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'reviews_review_requests' AND column_name = 'linked_request_id'",
        )
        assert columns == []
    finally:
        _alembic("upgrade", "head")
    found = rows(sync_engine, "SELECT id FROM reviews_review_replies WHERE id = :i", i=reply_id)
    assert found == []


# --- review follow-ups ----------------------------------------------------------------------


def _self_reviewed(
    client: TestClient, engine: Engine
) -> tuple[dict[str, str], UUID, dict[str, Any], str]:
    """An owner who also holds the engineering reviewer role, and v3 with no known author."""
    headers, owner_id = _user(client, engine, "Owner Reviewer", PSE, ENG)
    opp = _create(client, headers)
    v3 = _version(engine, opp["id"], 3)
    return headers, owner_id, opp, v3


def test_an_owner_who_is_the_reviewer_cannot_reply(client: TestClient, sync_engine: Engine) -> None:
    headers, owner_id, opp, v3 = _self_reviewed(client, sync_engine)
    (request,) = _send(client, headers, opp["id"], v3, 1, [owner_id]).json()["items"]
    asked = _decide(client, headers, opp["id"], request, "evidence_requested").json()["request"]

    assert_problem(_reply(client, headers, opp["id"], asked).json(), 403, "forbidden")
    assert _events(sync_engine, opp["id"], REPLIED) == []
    # No outcome item for their own decision.
    assert not [i for i in _items(sync_engine, owner_id) if i["kind"] == "review_outcome"]


def test_an_owner_who_is_the_named_reviewer_gets_no_outcome_the_sender_does(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, owner_id, opp, v3 = _self_reviewed(client, sync_engine)
    ben_h, ben = _user(client, sync_engine, "Ben Presales", PSE)
    assert _add(client, headers, opp, ben).status_code == 200
    (request,) = _send(client, ben_h, opp["id"], v3, 1, [owner_id]).json()["items"]

    assert _decide(client, headers, opp["id"], request, "rejected").status_code == 201

    assert not [i for i in _items(sync_engine, owner_id) if i["kind"] == "review_outcome"]
    (item,) = [i for i in _items(sync_engine, ben) if i["kind"] == "review_outcome"]
    assert item["summary"] == f"Owner Reviewer rejected Estimate v3: {REASON}"


def test_no_reply_on_a_request_whose_version_is_superseded(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _, opp, v3, [(ana_h, _)], [request] = _sent(client, sync_engine, "Ana Reviewer")
    asked = _decide(client, ana_h, opp["id"], request, "evidence_requested").json()["request"]
    with sync_engine.begin() as conn:  # a request left pending before 9.4 superseded them
        conn.execute(
            sa.text("UPDATE estimates_estimate_versions SET status = 'superseded' WHERE id = :i"),
            {"i": v3},
        )

    assert_problem(
        _reply(client, headers, opp["id"], asked).json(), 409, "review_request_not_pending"
    )


def test_a_decision_after_a_reply_needs_the_new_row_version(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _, opp, _, [(ana_h, _)], [request] = _sent(client, sync_engine, "Ana Reviewer")
    asked = _decide(client, ana_h, opp["id"], request, "evidence_requested").json()["request"]
    assert _reply(client, headers, opp["id"], asked).status_code == 201

    stale = _decide(client, ana_h, opp["id"], asked, "approved", reason=None)

    assert_problem(stale.json(), 412, "row_version_mismatch")
    assert stale.json()["detail"] == "Changed by Owner Person since you opened it."


def test_superseded_by_names_the_version_submitted_next(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, owner_id, opp, _, [(ana_h, _)], [request] = _sent(client, sync_engine, "Ana Reviewer")
    v4 = _version(sync_engine, opp["id"], 4, status="draft", created_by=owner_id)
    assert _submit(client, sync_engine, headers, opp["id"], v4).status_code == 200
    _version(sync_engine, opp["id"], 5, status="draft", created_by=owner_id)  # a later draft

    # Ana lost access with the request; the owner still reads its panel.
    panel = _panel(client, headers, opp["id"], request["id"]).json()
    assert panel["superseded_by"] == 4
    items = {i["subject_id"]: i for i in _of_kind(_inbox(client, ana_h), "review_requested")}
    assert items[request["id"]]["subject_status_label"] == "Superseded by v4"


def _asked_for_alternative(
    client: TestClient, engine: Engine
) -> tuple[dict[str, str], UUID, dict[str, Any], str, UUID, dict[str, Any]]:
    """v3 in review with Ana's alternative request: (owner headers, owner id, opp, v3, Ana's
    id, the request as now)."""
    headers, owner_id, opp, v3, [(ana_h, ana)], [request] = _sent(client, engine, "Ana Reviewer")
    asked = _decide(client, ana_h, opp["id"], request, "alternative_requested").json()["request"]
    return headers, owner_id, opp, v3, ana, asked


def test_a_later_evidence_reply_keeps_the_alternative(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, owner_id, opp, _, ana, asked = _asked_for_alternative(client, sync_engine)
    v4 = _version(sync_engine, opp["id"], 4, status="draft", created_by=owner_id)
    first = _reply(client, headers, opp["id"], asked, alternative=v4).json()["request"]
    assert _reply(client, headers, opp["id"], first, message="Also see R2.").status_code == 201

    assert _submit(client, sync_engine, headers, opp["id"], v4).status_code == 200

    (linked,) = [r for r in _requests(sync_engine, opp["id"]) if r["linked_request_id"]]
    assert (str(linked["linked_request_id"]), linked["reviewer_id"]) == (asked["id"], ana)
    assert str(linked["estimate_version_id"]) == v4


def test_an_alternative_redrafted_before_submit_is_still_linked(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, owner_id, opp, _, ana, asked = _asked_for_alternative(client, sync_engine)
    v4 = _version(sync_engine, opp["id"], 4, status="draft", created_by=owner_id)
    assert _reply(client, headers, opp["id"], asked, alternative=v4).status_code == 201
    with sync_engine.begin() as conn:  # a re-draft supersedes the draft v4 with v5
        conn.execute(
            sa.text("UPDATE estimates_estimate_versions SET status = 'superseded' WHERE id = :i"),
            {"i": v4},
        )
    v5 = _version(sync_engine, opp["id"], 5, status="draft", created_by=owner_id)

    assert _submit(client, sync_engine, headers, opp["id"], v5).status_code == 200

    (linked,) = [r for r in _requests(sync_engine, opp["id"]) if r["linked_request_id"]]
    assert (str(linked["estimate_version_id"]), linked["target_version"]) == (v5, 5)
    assert linked["reviewer_id"] == ana
    assert _status(sync_engine, v5) == "in_review"


def test_no_link_when_the_reviewer_authored_the_alternative(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _, opp, _, ana, asked = _asked_for_alternative(client, sync_engine)
    v4 = _version(sync_engine, opp["id"], 4, status="draft", created_by=ana)
    assert _reply(client, headers, opp["id"], asked, alternative=v4).status_code == 201

    assert _submit(client, sync_engine, headers, opp["id"], v4).status_code == 200

    assert [r for r in _requests(sync_engine, opp["id"]) if r["linked_request_id"]] == []
    assert _status(sync_engine, v4) == "submitted"
    (event,) = _events(sync_engine, opp["id"], SUPERSEDED)
    assert event["payload"]["linked_request_id"] is None


def test_new_version_from_an_approved_base(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, v3, [(ana_h, _)], [request] = _sent(client, sync_engine, "Ana Reviewer")
    assert _decide(client, ana_h, opp["id"], request, "approved", reason=None).status_code == 201
    estimate = client.get(f"{BASE}/{opp['id']}/estimate", headers=headers).json()
    assert estimate["can_create_version"] is True
    assert _panel(client, headers, opp["id"], request["id"]).json()["can_create_version"] is True

    resp = _new_version(client, headers, opp["id"], v3, None)

    assert resp.status_code == 201, resp.text
    assert (resp.json()["version"], _status(sync_engine, v3)) == (4, "approved")


def test_new_version_from_a_version_an_alternative_was_asked_for(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _, opp, v3, _, asked = _asked_for_alternative(client, sync_engine)
    assert _status(sync_engine, v3) == "in_review"
    estimate = client.get(f"{BASE}/{opp['id']}/estimate", headers=headers).json()
    assert estimate["can_create_version"] is True
    panel = _panel(client, headers, opp["id"], asked["id"]).json()
    assert (panel["can_reply"], panel["can_create_version"]) == (True, True)

    resp = _new_version(client, headers, opp["id"], v3, None)

    assert resp.status_code == 201, resp.text
    assert _status(sync_engine, v3) == "in_review"
    panel = _panel(client, headers, opp["id"], asked["id"]).json()
    assert (panel["can_create_version"], panel["can_link_alternative"]) == (False, True)
    assert_problem(
        _new_version(client, headers, opp["id"], v3, None).json(), 409, "estimate_draft_exists"
    )
