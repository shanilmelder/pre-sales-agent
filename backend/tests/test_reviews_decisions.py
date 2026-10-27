"""Review Decisions (Story 9.3) against a real, migrated Postgres as psa_app: the decision
rules (no DB), every row of the story's matrix (last and partial approval, reject, request
evidence, escalate, self-approval, not the reviewer, role revoked, stale, already decided),
the version roll-up across requests, the append-only grants, the trace payload, the escalation
Inbox items, the review panel for both target kinds, and `compare_versions`.

Estimate Versions, lines and Assessments are inserted directly; people sign in through `/me`
with their roles, so identity's role cache holds them (see `test_reviews_requests`).
"""

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.estimates.application.compare import diff_lines
from app.modules.estimates.application.models import (
    EstimateLine,
    RoleHours,
    RoleMix,
)
from app.modules.estimates.domain.estimates import Section
from app.modules.reviews.domain.decisions import (
    RECORDABLE,
    Decision,
    clean_decision_reason,
    reason_required,
    status_after,
)
from app.modules.reviews.domain.requests import RequestStatus
from tests import test_opportunities as opportunity_tests
from tests.test_gaps_detection import rows
from tests.test_health import assert_problem
from tests.test_intake_parse_job import _alembic
from tests.test_opportunities import BASE, PSE, _add, _create, _user
from tests.test_reviews_requests import (
    ENG,
    REP,
    SEC,
    _assessment,
    _collaborator_rows,
    _events,
    _requests,
    _row_version,
    _send,
    _setup,
    _status,
    _version,
)
from tests.test_role_admin import _reissue

client = opportunity_tests.client

RECORDED = "reviews.review_decision.recorded"
REASON = "Line L3 has no basis for 40 h."
INBOX = "/api/v1/inbox"


# --- the decision rules (no DB) -------------------------------------------------------------


def test_status_after_each_decision() -> None:
    assert status_after(Decision.APPROVED) is RequestStatus.APPROVED
    assert status_after(Decision.REJECTED) is RequestStatus.REJECTED
    assert status_after(Decision.CHALLENGED) is RequestStatus.CHALLENGED
    for stays in (
        Decision.EVIDENCE_REQUESTED,
        Decision.ALTERNATIVE_REQUESTED,
        Decision.ESCALATED,
    ):
        assert status_after(stays) is None
    assert Decision.CHALLENGED not in RECORDABLE
    assert RECORDABLE == set(Decision) - {Decision.CHALLENGED}


def test_every_decision_but_approve_needs_a_reason() -> None:
    assert not reason_required(Decision.APPROVED)
    assert clean_decision_reason(Decision.APPROVED, None) is None
    assert clean_decision_reason(Decision.APPROVED, "  ") is None
    assert clean_decision_reason(Decision.APPROVED, " Fine ") == "Fine"
    for decision in set(Decision) - {Decision.APPROVED}:
        assert reason_required(decision)
        with pytest.raises(ValueError):
            clean_decision_reason(decision, "   ")
        assert clean_decision_reason(decision, " Why ") == "Why"
    with pytest.raises(ValueError):
        clean_decision_reason(Decision.APPROVED, "x" * 1001)


def _line(section: Section, title: str, total: float, engineer: int = 100) -> EstimateLine:
    hours = RoleHours(engineer=total, project_manager=0, qa=0)
    return EstimateLine(
        id=str(uuid4()),
        position=1,
        section=section,
        title=title,
        basis="b",
        role_mix=RoleMix(engineer=engineer, project_manager=100 - engineer, qa=0),
        effort_hours=total,
        contingency_hours=0,
        total_hours=total,
        role_hours=hours,
        requirements=[],
        row_version=1,
        edited=False,
        edited_by_name=None,
        edited_at=None,
        edit_reason=None,
        edit_carried_from_version=None,
        conflicts=[],
    )


def test_diff_lines_matches_by_section_and_title() -> None:
    before = [
        _line(Section.FUNCTIONAL, "Pick station UI", 40),
        _line(Section.FUNCTIONAL, "Reports", 10),
        _line(Section.DATA, "Migration", 20),
    ]
    after = [
        _line(Section.FUNCTIONAL, " pick station ui ", 52),
        _line(Section.DATA, "Migration", 20, engineer=80),
        _line(Section.INTEGRATION, "WMS adapter", 16),
    ]
    found = [
        (d.change, d.title, d.before_hours, d.after_hours, d.delta_hours)
        for d in diff_lines(before, after)
    ]
    assert found == [
        ("changed", " pick station ui ", 40, 52, 12),
        ("removed", "Reports", 10, None, -10),
        ("added", "WMS adapter", None, 16, 16),
        ("changed", "Migration", 20, 20, 0),
    ]
    assert diff_lines(before, before) == []


# --- helpers --------------------------------------------------------------------------------


def _decide(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    request: dict[str, Any],
    decision: str,
    reason: str | None = REASON,
    escalated_to: UUID | None = None,
    row_version: int | None = None,
) -> Any:
    rv = request["row_version"] if row_version is None else row_version
    body: dict[str, Any] = {"decision": decision}
    if reason is not None:
        body["reason"] = reason
    if escalated_to is not None:
        body["escalated_to"] = str(escalated_to)
    return client.post(
        f"{BASE}/{opp_id}/review-requests/{request['id']}/decisions",
        headers={**headers, "If-Match": f'"{rv}"'},
        json=body,
    )


def _panel(client: TestClient, headers: dict[str, str], opp_id: str, request_id: str) -> Any:
    return client.get(f"{BASE}/{opp_id}/review-requests/{request_id}/panel", headers=headers)


def _decisions(engine: Engine, request_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM reviews_review_decisions WHERE review_request_id = :r ORDER BY decided_at",
        r=request_id,
    )


def _sent(
    client: TestClient, engine: Engine, *reviewers: str
) -> tuple[dict[str, str], UUID, dict[str, Any], str, list[tuple[dict[str, str], UUID]], list[Any]]:
    """`_setup` (v3 submitted, authored by the owner), then one engineering request per
    reviewer name: (owner headers, owner id, opp, v3, [(headers, id)], [requests])."""
    headers, owner_id, opp, v3 = _setup(client, engine)
    people = [_user(client, engine, name, ENG) for name in reviewers]
    resp = _send(client, headers, opp["id"], v3, 1, [p[1] for p in people])
    assert resp.status_code == 201, resp.text
    return headers, owner_id, opp, v3, people, resp.json()["items"]


# --- the matrix -----------------------------------------------------------------------------


def test_last_approval_approves_the_version(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, v3, [(ana_h, ana)], [request] = _sent(client, sync_engine, "Ana Reviewer")

    resp = _decide(client, ana_h, opp["id"], request, "approved", reason=None)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["request"]["status"] == "approved"
    assert body["request"]["row_version"] == request["row_version"] + 1
    assert resp.headers["ETag"] == f'"{body["request"]["row_version"]}"'
    assert body["version_status"] == "approved"
    assert body["decision"]["decision"] == "approved"
    assert body["decision"]["label"] == "Approved"
    assert body["decision"]["reason"] is None
    assert body["decision"]["decided_by"] == {"id": str(ana), "name": "Ana Reviewer"}
    assert body["request"]["latest_decision"]["id"] == body["decision"]["id"]
    assert _status(sync_engine, v3) == "approved"
    assert _collaborator_rows(sync_engine, opp["id"]) == {}

    (event,) = _events(sync_engine, opp["id"], RECORDED)
    assert event["payload"] == {
        "request_id": request["id"],
        "decision_id": body["decision"]["id"],
        "decision": "approved",
        "reason": None,
        "target_kind": "estimate_version",
        "target_id": v3,
        "target_version": 3,
        "escalated_to": None,
    }
    assert (event["actor_type"], event["actor_id"]) == ("user", str(ana))
    assert event["subject_type"] == "reviews.review_request"
    assert len(_events(sync_engine, opp["id"], "estimates.estimate_version.approved")) == 1

    # An approved version stays current, read only, and takes no new request.
    estimate = client.get(f"{BASE}/{opp['id']}/estimate", headers=headers).json()
    assert estimate["version"]["status"] == "approved"
    assert estimate["can_request_review"] is False
    listed = client.get(f"{BASE}/{opp['id']}/review-requests", headers=headers).json()
    assert listed["items"][0]["latest_decision"]["label"] == "Approved"
    assert listed["can_create"] is False
    assert (
        _send(client, headers, opp["id"], v3, _row_version(sync_engine, v3), [ana]).status_code
        == 409
    )
    rows_ = client.get(BASE, headers=headers).json()["items"]
    assert next(r for r in rows_ if r["id"] == opp["id"])["estimate"]["status"] == "approved"


def test_partial_approval_waits_for_every_request(client: TestClient, sync_engine: Engine) -> None:
    _, _, opp, v3, [(ana_h, _), (ben_h, ben)], [ana_req, ben_req] = _sent(
        client, sync_engine, "Ana Reviewer", "Ben Reviewer"
    )

    assert (
        _decide(client, ana_h, opp["id"], ana_req, "approved", "Totals check out.").status_code
        == 201
    )
    assert _status(sync_engine, v3) == "in_review"
    stored = {str(r["id"]): r["status"] for r in _requests(sync_engine, opp["id"])}
    assert stored == {ana_req["id"]: "approved", ben_req["id"]: "pending"}
    assert _collaborator_rows(sync_engine, opp["id"]) == {str(ben): "reviewer"}

    resp = _decide(client, ben_h, opp["id"], ben_req, "approved", reason=None)
    assert resp.json()["version_status"] == "approved"
    assert _status(sync_engine, v3) == "approved"


def test_a_cancelled_request_does_not_hold_the_roll_up(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _, opp, v3, [(ana_h, _), _], [ana_req, ben_req] = _sent(
        client, sync_engine, "Ana Reviewer", "Ben Reviewer"
    )
    cancel = client.post(
        f"{BASE}/{opp['id']}/review-requests/{ben_req['id']}/cancel",
        headers={**headers, "If-Match": '"1"'},
        json={"reason": "Not needed."},
    )
    assert cancel.status_code == 200, cancel.text
    _decide(client, ana_h, opp["id"], ana_req, "approved", reason=None)
    assert _status(sync_engine, v3) == "approved"


def test_reject_rejects_the_request_and_the_version(
    client: TestClient, sync_engine: Engine
) -> None:
    _, _, opp, v3, [(ana_h, _), (ben_h, _)], [ana_req, ben_req] = _sent(
        client, sync_engine, "Ana Reviewer", "Ben Reviewer"
    )

    blank = _decide(client, ana_h, opp["id"], ana_req, "rejected", reason="   ")
    assert blank.status_code == 422
    assert blank.json()["detail"] == "Give a reason of 1 to 1,000 characters."
    missing = _decide(client, ana_h, opp["id"], ana_req, "rejected", reason=None)
    assert missing.status_code == 422
    assert _decisions(sync_engine, ana_req["id"]) == []

    resp = _decide(client, ana_h, opp["id"], ana_req, "rejected")
    assert resp.status_code == 201, resp.text
    assert resp.json()["request"]["status"] == "rejected"
    assert resp.json()["version_status"] == "rejected"
    assert _status(sync_engine, v3) == "rejected"
    assert len(_events(sync_engine, opp["id"], "estimates.estimate_version.rejected")) == 1

    # Design note: a later approval is recorded, but the version stays rejected.
    late = _decide(client, ben_h, opp["id"], ben_req, "approved", reason=None)
    assert late.status_code == 201
    assert late.json()["version_status"] == "rejected"
    assert _status(sync_engine, v3) == "rejected"


@pytest.mark.parametrize(
    ("decision", "label"),
    [
        ("evidence_requested", "Evidence requested"),
        ("alternative_requested", "Alternative requested"),
    ],
)
def test_requests_for_more_keep_the_request_pending(
    client: TestClient, sync_engine: Engine, decision: str, label: str
) -> None:
    headers, _, opp, v3, [(ana_h, ana)], [request] = _sent(client, sync_engine, "Ana Reviewer")

    resp = _decide(client, ana_h, opp["id"], request, decision)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["request"]["status"] == "pending"
    assert body["request"]["row_version"] == 2
    assert body["version_status"] == "in_review"
    assert _status(sync_engine, v3) == "in_review"
    assert _collaborator_rows(sync_engine, opp["id"]) == {str(ana): "reviewer"}
    (stored,) = _decisions(sync_engine, request["id"])
    assert (stored["decision"], stored["reason"], stored["target_version"]) == (decision, REASON, 3)

    listed = client.get(f"{BASE}/{opp['id']}/review-requests", headers=headers).json()
    latest = listed["items"][0]["latest_decision"]
    assert (latest["label"], latest["reason"], latest["decided_by"]["name"]) == (
        label,
        REASON,
        "Ana Reviewer",
    )
    panel = _panel(client, ana_h, opp["id"], request["id"]).json()
    assert [d["decision"] for d in panel["decisions"]] == [decision]
    assert panel["can_decide"] is True

    # The reviewer can still decide (as of the new row version).
    again = _decide(client, ana_h, opp["id"], body["request"], "approved", reason=None)
    assert again.status_code == 201
    assert _status(sync_engine, v3) == "approved"


def test_escalate_hands_the_request_to_another_reviewer(
    client: TestClient, sync_engine: Engine
) -> None:
    _, owner_id, opp, v3, [(ana_h, ana)], [request] = _sent(client, sync_engine, "Ana Reviewer")
    cy_h, cy = _user(client, sync_engine, "Cy Reviewer", ENG)
    _, sec = _user(client, sync_engine, "Sec Reviewer", SEC)

    wrong_role = _decide(client, ana_h, opp["id"], request, "escalated", escalated_to=sec)
    assert wrong_role.status_code == 422
    assert wrong_role.json()["code"] == "reviewer_not_authorized_for_type"
    author = _decide(client, ana_h, opp["id"], request, "escalated", escalated_to=owner_id)
    assert author.status_code == 422
    assert author.json()["code"] == "author_cannot_review"
    no_target = _decide(client, ana_h, opp["id"], request, "escalated")
    assert no_target.status_code == 422
    to_self = _decide(client, ana_h, opp["id"], request, "escalated", escalated_to=ana)
    assert to_self.status_code == 422
    misplaced = _decide(client, ana_h, opp["id"], request, "rejected", escalated_to=cy)
    assert misplaced.status_code == 422
    assert _decisions(sync_engine, request["id"]) == []

    panel = _panel(client, ana_h, opp["id"], request["id"]).json()
    candidates = {p["id"] for p in panel["escalation_candidates"]}
    assert candidates  # engineering reviewers, by name (other tests' users too)
    assert {str(ana), str(owner_id), str(sec)} & candidates == set()

    resp = _decide(client, ana_h, opp["id"], request, "escalated", escalated_to=cy)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["request"]["status"] == "pending"
    assert body["request"]["reviewer"] == {"id": str(cy), "name": "Cy Reviewer"}
    assert body["decision"]["escalated_to"] == {"id": str(cy), "name": "Cy Reviewer"}
    assert _collaborator_rows(sync_engine, opp["id"]) == {str(cy): "reviewer"}
    (event,) = _events(sync_engine, opp["id"], RECORDED)
    assert event["payload"]["decision"] == "escalated"
    assert event["payload"]["escalated_to"] == str(cy)
    assert event["payload"]["reason"] == REASON
    assert _status(sync_engine, v3) == "in_review"

    # Cy has an unread Review item that opens the request; Ana's item is closed.
    cy_items = client.get(INBOX, headers=cy_h).json()["items"]
    (cy_item,) = [i for i in cy_items if i["subject_id"] == request["id"]]
    assert (cy_item["kind"], cy_item["read"], cy_item["subject_open"]) == (
        "review_requested",
        False,
        True,
    )
    assert cy_item["href"] == f"/opportunities/{opp['id']}/estimate?review={request['id']}"
    ana_items = client.get(INBOX, headers=ana_h).json()["items"]
    (ana_item,) = [i for i in ana_items if i["subject_id"] == request["id"]]
    assert (ana_item["subject_open"], ana_item["href"], ana_item["subject_status"]) == (
        False,
        None,
        "escalated",
    )
    assert ana_item["subject_status_label"] == "Escalated"

    # Ana no longer reads the Opportunity; Cy decides.
    assert _panel(client, ana_h, opp["id"], request["id"]).status_code == 404
    cy_panel = _panel(client, cy_h, opp["id"], request["id"]).json()
    assert cy_panel["can_decide"] is True
    old = _decide(client, ana_h, opp["id"], body["request"], "approved", reason=None)
    assert old.status_code == 404
    done = _decide(client, cy_h, opp["id"], body["request"], "approved", reason=None)
    assert done.status_code == 201
    assert _status(sync_engine, v3) == "approved"


def test_escalating_to_someone_with_the_same_pending_request_is_409(
    client: TestClient, sync_engine: Engine
) -> None:
    _, _, opp, _, [(ana_h, _), (_, ben)], [ana_req, _] = _sent(
        client, sync_engine, "Ana Reviewer", "Ben Reviewer"
    )
    resp = _decide(client, ana_h, opp["id"], ana_req, "escalated", escalated_to=ben)
    assert resp.status_code == 409
    assert resp.json()["code"] == "review_request_duplicate"


def test_the_author_cannot_approve(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)
    v1 = _version(sync_engine, opp["id"], 1)  # unknown author: the send allows anyone
    author_h, author = _user(client, sync_engine, "Author Reviewer", ENG)
    (request,) = _send(client, headers, opp["id"], v1, 1, [author]).json()["items"]
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE estimates_estimate_versions SET created_by = :a WHERE id = :v"),
            {"a": author, "v": v1},
        )

    panel = _panel(client, author_h, opp["id"], request["id"]).json()
    assert (panel["can_decide"], panel["can_approve"]) == (True, False)
    assert panel["approve_blocked_reason"] == "You authored v1, so you can't approve it."

    resp = _decide(client, author_h, opp["id"], request, "approved", reason=None)
    assert resp.status_code == 403
    assert_problem(resp.json(), 403, "self_approval_forbidden")
    assert _decisions(sync_engine, request["id"]) == []
    assert _status(sync_engine, v1) == "in_review"
    # Anything but Approve is still theirs to decide.
    assert _decide(client, author_h, opp["id"], request, "evidence_requested").status_code == 201


def test_only_the_reviewer_holding_the_role_decides(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _, opp, v3, [(_, ana), (ben_h, _)], [ana_req, _] = _sent(
        client, sync_engine, "Ana Reviewer", "Ben Reviewer"
    )

    ben = _decide(client, ben_h, opp["id"], ana_req, "approved", reason=None)
    assert ben.status_code == 403
    assert_problem(ben.json(), 403, "reviewer_not_authorized")
    owner = _decide(client, headers, opp["id"], ana_req, "approved", reason=None)
    assert owner.status_code == 403
    assert owner.json()["code"] == "reviewer_not_authorized"

    # Ana lost the engineering reviewer role in Auth0 (a new token, without it).
    revoked = _reissue(ana, PSE)
    resp = _decide(client, revoked, opp["id"], ana_req, "approved", reason=None)
    assert resp.status_code == 403
    assert resp.json()["code"] == "reviewer_not_authorized"
    assert _panel(client, revoked, opp["id"], ana_req["id"]).json()["can_decide"] is False
    assert _decisions(sync_engine, ana_req["id"]) == []
    assert _status(sync_engine, v3) == "in_review"


def test_a_sales_representative_never_decides(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, _, _, [request] = _sent(client, sync_engine, "Ana Reviewer")
    rep_h, rep = _user(client, sync_engine, "Rep Person", REP)
    current = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    assert _add(client, headers, current, rep).status_code == 200
    resp = _decide(client, rep_h, opp["id"], request, "approved", reason=None)
    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"
    outsider_h, _ = _user(client, sync_engine, "Out Sider", PSE)
    assert _decide(client, outsider_h, opp["id"], request, "approved").status_code == 404
    assert _panel(client, outsider_h, opp["id"], request["id"]).status_code == 404


def test_stale_if_match_is_412_with_who_changed_it(client: TestClient, sync_engine: Engine) -> None:
    _, _, opp, _, [(ana_h, _)], [request] = _sent(client, sync_engine, "Ana Reviewer")
    assert _decide(client, ana_h, opp["id"], request, "evidence_requested").status_code == 201

    resp = _decide(client, ana_h, opp["id"], request, "approved", reason=None, row_version=1)

    assert resp.status_code == 412
    assert_problem(resp.json(), 412, "row_version_mismatch")
    assert resp.json()["detail"] == "Changed by Ana Reviewer since you opened it."
    assert len(_decisions(sync_engine, request["id"])) == 1
    missing = client.post(
        f"{BASE}/{opp['id']}/review-requests/{request['id']}/decisions",
        headers=ana_h,
        json={"decision": "approved"},
    )
    assert missing.status_code == 428


def test_a_decided_request_is_409(client: TestClient, sync_engine: Engine) -> None:
    _, _, opp, _, [(ana_h, _)], [request] = _sent(client, sync_engine, "Ana Reviewer")
    first = _decide(client, ana_h, opp["id"], request, "rejected")
    assert first.status_code == 201
    # Ana lost access with her last pending request: re-share to see the 409.
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO opportunities_collaborators (opportunity_id, user_id, role) "
                "VALUES (:o, (SELECT reviewer_id FROM reviews_review_requests WHERE id = :r), "
                "'reviewer')"
            ),
            {"o": opp["id"], "r": request["id"]},
        )
    again = _decide(client, ana_h, opp["id"], first.json()["request"], "approved", reason=None)
    assert again.status_code == 409
    assert again.json()["code"] == "review_request_not_pending"


def test_a_challenge_is_raised_not_decided(client: TestClient, sync_engine: Engine) -> None:
    """Story 9.5: `challenged` is recorded by raising a Challenge (`POST …/challenges`, see
    `test_reviews_challenges`), never through the decisions endpoint."""
    _, _, opp, _, [(ana_h, _)], [request] = _sent(client, sync_engine, "Ana Reviewer")
    resp = _decide(client, ana_h, opp["id"], request, "challenged")
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Raise a Challenge to challenge this review."
    assert _decisions(sync_engine, request["id"]) == []


# --- grants and the DB checks ---------------------------------------------------------------


def test_decisions_are_append_only(client: TestClient, sync_engine: Engine) -> None:
    _, _, opp, _, [(ana_h, _)], [request] = _sent(client, sync_engine, "Ana Reviewer")
    decision_id = _decide(client, ana_h, opp["id"], request, "evidence_requested").json()[
        "decision"
    ]["id"]
    for statement in (
        "UPDATE reviews_review_decisions SET reason = 'x' WHERE id = :i",
        "DELETE FROM reviews_review_decisions WHERE id = :i",
    ):
        with pytest.raises(sa.exc.ProgrammingError), sync_engine.begin() as conn:
            conn.execute(sa.text(statement), {"i": decision_id})


@pytest.mark.parametrize(
    ("decision", "reason", "escalated_to"),
    [
        ("rejected", None, None),
        ("rejected", "  ", None),
        ("escalated", "Why", None),
        ("approved", None, "x"),
    ],
)
def test_the_db_checks_the_reason_and_the_escalation(
    client: TestClient,
    sync_engine: Engine,
    decision: str,
    reason: str | None,
    escalated_to: str | None,
) -> None:
    _, _, _, _, [(_, ana)], [request] = _sent(client, sync_engine, "Ana Reviewer")
    with pytest.raises(sa.exc.IntegrityError), sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO reviews_review_decisions (id, review_request_id, decision, reason, "
                "decided_by, target_version, escalated_to) VALUES (:id, :r, :d, :why, :by, 3, :to)"
            ),
            {
                "id": uuid4(),
                "r": request["id"],
                "d": decision,
                "why": reason,
                "by": ana,
                "to": None if escalated_to is None else ana,
            },
        )


# --- the panel ------------------------------------------------------------------------------


def _insert_line(
    engine: Engine, version_id: str, position: int, section: str, title: str, hours: str
) -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO estimates_estimate_lines (id, version_id, position, section, title, "
                "effort_hours, role_mix, basis) VALUES (:id, :v, :p, :s, :t, :h, "
                "CAST(:mix AS jsonb), 'Basis')"
            ),
            {
                "id": uuid4(),
                "v": version_id,
                "p": position,
                "s": section,
                "t": title,
                "h": Decimal(hours),
                "mix": '{"engineer": 100, "project_manager": 0, "qa": 0}',
            },
        )


def _version_id(engine: Engine, opp_id: str, number: int) -> str:
    (found,) = rows(
        engine,
        "SELECT id FROM estimates_estimate_versions WHERE opportunity_id = :o AND version = :n",
        o=opp_id,
        n=number,
    )
    return str(found["id"])


def test_the_panel_of_an_estimate_version(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, v3 = _setup(client, sync_engine)
    v2 = _version_id(sync_engine, opp["id"], 2)
    _insert_line(sync_engine, v2, 1, "functional", "Pick station UI", "40")
    _insert_line(sync_engine, v2, 2, "functional", "Reports", "10")
    _insert_line(sync_engine, v3, 1, "functional", "Pick station UI", "52")
    _insert_line(sync_engine, v3, 2, "integration", "WMS adapter", "16")
    ana_h, ana = _user(client, sync_engine, "Ana Reviewer", ENG)
    (request,) = _send(client, headers, opp["id"], v3, 1, [ana], message="Check L1.").json()[
        "items"
    ]

    resp = _panel(client, ana_h, opp["id"], request["id"])

    assert resp.status_code == 200, resp.text
    assert resp.headers["ETag"] == '"1"'
    panel = resp.json()
    assert panel["request"]["message"] == "Check L1."
    assert panel["request"]["requested_by"]["name"] == "Owner Person"
    assert panel["opportunity_title"] == opp["title"]
    assert (panel["version_status"], panel["superseded_by"]) == ("in_review", None)
    assert (panel["can_decide"], panel["can_approve"], panel["approve_blocked_reason"]) == (
        True,
        True,
        None,
    )
    assert panel["assessment"] is None
    estimate = panel["estimate"]
    assert estimate["version"] == 3
    assert estimate["totals"]["total_hours"] == 68
    assert [line["title"] for s in estimate["sections"] for line in s["lines"]] == [
        "Pick station UI",
        "WMS adapter",
    ]
    assert "assumptions" in estimate and "risks" in estimate
    diff = panel["diff"]
    assert (diff["version"], diff["previous_version"], diff["first"]) == (3, 2, False)
    assert (diff["total_before"], diff["total_after"], diff["total_delta"]) == (50, 68, 18)
    assert [(d["change"], d["title"], d["delta_hours"]) for d in diff["lines"]] == [
        ("changed", "Pick station UI", 12),
        ("removed", "Reports", -10),
        ("added", "WMS adapter", 16),
    ]

    # The owner (the author) reads the panel without actions.
    owner_panel = _panel(client, headers, opp["id"], request["id"]).json()
    assert (owner_panel["can_decide"], owner_panel["escalation_candidates"]) == (False, [])


def test_the_first_version_has_no_previous(client: TestClient, sync_engine: Engine) -> None:
    headers, owner_id = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)
    v1 = _version(sync_engine, opp["id"], 1, created_by=owner_id)
    ana_h, ana = _user(client, sync_engine, "Ana Reviewer", ENG)
    (request,) = _send(client, headers, opp["id"], v1, 1, [ana]).json()["items"]
    diff = _panel(client, ana_h, opp["id"], request["id"]).json()["diff"]
    assert (diff["first"], diff["previous_version"], diff["lines"]) == (True, None, [])


def test_the_panel_of_an_assessment(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, v3 = _setup(client, sync_engine)
    cy_h, cy = _user(client, sync_engine, "Cy Reviewer", SEC)
    a1 = _assessment(sync_engine, opp["id"], "security_agent", 2)
    finding_id, requirement_id = uuid4(), uuid4()
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO assessments_assessment_findings (id, assessment_id, position, kind, "
                "severity, title, detail) VALUES (:id, :a, 1, 'risk', 'high', 'No SSO', 'D')"
            ),
            {"id": finding_id, "a": a1},
        )
        conn.execute(
            sa.text(
                "INSERT INTO assessments_assessment_finding_requirements (finding_id, "
                "requirement_id, requirement_version) VALUES (:f, :r, 1)"
            ),
            {"f": finding_id, "r": requirement_id},
        )
    (request,) = _send(
        client, headers, opp["id"], v3, 1, [cy], "security", [{"id": a1, "version": 2}]
    ).json()["items"]

    panel = _panel(client, cy_h, opp["id"], request["id"]).json()

    assert (panel["estimate"], panel["diff"]) == (None, None)
    assessment = panel["assessment"]
    assert (assessment["id"], assessment["version"], assessment["confidence"]) == (a1, 2, "high")
    assert assessment["confidence_basis"] == "Basis"
    (finding,) = assessment["findings"]
    assert (finding["title"], finding["severity"]) == ("No SSO", "high")
    assert [r["id"] for r in finding["requirements"]] == [str(requirement_id)]


def test_a_superseded_version_has_a_read_only_panel(
    client: TestClient, sync_engine: Engine
) -> None:
    _, owner_id, opp, v3, [(ana_h, _)], [request] = _sent(client, sync_engine, "Ana Reviewer")
    _version(sync_engine, opp["id"], 4, created_by=owner_id)
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE estimates_estimate_versions SET status = 'superseded' WHERE id = :v"),
            {"v": v3},
        )
    panel = _panel(client, ana_h, opp["id"], request["id"]).json()
    assert (panel["version_status"], panel["superseded_by"], panel["can_decide"]) == (
        "superseded",
        4,
        False,
    )


# --- review follow-ups ----------------------------------------------------------------------


def test_a_superseded_version_takes_no_decision(client: TestClient, sync_engine: Engine) -> None:
    _, owner_id, opp, v3, [(ana_h, _)], [request] = _sent(client, sync_engine, "Ana Reviewer")
    _version(sync_engine, opp["id"], 4, created_by=owner_id)
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE estimates_estimate_versions SET status = 'superseded' WHERE id = :v"),
            {"v": v3},
        )
    resp = _decide(client, ana_h, opp["id"], request, "approved", reason=None)
    assert resp.status_code == 409
    assert resp.json()["code"] == "estimate_version_superseded"
    assert resp.json()["detail"] == "v3 is superseded by v4"
    assert _decisions(sync_engine, request["id"]) == []


def test_cancelling_the_last_pending_request_after_approvals_approves(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _, opp, v3, [(ana_h, _), _], [ana_req, ben_req] = _sent(
        client, sync_engine, "Ana Reviewer", "Ben Reviewer"
    )
    assert _decide(client, ana_h, opp["id"], ana_req, "approved", reason=None).status_code == 201
    assert _status(sync_engine, v3) == "in_review"
    cancel = client.post(
        f"{BASE}/{opp['id']}/review-requests/{ben_req['id']}/cancel",
        headers={**headers, "If-Match": '"1"'},
        json={"reason": "Not needed."},
    )
    assert cancel.status_code == 200, cancel.text
    assert _status(sync_engine, v3) == "approved"
    assert len(_events(sync_engine, opp["id"], "estimates.estimate_version.approved")) == 1


@pytest.mark.parametrize("decision", ["approved", "rejected"])
def test_submitting_a_newer_draft_supersedes_a_decided_version(
    client: TestClient, sync_engine: Engine, decision: str
) -> None:
    headers, owner_id, opp, v3, [(ana_h, _)], [request] = _sent(client, sync_engine, "Ana Reviewer")
    reason = None if decision == "approved" else REASON
    assert _decide(client, ana_h, opp["id"], request, decision, reason=reason).status_code == 201
    assert _status(sync_engine, v3) == decision
    v4 = _version(sync_engine, opp["id"], 4, status="draft", created_by=owner_id)
    submitted = client.post(
        f"{BASE}/{opp['id']}/estimate/versions/{v4}/submit",
        headers={**headers, "If-Match": '"1"'},
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["superseded_count"] == 1
    assert (_status(sync_engine, v3), _status(sync_engine, v4)) == ("superseded", "submitted")


@pytest.mark.parametrize(
    ("decision", "code"),
    [("rejected", "estimate_version_rejected"), ("approved", "estimate_version_not_submitted")],
)
def test_a_decided_version_takes_no_new_request(
    client: TestClient, sync_engine: Engine, decision: str, code: str
) -> None:
    headers, _, opp, v3, [(ana_h, ana)], [request] = _sent(client, sync_engine, "Ana Reviewer")
    reason = None if decision == "approved" else REASON
    assert _decide(client, ana_h, opp["id"], request, decision, reason=reason).status_code == 201
    resp = _send(client, headers, opp["id"], v3, _row_version(sync_engine, v3), [ana])
    assert resp.status_code == 409
    assert resp.json()["code"] == code


def test_a_reviewer_with_two_pending_requests_keeps_access_after_one(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _, opp, v3 = _setup(client, sync_engine)
    cy_h, cy = _user(client, sync_engine, "Cy Reviewer", SEC)
    a1 = _assessment(sync_engine, opp["id"], "security_agent")
    a2 = _assessment(sync_engine, opp["id"], "engineering_agent")
    refs = [{"id": a1, "version": 1}, {"id": a2, "version": 1}]
    first, second = _send(client, headers, opp["id"], v3, 1, [cy], "security", refs).json()["items"]

    assert _decide(client, cy_h, opp["id"], first, "approved", reason=None).status_code == 201
    assert _collaborator_rows(sync_engine, opp["id"]) == {str(cy): "reviewer"}
    assert _status(sync_engine, v3) == "in_review"
    assert _decide(client, cy_h, opp["id"], second, "approved", reason=None).status_code == 201
    assert _collaborator_rows(sync_engine, opp["id"]) == {}
    assert _status(sync_engine, v3) == "approved"


def test_the_downgrade_maps_decided_versions_back_to_in_review(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, owner_id = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)
    approved = _version(sync_engine, opp["id"], 1, status="approved", created_by=owner_id)
    rejected = _version(sync_engine, opp["id"], 2, status="rejected", created_by=owner_id)

    _alembic("downgrade", "0048_notifications")
    _alembic("upgrade", "head")

    assert (_status(sync_engine, approved), _status(sync_engine, rejected)) == (
        "in_review",
        "in_review",
    )
