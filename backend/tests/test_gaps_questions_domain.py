"""Clarification Question transitions (Story 4.5): pure, no DB."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.gaps.domain.gaps import (
    QUESTION_MAX,
    TOPIC_MAX,
    QuestionNotEditableError,
    QuestionState,
    QuestionStatus,
    approve_question,
    edit_question,
    question_text,
    question_topic,
    touched,
)

AT = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
DRAFT = QuestionState(text="Which SAP?", topic="SAP", status=QuestionStatus.DRAFTED)


def test_text_and_topic_are_trimmed_and_bounded() -> None:
    assert question_text("  Which SAP?  ") == "Which SAP?"
    assert question_text("x" * QUESTION_MAX) == "x" * QUESTION_MAX
    assert question_topic(" SAP ") == "SAP"
    assert question_topic("t" * TOPIC_MAX) == "t" * TOPIC_MAX
    for bad in ("", "   ", "x" * (QUESTION_MAX + 1)):
        with pytest.raises(ValueError, match="question must be 1 to 1,000"):
            question_text(bad)
    for bad in ("", " \n", "t" * (TOPIC_MAX + 1)):
        with pytest.raises(ValueError, match="topic must be 1 to 80"):
            question_topic(bad)


def test_an_edit_marks_the_question_edited_and_names_the_changed_fields() -> None:
    edited, changed = edit_question(DRAFT, text="Which SAP release?", topic="SAP")

    assert changed == ("text",)
    assert (edited.text, edited.topic) == ("Which SAP release?", "SAP")
    assert edited.status == QuestionStatus.DRAFTED
    assert edited.edited_by_human is True

    _, changed = edit_question(DRAFT, text="New?", topic="New topic")
    assert changed == ("text", "topic")


def test_an_unchanged_edit_changes_nothing() -> None:
    assert edit_question(DRAFT, text="Which SAP?") == (DRAFT, ())
    assert edit_question(DRAFT) == (DRAFT, ())


def test_approving_records_who_and_when_and_is_idempotent() -> None:
    user = uuid4()
    approved = approve_question(DRAFT, user_id=user, at=AT)

    assert approved.status == QuestionStatus.APPROVED
    assert (approved.approved_by, approved.approved_at) == (user, AT)
    assert approve_question(approved, user_id=uuid4(), at=datetime.now(UTC)) is approved


def test_editing_an_approved_question_returns_it_to_drafted() -> None:
    approved = approve_question(DRAFT, user_id=uuid4(), at=AT)

    edited, changed = edit_question(approved, topic="ERP")

    assert changed == ("topic",)
    assert edited.status == QuestionStatus.DRAFTED
    assert (edited.approved_by, edited.approved_at) == (None, None)
    assert edited.edited_by_human is True
    # An edit that changes nothing keeps the approval.
    assert edit_question(approved, text="Which SAP?") == (approved, ())


def test_a_superseded_question_cannot_change() -> None:
    superseded = QuestionState(text="Old?", topic="Old", status=QuestionStatus.SUPERSEDED)
    with pytest.raises(QuestionNotEditableError):
        edit_question(superseded, text="New?")
    with pytest.raises(QuestionNotEditableError):
        approve_question(superseded, user_id=uuid4(), at=AT)


def test_touched_means_edited_or_approved() -> None:
    assert touched(status="drafted", edited_by_human=False) is False
    assert touched(status="drafted", edited_by_human=True) is True
    assert touched(status="approved", edited_by_human=False) is True
