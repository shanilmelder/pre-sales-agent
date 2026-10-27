"""Review Requests (Story 9.1) against a real, migrated Postgres as psa_app: the state machine
(every allowed and forbidden pair), sending requests (happy path, narrowed to Assessments,
wrong role, author, draft / superseded, sales representative, outsider, duplicate, stale and
missing `If-Match`), reviewer read-only collaboration, cancelling (last pending, blank
reason, stale, not pending, who may), the blockers' `to_baseline`, the reviewer candidates,
the grants and the `created_by` backfill.

Estimate Versions and Assessments are inserted directly; people sign in through `/me` with
their roles, so identity's role cache holds them.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.reviews.domain.requests import (
    MESSAGE_MAX,
    TRANSITIONS,
    InvalidTransitionError,
    RequestStatus,
    can_transition,
    clean_message,
    clean_reason,
    transition,
)
from tests import test_opportunities as opportunity_tests
from tests.test_gaps_detection import rows
from tests.test_health import assert_problem
from tests.test_intake_parse_job import _alembic
from tests.test_opportunities import BASE, PSE, _add, _create, _user

client = opportunity_tests.client

ENG = "engineering_reviewer"
PM = "pm_reviewer"
SEC = "security_reviewer"
REP = "sales_representative"
CREATED = "reviews.review_request.created"
CANCELLED = "reviews.review_request.cancelled"
REASON = "Sent to the wrong reviewer."


# --- the state machine (no DB) --------------------------------------------------------------

ALLOWED = {
    (RequestStatus.PENDING, RequestStatus.APPROVED),
    (RequestStatus.PENDING, RequestStatus.REJECTED),
    (RequestStatus.PENDING, RequestStatus.CHALLENGED),
    (RequestStatus.PENDING, RequestStatus.SUPERSEDED),
    (RequestStatus.PENDING, RequestStatus.CANCELLED),
    (RequestStatus.APPROVED, RequestStatus.SUPERSEDED),
    (RequestStatus.REJECTED, RequestStatus.SUPERSEDED),
    (RequestStatus.CHALLENGED, RequestStatus.SUPERSEDED),
}


@pytest.mark.parametrize("current", list(RequestStatus))
@pytest.mark.parametrize("target", list(RequestStatus))
def test_every_transition_pair(current: RequestStatus, target: RequestStatus) -> None:
    allowed = (current, target) in ALLOWED
    assert can_transition(current, target) is allowed
    if allowed:
        assert transition(current, target) is target
    else:
        with pytest.raises(InvalidTransitionError):
            transition(current, target)


def test_the_table_covers_every_status() -> None:
    assert set(TRANSITIONS) == set(RequestStatus)


def test_message_and_reason_rules() -> None:
    assert clean_message(None) is None
    assert clean_message("   ") is None
    assert clean_message("  Please check L3  ") == "Please check L3"
    assert clean_message("x" * MESSAGE_MAX) == "x" * MESSAGE_MAX
    with pytest.raises(ValueError):
        clean_message("x" * (MESSAGE_MAX + 1))
    assert clean_reason("  ") is None
    assert clean_reason("x" * 1001) is None
    assert clean_reason(" Wrong person ") == "Wrong person"


# --- helpers --------------------------------------------------------------------------------


def _version(
    engine: Engine,
    opp_id: str,
    number: int,
    *,
    status: str = "submitted",
    created_by: UUID | None = None,
) -> str:
    version_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO estimates_estimate_versions (id, opportunity_id, version, status, "
                "template_version, uncovered_count, dropped_count, row_version, submitted_at, "
                "created_by) VALUES (:id, :o, :v, :s, 'v1', 0, 0, 1, :at, :by)"
            ),
            {
                "id": version_id,
                "o": opp_id,
                "v": number,
                "s": status,
                "at": None if status == "draft" else datetime.now(UTC),
                "by": created_by,
            },
        )
    return str(version_id)


def _assessment(engine: Engine, opp_id: str, agent: str, version: int = 1) -> str:
    assessment_id, run_id = uuid4(), uuid4()
    with engine.begin() as conn:
        # A real run: older migrations (a downgrade in other tests) key Assessments to it.
        conn.execute(
            sa.text(
                "INSERT INTO workflows_runs (id, opportunity_id, status) "
                "VALUES (:id, :o, 'succeeded')"
            ),
            {"id": run_id, "o": opp_id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO assessments_assessments (id, opportunity_id, agent, version, "
                "run_id, status, recommendation, confidence, confidence_basis, dropped_count, "
                "config_version_id) SELECT :id, :o, :a, :v, :run, 'current', 'proceed', 'high', "
                "'Basis', 0, id FROM registry_agent_config_versions WHERE agent_id = :a "
                "ORDER BY version LIMIT 1"
            ),
            {"id": assessment_id, "o": opp_id, "a": agent, "v": version, "run": run_id},
        )
    return str(assessment_id)


def _row_version(engine: Engine, version_id: str) -> int:
    (found,) = rows(
        engine, "SELECT row_version FROM estimates_estimate_versions WHERE id = :i", i=version_id
    )
    return int(found["row_version"])


def _status(engine: Engine, version_id: str) -> str:
    (found,) = rows(
        engine, "SELECT status FROM estimates_estimate_versions WHERE id = :i", i=version_id
    )
    return str(found["status"])


def _requests(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM reviews_review_requests WHERE opportunity_id = :o ORDER BY created_at, id",
        o=opp_id,
    )


def _collaborator_rows(engine: Engine, opp_id: str) -> dict[str, str]:
    found = rows(
        engine,
        "SELECT user_id, role FROM opportunities_collaborators WHERE opportunity_id = :o",
        o=opp_id,
    )
    return {str(r["user_id"]): r["role"] for r in found}


def _events(engine: Engine, opp_id: str, event_type: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM platform_trace_events WHERE opportunity_id = :o AND event_type = :e "
        "ORDER BY occurred_at, id",
        o=opp_id,
        e=event_type,
    )


def _send(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    version_id: str,
    row_version: int | None,
    reviewers: list[UUID],
    review_type: str = "engineering",
    assessments: list[dict[str, Any]] | None = None,
    message: str | None = None,
) -> Any:
    extra = {} if row_version is None else {"If-Match": f'"{row_version}"'}
    body: dict[str, Any] = {
        "version_id": version_id,
        "review_type": review_type,
        "reviewer_ids": [str(r) for r in reviewers],
        "assessment_refs": assessments or [],
    }
    if message is not None:
        body["message"] = message
    return client.post(f"{BASE}/{opp_id}/review-requests", headers={**headers, **extra}, json=body)


def _cancel(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    request: dict[str, Any],
    reason: str = REASON,
    row_version: int | None = None,
) -> Any:
    rv = request["row_version"] if row_version is None else row_version
    return client.post(
        f"{BASE}/{opp_id}/review-requests/{request['id']}/cancel",
        headers={**headers, "If-Match": f'"{rv}"'},
        json={"reason": reason},
    )


def _listed(client: TestClient, headers: dict[str, str], opp_id: str) -> dict[str, Any]:
    resp = client.get(f"{BASE}/{opp_id}/review-requests", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _setup(client: TestClient, engine: Engine) -> tuple[dict[str, str], UUID, dict[str, Any], str]:
    """An Opportunity owned by a presales engineer with a submitted v3 (v1, v2 superseded)
    whose author is the owner."""
    headers, owner_id = _user(client, engine, "Owner Person", PSE)
    opp = _create(client, headers)
    _version(engine, opp["id"], 1, status="superseded", created_by=owner_id)
    _version(engine, opp["id"], 2, status="superseded", created_by=owner_id)
    v3 = _version(engine, opp["id"], 3, created_by=owner_id)
    return headers, owner_id, opp, v3


# --- sending --------------------------------------------------------------------------------


def test_happy_path_sends_one_request_per_reviewer(client: TestClient, sync_engine: Engine) -> None:
    headers, owner_id, opp, v3 = _setup(client, sync_engine)
    _, ana = _user(client, sync_engine, "Ana Reviewer", ENG)
    _, ben = _user(client, sync_engine, "Ben Reviewer", ENG)

    before = client.get(f"{BASE}/{opp['id']}/estimate", headers=headers).json()
    assert before["can_request_review"] is True
    resp = _send(
        client, headers, opp["id"], v3, 1, [ana, ben], message="  Please check the totals.  "
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["version_status"] == "in_review"
    assert resp.headers["ETag"] == f'"{body["version_row_version"]}"'
    assert [i["reviewer"]["name"] for i in body["items"]] == ["Ana Reviewer", "Ben Reviewer"]
    for item in body["items"]:
        assert item["status"] == "pending"
        assert item["target"] == {
            "kind": "estimate_version",
            "id": v3,
            "version": 3,
            "label": "Estimate v3",
        }
        assert item["requested_by"] == {"id": str(owner_id), "name": "Owner Person"}
        assert item["message"] == "Please check the totals."
        assert item["can_cancel"] is True
    assert _status(sync_engine, v3) == "in_review"
    assert _collaborator_rows(sync_engine, opp["id"]) == {
        str(ana): "reviewer",
        str(ben): "reviewer",
    }
    created = _events(sync_engine, opp["id"], CREATED)
    assert len(created) == 2
    assert created[0]["payload"] == {
        "request_id": body["items"][0]["id"],
        "review_type": "engineering",
        "target_kind": "estimate_version",
        "target_id": v3,
        "target_version": 3,
        "estimate_version_id": v3,
        "reviewer_id": str(ana),
        "message_length": len("Please check the totals."),
        "linked_request_id": None,
    }
    assert (created[0]["actor_type"], created[0]["actor_id"]) == ("user", str(owner_id))
    assert len(_events(sync_engine, opp["id"], "estimates.estimate_version.review_started")) == 1

    estimate = client.get(f"{BASE}/{opp['id']}/estimate", headers=headers).json()
    assert estimate["version"]["status"] == "in_review"
    assert estimate["can_request_review"] is True
    listed = _listed(client, headers, opp["id"])
    assert (listed["version_id"], listed["version"], listed["can_create"]) == (v3, 3, True)
    assert {i["id"] for i in listed["items"]} == {i["id"] for i in body["items"]}

    detail = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    assert detail["collaborators"] == []
    assert [r["name"] for r in detail["reviewers"]] == ["Ana Reviewer", "Ben Reviewer"]


def test_narrowed_to_assessments_one_row_per_reviewer_and_assessment(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _, opp, v3 = _setup(client, sync_engine)
    _, cy = _user(client, sync_engine, "Cy Reviewer", SEC)
    a1 = _assessment(sync_engine, opp["id"], "security_agent", 2)
    a2 = _assessment(sync_engine, opp["id"], "engineering_agent", 1)
    options = {a["id"]: a for a in _listed(client, headers, opp["id"])["assessments"]}
    assert options[a1]["label"] == "Security Assessment v2"

    resp = _send(
        client,
        headers,
        opp["id"],
        v3,
        1,
        [cy],
        "security",
        [{"id": a1, "version": 2}, {"id": a2, "version": 1}],
    )

    assert resp.status_code == 201, resp.text
    stored = _requests(sync_engine, opp["id"])
    assert sorted((str(r["target_id"]), r["target_version"]) for r in stored) == sorted(
        [(a1, 2), (a2, 1)]
    )
    assert {r["target_kind"] for r in stored} == {"assessment"}
    assert {str(r["estimate_version_id"]) for r in stored} == {v3}
    assert {str(r["reviewer_id"]) for r in stored} == {str(cy)}
    labels = sorted(i["target"]["label"] for i in resp.json()["items"])
    assert labels == ["Engineering Assessment v1", "Security Assessment v2"]

    stale = _send(
        client,
        headers,
        opp["id"],
        v3,
        _row_version(sync_engine, v3),
        [cy],
        "security",
        [{"id": a1, "version": 1}],
    )
    assert_problem(stale.json(), 422, "validation_error")


def test_wrong_role_writes_nothing(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, v3 = _setup(client, sync_engine)
    _, pm = _user(client, sync_engine, "Pat Manager", PM)
    resp = _send(client, headers, opp["id"], v3, 1, [pm], "engineering")
    assert_problem(resp.json(), 422, "reviewer_not_authorized_for_type")
    assert "Pat Manager" in resp.json()["detail"]
    assert _requests(sync_engine, opp["id"]) == []
    assert _status(sync_engine, v3) == "submitted"
    assert _collaborator_rows(sync_engine, opp["id"]) == {}


def test_the_author_cannot_review(client: TestClient, sync_engine: Engine) -> None:
    tag = uuid4().hex[:8]
    _, author_id = _user(client, sync_engine, f"Author {tag}", PSE, ENG)
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)
    v3 = _version(sync_engine, opp["id"], 3, created_by=author_id)
    candidates = client.get(
        f"{BASE}/{opp['id']}/review-requests/reviewer-candidates",
        headers=headers,
        params={"review_type": "engineering", "q": tag},
    )
    assert candidates.status_code == 200, candidates.text
    assert candidates.json()["items"] == []

    resp = _send(client, headers, opp["id"], v3, 1, [author_id])

    assert_problem(resp.json(), 422, "author_cannot_review")
    assert resp.json()["detail"] == "The author of v3 can't review it"
    assert _requests(sync_engine, opp["id"]) == []


def test_unknown_author_skips_the_check(client: TestClient, sync_engine: Engine) -> None:
    headers, _ = _user(client, sync_engine, "Owner Person", PSE)
    _, eve = _user(client, sync_engine, "Eve Reviewer", ENG)
    opp = _create(client, headers)
    v1 = _version(sync_engine, opp["id"], 1, created_by=None)
    assert _send(client, headers, opp["id"], v1, 1, [eve]).status_code == 201


def test_draft_and_superseded_versions_are_409(client: TestClient, sync_engine: Engine) -> None:
    headers, owner_id = _user(client, sync_engine, "Owner Person", PSE)
    _, ana = _user(client, sync_engine, "Ana Reviewer", ENG)
    opp = _create(client, headers)
    v2 = _version(sync_engine, opp["id"], 2, status="superseded", created_by=owner_id)
    _version(sync_engine, opp["id"], 3, created_by=owner_id)
    v4 = _version(sync_engine, opp["id"], 4, status="draft", created_by=owner_id)

    estimate = client.get(f"{BASE}/{opp['id']}/estimate", headers=headers).json()
    assert estimate["version"]["status"] == "draft"
    assert estimate["can_request_review"] is False
    assert _listed(client, headers, opp["id"])["can_create"] is False

    draft = _send(client, headers, opp["id"], v4, 1, [ana])
    assert_problem(draft.json(), 409, "estimate_version_not_submitted")
    assert draft.json()["detail"] == "Submit this Estimate Version before requesting review"
    superseded = _send(client, headers, opp["id"], v2, 1, [ana])
    assert_problem(superseded.json(), 409, "estimate_version_superseded")
    # Story 9.4: superseded by the next version submitted, not the later draft.
    assert superseded.json()["detail"] == "v2 is superseded by v3"
    assert _requests(sync_engine, opp["id"]) == []


def test_who_may_send(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, v3 = _setup(client, sync_engine)
    rep, rep_id = _user(client, sync_engine, "Rep Person", REP)
    member, member_id = _user(client, sync_engine, "Member Person", PSE)
    for user_id in (rep_id, member_id):
        current = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
        assert _add(client, headers, current, user_id).status_code == 200
    outsider, _ = _user(client, sync_engine, "Outsider", PSE)
    _, ana = _user(client, sync_engine, "Ana Reviewer", ENG)

    seen = client.get(f"{BASE}/{opp['id']}/estimate", headers=rep).json()
    assert seen["can_request_review"] is False
    assert _listed(client, rep, opp["id"])["can_create"] is False
    assert_problem(_send(client, rep, opp["id"], v3, 1, [ana]).json(), 403, "forbidden")
    candidates = f"{BASE}/{opp['id']}/review-requests/reviewer-candidates"
    params = {"review_type": "engineering"}
    assert client.get(candidates, headers=rep, params=params).status_code == 403
    for path in (f"{BASE}/{opp['id']}/review-requests", candidates):
        assert_problem(client.get(path, headers=outsider, params=params).json(), 404, "not_found")
    assert_problem(_send(client, outsider, opp["id"], v3, 1, [ana]).json(), 404, "not_found")

    sent = _send(client, member, opp["id"], v3, 1, [ana])
    assert sent.status_code == 201, sent.text
    request = sent.json()["items"][0]
    assert_problem(_cancel(client, rep, opp["id"], request).json(), 403, "forbidden")
    assert_problem(_cancel(client, outsider, opp["id"], request).json(), 404, "not_found")
    # The owner may cancel a request a collaborator sent.
    assert _cancel(client, headers, opp["id"], request).status_code == 200


def test_duplicate_pending_request_is_409(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, v3 = _setup(client, sync_engine)
    _, ana = _user(client, sync_engine, "Ana Reviewer", ENG)
    _, ben = _user(client, sync_engine, "Ben Reviewer", ENG)
    assert _send(client, headers, opp["id"], v3, 1, [ana]).status_code == 201
    again = _send(client, headers, opp["id"], v3, _row_version(sync_engine, v3), [ben, ana])
    assert_problem(again.json(), 409, "review_request_duplicate")
    assert "Ana Reviewer" in again.json()["detail"]
    assert len(_requests(sync_engine, opp["id"])) == 1
    # Another review type on the same target is not a duplicate; the version stays in review.
    _, ana_pm = _user(client, sync_engine, "Ana PM", PM)
    rv = _row_version(sync_engine, v3)
    assert _send(client, headers, opp["id"], v3, rv, [ana_pm], "pm").status_code == 201
    assert _status(sync_engine, v3) == "in_review"


def test_stale_or_missing_if_match(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, v3 = _setup(client, sync_engine)
    _, ana = _user(client, sync_engine, "Ana Reviewer", ENG)
    _, ben = _user(client, sync_engine, "Ben Reviewer", ENG)
    assert _send(client, headers, opp["id"], v3, 1, [ana]).status_code == 201
    stale = _send(client, headers, opp["id"], v3, 1, [ben])
    assert_problem(stale.json(), 412, "row_version_mismatch")
    missing = _send(client, headers, opp["id"], v3, None, [ben])
    assert_problem(missing.json(), 428, "if_match_required")
    assert len(_requests(sync_engine, opp["id"])) == 1


def test_bad_bodies_are_422(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, v3 = _setup(client, sync_engine)
    _, ana = _user(client, sync_engine, "Ana Reviewer", ENG)
    assert_problem(_send(client, headers, opp["id"], v3, 1, []).json(), 422, "validation_error")
    twice = _send(client, headers, opp["id"], v3, 1, [ana, ana])
    assert_problem(twice.json(), 422, "validation_error")
    long = _send(client, headers, opp["id"], v3, 1, [ana], message="x" * (MESSAGE_MAX + 1))
    assert_problem(long.json(), 422, "validation_error")
    assert _requests(sync_engine, opp["id"]) == []


# --- reviewer collaboration -----------------------------------------------------------------


def test_a_reviewer_reads_every_tab_but_writes_nothing(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _, opp, v3 = _setup(client, sync_engine)
    reviewer, ana = _user(client, sync_engine, "Ana Reviewer", ENG)
    opp_id = opp["id"]
    assert client.get(f"{BASE}/{opp_id}", headers=reviewer).status_code == 404
    assert _send(client, headers, opp_id, v3, 1, [ana]).status_code == 201

    for path in (
        "",
        "/requirements",
        "/gaps",
        "/assessments",
        "/conflicts",
        "/estimate",
        "/trace",
        "/submission-blockers",
        "/review-requests",
        "/red-team",
        "/critic",
    ):
        assert client.get(f"{BASE}/{opp_id}{path}", headers=reviewer).status_code == 200, path
    detail = client.get(f"{BASE}/{opp_id}", headers=reviewer).json()
    assert (detail["can_edit"], detail["can_add_sources"]) == (False, False)
    assert detail["can_manage_collaborators"] is False
    estimate = client.get(f"{BASE}/{opp_id}/estimate", headers=reviewer).json()
    flags = [k for k, v in estimate.items() if k.startswith("can_") and v]
    assert flags == []
    listed = _listed(client, reviewer, opp_id)
    assert listed["can_create"] is False
    assert [i["can_cancel"] for i in listed["items"]] == [False]

    rv = _row_version(sync_engine, v3)
    writes = [
        client.post(
            f"{BASE}/{opp_id}/requirements",
            headers=reviewer,
            json={"text": "The system shall log every pick.", "classification": "functional"},
        ),
        client.post(f"{BASE}/{opp_id}/assumptions/accept-all", headers=reviewer),
        client.post(f"{BASE}/{opp_id}/estimate-drafts", headers=reviewer),
        client.post(
            f"{BASE}/{opp_id}/estimate/versions/{v3}/submit",
            headers={**reviewer, "If-Match": f'"{rv}"'},
        ),
        _send(client, reviewer, opp_id, v3, rv, [ana]),
        _cancel(client, reviewer, opp_id, listed["items"][0]),
        client.patch(
            f"{BASE}/{opp_id}",
            headers={**reviewer, "If-Match": f'"{detail["row_version"]}"'},
            json={"title": "Renamed"},
        ),
    ]
    for resp in writes:
        assert_problem(resp.json(), 403, "forbidden")


def test_the_owner_cannot_remove_a_reviewer_but_can_make_them_a_collaborator(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _, opp, v3 = _setup(client, sync_engine)
    _, ana = _user(client, sync_engine, "Ana Reviewer", ENG)
    assert _send(client, headers, opp["id"], v3, 1, [ana]).status_code == 201
    current = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    removed = client.delete(
        f"{BASE}/{opp['id']}/collaborators/{ana}",
        headers={**headers, "If-Match": f'"{current["row_version"]}"'},
    )
    assert removed.status_code == 200, removed.text
    assert _collaborator_rows(sync_engine, opp["id"]) == {str(ana): "reviewer"}

    assert _add(client, headers, current, ana).status_code == 200
    assert _collaborator_rows(sync_engine, opp["id"]) == {str(ana): "collaborator"}
    request = _listed(client, headers, opp["id"])["items"][0]
    assert _cancel(client, headers, opp["id"], request).status_code == 200
    # A full collaborator keeps their access when the request is cancelled.
    assert _collaborator_rows(sync_engine, opp["id"]) == {str(ana): "collaborator"}


# --- cancelling -----------------------------------------------------------------------------


def test_cancelling_the_last_pending_request(client: TestClient, sync_engine: Engine) -> None:
    headers, owner_id, opp, v3 = _setup(client, sync_engine)
    reviewer, ana = _user(client, sync_engine, "Ana Reviewer", ENG)
    _, ben = _user(client, sync_engine, "Ben Reviewer", ENG)
    first, second = _send(client, headers, opp["id"], v3, 1, [ana, ben]).json()["items"]

    assert_problem(
        _cancel(client, headers, opp["id"], first, "   ").json(), 422, "validation_error"
    )
    assert_problem(
        _cancel(client, headers, opp["id"], first, "x" * 1001).json(), 422, "validation_error"
    )
    stale = _cancel(client, headers, opp["id"], first, row_version=7)
    assert_problem(stale.json(), 412, "row_version_mismatch")

    resp = _cancel(client, headers, opp["id"], first, f"  {REASON}  ")
    assert resp.status_code == 200, resp.text
    cancelled = resp.json()
    assert (cancelled["status"], cancelled["cancel_reason"]) == ("cancelled", REASON)
    assert resp.headers["ETag"] == f'"{cancelled["row_version"]}"'
    assert cancelled["can_cancel"] is False
    assert _status(sync_engine, v3) == "in_review"  # Ben's is still pending
    assert _collaborator_rows(sync_engine, opp["id"]) == {str(ben): "reviewer"}
    assert client.get(f"{BASE}/{opp['id']}", headers=reviewer).status_code == 404
    again = _cancel(client, headers, opp["id"], cancelled)
    assert_problem(again.json(), 409, "review_request_not_pending")

    assert _cancel(client, headers, opp["id"], second).status_code == 200
    assert _status(sync_engine, v3) == "submitted"
    assert _collaborator_rows(sync_engine, opp["id"]) == {}
    events = _events(sync_engine, opp["id"], CANCELLED)
    assert [e["payload"]["reason_length"] for e in events] == [len(REASON), len(REASON)]
    assert {e["actor_id"] for e in events} == {str(owner_id)}
    assert len(_events(sync_engine, opp["id"], "estimates.estimate_version.review_ended")) == 1
    estimate = client.get(f"{BASE}/{opp['id']}/estimate", headers=headers).json()
    assert estimate["version"]["status"] == "submitted"


def test_a_collaborator_may_cancel_only_their_own(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, v3 = _setup(client, sync_engine)
    member, member_id = _user(client, sync_engine, "Member Person", PSE)
    current = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    assert _add(client, headers, current, member_id).status_code == 200
    _, ana = _user(client, sync_engine, "Ana Reviewer", ENG)
    owners = _send(client, headers, opp["id"], v3, 1, [ana]).json()["items"][0]
    assert _listed(client, member, opp["id"])["items"][0]["can_cancel"] is False
    assert_problem(_cancel(client, member, opp["id"], owners).json(), 403, "forbidden")
    missing = {**owners, "id": str(uuid4())}
    assert_problem(_cancel(client, headers, opp["id"], missing).json(), 404, "not_found")


# --- blockers -------------------------------------------------------------------------------


def test_open_requests_are_blockers_to_baseline(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, v3 = _setup(client, sync_engine)
    _, ana = _user(client, sync_engine, "Ana Reviewer", ENG)
    before = client.get(f"{BASE}/{opp['id']}/submission-blockers", headers=headers).json()
    # Story 9.7: a submitted version with no Review Request yet is blocked from the Baseline.
    assert before["to_submit"] == []
    assert [b["kind"] for b in before["to_baseline"]] == ["no_review_request"]

    request = _send(client, headers, opp["id"], v3, 1, [ana], message="Check L3 hours").json()[
        "items"
    ][0]

    view = client.get(f"{BASE}/{opp['id']}/submission-blockers", headers=headers).json()
    assert view["version"]["status"] == "in_review"
    (blocker,) = view["to_baseline"]
    assert blocker["kind"] == "review_request"
    assert blocker["subject_id"] == request["id"]
    assert blocker["title"] == "Engineering review · Ana Reviewer · Pending"
    assert blocker["detail"].startswith("Sent ")
    assert blocker["detail"].endswith(" · Check L3 hours")
    assert blocker["href"] == f"/opportunities/{opp['id']}/estimate?review={request['id']}"
    assert view["to_submit"] == []
    estimate = client.get(f"{BASE}/{opp['id']}/estimate", headers=headers).json()
    assert estimate["blockers"]["to_baseline"] == view["to_baseline"]

    assert _cancel(client, headers, opp["id"], request).status_code == 200
    after = client.get(f"{BASE}/{opp['id']}/submission-blockers", headers=headers).json()
    # The cancelled request no longer blocks, but with none left the version needs one again.
    assert [b["kind"] for b in after["to_baseline"]] == ["no_review_request"]


# --- reviewer candidates --------------------------------------------------------------------


def test_reviewer_candidates_hold_the_role(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, _ = _setup(client, sync_engine)
    tag = uuid4().hex[:8]
    _user(client, sync_engine, f"Eng {tag}", ENG)
    _user(client, sync_engine, f"Sec {tag}", SEC)
    _user(client, sync_engine, f"Plain {tag}", PSE)
    path = f"{BASE}/{opp['id']}/review-requests/reviewer-candidates"

    def names(review_type: str) -> list[str]:
        resp = client.get(path, headers=headers, params={"review_type": review_type, "q": tag})
        assert resp.status_code == 200, resp.text
        return [i["name"] for i in resp.json()["items"]]

    assert names("engineering") == [f"Eng {tag}"]
    assert names("security") == [f"Sec {tag}"]
    assert names("pm") == []
    bad = client.get(path, headers=headers, params={"review_type": "legal"})
    assert_problem(bad.json(), 422, "validation_error")


# --- grants and migration -------------------------------------------------------------------


def test_psa_app_cannot_delete_review_requests(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, v3 = _setup(client, sync_engine)
    _, ana = _user(client, sync_engine, "Ana Reviewer", ENG)
    request = _send(client, headers, opp["id"], v3, 1, [ana]).json()["items"][0]
    with pytest.raises(sa.exc.ProgrammingError), sync_engine.begin() as conn:
        conn.execute(
            sa.text("DELETE FROM reviews_review_requests WHERE id = :i"), {"i": request["id"]}
        )


def test_migration_backfills_created_by(client: TestClient, sync_engine: Engine) -> None:
    headers, owner_id = _user(client, sync_engine, "Owner Person", PSE)
    opp = _create(client, headers)
    traced = _version(sync_engine, opp["id"], 1, status="superseded")
    unknown = _version(sync_engine, opp["id"], 2, status="superseded")
    from_run, run_id = uuid4(), uuid4()
    with sync_engine.begin() as conn:
        # A version from the Assessments of a run the owner started, with no user trace event.
        conn.execute(
            sa.text(
                "INSERT INTO workflows_runs (id, opportunity_id, status) "
                "VALUES (:id, :o, 'succeeded')"
            ),
            {"id": run_id, "o": opp["id"]},
        )
        conn.execute(
            sa.text(
                "INSERT INTO workflows_plan_versions (id, run_id, version, tasks, "
                "created_by_type, created_by) VALUES (:id, :r, 1, CAST('[]' AS jsonb), 'user', :u)"
            ),
            {"id": uuid4(), "r": run_id, "u": str(owner_id)},
        )
        conn.execute(
            sa.text(
                "INSERT INTO estimates_estimate_versions (id, opportunity_id, version, status, "
                "template_version, uncovered_count, dropped_count, row_version, source, "
                "source_run_id) VALUES (:id, :o, 3, 'draft', 'v1', 0, 0, 1, 'assessments', :r)"
            ),
            {"id": from_run, "o": opp["id"], "r": run_id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO platform_trace_events (id, opportunity_id, actor_type, actor_id, "
                "event_type, subject_type, subject_id, payload) VALUES (:id, :o, 'user', :a, "
                "'estimates.estimate_version.created', 'estimates.estimate_version', :s, "
                "CAST('{}' AS jsonb))"
            ),
            {"id": uuid4(), "o": opp["id"], "a": str(owner_id), "s": traced},
        )

    _alembic("downgrade", "0044_submitted_status")
    _alembic("upgrade", "head")

    found = {
        str(r["id"]): r["created_by"]
        for r in rows(
            sync_engine,
            "SELECT id, created_by FROM estimates_estimate_versions WHERE opportunity_id = :o",
            o=opp["id"],
        )
    }
    assert found == {traced: owner_id, unknown: None, str(from_run): owner_id}


# --- review follow-ups ----------------------------------------------------------------------


def _mine(client: TestClient, headers: dict[str, str]) -> dict[str, dict[str, Any]]:
    body = client.get(BASE, headers=headers, params={"scope": "mine", "page_size": 200}).json()
    return {item["id"]: item for item in body["items"]}


def test_submitting_a_newer_version_supersedes_one_in_review(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, owner_id = _user(client, sync_engine, "Owner Person", PSE)
    _, ana = _user(client, sync_engine, "Ana Reviewer", ENG)
    opp = _create(client, headers)
    v1 = _version(sync_engine, opp["id"], 1, created_by=owner_id)
    assert _send(client, headers, opp["id"], v1, 1, [ana]).status_code == 201
    assert _status(sync_engine, v1) == "in_review"
    v2 = _version(sync_engine, opp["id"], 2, status="draft", created_by=owner_id)

    submitted = client.post(
        f"{BASE}/{opp['id']}/estimate/versions/{v2}/submit",
        headers={**headers, "If-Match": '"1"'},
    )

    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["superseded_count"] == 1
    assert (_status(sync_engine, v1), _status(sync_engine, v2)) == ("superseded", "submitted")
    # Story 9.4: its pending request is superseded too, and Ana's access ends with it.
    (request,) = _requests(sync_engine, opp["id"])
    assert request["status"] == "superseded"
    assert _collaborator_rows(sync_engine, opp["id"]) == {}
    (event,) = _events(sync_engine, opp["id"], "reviews.review_request.superseded")
    assert event["payload"]["superseded_by_version"] == 2


def test_a_reviewer_keeps_access_until_their_last_pending_request_is_cancelled(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _, opp, v3 = _setup(client, sync_engine)
    reviewer, cy = _user(client, sync_engine, "Cy Reviewer", SEC)
    a1 = _assessment(sync_engine, opp["id"], "security_agent")
    a2 = _assessment(sync_engine, opp["id"], "engineering_agent")
    refs = [{"id": a1, "version": 1}, {"id": a2, "version": 1}]
    assert opp["id"] not in _mine(client, reviewer)
    sent = _send(client, headers, opp["id"], v3, 1, [cy], "security", refs)
    first, second = sent.json()["items"]
    assert opp["id"] in _mine(client, reviewer)

    assert _cancel(client, headers, opp["id"], first).status_code == 200
    assert _collaborator_rows(sync_engine, opp["id"]) == {str(cy): "reviewer"}
    assert client.get(f"{BASE}/{opp['id']}", headers=reviewer).status_code == 200
    assert opp["id"] in _mine(client, reviewer)

    assert _cancel(client, headers, opp["id"], second).status_code == 200
    assert _collaborator_rows(sync_engine, opp["id"]) == {}
    assert_problem(client.get(f"{BASE}/{opp['id']}", headers=reviewer).json(), 404, "not_found")
    assert opp["id"] not in _mine(client, reviewer)


def test_the_list_row_shows_an_in_review_version(client: TestClient, sync_engine: Engine) -> None:
    headers, _, opp, v3 = _setup(client, sync_engine)
    _, ana = _user(client, sync_engine, "Ana Reviewer", ENG)
    assert _send(client, headers, opp["id"], v3, 1, [ana]).status_code == 201
    row = _mine(client, headers)[opp["id"]]
    assert (row["estimate"]["version"], row["estimate"]["status"]) == (3, "in_review")
