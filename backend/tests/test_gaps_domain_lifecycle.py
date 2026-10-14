"""Gap transitions (Story 4.4): impact change, dismiss and reopen. Pure, no DB."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.gaps.domain.gaps import (
    REASON_MAX,
    DismissReasonKind,
    GapNotDismissedTransitionError,
    GapNotOpenTransitionError,
    GapState,
    GapStatus,
    Impact,
    change_impact,
    dismiss_gap,
    dismiss_note,
    gap_key,
    reason_text,
    reopen_gap,
)

AT = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
OPEN = GapState(status=GapStatus.OPEN, impact=Impact.HIGH)


def test_reasons_are_trimmed_and_bounded() -> None:
    assert reason_text("  too vague  ") == "too vague"
    assert reason_text("x" * REASON_MAX) == "x" * REASON_MAX
    for bad in ("", "   ", "x" * (REASON_MAX + 1)):
        with pytest.raises(ValueError, match="reason must be 1 to 500"):
            reason_text(bad)


def test_a_note_is_required_for_other_and_optional_for_not_relevant() -> None:
    assert dismiss_note(DismissReasonKind.NOT_RELEVANT, None) is None
    assert dismiss_note(DismissReasonKind.NOT_RELEVANT, "  ") is None
    assert dismiss_note(DismissReasonKind.NOT_RELEVANT, " dup ") == "dup"
    assert dismiss_note(DismissReasonKind.OTHER, " covered elsewhere ") == "covered elsewhere"
    for bad in (None, "", "  "):
        with pytest.raises(ValueError, match="note is required"):
            dismiss_note(DismissReasonKind.OTHER, bad)
    with pytest.raises(ValueError, match="note must be 1 to 500"):
        dismiss_note(DismissReasonKind.NOT_RELEVANT, "x" * (REASON_MAX + 1))


def test_an_impact_change_marks_the_gap_touched() -> None:
    lowered = change_impact(OPEN, Impact.LOW)
    assert lowered.impact == Impact.LOW
    assert lowered.touched_by_human
    assert change_impact(OPEN, Impact.HIGH) is OPEN


@pytest.mark.parametrize("status", [GapStatus.DISMISSED, GapStatus.CONVERTED, GapStatus.SUPERSEDED])
def test_only_an_open_gap_changes_impact_or_is_dismissed(status: GapStatus) -> None:
    state = GapState(status=status, impact=Impact.HIGH)
    with pytest.raises(GapNotOpenTransitionError):
        change_impact(state, Impact.LOW)
    with pytest.raises(GapNotOpenTransitionError):
        dismiss_gap(state, kind=DismissReasonKind.NOT_RELEVANT, note=None, user_id=uuid4(), at=AT)


def test_dismiss_then_reopen_clears_the_dismissal() -> None:
    user = uuid4()
    dismissed = dismiss_gap(OPEN, kind=DismissReasonKind.OTHER, note="dup", user_id=user, at=AT)
    assert dismissed.status == GapStatus.DISMISSED
    assert dismissed.dismiss_reason_kind == DismissReasonKind.OTHER
    assert (dismissed.dismiss_note, dismissed.dismissed_by, dismissed.dismissed_at) == (
        "dup",
        user,
        AT,
    )
    assert not dismissed.touched_by_human
    reopened = reopen_gap(dismissed)
    assert reopened.status == GapStatus.OPEN
    assert reopened.dismiss_reason_kind is None
    assert reopened.dismiss_note is None
    assert reopened.dismissed_by is None
    assert reopened.dismissed_at is None
    assert reopened.touched_by_human


@pytest.mark.parametrize("status", [GapStatus.OPEN, GapStatus.CONVERTED, GapStatus.SUPERSEDED])
def test_only_a_dismissed_gap_reopens(status: GapStatus) -> None:
    with pytest.raises(GapNotDismissedTransitionError):
        reopen_gap(GapState(status=status, impact=Impact.LOW))


def test_gap_key_ignores_case_and_spacing() -> None:
    assert gap_key("data_volumes", "  Peak  ORDER volume ") == gap_key(
        "data_volumes", "peak order volume"
    )
    assert gap_key("other", "Peak order volume") != gap_key("data_volumes", "Peak order volume")
