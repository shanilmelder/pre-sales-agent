"""Actuals rules (Story 10.1): variance numbers and labels, and the validation rules. Pure."""

from decimal import Decimal

import pytest

from app.modules.actuals.domain.actuals import (
    CAUSE_REQUIRED,
    MINUS,
    NOTE_REQUIRED,
    UNPLANNED_CAUSE,
    UNPLANNED_CAUSES,
    UNPLANNED_REF,
    ActualDraft,
    ActualKind,
    VarianceCause,
    VarianceDirection,
    clean_reason,
    open_line_count,
    open_lines_message,
    total_variance,
    validate,
    variance,
)

D = Decimal


def _fields(draft: ActualDraft) -> dict[str, str]:
    return {e.field: e.message for e in validate(draft)}


# --- variance -------------------------------------------------------------------------------


def test_over_is_signed_hours_and_percent() -> None:
    v = variance(D("36.0"), D("41.0"))
    assert (v.hours, v.percent, v.direction) == (D("5.0"), D("13.9"), VarianceDirection.OVER)
    assert v.label == "+5.0 h (13.9%)"
    assert v.direction_label == "Over estimate"


def test_under_uses_the_minus_sign() -> None:
    v = variance(D("20.0"), D("18.0"))
    assert (v.hours, v.percent, v.direction) == (D("-2.0"), D("-10.0"), VarianceDirection.UNDER)
    assert v.label == f"{MINUS}2.0 h ({MINUS}10.0%)"


def test_on_estimate() -> None:
    v = variance(D("12.5"), D("12.5"))
    assert v.direction is VarianceDirection.ON
    assert v.label == "±0.0 h (0.0%)"


def test_no_estimate_has_no_percent() -> None:
    v = variance(D(0), D("8.0"))
    assert v.percent is None
    assert v.label == "+8.0 h"


def test_percent_rounds_half_up_to_a_tenth() -> None:
    assert variance(D("3.0"), D("3.1")).percent == D("3.3")  # 3.333…
    assert variance(D("8.0"), D("8.1")).percent == D("1.3")  # 1.25 -> 1.3


def test_total_variance_sums_the_pairs() -> None:
    assert total_variance([]) is None
    total = total_variance([(D("36.0"), D("41.0")), (D("20.0"), D("18.0")), (D(0), D("4.0"))])
    assert total is not None
    assert (total.hours, total.percent) == (D("7.0"), D("12.5"))


# --- validation -----------------------------------------------------------------------------


def test_a_final_actual_that_differs_needs_a_cause() -> None:
    draft = ActualDraft(ActualKind.FINAL, D("41.0"), D("36.0"))
    assert _fields(draft) == {"variance_cause": CAUSE_REQUIRED}
    ok = ActualDraft(ActualKind.FINAL, D("41.0"), D("36.0"), cause=VarianceCause.ESTIMATION_ERROR)
    assert _fields(ok) == {}
    assert _fields(ActualDraft(ActualKind.FINAL, D("36.0"), D("36.0"))) == {}


def test_other_needs_a_note() -> None:
    draft = ActualDraft(ActualKind.FINAL, D("41.0"), D("36.0"), cause=VarianceCause.OTHER)
    assert _fields(draft) == {"note": NOTE_REQUIRED}
    blank = ActualDraft(
        ActualKind.FINAL, D("41.0"), D("36.0"), cause=VarianceCause.OTHER, note="   "
    )
    assert _fields(blank) == {"note": NOTE_REQUIRED}
    noted = ActualDraft(
        ActualKind.FINAL, D("41.0"), D("36.0"), cause=VarianceCause.OTHER, note="Weather"
    )
    assert _fields(noted) == {}


def test_a_milestone_needs_no_cause() -> None:
    assert _fields(ActualDraft(ActualKind.MILESTONE, D("10.0"), D("36.0"))) == {}


def test_unplanned_work_needs_a_ref_and_an_unplanned_cause() -> None:
    assert UNPLANNED_CAUSES == {"scope_change", "unknown_requirement", "other"}
    bare = ActualDraft(ActualKind.FINAL, D("8.0"), None)
    assert _fields(bare) == {
        "integration_type_id": UNPLANNED_REF,
        "variance_cause": UNPLANNED_CAUSE,
    }
    wrong = ActualDraft(
        ActualKind.FINAL, D("8.0"), None, cause=VarianceCause.CUSTOMER_DELAY, has_catalogue_ref=True
    )
    assert _fields(wrong) == {"variance_cause": UNPLANNED_CAUSE}
    ok = ActualDraft(
        ActualKind.FINAL, D("8.0"), None, cause=VarianceCause.SCOPE_CHANGE, has_catalogue_ref=True
    )
    assert _fields(ok) == {}


@pytest.mark.parametrize("effort", [D("-0.1"), D("1.25"), D("1000000000.0"), D("NaN")])
def test_effort_is_numeric_10_1(effort: Decimal) -> None:
    assert set(_fields(ActualDraft(ActualKind.MILESTONE, effort, D("1.0")))) == {"effort_hours"}


def test_cost_and_currency_come_together() -> None:
    base = {"kind": ActualKind.MILESTONE, "effort_hours": D("1.0"), "estimate_hours": D("1.0")}
    assert set(_fields(ActualDraft(**base, cost_minor=100))) == {"currency"}  # type: ignore[arg-type]
    assert set(_fields(ActualDraft(**base, currency="EUR"))) == {"currency"}  # type: ignore[arg-type]
    assert set(_fields(ActualDraft(**base, cost_minor=100, currency="eur"))) == {"currency"}  # type: ignore[arg-type]
    assert set(_fields(ActualDraft(**base, cost_minor=-1, currency="EUR"))) == {"cost_minor"}  # type: ignore[arg-type]
    assert _fields(ActualDraft(**base, cost_minor=480000, currency="EUR")) == {}  # type: ignore[arg-type]


def test_reasons_and_open_lines() -> None:
    assert clean_reason("  ") is None
    assert clean_reason("x" * 1001) is None
    assert clean_reason(" Timesheet corrected ") == "Timesheet corrected"
    assert open_line_count([ActualKind.FINAL, ActualKind.MILESTONE, None]) == 2
    assert open_lines_message(4) == "4 lines have no final Actual"
    assert open_lines_message(1) == "1 line has no final Actual"
