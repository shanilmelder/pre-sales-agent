"""Report variance rules (Story 10.3): tone thresholds, the diverging bar, the zero-estimate
label, the main cause tie-breaks and the calibration sentence. Pure, no database."""

from decimal import Decimal

import pytest

from app.modules.actuals.domain.actuals import MINUS
from app.modules.reporting.domain.variance import (
    CauseStats,
    Tone,
    VarianceCause,
    calibration_message,
    main_cause,
    report_variance,
)

D = Decimal


@pytest.mark.parametrize(
    ("estimate", "actual", "display", "tone", "left", "width"),
    [
        ("420", "468", "+11.4%", Tone.OVER, "50", "6.8"),
        ("96", "88", f"{MINUS}8.3%", Tone.UNDER, "45.0", "5.0"),
        ("100", "110", "+10.0%", Tone.NEUTRAL, "50", "6.0"),  # not above +10%
        ("100", "95", f"{MINUS}5.0%", Tone.NEUTRAL, "47.0", "3.0"),  # not below -5%
        ("100", "100", "±0.0%", Tone.NEUTRAL, "50", "0.0"),
        ("100", "300", "+200.0%", Tone.OVER, "50", "50.0"),  # the bar stops at the edge
        ("0", "12", "+12.0 h", Tone.OVER, "50", "50.0"),  # no estimate: hours, no percent
        ("0", "0", "±0.0 h", Tone.NEUTRAL, "50", "0.0"),
    ],
)
def test_report_variance(
    estimate: str, actual: str, display: str, tone: Tone, left: str, width: str
) -> None:
    rv = report_variance(D(estimate), D(actual))
    assert rv.display == display
    assert rv.tone == tone
    assert (rv.bar.left, rv.bar.width) == (D(left), D(width))


def test_sr_labels() -> None:
    assert report_variance(D(10), D(12)).sr_label == "over"
    assert report_variance(D(10), D(8)).sr_label == "under"
    assert report_variance(D(10), D(10)).sr_label == "on estimate"


def test_main_cause() -> None:
    c = VarianceCause
    assert main_cause([]) is None
    # Most frequent wins.
    assert (
        main_cause([CauseStats(c.SCOPE_CHANGE, 2, D(1)), CauseStats(c.OTHER, 1, D(50))])
        == c.SCOPE_CHANGE
    )
    # A tie goes to the larger summed |variance|, counted across rows of the same cause.
    assert (
        main_cause(
            [
                CauseStats(c.SCOPE_CHANGE, 1, D(4)),
                CauseStats(c.ESTIMATION_ERROR, 2, D(5)),
                CauseStats(c.SCOPE_CHANGE, 1, D(3)),
            ]
        )
        == c.SCOPE_CHANGE
    )
    # Then alphabetically by label: "Customer delay" before "Other".
    assert (
        main_cause([CauseStats(c.OTHER, 1, D(5)), CauseStats(c.CUSTOMER_DELAY, 1, D(5))])
        == c.CUSTOMER_DELAY
    )


def test_calibration_message() -> None:
    need = "Suggestions need at least 5 closed Opportunities per Integration Type."
    assert calibration_message([]) == f"{need} No Integration Type has a closed Opportunity yet."
    assert calibration_message([1, 2, 5]) == f"{need} 1 of 3 types has that many."
    assert calibration_message([7]) == f"{need} 1 of 1 type has that many."
    assert calibration_message([0, 2]) == f"{need} 0 of 2 types have that many."
