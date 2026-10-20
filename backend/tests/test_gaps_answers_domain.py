"""Answer transitions (Story 4.7): answering a question and its Gap, reopening an answered Gap
and its question, the answer limits and the touched rule. Pure, no DB."""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from app.modules.gaps.domain.gaps import (
    ANSWER_MAX,
    GapNotOpenTransitionError,
    GapNotReopenableTransitionError,
    GapState,
    GapStatus,
    Impact,
    QuestionNotSentTransitionError,
    QuestionSentError,
    QuestionState,
    QuestionStatus,
    answer_gap,
    answer_question,
    answer_text,
    answered_date,
    approve_question,
    edit_question,
    reopen_gap,
    reopen_question,
    touched,
)

ON = date(2026, 10, 12)
USER = uuid4()
PASSAGE = uuid4()


def _question(status: QuestionStatus) -> QuestionState:
    sent = status in (QuestionStatus.SENT, QuestionStatus.UNANSWERED, QuestionStatus.ANSWERED)
    return QuestionState(
        text="Which SAP release?",
        topic="SAP",
        status=status,
        approved_by=USER,
        approved_at=datetime(2026, 10, 5, tzinfo=UTC),
        sent_on=date(2026, 10, 6) if sent else None,
        sent_by=USER if sent else None,
    )


@pytest.mark.parametrize("status", [QuestionStatus.SENT, QuestionStatus.UNANSWERED])
def test_a_sent_or_unanswered_question_is_answered_keeping_its_sending(
    status: QuestionStatus,
) -> None:
    answered = answer_question(_question(status), user_id=USER, on=ON, passage_id=PASSAGE)

    assert answered.status == QuestionStatus.ANSWERED
    assert (answered.answered_on, answered.answered_by, answered.answer_passage_id) == (
        ON,
        USER,
        PASSAGE,
    )
    assert answered.sent_on == date(2026, 10, 6)
    assert answered.approved_by == USER


@pytest.mark.parametrize(
    "status",
    [
        QuestionStatus.DRAFTED,
        QuestionStatus.APPROVED,
        QuestionStatus.ANSWERED,
        QuestionStatus.SUPERSEDED,
    ],
)
def test_any_other_question_is_not_answerable(status: QuestionStatus) -> None:
    with pytest.raises(QuestionNotSentTransitionError):
        answer_question(_question(status), user_id=USER, on=ON, passage_id=PASSAGE)


def test_an_answered_question_cannot_be_edited_or_approved_and_counts_as_touched() -> None:
    answered = _question(QuestionStatus.ANSWERED)
    with pytest.raises(QuestionSentError):
        edit_question(answered, text="New")
    with pytest.raises(QuestionSentError):
        approve_question(answered, user_id=USER, at=datetime.now(UTC))
    assert touched(status="answered", edited_by_human=False)


def test_only_an_open_gap_is_answered() -> None:
    answered = answer_gap(
        GapState(status=GapStatus.OPEN, impact=Impact.HIGH),
        user_id=USER,
        on=ON,
        passage_id=PASSAGE,
    )
    assert (answered.status, answered.answer_passage_id) == (GapStatus.ANSWERED, PASSAGE)
    for status in (GapStatus.DISMISSED, GapStatus.CONVERTED, GapStatus.ANSWERED):
        with pytest.raises(GapNotOpenTransitionError):
            answer_gap(
                GapState(status=status, impact=Impact.HIGH),
                user_id=USER,
                on=ON,
                passage_id=PASSAGE,
            )


def test_reopening_an_answered_gap_clears_its_answer_and_sends_its_question_again() -> None:
    gap = answer_gap(
        GapState(status=GapStatus.OPEN, impact=Impact.LOW), user_id=USER, on=ON, passage_id=PASSAGE
    )
    reopened = reopen_gap(gap)
    assert reopened.status == GapStatus.OPEN
    assert (reopened.answered_on, reopened.answered_by, reopened.answer_passage_id) == (
        None,
        None,
        None,
    )
    assert reopened.touched_by_human

    question = answer_question(
        _question(QuestionStatus.SENT), user_id=USER, on=ON, passage_id=PASSAGE
    )
    again = reopen_question(question)
    assert again.status == QuestionStatus.SENT
    assert again.answered_on is None and again.answer_passage_id is None
    assert again.sent_on == date(2026, 10, 6)
    # Any other question stays as it is.
    drafted = _question(QuestionStatus.DRAFTED)
    assert reopen_question(drafted) is drafted


@pytest.mark.parametrize("status", [GapStatus.OPEN, GapStatus.CONVERTED, GapStatus.SUPERSEDED])
def test_open_converted_and_superseded_gaps_are_not_reopenable(status: GapStatus) -> None:
    with pytest.raises(GapNotReopenableTransitionError):
        reopen_gap(GapState(status=status, impact=Impact.LOW))


def test_answers_are_trimmed_and_bounded_and_not_dated_in_the_future() -> None:
    assert answer_text("  Yes  ") == "Yes"
    assert answer_text("x" * ANSWER_MAX) == "x" * ANSWER_MAX
    for bad in ("", "  ", "x" * (ANSWER_MAX + 1)):
        with pytest.raises(ValueError, match="answer must be 1 to 20,000"):
            answer_text(bad)
    assert answered_date(ON, today=ON) == ON
    with pytest.raises(ValueError, match="can't be in the future"):
        answered_date(date(2026, 10, 13), today=ON)
