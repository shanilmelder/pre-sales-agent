"""Challenges (Story 9.5) against a real, migrated Postgres as psa_app: the state machine and
the suggestion rules (no DB), every row of the story's matrix (reviewer raises from a review,
owner raises their own, confirm, confirm twice, decline, superseded, run active, not
allowed, already decided), the Review Request transitions, access kept while challenged, the
Inbox items, the suggestions read, the grants and the migration down and up.

Estimate Versions, Assessments, Findings and Requirements are inserted directly; people sign
in through `/me` with their roles (see `test_reviews_requests`).
"""

from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.reviews.domain.challenges import (
    CHALLENGE_TRANSITIONS,
    ChallengeStatus,
    CitingAssessment,
    InvalidChallengeTransitionError,
    SuggestionTag,
    can_transition,
    clean_challenge_reason,
    suggest,
    transition,
)
from tests import test_opportunities as opportunity_tests
from tests.test_gaps_detection import rows
from tests.test_intake_parse_job import _alembic
from tests.test_opportunities import BASE, PSE, _add, _create, _user
from tests.test_reviews_decisions import _decide
from tests.test_reviews_requests import (
    ENG,
    REP,
    _assessment,
    _cancel,
    _collaborator_rows,
    _events,
    _row_version,
    _send,
    _setup,
    _version,
)

client = opportunity_tests.client

INBOX = "/api/v1/inbox"
REASON = "F1 ignores the ERP rate limit."
RAISED = "reviews.challenge.raised"
CONFIRMED = "reviews.challenge.confirmed"
DECLINED = "reviews.challenge.declined"
ENGINEERING = "engineering_agent"


@pytest.fixture(autouse=True)
def _no_runs_left_queued(request: pytest.FixtureRequest) -> Any:
    """The reassessment runs these tests start are never executed: park their jobs so a later
    worker test does not pick them up."""
    if "sync_engine" not in request.fixturenames:
        yield
        return
    engine: Engine = request.getfixturevalue("sync_engine")
    yield
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE platform_jobs SET status = 'dead', last_error = 'test: not run' "
                "WHERE status = 'queued' AND job_type = 'workflows.execute' "
                "AND opportunity_id IN (SELECT opportunity_id FROM reviews_challenges)"
            )
        )


# --- the state machine and the rules (no DB) ------------------------------------------------

ALLOWED = {
    (ChallengeStatus.AWAITING_CONFIRMATION, ChallengeStatus.REASSESSING),
    (ChallengeStatus.AWAITING_CONFIRMATION, ChallengeStatus.DECLINED),
    (ChallengeStatus.REASSESSING, ChallengeStatus.COMPLETED),
    (ChallengeStatus.REASSESSING, ChallengeStatus.FAILED),
}


@pytest.mark.parametrize("current", list(ChallengeStatus))
@pytest.mark.parametrize("target", list(ChallengeStatus))
def test_every_transition_pair(current: ChallengeStatus, target: ChallengeStatus) -> None:
    allowed = (current, target) in ALLOWED
    assert can_transition(current, target) is allowed
    if allowed:
        assert transition(current, target) is target
    else:
        with pytest.raises(InvalidChallengeTransitionError):
            transition(current, target)


def test_the_table_covers_every_status() -> None:
    assert set(CHALLENGE_TRANSITIONS) == set(ChallengeStatus)


def test_the_reason_rule() -> None:
    assert clean_challenge_reason(None) is None
    assert clean_challenge_reason("   ") is None
    assert clean_challenge_reason("x" * 1001) is None
    assert clean_challenge_reason("  Too low  ") == "Too low"
    assert clean_challenge_reason("x" * 1000) == "x" * 1000


def test_suggestions_are_deterministic() -> None:
    r1, r2, r3, erp, crm = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    found = suggest(
        holders=[("engineering_agent", "Holds the challenged Finding")],
        target_requirements=frozenset({r1, r3}),
        requirement_numbers={r1: 12, r2: 4, r3: 7},
        requirement_types={r1: [(erp, "ERP")], r2: [(erp, "ERP"), (crm, "CRM")]},
        others=[
            CitingAssessment("security_agent", frozenset({r2})),
            CitingAssessment("pm_agent", frozenset({r1, r3})),
            CitingAssessment("engineering_agent", frozenset({r1})),
        ],
    )
    assert [(s.agent, s.why, s.tag) for s in found] == [
        ("engineering_agent", "Holds the challenged Finding", SuggestionTag.SUGGESTED),
        ("pm_agent", "Cites R7", SuggestionTag.OPTIONAL),
        ("security_agent", "Shares the ERP integration type", SuggestionTag.OPTIONAL),
    ]
    assert [s.preselected for s in found] == [True, False, False]
    # Nothing shared: only the holder.
    alone = suggest(
        holders=[("pm_agent", "The challenged Assessment")],
        target_requirements=frozenset({r3}),
        requirement_numbers={},
        requirement_types={},
        others=[CitingAssessment("security_agent", frozenset({r2}))],
    )
    assert [s.agent for s in alone] == ["pm_agent"]


# --- helpers --------------------------------------------------------------------------------


def _requirement(engine: Engine, opp_id: str, number: int, *entries: UUID) -> UUID:
    requirement_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO intake_requirements (id, opportunity_id, text, classification, "
                "origin, locked_by_human, status, version, row_version, number) VALUES "
                "(:i, :o, 'Sync orders.', 'integration', 'human', true, 'active', 1, 1, :n)"
            ),
            {"i": requirement_id, "o": opp_id, "n": number},
        )
        for entry_id in entries:
            conn.execute(
                sa.text(
                    "INSERT INTO intake_requirement_integration_types (requirement_id, entry_id, "
                    "tagged_by) VALUES (:r, :e, :u)"
                ),
                {"r": requirement_id, "e": entry_id, "u": uuid4()},
            )
    return requirement_id


def _entry(engine: Engine, name: str) -> UUID:
    entry_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO knowledge_catalogue_entries (id, kind, code, status, row_version) "
                "VALUES (:i, 'integration_type', :c, 'active', 1)"
            ),
            {"i": entry_id, "c": f"CH-{uuid4().hex[:8]}"},
        )
        conn.execute(
            sa.text(
                "INSERT INTO knowledge_catalogue_entry_versions "
                "(entry_id, version, name, definition, changed_by) "
                "VALUES (:i, 1, :n, 'A definition.', :u)"
            ),
            {"i": entry_id, "n": name, "u": uuid4()},
        )
    return entry_id


def _finding(
    engine: Engine, assessment_id: str, title: str, *requirements: UUID, position: int = 1
) -> str:
    finding_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO assessments_assessment_findings (id, assessment_id, position, kind, "
                "severity, title, detail) VALUES (:id, :a, :p, 'risk', 'high', :t, 'D')"
            ),
            {"id": finding_id, "a": assessment_id, "p": position, "t": title},
        )
        for requirement_id in requirements:
            conn.execute(
                sa.text(
                    "INSERT INTO assessments_assessment_finding_requirements (finding_id, "
                    "requirement_id, requirement_version) VALUES (:f, :r, 1)"
                ),
                {"f": finding_id, "r": requirement_id},
            )
    return str(finding_id)


class Scene:
    """`_setup` (v3 submitted by the owner) with three current Assessments: Engineering v2
    whose Finding F1 cites R1 (tagged with an ERP Integration Type), PM v1 citing R1 too,
    Security v1 citing R2 (also ERP-tagged); and Ana, an engineering reviewer, with a
    pending request on the Engineering Assessment."""

    def __init__(self, client: TestClient, engine: Engine) -> None:
        self.headers, self.owner_id, self.opp, self.v3 = _setup(client, engine)
        self.erp_name = f"ERP {uuid4().hex[:6]}"
        erp = _entry(engine, self.erp_name)
        r1 = _requirement(engine, self.opp["id"], 1, erp)
        r2 = _requirement(engine, self.opp["id"], 2, erp)
        self.eng = _assessment(engine, self.opp["id"], ENGINEERING, 2)
        self.pm = _assessment(engine, self.opp["id"], "pm_agent", 1)
        self.sec = _assessment(engine, self.opp["id"], "security_agent", 1)
        self.f1 = _finding(engine, self.eng, "No ERP retry budget", r1)
        _finding(engine, self.pm, "Order sync scope", r1)
        _finding(engine, self.sec, "ERP credentials", r2)
        self.ana_h, self.ana = _user(client, engine, "Ana Reviewer", ENG)
        resp = _send(
            client,
            self.headers,
            self.opp["id"],
            self.v3,
            1,
            [self.ana],
            "engineering",
            [{"id": self.eng, "version": 2}],
        )
        assert resp.status_code == 201, resp.text
        (self.request,) = resp.json()["items"]


def _raise(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    target_kind: str,
    target_id: str,
    *,
    reason: str = REASON,
    review_request_id: str | None = None,
    confirmed: list[str] | None = None,
) -> Any:
    body: dict[str, Any] = {"target_kind": target_kind, "target_id": target_id, "reason": reason}
    if review_request_id is not None:
        body["review_request_id"] = review_request_id
    if confirmed is not None:
        body["confirmed"] = confirmed
    return client.post(f"{BASE}/{opp_id}/challenges", headers=headers, json=body)


def _confirm(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    challenge: dict[str, Any],
    confirmed: list[str],
    row_version: int | None = None,
) -> Any:
    rv = challenge["row_version"] if row_version is None else row_version
    return client.post(
        f"{BASE}/{opp_id}/challenges/{challenge['id']}/confirm",
        headers={**headers, "If-Match": f'"{rv}"'},
        json={"confirmed": confirmed},
    )


def _decline(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    challenge: dict[str, Any],
    reason: str = "Already covered by R1's buffer.",
) -> Any:
    return client.post(
        f"{BASE}/{opp_id}/challenges/{challenge['id']}/decline",
        headers={**headers, "If-Match": f'"{challenge["row_version"]}"'},
        json={"reason": reason},
    )


def _challenges(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM reviews_challenges WHERE opportunity_id = :o ORDER BY created_at",
        o=opp_id,
    )


def _runs(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM workflows_runs WHERE opportunity_id = :o ORDER BY created_at, id",
        o=opp_id,
    )


def _request_status(engine: Engine, request_id: str) -> str:
    (found,) = rows(
        engine, "SELECT status FROM reviews_review_requests WHERE id = :i", i=request_id
    )
    return str(found["status"])


def _from_review(client: TestClient, scene: Scene) -> dict[str, Any]:
    resp = _raise(
        client,
        scene.ana_h,
        scene.opp["id"],
        "finding",
        scene.f1,
        review_request_id=scene.request["id"],
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


# --- the matrix -----------------------------------------------------------------------------


def test_a_reviewer_raises_from_the_review(client: TestClient, sync_engine: Engine) -> None:
    scene = Scene(client, sync_engine)
    opp_id = scene.opp["id"]

    challenge = _from_review(client, scene)

    assert challenge["status"] == "awaiting_confirmation"
    assert challenge["status_label"] == "Awaiting confirmation"
    assert challenge["title"] == "Challenge Finding: No ERP retry budget"
    assert challenge["target"] == {
        "kind": "finding",
        "id": scene.f1,
        "version": 2,
        "label": "Finding: No ERP retry budget",
    }
    assert [(s["agent"], s["label"], s["why"], s["tag"]) for s in challenge["suggested"]] == [
        (ENGINEERING, "Engineering Agent", "Holds the challenged Finding", "suggested"),
        ("pm_agent", "PM Agent", "Cites R1", "optional"),
        (
            "security_agent",
            "Security Agent",
            f"Shares the {scene.erp_name} integration type",
            "optional",
        ),
    ]
    assert challenge["always_rerun"] == ["Critic", "Red Team"]
    assert (challenge["estimate_version"], challenge["superseded_by"]) == (3, None)
    assert (challenge["can_confirm"], challenge["can_decline"]) == (False, False)
    assert challenge["challenger"]["name"] == "Ana Reviewer"

    # The request is challenged with a `challenged` decision; Ana keeps her access.
    assert _request_status(sync_engine, scene.request["id"]) == "challenged"
    (decision,) = rows(
        sync_engine,
        "SELECT * FROM reviews_review_decisions WHERE review_request_id = :r",
        r=scene.request["id"],
    )
    assert (decision["decision"], decision["reason"]) == ("challenged", REASON)
    assert _collaborator_rows(sync_engine, opp_id) == {str(scene.ana): "reviewer"}
    seen = client.get(f"{BASE}/{opp_id}/challenges/{challenge['id']}", headers=scene.ana_h)
    assert seen.status_code == 200

    (stored,) = _challenges(sync_engine, opp_id)
    assert (stored["estimate_version_id"], stored["assessment_id"]) == (
        UUID(scene.v3),
        UUID(scene.eng),
    )
    assert stored["suggested"][0] == {
        "agent": ENGINEERING,
        "why": "Holds the challenged Finding",
        "tag": "suggested",
    }
    (raised,) = _events(sync_engine, opp_id, RAISED)
    assert raised["payload"]["suggested"] == [ENGINEERING, "pm_agent", "security_agent"]
    assert (raised["payload"]["reason"], raised["payload"]["target_kind"]) == (REASON, "finding")
    assert str(raised["actor_id"]) == str(scene.ana)
    recorded = _events(sync_engine, opp_id, "reviews.review_decision.recorded")
    assert [e["payload"]["decision"] for e in recorded] == ["challenged"]

    # The owner has a Challenges item that opens the dialog.
    (item,) = [
        i
        for i in client.get(INBOX, headers=scene.headers).json()["items"]
        if i["kind"] == "challenge_raised"
    ]
    assert (item["group"], item["subject_open"], item["sender"]) == (
        "challenges",
        True,
        "Ana Reviewer",
    )
    assert item["subject_status_label"] == "Awaiting confirmation"
    assert item["href"] == f"/opportunities/{opp_id}/assessments?challenge={challenge['id']}"
    assert REASON not in item["summary"]

    # The owner sees it as confirmable.
    owner_view = client.get(f"{BASE}/{opp_id}/challenges/{challenge['id']}", headers=scene.headers)
    assert owner_view.headers["ETag"] == '"1"'
    assert (owner_view.json()["can_confirm"], owner_view.json()["can_decline"]) == (True, True)


def test_a_blank_reason_is_422_and_writes_nothing(client: TestClient, sync_engine: Engine) -> None:
    scene = Scene(client, sync_engine)
    resp = _raise(
        client,
        scene.ana_h,
        scene.opp["id"],
        "finding",
        scene.f1,
        reason="   ",
        review_request_id=scene.request["id"],
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Give a reason of 1 to 1,000 characters."
    assert _challenges(sync_engine, scene.opp["id"]) == []
    assert _request_status(sync_engine, scene.request["id"]) == "pending"


def test_the_owner_confirms_and_the_run_starts(client: TestClient, sync_engine: Engine) -> None:
    scene = Scene(client, sync_engine)
    opp_id = scene.opp["id"]
    challenge = _from_review(client, scene)
    before = len(_runs(sync_engine, opp_id))

    stale = _confirm(client, scene.headers, opp_id, challenge, [ENGINEERING], row_version=7)
    assert stale.status_code == 412
    assert _runs(sync_engine, opp_id)[before:] == []

    resp = _confirm(client, scene.headers, opp_id, challenge, [ENGINEERING, "pm_agent"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["status"], body["confirmed"]) == ("reassessing", [ENGINEERING, "pm_agent"])
    assert body["run_number"] == before + 1
    assert resp.headers["ETag"] == '"2"'
    (run,) = _runs(sync_engine, opp_id)[before:]
    assert str(run["id"]) == body["workflow_run_id"]
    assert (run["run_type"], str(run["trigger_ref"]), run["idempotency_key"]) == (
        "challenge",
        challenge["id"],
        f"run:{opp_id}:challenge:{challenge['id']}",
    )
    tasks = rows(sync_engine, "SELECT agent FROM workflows_tasks WHERE run_id = :r", r=run["id"])
    # Story 9.6: then Conflict detection, the Critic and the new version.
    assert sorted(t["agent"] for t in tasks) == [
        "conflict_detection",
        "critic_agent",
        ENGINEERING,
        "new_version",
        "pm_agent",
    ]
    (confirmed,) = _events(sync_engine, opp_id, CONFIRMED)
    assert confirmed["payload"]["workflow_run_id"] == body["workflow_run_id"]

    # The run shows in the Assessments tab's run header.
    latest = client.get(f"{BASE}/{opp_id}/assessments", headers=scene.headers).json()["run"]
    assert latest["id"] == body["workflow_run_id"]
    assert [t["agent"] for t in latest["tasks"]] == [
        ENGINEERING,
        "pm_agent",
        "conflict_detection",
        "critic_agent",
        "new_version",
    ]
    assert latest["run_type"] == "challenge"

    # Confirming again returns the same run: no new run, no new event.
    again = _confirm(client, scene.headers, opp_id, challenge, [ENGINEERING])
    assert again.status_code == 200
    assert again.json()["workflow_run_id"] == body["workflow_run_id"]
    assert len(_runs(sync_engine, opp_id)) == before + 1
    assert len(_events(sync_engine, opp_id, CONFIRMED)) == 1
    # The request stays challenged; Ana keeps access.
    assert _request_status(sync_engine, scene.request["id"]) == "challenged"
    assert str(scene.ana) in _collaborator_rows(sync_engine, opp_id)


def test_confirm_needs_a_suggested_tick(client: TestClient, sync_engine: Engine) -> None:
    scene = Scene(client, sync_engine)
    challenge = _from_review(client, scene)
    none = _confirm(client, scene.headers, scene.opp["id"], challenge, [])
    assert none.status_code == 422
    stranger = _confirm(client, scene.headers, scene.opp["id"], challenge, ["critic_agent"])
    assert stranger.status_code == 422
    assert stranger.json()["detail"] == "Pick the Assessments to rerun from the suggestions."
    assert _challenges(sync_engine, scene.opp["id"])[0]["status"] == "awaiting_confirmation"


def test_the_owner_raises_and_confirms_at_once(client: TestClient, sync_engine: Engine) -> None:
    scene = Scene(client, sync_engine)
    opp_id = scene.opp["id"]

    none = _raise(client, scene.headers, opp_id, "assessment", scene.eng, confirmed=[])
    assert none.status_code == 422
    assert none.json()["detail"] == "Tick at least one Assessment to rerun."
    assert _challenges(sync_engine, opp_id) == []

    resp = _raise(client, scene.headers, opp_id, "assessment", scene.eng, confirmed=[ENGINEERING])
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert (body["status"], body["title"]) == ("reassessing", "Challenge Engineering Assessment v2")
    assert body["suggested"][0]["why"] == "The challenged Assessment"
    assert body["workflow_run_id"] is not None
    assert len(_events(sync_engine, opp_id, RAISED)) == 1
    assert len(_events(sync_engine, opp_id, CONFIRMED)) == 1
    # The owner's own Challenge creates no Inbox item.
    kinds = [i["kind"] for i in client.get(INBOX, headers=scene.headers).json()["items"]]
    assert "challenge_raised" not in kinds


def test_decline_puts_the_request_back(client: TestClient, sync_engine: Engine) -> None:
    scene = Scene(client, sync_engine)
    opp_id = scene.opp["id"]
    challenge = _from_review(client, scene)

    blank = _decline(client, scene.headers, opp_id, challenge, reason="  ")
    assert blank.status_code == 422
    resp = _decline(client, scene.headers, opp_id, challenge)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["status"], body["decline_reason"]) == (
        "declined",
        "Already covered by R1's buffer.",
    )
    assert _request_status(sync_engine, scene.request["id"]) == "pending"
    (declined,) = _events(sync_engine, opp_id, DECLINED)
    assert declined["payload"]["review_request_id"] == scene.request["id"]

    (item,) = [
        i
        for i in client.get(INBOX, headers=scene.ana_h).json()["items"]
        if i["kind"] == "challenge_declined"
    ]
    assert (item["group"], item["subject_open"], item["subject_status_label"]) == (
        "challenges",
        False,
        "Declined",
    )
    # Ana reads the reason on the Challenge, and may decide or challenge again.
    seen = client.get(f"{BASE}/{opp_id}/challenges/{challenge['id']}", headers=scene.ana_h)
    assert seen.json()["decline_reason"] == "Already covered by R1's buffer."

    # Already decided: 409 for both.
    for again in (
        _confirm(client, scene.headers, opp_id, body, [ENGINEERING]),
        _decline(client, scene.headers, opp_id, body),
    ):
        assert again.status_code == 409
        assert again.json()["code"] == "challenge_not_awaiting_confirmation"


def test_a_superseded_version_blocks_the_confirm(client: TestClient, sync_engine: Engine) -> None:
    scene = Scene(client, sync_engine)
    opp_id = scene.opp["id"]
    challenge = _from_review(client, scene)
    v4 = _version(sync_engine, opp_id, 4, created_by=scene.owner_id)
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE estimates_estimate_versions SET status = 'superseded' WHERE id = :v"),
            {"v": scene.v3},
        )
    before = len(_runs(sync_engine, opp_id))

    resp = _confirm(client, scene.headers, opp_id, challenge, [ENGINEERING])

    assert resp.status_code == 409
    assert resp.json()["code"] == "challenge_version_superseded"
    assert resp.json()["detail"] == (
        "v3 is superseded by v4. Raise the Challenge again on v4 if it still applies."
    )
    assert len(_runs(sync_engine, opp_id)) == before
    assert _challenges(sync_engine, opp_id)[0]["status"] == "awaiting_confirmation"
    seen = client.get(f"{BASE}/{opp_id}/challenges/{challenge['id']}", headers=scene.headers)
    assert seen.json()["superseded_by"] == 4
    assert seen.json()["superseded_by_id"] == v4


def test_an_active_run_blocks_the_confirm(client: TestClient, sync_engine: Engine) -> None:
    scene = Scene(client, sync_engine)
    opp_id = scene.opp["id"]
    challenge = _from_review(client, scene)
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO workflows_runs (id, opportunity_id, status) VALUES (:i, :o, 'running')"
            ),
            {"i": uuid4(), "o": opp_id},
        )
    before = len(_runs(sync_engine, opp_id))

    resp = _confirm(client, scene.headers, opp_id, challenge, [ENGINEERING])

    assert resp.status_code == 409
    assert resp.json()["code"] == "assessment_in_progress"
    assert len(_runs(sync_engine, opp_id)) == before
    (stored,) = _challenges(sync_engine, opp_id)
    assert (stored["status"], stored["workflow_run_id"]) == ("awaiting_confirmation", None)
    assert _events(sync_engine, opp_id, CONFIRMED) == []


def test_who_may_raise_confirm_and_decline(client: TestClient, sync_engine: Engine) -> None:
    scene = Scene(client, sync_engine)
    opp_id = scene.opp["id"]
    rep_h, rep = _user(client, sync_engine, "Rep Person", REP)
    member_h, member = _user(client, sync_engine, "Member Person", PSE)
    current = client.get(f"{BASE}/{opp_id}", headers=scene.headers).json()
    assert _add(client, scene.headers, current, rep).status_code == 200
    current = client.get(f"{BASE}/{opp_id}", headers=scene.headers).json()
    assert _add(client, scene.headers, current, member).status_code == 200

    for headers in (rep_h, member_h):
        resp = _raise(client, headers, opp_id, "finding", scene.f1)
        assert resp.status_code == 403, resp.text

    # Ben, another engineering reviewer, can't raise from Ana's request.
    ben_h, ben = _user(client, sync_engine, "Ben Reviewer", ENG)
    rv = _row_version(sync_engine, scene.v3)
    assert _send(client, scene.headers, opp_id, scene.v3, rv, [ben]).status_code == 201
    other = _raise(
        client, ben_h, opp_id, "finding", scene.f1, review_request_id=scene.request["id"]
    )
    assert (other.status_code, other.json()["code"]) == (403, "reviewer_not_authorized")
    # Nor confirm on raise.
    early = _raise(client, ben_h, opp_id, "finding", scene.f1, confirmed=[ENGINEERING])
    assert early.status_code == 403

    challenge = _from_review(client, scene)
    for resp in (
        _confirm(client, scene.ana_h, opp_id, challenge, [ENGINEERING]),
        _decline(client, scene.ana_h, opp_id, challenge),
        _confirm(client, member_h, opp_id, challenge, [ENGINEERING]),
    ):
        assert resp.status_code == 403
    # Ana's only request is challenged now: no other Challenge without a pending request.
    again = _raise(client, scene.ana_h, opp_id, "assessment", scene.pm)
    assert again.status_code == 403
    # Raising again from the challenged request is 409.
    twice = _raise(
        client, scene.ana_h, opp_id, "finding", scene.f1, review_request_id=scene.request["id"]
    )
    assert (twice.status_code, twice.json()["code"]) == (409, "review_request_not_pending")
    assert len(_challenges(sync_engine, opp_id)) == 1


def test_an_estimate_with_no_assessment_suggests_every_specialist(
    client: TestClient, sync_engine: Engine
) -> None:
    headers, _, opp, v3 = _setup(client, sync_engine)
    url = f"{BASE}/{opp['id']}/challenges/suggestions"
    shown = client.get(
        url, headers=headers, params={"target_kind": "estimate_version", "target_id": v3}
    ).json()
    assert [(s["agent"], s["why"], s["tag"]) for s in shown["suggested"]] == [
        (ENGINEERING, "Not assessed yet", "suggested"),
        ("pm_agent", "Not assessed yet", "suggested"),
        ("security_agent", "Not assessed yet", "suggested"),
    ]
    resp = _raise(client, headers, opp["id"], "estimate_version", v3, confirmed=[ENGINEERING])
    assert resp.status_code == 201, resp.text
    assert (resp.json()["status"], resp.json()["confirmed"]) == ("reassessing", [ENGINEERING])


@pytest.mark.parametrize("ends", ["approved", "cancelled"])
def test_a_challenged_request_keeps_access_when_another_closes(
    client: TestClient, sync_engine: Engine, ends: str
) -> None:
    scene = Scene(client, sync_engine)
    opp_id = scene.opp["id"]
    rv = _row_version(sync_engine, scene.v3)
    second = _send(
        client,
        scene.headers,
        opp_id,
        scene.v3,
        rv,
        [scene.ana],
        "engineering",
        [{"id": scene.pm, "version": 1}],
    )
    assert second.status_code == 201, second.text
    (other,) = second.json()["items"]
    challenge = _from_review(client, scene)

    if ends == "approved":
        closed = _decide(client, scene.ana_h, opp_id, other, "approved", reason=None)
        assert closed.status_code == 201, closed.text
    else:
        closed = _cancel(client, scene.headers, opp_id, other)
        assert closed.status_code == 200, closed.text

    assert _collaborator_rows(sync_engine, opp_id) == {str(scene.ana): "reviewer"}
    seen = client.get(f"{BASE}/{opp_id}/challenges/{challenge['id']}", headers=scene.ana_h)
    assert seen.status_code == 200


def test_targets_that_cannot_be_challenged(client: TestClient, sync_engine: Engine) -> None:
    scene = Scene(client, sync_engine)
    opp_id = scene.opp["id"]
    critic = _raise(client, scene.headers, opp_id, "finding", str(uuid4()))
    assert critic.status_code == 422
    assert critic.json()["detail"].startswith("Only a Finding of a current specialist")
    old = _raise(client, scene.headers, opp_id, "estimate_version", str(uuid4()))
    assert old.status_code == 422

    bare_h, _ = _user(client, sync_engine, "Bare Owner", PSE)
    bare = _create(client, bare_h)
    empty = _raise(client, bare_h, bare["id"], "assessment", str(uuid4()))
    assert (empty.status_code, empty.json()["code"]) == (409, "challenge_needs_estimate")


def test_the_suggestions_read(client: TestClient, sync_engine: Engine) -> None:
    scene = Scene(client, sync_engine)
    opp_id = scene.opp["id"]
    url = f"{BASE}/{opp_id}/challenges/suggestions"

    owner = client.get(
        url,
        headers=scene.headers,
        params={"target_kind": "estimate_version", "target_id": scene.v3},
    ).json()
    assert owner["title"] == "Challenge Estimate v3"
    assert [(s["agent"], s["tag"]) for s in owner["suggested"]] == [
        (ENGINEERING, "suggested"),
        ("pm_agent", "suggested"),
        ("security_agent", "suggested"),
    ]
    assert (owner["can_raise"], owner["can_confirm"]) == (True, True)

    ana = client.get(
        url, headers=scene.ana_h, params={"target_kind": "finding", "target_id": scene.f1}
    ).json()
    assert ana["title"] == "Challenge Finding: No ERP retry budget"
    assert (ana["can_raise"], ana["can_confirm"]) == (True, False)
    assert [s["preselected"] for s in ana["suggested"]] == [True, False, False]
    assert _challenges(sync_engine, opp_id) == []

    # The Assessments tab's flag: the owner and a reviewer with a pending request.
    tab = f"{BASE}/{opp_id}/assessments"
    assert client.get(tab, headers=scene.headers).json()["can_challenge"] is True
    assert client.get(tab, headers=scene.ana_h).json()["can_challenge"] is True
    _from_review(client, scene)
    assert client.get(tab, headers=scene.ana_h).json()["can_challenge"] is False


def test_challenges_are_never_deleted(client: TestClient, sync_engine: Engine) -> None:
    scene = Scene(client, sync_engine)
    challenge = _from_review(client, scene)
    with pytest.raises(sa.exc.ProgrammingError), sync_engine.begin() as conn:
        conn.execute(
            sa.text("DELETE FROM reviews_challenges WHERE id = :i"), {"i": challenge["id"]}
        )


def test_the_migration_goes_down_and_up(client: TestClient, sync_engine: Engine) -> None:
    scene = Scene(client, sync_engine)
    _from_review(client, scene)

    _alembic("downgrade", "0050_review_outcomes")
    try:
        kinds = rows(
            sync_engine,
            "SELECT kind FROM notifications_notifications WHERE kind LIKE 'challenge_%'",
        )
        assert kinds == []
    finally:
        _alembic("upgrade", "head")

    assert _challenges(sync_engine, scene.opp["id"]) == []
    (run_type,) = {r["run_type"] for r in _runs(sync_engine, scene.opp["id"])}
    assert run_type == "assessment"
