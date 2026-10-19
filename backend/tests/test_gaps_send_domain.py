"""Sending Clarification Questions (Story 4.6): the pure transitions and the customer-facing
document. No DB."""

from datetime import UTC, date, datetime
from email import message_from_bytes
from email.policy import default
from io import BytesIO
from uuid import uuid4

import pytest
from docx import Document

from app.modules.gaps.adapters.question_document import (
    ExportQuestion,
    build_document,
    file_name,
    plain_text,
    render_docx,
    render_eml,
)
from app.modules.gaps.domain.gaps import (
    QuestionNotApprovedTransitionError,
    QuestionNotSentTransitionError,
    QuestionSentError,
    QuestionState,
    QuestionStatus,
    approve_question,
    edit_question,
    mark_sent,
    mark_unanswered,
    sent_date,
    touched,
)

AT = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
ON = date(2026, 10, 14)
APPROVER = uuid4()
APPROVED = QuestionState(
    text="Which SAP?",
    topic="SAP",
    status=QuestionStatus.APPROVED,
    approved_by=APPROVER,
    approved_at=AT,
)


def test_an_approved_question_is_marked_sent_keeping_its_approval() -> None:
    sender = uuid4()
    sent = mark_sent(APPROVED, user_id=sender, on=ON)
    assert (sent.status, sent.sent_on, sent.sent_by) == (QuestionStatus.SENT, ON, sender)
    assert (sent.approved_by, sent.approved_at) == (APPROVER, AT)


@pytest.mark.parametrize(
    "status", [QuestionStatus.DRAFTED, QuestionStatus.SENT, QuestionStatus.UNANSWERED]
)
def test_only_an_approved_question_is_marked_sent(status: QuestionStatus) -> None:
    with pytest.raises(QuestionNotApprovedTransitionError):
        mark_sent(QuestionState(text="Q?", topic="T", status=status), user_id=uuid4(), on=ON)


def test_a_sent_question_is_marked_no_answer_keeping_when_it_was_sent() -> None:
    sent = mark_sent(APPROVED, user_id=uuid4(), on=ON)
    unanswered = mark_unanswered(sent)
    assert unanswered.status == QuestionStatus.UNANSWERED
    assert (unanswered.sent_on, unanswered.sent_by) == (sent.sent_on, sent.sent_by)
    for state in (APPROVED, unanswered):
        with pytest.raises(QuestionNotSentTransitionError):
            mark_unanswered(state)


def test_a_sent_or_unanswered_question_cannot_be_edited_or_approved() -> None:
    sent = mark_sent(APPROVED, user_id=uuid4(), on=ON)
    for state in (sent, mark_unanswered(sent)):
        with pytest.raises(QuestionSentError):
            edit_question(state, text="New?")
        with pytest.raises(QuestionSentError):
            approve_question(state, user_id=uuid4(), at=AT)


def test_the_sent_date_may_not_be_in_the_future() -> None:
    assert sent_date(ON, today=ON) == ON
    assert sent_date(date(2026, 10, 1), today=ON) == date(2026, 10, 1)
    with pytest.raises(ValueError, match="future"):
        sent_date(date(2026, 10, 15), today=ON)


def test_sent_and_unanswered_questions_count_as_touched() -> None:
    assert touched(status="sent", edited_by_human=False) is True
    assert touched(status="unanswered", edited_by_human=False) is True
    assert touched(status="drafted", edited_by_human=False) is False


# --- the document -----------------------------------------------------------------------------


def _questions() -> list[ExportQuestion]:
    return [
        ExportQuestion(topic="SAP", text="Which SAP release?", rank=(1, "b", "1")),
        ExportQuestion(topic="Availability", text="What uptime?", rank=(0, "a", "2")),
        ExportQuestion(topic=" sap ", text="Which IDoc types?", rank=(0, "c", "3")),
    ]


def test_questions_are_grouped_by_topic_a_to_z_then_by_rank_and_numbered() -> None:
    document = build_document(customer_name=" ACME ", on=ON, questions=_questions())

    assert [g.topic for g in document.groups] == ["Availability", "SAP"]
    assert [(q.number, q.text) for g in document.groups for q in g.questions] == [
        (1, "What uptime?"),
        (2, "Which IDoc types?"),
        (3, "Which SAP release?"),
    ]
    assert plain_text(document) == (
        "Clarification questions for ACME\n"
        "14 Oct 2026\n"
        "\n"
        "Availability\n"
        "1. What uptime?\n"
        "\n"
        "SAP\n"
        "2. Which IDoc types?\n"
        "3. Which SAP release?\n"
    )


def test_the_plain_text_drops_control_characters() -> None:
    document = build_document(
        customer_name="AC\x07ME",
        on=ON,
        questions=[ExportQuestion(topic="S\x00AP", text="Which\x1b SAP?", rank=(0, "a", "1"))],
    )
    text = plain_text(document)
    assert "\x07" not in text and "\x00" not in text and "\x1b" not in text
    assert "1. Which SAP?" in text


def test_the_docx_holds_the_same_customer_wording() -> None:
    document = build_document(customer_name="ACME", on=ON, questions=_questions())
    parsed = Document(BytesIO(render_docx(document)))
    texts = [p.text for p in parsed.paragraphs if p.text]
    assert texts == [
        "Clarification questions for ACME",
        "14 Oct 2026",
        "Availability",
        "1. What uptime?",
        "SAP",
        "2. Which IDoc types?",
        "3. Which SAP release?",
    ]


def test_the_eml_is_an_unsent_draft_with_no_recipient() -> None:
    document = build_document(customer_name="ACME", on=ON, questions=_questions())
    message = message_from_bytes(render_eml(document), policy=default)
    assert message["X-Unsent"] == "1"
    assert message["To"] is None and message["Cc"] is None and message["Bcc"] is None
    assert message["Subject"] == "Clarification questions — ACME"
    assert message.get_content_type() == "text/plain"
    body = message.get_content()  # type: ignore[attr-defined]
    assert body.replace("\r\n", "\n") == plain_text(document)


def test_file_names_are_ascii_slugs() -> None:
    assert file_name("Brøndby A/S", ON, "docx") == (
        "clarification-questions-brndby-a-s-2026-10-14.docx"
    )
    assert file_name("???", ON, "eml") == "clarification-questions-2026-10-14.eml"
