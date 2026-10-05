"""Editing and approving Clarification Questions (Story 4.5, demo slice) against a real,
migrated Postgres as psa_app: `PATCH …/clarification-questions/{qid}`, `POST …/approve`,
`POST …/approve-all`, the sales representative's view, and the re-detection rule. Reuses the
fake ModelGateway and hidden jobs of `test_intake_extraction.py`."""

import logging
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.gaps.application import questions as questions_app
from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests.test_gaps_detection import events, extracted, gap, gaps_out, requeue, rows
from tests.test_health import assert_problem
from tests.test_intake_extraction import BASE, DETECT, FakeGateway, drain
from tests.test_opportunities import PSE, _add, _user

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile

EDITED = "gaps.clarification_question.edited"
APPROVED = "gaps.clarification_question.approved"
SECRET = "Which SAP EWM release and IDoc types do you run?"


def _gaps(client: TestClient, headers: dict[str, str], opp_id: str) -> Any:
    resp = client.get(f"{BASE}/{opp_id}/gaps", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _questions(client: TestClient, headers: dict[str, str], opp_id: str) -> dict[str, Any]:
    """Gap title to its question."""
    return {g["title"]: g["question"] for g in _gaps(client, headers, opp_id)["items"]}


def _if_match(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


def _edit(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    question: dict[str, Any],
    body: dict[str, Any],
    version: int | None = None,
) -> Any:
    v = question["row_version"] if version is None else version
    return client.patch(
        f"{BASE}/{opp_id}/clarification-questions/{question['id']}",
        headers={**headers, **_if_match(v)},
        json=body,
    )


def _approve(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    question: dict[str, Any],
    version: int | None = None,
) -> Any:
    v = question["row_version"] if version is None else version
    return client.post(
        f"{BASE}/{opp_id}/clarification-questions/{question['id']}/approve",
        headers={**headers, **_if_match(v)},
    )


def _shown(client: TestClient, headers: dict[str, str], opp_id: str) -> list[dict[str, Any]]:
    """The drafted questions of open Gaps the caller sees, as **Approve all** sends them."""
    resp = client.get(f"{BASE}/{opp_id}/gaps", headers=headers)
    if resp.status_code != 200:
        return []
    return [
        {"id": g["question"]["id"], "row_version": g["question"]["row_version"]}
        for g in resp.json()["items"]
        if g["status"] == "open" and g["question"] and g["question"]["status"] == "drafted"
    ]


def _approve_all(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    shown: list[dict[str, Any]] | None = None,
) -> Any:
    body = _shown(client, headers, opp_id) if shown is None else shown
    return client.post(
        f"{BASE}/{opp_id}/clarification-questions/approve-all", headers=headers, json=body
    )


def _question_row(engine: Engine, question_id: str) -> dict[str, Any]:
    (row,) = rows(engine, "SELECT * FROM gaps_clarification_questions WHERE id = :q", q=question_id)
    return row


def detected(
    client: TestClient, engine: Engine, db_url: str, gateway: FakeGateway, count: int = 1
) -> tuple[dict[str, str], dict[str, Any]]:
    """An Opportunity with `count` (1 to 4) open Gaps, each with a drafted question."""
    headers, opp = extracted(client, engine, db_url, gateway)
    candidates = [
        gap("SAP interface type", ["R1"], topic="SAP"),
        gap("Uptime window", ["R2"], category="non_functional", impact="medium"),
        gap("Peak growth", ["R3"], category="data_volumes", impact="medium"),
        gap("SSO provider", ["R4"], category="security_and_compliance", impact="low"),
    ]
    gateway.replies = [gaps_out(*candidates[:count])]
    assert drain(db_url, DETECT) == ["succeeded"]
    return headers, opp


# --- edit -----------------------------------------------------------------------------------


def test_the_owner_edits_a_drafted_question(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway)
    question = _questions(client, headers, opp["id"])["SAP interface type"]
    assert (question["edited_by_human"], question["last_changed_by"]) == (False, None)

    with caplog.at_level(logging.DEBUG):
        resp = _edit(client, headers, opp["id"], question, {"text": f"  {SECRET}  "})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert resp.headers["ETag"] == '"2"'
    assert (body["text"], body["topic"], body["status"]) == (SECRET, "SAP", "drafted")
    assert (body["edited_by_human"], body["row_version"]) == (True, 2)
    assert body["last_changed_by"]["name"] == "Owner Person"
    assert body["status_changed_at"] == question["status_changed_at"]  # status unchanged
    assert body == _questions(client, headers, opp["id"])["SAP interface type"]
    (event,) = events(sync_engine, opp["id"], EDITED)
    assert event["payload"] == {
        "gap_id": _gaps(client, headers, opp["id"])["items"][0]["id"],
        "fields": ["text"],
        "row_version": 2,
        "approval_revoked": False,
    }
    assert (event["subject_type"], str(event["subject_id"])) == (
        "gaps.clarification_question",
        question["id"],
    )
    assert event["actor_type"] == "user"
    # Privacy: no question text in logs or trace.
    logged = caplog.text + str([r.__dict__ for r in caplog.records])
    assert SECRET not in logged and "SAP EWM" not in logged
    assert "SAP EWM" not in str(events(sync_engine, opp["id"]))

    topic = _edit(client, headers, opp["id"], body, {"topic": "ERP", "text": SECRET})
    assert topic.status_code == 200, topic.text
    assert (topic.json()["topic"], topic.json()["row_version"]) == ("ERP", 3)
    assert events(sync_engine, opp["id"], EDITED)[-1]["payload"]["fields"] == ["topic"]


def test_an_unchanged_edit_writes_nothing_but_a_stale_one_is_still_412(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway)
    question = _questions(client, headers, opp["id"])["SAP interface type"]

    same = _edit(client, headers, opp["id"], question, {"text": question["text"] + " "})

    assert same.status_code == 200, same.text
    assert same.json() == question
    assert _question_row(sync_engine, question["id"])["edited_by_human"] is False
    assert events(sync_engine, opp["id"], EDITED) == []
    stale = _edit(client, headers, opp["id"], question, {"topic": "SAP"}, version=7)
    assert stale.status_code == 412
    assert_problem(stale.json(), 412, "row_version_mismatch")


def test_editing_an_approved_question_returns_it_to_drafted(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway)
    question = _questions(client, headers, opp["id"])["SAP interface type"]
    approved = _approve(client, headers, opp["id"], question).json()
    assert approved["status"] == "approved"

    resp = _edit(client, headers, opp["id"], approved, {"text": "Which SAP release?"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "drafted"
    assert (body["approved_by"], body["approved_at"]) == (None, None)
    assert body["status_changed_at"] > approved["status_changed_at"]
    row = _question_row(sync_engine, question["id"])
    assert (row["status"], row["approved_by"], row["approved_at"]) == ("drafted", None, None)
    (event,) = events(sync_engine, opp["id"], EDITED)
    assert event["payload"]["approval_revoked"] is True


@pytest.mark.parametrize(
    "body",
    [
        {"text": ""},
        {"text": "   "},
        {"text": "x" * 1001},
        {"topic": "t" * 81},
        {"topic": ""},
        {"text": "Fine?", "status": "approved"},
        {"text": 42},
    ],
)
def test_an_invalid_edit_is_422_and_changes_nothing(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    body: dict[str, Any],
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway)
    question = _questions(client, headers, opp["id"])["SAP interface type"]
    before = _question_row(sync_engine, question["id"])

    resp = _edit(client, headers, opp["id"], question, body)

    assert resp.status_code == 422, resp.text
    assert_problem(resp.json(), 422, "validation_error")
    assert _question_row(sync_engine, question["id"]) == before
    assert events(sync_engine, opp["id"], EDITED) == []


def test_the_limits_themselves_are_accepted(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway)
    question = _questions(client, headers, opp["id"])["SAP interface type"]

    resp = _edit(client, headers, opp["id"], question, {"text": "x" * 1000, "topic": "t" * 80})

    assert resp.status_code == 200, resp.text
    assert events(sync_engine, opp["id"], EDITED)[0]["payload"]["fields"] == ["text", "topic"]


# --- approve --------------------------------------------------------------------------------


def test_approving_records_who_and_when_once(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway)
    question = _questions(client, headers, opp["id"])["SAP interface type"]

    resp = _approve(client, headers, opp["id"], question)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert resp.headers["ETag"] == '"2"'
    assert (body["status"], body["row_version"], body["edited_by_human"]) == ("approved", 2, False)
    assert body["approved_by"]["name"] == "Owner Person"
    assert body["approved_at"] is not None
    assert body["status_changed_at"] == body["approved_at"]
    assert body["last_changed_by"] == body["approved_by"]
    (event,) = events(sync_engine, opp["id"], APPROVED)
    assert event["payload"] == {
        "gap_id": _gaps(client, headers, opp["id"])["items"][0]["id"],
        "approved_by": body["approved_by"]["id"],
        "row_version": 2,
    }

    again = _approve(client, headers, opp["id"], question)  # an old If-Match: still a no-op

    assert again.status_code == 200, again.text
    assert again.json() == body
    assert len(events(sync_engine, opp["id"], APPROVED)) == 1


def test_approve_all_approves_every_drafted_question_of_open_gaps(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway, count=4)
    questions = _questions(client, headers, opp["id"])
    assert _approve(client, headers, opp["id"], questions["SAP interface type"]).status_code == 200

    resp = _approve_all(client, headers, opp["id"])

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"count": 3}
    after = _questions(client, headers, opp["id"])
    assert {q["status"] for q in after.values()} == {"approved"}
    assert {q["approved_by"]["name"] for q in after.values()} == {"Owner Person"}
    assert len(events(sync_engine, opp["id"], APPROVED)) == 4
    assert _approve_all(client, headers, opp["id"]).json() == {"count": 0}


def test_approve_all_leaves_questions_of_converted_gaps_alone(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway, count=2)
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE gaps_gaps SET status = 'converted', converted_to = 'condition' "
                "WHERE opportunity_id = :o AND title = 'Uptime window'"
            ),
            {"o": opp["id"]},
        )

    assert _approve_all(client, headers, opp["id"]).json() == {"count": 1}
    questions = _questions(client, headers, opp["id"])
    assert questions["Uptime window"]["status"] == "drafted"


def test_approve_all_is_412_when_a_listed_question_changed_and_approves_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway, count=3)
    shown = _shown(client, headers, opp["id"])
    sap = _questions(client, headers, opp["id"])["SAP interface type"]
    edited = _edit(client, headers, opp["id"], sap, {"text": "Which SAP release?"})
    assert edited.status_code == 200

    resp = _approve_all(client, headers, opp["id"], shown)

    assert resp.status_code == 412, resp.text
    assert_problem(resp.json(), 412, "row_version_mismatch")
    assert {q["status"] for q in _questions(client, headers, opp["id"]).values()} == {"drafted"}
    assert events(sync_engine, opp["id"], APPROVED) == []


def test_approve_all_is_412_when_a_drafted_question_is_not_listed_or_no_longer_drafted(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway, count=3)
    shown = _shown(client, headers, opp["id"])

    missing = _approve_all(client, headers, opp["id"], shown[:2])
    first = next(
        q for q in _questions(client, headers, opp["id"]).values() if q["id"] == shown[0]["id"]
    )
    assert _approve(client, headers, opp["id"], first).status_code == 200
    no_longer_drafted = _approve_all(client, headers, opp["id"], shown)

    for resp in (missing, no_longer_drafted):
        assert resp.status_code == 412, resp.text
        assert_problem(resp.json(), 412, "row_version_mismatch")
    assert len(events(sync_engine, opp["id"], APPROVED)) == 1  # only the single approve
    assert _approve_all(client, headers, opp["id"], shown[1:]).json() == {"count": 2}


def test_a_gap_converted_after_the_open_check_is_409(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway)
    question = _questions(client, headers, opp["id"])["SAP interface type"]
    real = questions_app._open

    def converted_after_check(gap: Any) -> None:
        real(gap)
        with sync_engine.begin() as conn:  # `estimates` converts it, without the gaps lock
            conn.execute(
                sa.text(
                    "UPDATE gaps_gaps SET status = 'converted', converted_to = 'condition' "
                    "WHERE id = :g"
                ),
                {"g": str(gap.id)},
            )

    monkeypatch.setattr(questions_app, "_open", converted_after_check)
    before = _question_row(sync_engine, question["id"])

    resp = _approve(client, headers, opp["id"], question)

    assert resp.status_code == 409, resp.text
    assert_problem(resp.json(), 409, "gap_not_open")
    assert _question_row(sync_engine, question["id"]) == before
    assert events(sync_engine, opp["id"], APPROVED) == []


def test_a_superseded_question_of_an_open_gap_is_409_not_500(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway)
    question = _questions(client, headers, opp["id"])["SAP interface type"]
    with sync_engine.begin() as conn:  # inconsistent data
        conn.execute(
            sa.text("UPDATE gaps_clarification_questions SET status = 'superseded' WHERE id = :q"),
            {"q": question["id"]},
        )

    for resp in (
        _edit(client, headers, opp["id"], question, {"text": "Other?"}),
        _approve(client, headers, opp["id"], question),
    ):
        assert resp.status_code == 409, resp.text
        assert_problem(resp.json(), 409, "gap_not_open")


# --- concurrency and lifecycle --------------------------------------------------------------


def test_a_stale_or_missing_if_match_changes_nothing(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway)
    question = _questions(client, headers, opp["id"])["SAP interface type"]
    edited = _edit(client, headers, opp["id"], question, {"text": "Which SAP release?"})
    assert edited.status_code == 200
    before = _question_row(sync_engine, question["id"])
    url = f"{BASE}/{opp['id']}/clarification-questions/{question['id']}"

    stale_edit = _edit(client, headers, opp["id"], question, {"text": "Other?"})
    stale_approve = _approve(client, headers, opp["id"], question)
    missing_edit = client.patch(url, headers=headers, json={"text": "Other?"})
    missing_approve = client.post(f"{url}/approve", headers=headers)
    junk = client.post(f"{url}/approve", headers={**headers, "If-Match": 'W/"2"'})

    for resp in (stale_edit, stale_approve, junk):
        assert resp.status_code == 412, resp.text
        assert_problem(resp.json(), 412, "row_version_mismatch")
    for resp in (missing_edit, missing_approve):
        assert resp.status_code == 428, resp.text
        assert_problem(resp.json(), 428, "if_match_required")
    assert _question_row(sync_engine, question["id"]) == before
    assert len(events(sync_engine, opp["id"], EDITED)) == 1
    assert events(sync_engine, opp["id"], APPROVED) == []
    # The 412 view can name who changed it.
    current = _questions(client, headers, opp["id"])["SAP interface type"]
    assert current["last_changed_by"]["name"] == "Owner Person"


def test_a_question_of_a_gap_that_is_not_open_is_409(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway)
    question = _questions(client, headers, opp["id"])["SAP interface type"]
    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE gaps_gaps SET status = 'converted', converted_to = 'contingency' "
                "WHERE opportunity_id = :o"
            ),
            {"o": opp["id"]},
        )
    before = _question_row(sync_engine, question["id"])

    edit = _edit(client, headers, opp["id"], question, {"text": "Other?"})
    approve = _approve(client, headers, opp["id"], question)

    for resp in (edit, approve):
        assert resp.status_code == 409, resp.text
        assert_problem(resp.json(), 409, "gap_not_open")
    assert _question_row(sync_engine, question["id"]) == before
    assert events(sync_engine, opp["id"], EDITED) == []
    assert events(sync_engine, opp["id"], APPROVED) == []


def test_unknown_or_foreign_questions_are_404_and_ids_must_be_uuids(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway)
    question = _questions(client, headers, opp["id"])["SAP interface type"]
    other_headers, other = extracted(client, sync_engine, db_url, gateway)

    unknown = _edit(client, headers, opp["id"], {**question, "id": str(uuid4())}, {"text": "A?"})
    foreign = _approve(client, other_headers, other["id"], question)
    bad = client.post(
        f"{BASE}/{opp['id']}/clarification-questions/nope/approve",
        headers={**headers, **_if_match(1)},
    )

    for resp in (unknown, foreign):
        assert resp.status_code == 404, resp.text
        assert_problem(resp.json(), 404, "not_found")
    assert bad.status_code == 422
    url = f"{BASE}/{opp['id']}/clarification-questions/approve-all"
    assert client.post(url, json=[]).status_code == 401
    bad_id = client.post(url, headers=headers, json=[{"id": "nope", "row_version": 1}])
    assert bad_id.status_code == 422
    assert client.post(url, headers=headers, json={"id": question["id"]}).status_code == 422


# --- who ------------------------------------------------------------------------------------


def test_sales_reps_and_readers_may_not_edit_and_reps_see_only_approved_questions(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway, count=2)
    rep, rep_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    added = _add(client, headers, opp, rep_id)
    assert added.status_code == 200, added.text
    colleague, colleague_id = _user(client, sync_engine, "Colleague", PSE)
    assert _add(client, headers, added.json(), colleague_id).status_code == 200
    reader, _ = _user(client, sync_engine, "Head Person", "head_of_delivery")
    outsider, _ = _user(client, sync_engine, "Outsider", PSE)
    questions = _questions(client, headers, opp["id"])
    sap = questions["SAP interface type"]

    for forbidden in (rep, reader):
        for resp in (
            _edit(client, forbidden, opp["id"], sap, {"text": "Other?"}),
            _approve(client, forbidden, opp["id"], sap),
            _approve_all(client, forbidden, opp["id"]),
        ):
            assert resp.status_code == 403, resp.text
            assert_problem(resp.json(), 403, "forbidden")
    for resp in (
        _edit(client, outsider, opp["id"], sap, {"text": "Other?"}),
        _approve_all(client, outsider, opp["id"]),
    ):
        assert resp.status_code == 404, resp.text
    assert events(sync_engine, opp["id"], EDITED) == []
    assert events(sync_engine, opp["id"], APPROVED) == []

    seen = _gaps(client, rep, opp["id"])
    assert seen["can_edit_questions"] is False
    assert [g["question"] for g in seen["items"]] == [None, None]  # the Gaps still show
    assert _gaps(client, reader, opp["id"])["can_edit_questions"] is False
    assert _gaps(client, colleague, opp["id"])["can_edit_questions"] is True

    approved = _approve(client, colleague, opp["id"], sap)

    assert approved.status_code == 200, approved.text
    assert approved.json()["approved_by"]["name"] == "Colleague"
    items = {g["title"]: g["question"] for g in _gaps(client, rep, opp["id"])["items"]}
    assert items["Uptime window"] is None
    assert items["SAP interface type"]["status"] == "approved"
    assert items["SAP interface type"]["approved_by"]["name"] == "Colleague"
    # A sales representative who is also a presales engineer edits like any collaborator.
    both, both_id = _user(client, sync_engine, "Both Roles", "sales_representative", PSE)
    current = client.get(f"{BASE}/{opp['id']}", headers=headers).json()
    assert _add(client, headers, current, both_id).status_code == 200
    mixed = _gaps(client, both, opp["id"])
    assert mixed["can_edit_questions"] is True
    mixed_questions = {g["title"]: g["question"] for g in mixed["items"]}
    assert mixed_questions["Uptime window"]["status"] == "drafted"
    # A reader who isn't a sales representative sees the drafted question too.
    assert _questions(client, reader, opp["id"])["Uptime window"]["status"] == "drafted"


# --- re-detection ---------------------------------------------------------------------------


def test_a_re_detection_keeps_gaps_whose_question_a_person_touched(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected(client, sync_engine, db_url, gateway, count=4)
    questions = _questions(client, headers, opp["id"])
    edited = _edit(
        client, headers, opp["id"], questions["SAP interface type"], {"text": SECRET}
    ).json()
    approved = _approve(client, headers, opp["id"], questions["Uptime window"]).json()
    requeue(db_url, opp["id"])
    gateway.replies = [
        gaps_out(
            gap("Price indexation", ["R5"], category="commercial", impact="low"),
            gap("Interface owner", ["R1"], category="scope_and_ownership"),
            gap("Response times", ["R2"], category="non_functional", impact="medium"),
        )
    ]

    assert drain(db_url, DETECT) == ["succeeded"]

    after = _questions(client, headers, opp["id"])
    assert set(after) == {
        "SAP interface type",
        "Uptime window",
        "Price indexation",
        "Interface owner",
        "Response times",
    }
    assert after["SAP interface type"] == edited
    assert after["Uptime window"] == approved
    superseded = rows(
        sync_engine,
        "SELECT g.title, q.status FROM gaps_gaps g JOIN gaps_clarification_questions q "
        "ON q.gap_id = g.id WHERE g.opportunity_id = :o AND g.status = 'superseded'",
        o=opp["id"],
    )
    assert {(r["title"], r["status"]) for r in superseded} == {
        ("Peak growth", "superseded"),
        ("SSO provider", "superseded"),
    }
    completed = [
        e["payload"]
        for e in events(sync_engine, opp["id"])
        if e["event_type"] == "gaps.detection.completed"
    ]
    assert completed[-1] == {
        "gap_count": 3,
        "dropped_count": 0,
        "requirement_count": 5,
        "superseded_count": 2,
        "kept_count": 2,
    }
    # Approve all then still approves the new drafted questions alongside.
    assert _approve_all(client, headers, opp["id"]).json() == {"count": 4}
    assert {q["status"] for q in _questions(client, headers, opp["id"]).values()} == {"approved"}
