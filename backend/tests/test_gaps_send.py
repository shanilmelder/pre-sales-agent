"""Exporting Clarification Questions and marking them sent and "No answer" (Story 4.6, demo
slice) against a real, migrated Postgres as psa_app: `POST …/clarification-questions/export`,
`POST …/clarification-questions/mark-sent`, `POST …/clarification-questions/{qid}/no-answer`,
the edit and approve guards, the sales representative's view, the re-detection rule and the
migration. Reuses the fake ModelGateway and hidden jobs of `test_intake_extraction.py`."""

import logging
from datetime import UTC, datetime, timedelta
from email import message_from_bytes
from email.policy import default
from io import BytesIO
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests.test_gaps_detection import events, gap, gaps_out, requeue, rows
from tests.test_gaps_questions import _approve, _edit, _gaps, _if_match, _question_row
from tests.test_health import assert_problem
from tests.test_intake_extraction import BASE, DETECT, FakeGateway, drain
from tests.test_intake_parse_job import _alembic
from tests.test_opportunities import PSE, _add, _user

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile

EXPORTED = "gaps.clarification_question.exported"
SENT = "gaps.clarification_question.sent"
UNANSWERED = "gaps.clarification_question.marked_unanswered"
SECRET_Q = "Which SAP EWM release and IDoc types do you run?"
GAP_ONLY = ("Changes the effort", "Drives the integration", "SAP interface type")


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def detected_topics(
    client: TestClient, engine: Engine, db_url: str, gateway: FakeGateway
) -> tuple[dict[str, str], dict[str, Any]]:
    """An Opportunity with 4 open Gaps whose questions have topics `SAP`, `Availability`,
    `SAP` and `Security`."""
    headers, opp = detection_tests.extracted(client, engine, db_url, gateway)
    gateway.replies = [
        gaps_out(
            gap("SAP interface type", ["R1"], topic="SAP", question=SECRET_Q),
            gap("Uptime window", ["R2"], category="non_functional", topic="Availability"),
            gap("Peak growth", ["R3"], category="data_volumes", impact="medium", topic="sap"),
            gap("SSO provider", ["R4"], category="security_and_compliance", topic="Security"),
        )
    ]
    assert drain(db_url, DETECT) == ["succeeded"]
    return headers, opp


def _questions(client: TestClient, headers: dict[str, str], opp_id: str) -> dict[str, Any]:
    return {g["title"]: g["question"] for g in _gaps(client, headers, opp_id)["items"]}


def _approved(
    client: TestClient, headers: dict[str, str], opp_id: str, *titles: str
) -> dict[str, Any]:
    questions = _questions(client, headers, opp_id)
    for title in titles:
        resp = _approve(client, headers, opp_id, questions[title])
        assert resp.status_code == 200, resp.text
    return _questions(client, headers, opp_id)


def _export(client: TestClient, headers: dict[str, str], opp_id: str, fmt: str) -> Any:
    return client.post(
        f"{BASE}/{opp_id}/clarification-questions/export", headers=headers, json={"format": fmt}
    )


def _mark_sent(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    questions: list[dict[str, Any]],
    sent_on: str | None = None,
) -> Any:
    return client.post(
        f"{BASE}/{opp_id}/clarification-questions/mark-sent",
        headers=headers,
        json={
            "sent_on": sent_on or _today(),
            "questions": [{"id": q["id"], "row_version": q["row_version"]} for q in questions],
        },
    )


def _no_answer(
    client: TestClient,
    headers: dict[str, str],
    opp_id: str,
    question: dict[str, Any],
    version: int | None = None,
) -> Any:
    v = question["row_version"] if version is None else version
    return client.post(
        f"{BASE}/{opp_id}/clarification-questions/{question['id']}/no-answer",
        headers={**headers, **_if_match(v)},
    )


def _download(client: TestClient, body: dict[str, Any]) -> bytes:
    resp = client.get(body["url"])
    assert resp.status_code == 200, resp.text
    return resp.content


# --- export ---------------------------------------------------------------------------------


def test_copy_exports_approved_questions_grouped_by_topic_in_customer_wording(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    headers, opp = detected_topics(client, sync_engine, db_url, gateway)
    approved = _approved(
        client, headers, opp["id"], "SAP interface type", "Uptime window", "Peak growth"
    )

    with caplog.at_level(logging.DEBUG):
        resp = _export(client, headers, opp["id"], "copy")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["format"], body["question_count"], body["url"]) == ("copy", 3, None)
    lines = body["text"].splitlines()
    assert lines[0] == f"Clarification questions for {opp['customer_name']}"
    assert lines[2:] == [
        "",
        "Availability",
        "1. Could you tell us about uptime window?",
        "",
        "SAP",
        f"2. {SECRET_Q}",
        "3. Could you tell us about peak growth?",
    ]
    assert "sso provider" not in body["text"]  # still drafted
    for internal in GAP_ONLY:
        assert internal not in body["text"]
    (event,) = events(sync_engine, opp["id"], EXPORTED)
    assert event["payload"]["format"] == "copy"
    assert sorted(event["payload"]["question_ids"]) == sorted(
        approved[t]["id"] for t in ("SAP interface type", "Uptime window", "Peak growth")
    )
    assert (event["subject_type"], str(event["subject_id"])) == (
        "opportunities.opportunity",
        opp["id"],
    )
    # Privacy: no question text in logs or trace.
    logged = caplog.text + str([r.__dict__ for r in caplog.records])
    assert "SAP EWM" not in logged
    assert "SAP EWM" not in str(events(sync_engine, opp["id"]))


def test_docx_and_eml_are_signed_links_to_customer_wording_only(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected_topics(client, sync_engine, db_url, gateway)
    _approved(client, headers, opp["id"], "SAP interface type", "Uptime window", "Peak growth")
    copied = _export(client, headers, opp["id"], "copy").json()["text"]

    docx = _export(client, headers, opp["id"], "docx")
    eml = _export(client, headers, opp["id"], "eml")

    for resp, ext in ((docx, "docx"), (eml, "eml")):
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["text"] is None
        assert body["url"].startswith("/api/v1/downloads/")
        assert body["file_name"].startswith("clarification-questions-")
        assert body["file_name"].endswith(f"-{_today()}.{ext}")
        assert datetime.fromisoformat(body["expires_at"]) > datetime.now(UTC)
    document = Document(BytesIO(_download(client, docx.json())))
    paragraphs = [p.text for p in document.paragraphs if p.text]
    assert paragraphs == [line for line in copied.splitlines() if line]
    message = message_from_bytes(_download(client, eml.json()), policy=default)
    assert message["X-Unsent"] == "1"
    assert message["To"] is None
    assert message["Subject"].startswith("Clarification questions")
    content = message.get_content()  # type: ignore[attr-defined]
    assert content.replace("\r\n", "\n") == copied
    for internal in GAP_ONLY:
        assert internal not in content and internal not in "".join(paragraphs)
    formats = [e["payload"]["format"] for e in events(sync_engine, opp["id"], EXPORTED)]
    assert formats == ["copy", "docx", "eml"]


def test_nothing_approved_is_409_with_no_event(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected_topics(client, sync_engine, db_url, gateway)

    for fmt in ("copy", "docx", "eml"):
        resp = _export(client, headers, opp["id"], fmt)
        assert resp.status_code == 409, resp.text
        assert_problem(resp.json(), 409, "no_approved_questions")
    assert events(sync_engine, opp["id"], EXPORTED) == []
    bad = _export(client, headers, opp["id"], "pdf")
    assert bad.status_code == 422


def test_sent_questions_and_questions_of_gaps_not_open_are_not_exported(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected_topics(client, sync_engine, db_url, gateway)
    approved = _approved(client, headers, opp["id"], "SAP interface type", "Uptime window")
    assert _mark_sent(client, headers, opp["id"], [approved["Uptime window"]]).status_code == 200

    text = _export(client, headers, opp["id"], "copy").json()["text"]
    assert SECRET_Q in text and "uptime window" not in text

    with sync_engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE gaps_gaps SET status = 'converted', converted_to = 'condition' "
                "WHERE opportunity_id = :o AND title = 'SAP interface type'"
            ),
            {"o": opp["id"]},
        )
    assert_problem(_export(client, headers, opp["id"], "copy").json(), 409, "no_approved_questions")


# --- mark sent ------------------------------------------------------------------------------


def test_marking_two_approved_questions_sent_today(
    client: TestClient,
    sync_engine: Engine,
    db_url: str,
    gateway: FakeGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    headers, opp = detected_topics(client, sync_engine, db_url, gateway)
    approved = _approved(client, headers, opp["id"], "SAP interface type", "Uptime window")
    chosen = [approved["SAP interface type"], approved["Uptime window"]]

    with caplog.at_level(logging.DEBUG):
        resp = _mark_sent(client, headers, opp["id"], chosen)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"count": 2}
    after = _questions(client, headers, opp["id"])
    for title in ("SAP interface type", "Uptime window"):
        q = after[title]
        assert (q["status"], q["sent_on"], q["row_version"]) == ("sent", _today(), 3)
        assert q["sent_by"]["name"] == "Owner Person"
        assert q["approved_by"]["name"] == "Owner Person"  # the approval is kept
        assert q["status_changed_at"] > approved[title]["status_changed_at"]
    assert after["Peak growth"]["status"] == "drafted"
    sent = events(sync_engine, opp["id"], SENT)
    assert len(sent) == 2
    gap_ids = {g["title"]: g["id"] for g in _gaps(client, headers, opp["id"])["items"]}
    assert {e["payload"]["gap_id"] for e in sent} == {
        gap_ids["SAP interface type"],
        gap_ids["Uptime window"],
    }
    assert all(e["payload"]["sent_on"] == _today() for e in sent)
    assert all(e["payload"]["row_version"] == 3 for e in sent)
    assert {e["subject_type"] for e in sent} == {"gaps.clarification_question"}
    # The Gaps stay open.
    assert {g["status"] for g in _gaps(client, headers, opp["id"])["items"]} == {"open"}
    logged = caplog.text + str([r.__dict__ for r in caplog.records])
    assert "SAP EWM" not in logged


def test_a_drafted_stale_or_foreign_question_in_the_list_is_412_and_nothing_is_marked(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected_topics(client, sync_engine, db_url, gateway)
    approved = _approved(client, headers, opp["id"], "SAP interface type")
    sap, drafted = approved["SAP interface type"], approved["Uptime window"]

    for listed in (
        [sap, drafted],
        [{**sap, "row_version": 1}],
        [sap, {**sap, "row_version": 1}],
        [sap, {"id": str(uuid4()), "row_version": 1}],
    ):
        resp = _mark_sent(client, headers, opp["id"], listed)
        assert resp.status_code == 412, resp.text
        assert_problem(resp.json(), 412, "row_version_mismatch")
    assert _questions(client, headers, opp["id"])["SAP interface type"] == sap
    assert events(sync_engine, opp["id"], SENT) == []


def test_a_future_date_or_a_bad_list_is_422_and_nothing_is_marked(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected_topics(client, sync_engine, db_url, gateway)
    sap = _approved(client, headers, opp["id"], "SAP interface type")["SAP interface type"]
    later = (datetime.now(UTC).date() + timedelta(days=2)).isoformat()

    future = _mark_sent(client, headers, opp["id"], [sap], sent_on=later)
    empty = _mark_sent(client, headers, opp["id"], [])
    url = f"{BASE}/{opp['id']}/clarification-questions/mark-sent"
    no_date = client.post(url, headers=headers, json={"questions": [sap]})
    too_many = client.post(
        url,
        headers=headers,
        json={
            "sent_on": _today(),
            "questions": [{"id": str(uuid4()), "row_version": 1}] * 201,
        },
    )

    assert future.status_code == 422, future.text
    assert_problem(future.json(), 422, "validation_error")
    assert "future" in future.json()["detail"]
    for resp in (empty, no_date, too_many):
        assert resp.status_code == 422, resp.text
    assert _questions(client, headers, opp["id"])["SAP interface type"] == sap
    assert events(sync_engine, opp["id"], SENT) == []
    earlier = _mark_sent(client, headers, opp["id"], [sap], sent_on="2026-10-01")
    assert earlier.status_code == 200, earlier.text
    assert _questions(client, headers, opp["id"])["SAP interface type"]["sent_on"] == "2026-10-01"


def test_utc_today_plus_one_is_accepted_and_plus_two_is_422(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    """A user ahead of UTC may mark questions sent on their own today."""
    headers, opp = detected_topics(client, sync_engine, db_url, gateway)
    sap = _approved(client, headers, opp["id"], "SAP interface type")["SAP interface type"]
    utc_today = datetime.now(UTC).date()

    too_late = _mark_sent(
        client, headers, opp["id"], [sap], sent_on=(utc_today + timedelta(days=2)).isoformat()
    )
    ahead = _mark_sent(
        client, headers, opp["id"], [sap], sent_on=(utc_today + timedelta(days=1)).isoformat()
    )

    assert_problem(too_late.json(), 422, "validation_error")
    assert ahead.status_code == 200, ahead.text


# --- no answer ------------------------------------------------------------------------------


def test_no_answer_on_a_sent_question_keeps_the_gap_open(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected_topics(client, sync_engine, db_url, gateway)
    approved = _approved(client, headers, opp["id"], "SAP interface type")
    sap = approved["SAP interface type"]
    assert _mark_sent(client, headers, opp["id"], [sap]).status_code == 200
    sent = _questions(client, headers, opp["id"])["SAP interface type"]

    resp = _no_answer(client, headers, opp["id"], sent)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert resp.headers["ETag"] == f'"{sent["row_version"] + 1}"'
    assert (body["status"], body["sent_on"]) == ("unanswered", sent["sent_on"])
    assert body["sent_by"] == sent["sent_by"]
    sap_gap = next(
        g for g in _gaps(client, headers, opp["id"])["items"] if g["title"] == "SAP interface type"
    )
    assert sap_gap["status"] == "open"
    (event,) = events(sync_engine, opp["id"], UNANSWERED)
    assert event["payload"] == {"gap_id": sap_gap["id"], "row_version": body["row_version"]}

    again = _no_answer(client, headers, opp["id"], body)
    drafted = _no_answer(
        client, headers, opp["id"], _questions(client, headers, opp["id"])["Uptime window"]
    )
    for conflict in (again, drafted):
        assert conflict.status_code == 409, conflict.text
        assert_problem(conflict.json(), 409, "question_not_sent")
    assert len(events(sync_engine, opp["id"], UNANSWERED)) == 1


def test_no_answer_needs_a_current_if_match(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected_topics(client, sync_engine, db_url, gateway)
    approved = _approved(client, headers, opp["id"], "SAP interface type")
    sap = approved["SAP interface type"]
    assert _mark_sent(client, headers, opp["id"], [sap]).status_code == 200
    sent = _questions(client, headers, opp["id"])["SAP interface type"]
    before = _question_row(sync_engine, sent["id"])

    stale = _no_answer(client, headers, opp["id"], sent, version=sent["row_version"] - 1)
    missing = client.post(
        f"{BASE}/{opp['id']}/clarification-questions/{sent['id']}/no-answer", headers=headers
    )
    unknown = _no_answer(client, headers, opp["id"], {**sent, "id": str(uuid4())})

    assert_problem(stale.json(), 412, "row_version_mismatch")
    assert_problem(missing.json(), 428, "if_match_required")
    assert_problem(unknown.json(), 404, "not_found")
    assert _question_row(sync_engine, sent["id"]) == before
    assert events(sync_engine, opp["id"], UNANSWERED) == []


# --- edit and approve guards ------------------------------------------------------------------


def test_a_sent_or_unanswered_question_cannot_be_edited_or_approved(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected_topics(client, sync_engine, db_url, gateway)
    approved = _approved(client, headers, opp["id"], "SAP interface type")
    sap = approved["SAP interface type"]
    assert _mark_sent(client, headers, opp["id"], [sap]).status_code == 200
    sent = _questions(client, headers, opp["id"])["SAP interface type"]

    for question in (sent, _no_answer(client, headers, opp["id"], sent).json()):
        before = _question_row(sync_engine, question["id"])
        for resp in (
            _edit(client, headers, opp["id"], question, {"text": "Other?"}),
            _approve(client, headers, opp["id"], question),
        ):
            assert resp.status_code == 409, resp.text
            assert_problem(resp.json(), 409, "question_not_editable")
        assert _question_row(sync_engine, question["id"]) == before


# --- who ------------------------------------------------------------------------------------


def test_a_sales_rep_exports_marks_sent_and_no_answer_but_may_not_edit(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected_topics(client, sync_engine, db_url, gateway)
    approved = _approved(client, headers, opp["id"], "SAP interface type", "Uptime window")
    rep, rep_id = _user(client, sync_engine, "Rep Person", "sales_representative")
    assert _add(client, headers, opp, rep_id).status_code == 200
    reader, _ = _user(client, sync_engine, "Head Person", "head_of_delivery")
    outsider, _ = _user(client, sync_engine, "Outsider", PSE)

    seen = _gaps(client, rep, opp["id"])
    assert (seen["can_send_questions"], seen["can_edit_questions"]) == (True, False)
    assert _gaps(client, headers, opp["id"])["can_send_questions"] is True
    assert _gaps(client, reader, opp["id"])["can_send_questions"] is False

    assert _export(client, rep, opp["id"], "copy").status_code == 200
    sent = _mark_sent(client, rep, opp["id"], [approved["SAP interface type"]])
    assert sent.status_code == 200, sent.text
    rep_view = {g["title"]: g["question"] for g in _gaps(client, rep, opp["id"])["items"]}
    sap = rep_view["SAP interface type"]
    assert (sap["status"], sap["sent_by"]["name"]) == ("sent", "Rep Person")
    assert rep_view["Uptime window"]["status"] == "approved"
    assert rep_view["Peak growth"] is None  # still drafted: hidden from the rep
    unanswered = _no_answer(client, rep, opp["id"], sap)
    assert unanswered.status_code == 200, unanswered.text
    rep_view = {g["title"]: g["question"] for g in _gaps(client, rep, opp["id"])["items"]}
    assert rep_view["SAP interface type"]["status"] == "unanswered"
    edit = _edit(client, rep, opp["id"], rep_view["Uptime window"], {"text": "Other?"})
    assert_problem(edit.json(), 403, "forbidden")

    for resp in (
        _export(client, reader, opp["id"], "copy"),
        _mark_sent(client, reader, opp["id"], [approved["Uptime window"]]),
        _no_answer(client, reader, opp["id"], approved["Uptime window"]),
    ):
        assert_problem(resp.json(), 403, "forbidden")
    for resp in (
        _export(client, outsider, opp["id"], "copy"),
        _mark_sent(client, outsider, opp["id"], [approved["Uptime window"]]),
        _no_answer(client, outsider, opp["id"], approved["Uptime window"]),
    ):
        assert_problem(resp.json(), 404, "not_found")


# --- re-detection ---------------------------------------------------------------------------


def test_a_re_detection_keeps_gaps_with_sent_or_unanswered_questions(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected_topics(client, sync_engine, db_url, gateway)
    approved = _approved(client, headers, opp["id"], "SAP interface type", "Uptime window")
    marked = _mark_sent(
        client, headers, opp["id"], [approved["SAP interface type"], approved["Uptime window"]]
    )
    assert marked.status_code == 200, marked.text
    current = _questions(client, headers, opp["id"])
    assert _no_answer(client, headers, opp["id"], current["Uptime window"]).status_code == 200
    kept = _questions(client, headers, opp["id"])
    requeue(db_url, opp["id"])
    gateway.replies = [gaps_out(gap("Price indexation", ["R5"], category="commercial"))]

    assert drain(db_url, DETECT) == ["succeeded"]

    after = _questions(client, headers, opp["id"])
    assert set(after) == {"SAP interface type", "Uptime window", "Price indexation"}
    assert after["SAP interface type"] == kept["SAP interface type"]
    assert after["Uptime window"] == kept["Uptime window"]
    superseded = rows(
        sync_engine,
        "SELECT title FROM gaps_gaps WHERE opportunity_id = :o AND status = 'superseded'",
        o=opp["id"],
    )
    assert {r["title"] for r in superseded} == {"Peak growth", "SSO provider"}


# --- the migration --------------------------------------------------------------------------


def test_the_downgrade_returns_sent_questions_to_approved(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    headers, opp = detected_topics(client, sync_engine, db_url, gateway)
    approved = _approved(client, headers, opp["id"], "SAP interface type")
    sap = approved["SAP interface type"]
    assert _mark_sent(client, headers, opp["id"], [sap]).status_code == 200

    _alembic("downgrade", "0029_gaps_dismiss_history")
    try:
        (row,) = rows(
            sync_engine,
            "SELECT status, approved_by FROM gaps_clarification_questions WHERE id = :q",
            q=sap["id"],
        )
        assert row["status"] == "approved" and row["approved_by"] is not None
    finally:
        _alembic("upgrade", "head")

    after = _question_row(sync_engine, sap["id"])
    assert (after["status"], after["sent_on"], after["sent_by"]) == ("approved", None, None)
