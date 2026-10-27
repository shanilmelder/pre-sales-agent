"""Report variance rules (Story 10.3). Pure, no I/O.

- The variance itself (hours to 0.1, percent of the estimate to 0.1 half up, none when the
  estimate is 0) is the Actuals tab's rule, reused through `actuals`' public API.
- Reports colour a variance as an aggregate (on purpose unlike the Actuals tab): `over` (red)
  only above +10 %, `under` (green) below -5 %, otherwise `neutral`. With no estimate, any
  overrun is `over`.
- The diverging bar is centred at 50 %: its width is `min(50, |percent| * 0.6)` % of the track,
  to the right of centre when over and to the left when under.
- A group's main cause is its most frequent cause; ties go to the larger summed |variance|,
  then alphabetically by label.
- Calibration needs at least `CALIBRATION_THRESHOLD` closed Opportunities per Integration
  Type; the strip says how many types have that many.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.modules.actuals.application.public import (
    CAUSE_LABELS,
    MINUS,
    Variance,
    VarianceCause,
    VarianceDirection,
    variance,
)

OVER_THRESHOLD = Decimal(10)
UNDER_THRESHOLD = Decimal(-5)
BAR_HALF = Decimal(50)
BAR_SCALE = Decimal("0.6")
CALIBRATION_THRESHOLD = 5

__all__ = [
    "CALIBRATION_THRESHOLD",
    "CAUSE_LABELS",
    "Bar",
    "CauseStats",
    "ReportVariance",
    "Tone",
    "Variance",
    "VarianceCause",
    "VarianceDirection",
    "calibration_message",
    "main_cause",
    "report_variance",
]


class Tone(StrEnum):
    OVER = "over"
    UNDER = "under"
    NEUTRAL = "neutral"


@dataclass(frozen=True, slots=True)
class Bar:
    """Where the diverging bar's fill sits, as percents of the track."""

    left: Decimal
    width: Decimal


@dataclass(frozen=True, slots=True)
class ReportVariance:
    variance: Variance
    tone: Tone
    bar: Bar

    @property
    def display(self) -> str:
        """The table's figure: the signed percent ("+11.4%", "-8.3%" with a minus sign,
        "±0.0%"), or the signed hours ("+12.0 h") when there is no estimate."""
        v = self.variance
        if v.percent is None:
            return v.label
        sign = {
            VarianceDirection.OVER: "+",
            VarianceDirection.UNDER: MINUS,
            VarianceDirection.ON: "±",
        }[v.direction]
        return f"{sign}{abs(v.percent):.1f}%"

    @property
    def sr_label(self) -> str:
        """The words read with the figure, so colour is never alone: "over" or "under"."""
        if self.variance.direction == VarianceDirection.OVER:
            return "over"
        if self.variance.direction == VarianceDirection.UNDER:
            return "under"
        return "on estimate"


def _tone(v: Variance) -> Tone:
    if v.percent is None:
        return Tone.OVER if v.direction == VarianceDirection.OVER else Tone.NEUTRAL
    if v.percent > OVER_THRESHOLD:
        return Tone.OVER
    if v.percent < UNDER_THRESHOLD:
        return Tone.UNDER
    return Tone.NEUTRAL


def _bar(v: Variance) -> Bar:
    if v.percent is None:
        width = BAR_HALF if v.direction == VarianceDirection.OVER else Decimal(0)
    else:
        width = min(BAR_HALF, abs(v.percent) * BAR_SCALE)
    width = width.quantize(Decimal("0.1"))
    left = BAR_HALF if v.direction != VarianceDirection.UNDER else BAR_HALF - width
    return Bar(left=left, width=width)


def report_variance(estimate: Decimal, actual: Decimal) -> ReportVariance:
    """The report variance of summed `actual` against summed `estimate` (person-hours)."""
    v = variance(estimate, actual)
    return ReportVariance(variance=v, tone=_tone(v), bar=_bar(v))


@dataclass(frozen=True, slots=True)
class CauseStats:
    """How often a cause was given in a group, and the summed |actual - estimate| of those
    Actuals."""

    cause: VarianceCause
    count: int
    abs_variance: Decimal


def main_cause(stats: Iterable[CauseStats]) -> VarianceCause | None:
    """The most frequent cause, ties to the larger summed |variance|, then by label; None
    when no Actual gave a cause."""
    merged: dict[VarianceCause, tuple[int, Decimal]] = {}
    for s in stats:
        count, total = merged.get(s.cause, (0, Decimal(0)))
        merged[s.cause] = (count + s.count, total + s.abs_variance)
    if not merged:
        return None
    return min(
        merged,
        key=lambda c: (-merged[c][0], -merged[c][1], CAUSE_LABELS[c].casefold()),
    )


def calibration_message(closed_per_type: Iterable[int]) -> str:
    """The calibration strip's sentence from each Integration Type's closed-Opportunity
    count, e.g. "Suggestions need at least 5 closed Opportunities per Integration Type. 1 of
    4 types has that many."."""
    counts = list(closed_per_type)
    need = (
        f"Suggestions need at least {CALIBRATION_THRESHOLD} closed Opportunities per "
        "Integration Type."
    )
    if not counts:
        return f"{need} No Integration Type has a closed Opportunity yet."
    ready = sum(1 for c in counts if c >= CALIBRATION_THRESHOLD)
    total = len(counts)
    verb = "has" if ready == 1 else "have"
    noun = "type" if total == 1 else "types"
    return f"{need} {ready} of {total} {noun} {verb} that many."
