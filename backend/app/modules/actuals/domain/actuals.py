"""Actuals rules (Story 10.1; FR-49, AD-10). Pure, no I/O.

- Kinds: `milestone | final`. Only a final Actual closes a line.
- Variance causes are a fixed set; Unplanned work (no Estimate line) takes only
  `scope_change`, `unknown_requirement` or `other`.
- Variance is computed here, never in the browser: hours are `actual - estimate` (0.1 h) and
  percent is that over the estimate (0.1 %, half up; none when the estimate is 0).
- A final Actual whose effort differs from the estimate needs a cause, and `other` always
  needs a note. Unplanned work needs an Integration Type or a Work Package and a cause.
- Effort and duration are `numeric(10,1)`; cost is integer minor units with an ISO-4217
  currency, both or neither.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

ACTUAL_SUBJECT_TYPE = "actuals.actual"
DELIVERY_SUBJECT_TYPE = "actuals.delivery"

TENTH = Decimal("0.1")
HUNDRED = Decimal(100)
EFFORT_MAX = Decimal("999999999.9")
"""The largest `numeric(10,1)`."""
COST_MAX = 2**63 - 1
NOTE_MAX = 2000
MILESTONE_LABEL_MAX = 200
REASON_MAX = 1000
FAILED_ASSUMPTIONS_MAX = 50
"""The most failed Assumptions one Actual may name."""
MINUS = "−"  # noqa: RUF001 - the real minus sign on purpose
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class ActualKind(StrEnum):
    MILESTONE = "milestone"
    FINAL = "final"


class VarianceCause(StrEnum):
    UNKNOWN_REQUIREMENT = "unknown_requirement"
    INTEGRATION_COMPLEXITY = "integration_complexity"
    CUSTOMER_DELAY = "customer_delay"
    SCOPE_CHANGE = "scope_change"
    ESTIMATION_ERROR = "estimation_error"
    OTHER = "other"


CAUSE_LABELS: dict[VarianceCause, str] = {
    VarianceCause.UNKNOWN_REQUIREMENT: "Unknown requirement",
    VarianceCause.INTEGRATION_COMPLEXITY: "Integration complexity",
    VarianceCause.CUSTOMER_DELAY: "Customer delay",
    VarianceCause.SCOPE_CHANGE: "Scope change",
    VarianceCause.ESTIMATION_ERROR: "Estimation error",
    VarianceCause.OTHER: "Other",
}

UNPLANNED_CAUSES: frozenset[VarianceCause] = frozenset(
    {VarianceCause.SCOPE_CHANGE, VarianceCause.UNKNOWN_REQUIREMENT, VarianceCause.OTHER}
)
"""The causes Unplanned work may give."""


class VarianceDirection(StrEnum):
    OVER = "over"
    UNDER = "under"
    ON = "on"


DIRECTION_LABELS: dict[VarianceDirection, str] = {
    VarianceDirection.OVER: "Over estimate",
    VarianceDirection.UNDER: "Under estimate",
    VarianceDirection.ON: "On estimate",
}


@dataclass(frozen=True, slots=True)
class Variance:
    """Actual minus estimate: hours (0.1 h), percent of the estimate (0.1 %, None when the
    estimate is 0) and the direction."""

    hours: Decimal
    percent: Decimal | None
    direction: VarianceDirection

    @property
    def label(self) -> str:
        """E.g. "+5.0 h (13.9%)", "-2.0 h (-10.0%)" (with the minus sign), "±0.0 h (0.0%)",
        "+8.0 h" (no estimate). Always signed, never colour alone."""
        sign = {
            VarianceDirection.OVER: "+",
            VarianceDirection.UNDER: MINUS,
            VarianceDirection.ON: "±",
        }[self.direction]
        hours = f"{sign}{abs(self.hours):.1f} h"
        if self.percent is None:
            return hours
        percent = f"{abs(self.percent):.1f}%"
        if self.percent < 0:
            percent = MINUS + percent
        return f"{hours} ({percent})"

    @property
    def direction_label(self) -> str:
        return DIRECTION_LABELS[self.direction]


def tenths(value: Decimal) -> Decimal:
    return value.quantize(TENTH, rounding=ROUND_HALF_UP)


def variance(estimate: Decimal, actual: Decimal) -> Variance:
    """The variance of `actual` against `estimate` (both person-hours)."""
    hours = tenths(actual - estimate)
    percent = None if estimate == 0 else tenths(hours / estimate * HUNDRED)
    if hours > 0:
        direction = VarianceDirection.OVER
    elif hours < 0:
        direction = VarianceDirection.UNDER
    else:
        direction = VarianceDirection.ON
    return Variance(hours=hours, percent=percent, direction=direction)


def total_variance(pairs: Iterable[tuple[Decimal, Decimal]]) -> Variance | None:
    """The variance of the summed (estimate, actual) pairs; None when there are none. Only
    the recorded lines and Unplanned work (estimate 0) are passed in."""
    items = list(pairs)
    if not items:
        return None
    return variance(sum((e for e, _ in items), Decimal(0)), sum((a for _, a in items), Decimal(0)))


@dataclass(frozen=True, slots=True)
class FieldError:
    field: str
    message: str


@dataclass(frozen=True, slots=True)
class ActualDraft:
    """What a person entered for one Actual, as the rules need it. `estimate_hours` is the
    line's estimate, None for Unplanned work."""

    kind: ActualKind
    effort_hours: Decimal
    estimate_hours: Decimal | None
    cause: VarianceCause | None = None
    note: str | None = None
    milestone_label: str | None = None
    duration_days: Decimal | None = None
    cost_minor: int | None = None
    currency: str | None = None
    has_catalogue_ref: bool = False

    @property
    def unplanned(self) -> bool:
        return self.estimate_hours is None


CAUSE_REQUIRED = "A final Actual that differs from the estimate needs a variance cause."
NOTE_REQUIRED = "A variance cause of Other needs a note."
UNPLANNED_CAUSE = "Unplanned work needs a cause: scope change, unknown requirement or other."
UNPLANNED_REF = "Unplanned work needs an Integration Type or a Work Package."
EFFORT_RULE = "Effort is 0.0 to 999,999,999.9 person-hours, to one decimal place."
DURATION_RULE = "Duration is 0.0 to 999,999,999.9 working days, to one decimal place."
COST_RULE = "Cost is a whole number of minor units, 0 or more."
CURRENCY_RULE = "Currency is an ISO-4217 code such as EUR, given with the cost."
NOTE_RULE = f"A note is at most {NOTE_MAX:,} characters."
LABEL_RULE = f"A milestone label is at most {MILESTONE_LABEL_MAX} characters."


def _tenths_in_range(value: Decimal) -> bool:
    return value.is_finite() and Decimal(0) <= value <= EFFORT_MAX and value == tenths(value)


def clean_text(value: str | None) -> str | None:
    """Trimmed text, or None when blank."""
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def clean_reason(value: str | None) -> str | None:
    """A correction reason, trimmed, 1 to `REASON_MAX` characters; None when blank or too
    long (the caller answers 422)."""
    trimmed = clean_text(value)
    if trimmed is None or len(trimmed) > REASON_MAX:
        return None
    return trimmed


def validate(draft: ActualDraft) -> list[FieldError]:
    """Every rule the draft breaks, by field (module docstring); empty when it may be
    saved."""
    errors: list[FieldError] = []
    if not _tenths_in_range(draft.effort_hours):
        errors.append(FieldError("effort_hours", EFFORT_RULE))
    if draft.duration_days is not None and not _tenths_in_range(draft.duration_days):
        errors.append(FieldError("duration_days", DURATION_RULE))
    if draft.cost_minor is not None and not 0 <= draft.cost_minor <= COST_MAX:
        errors.append(FieldError("cost_minor", COST_RULE))
    if (draft.cost_minor is None) != (draft.currency is None) or (
        draft.currency is not None and not CURRENCY_RE.match(draft.currency)
    ):
        errors.append(FieldError("currency", CURRENCY_RULE))
    note = clean_text(draft.note)
    if note is not None and len(note) > NOTE_MAX:
        errors.append(FieldError("note", NOTE_RULE))
    label = clean_text(draft.milestone_label)
    if label is not None and len(label) > MILESTONE_LABEL_MAX:
        errors.append(FieldError("milestone_label", LABEL_RULE))

    if draft.unplanned:
        if not draft.has_catalogue_ref:
            errors.append(FieldError("integration_type_id", UNPLANNED_REF))
        if draft.cause is None or draft.cause not in UNPLANNED_CAUSES:
            errors.append(FieldError("variance_cause", UNPLANNED_CAUSE))
    elif (
        draft.kind == ActualKind.FINAL
        and draft.cause is None
        and draft.estimate_hours is not None
        and draft.effort_hours != draft.estimate_hours
    ):
        errors.append(FieldError("variance_cause", CAUSE_REQUIRED))
    if draft.cause == VarianceCause.OTHER and note is None:
        errors.append(FieldError("note", NOTE_REQUIRED))
    return errors


def open_line_count(line_kinds: Iterable[ActualKind | None]) -> int:
    """How many Baseline lines have no final Actual (None: nothing recorded)."""
    return sum(1 for kind in line_kinds if kind != ActualKind.FINAL)


def open_lines_message(count: int) -> str:
    """E.g. "4 lines have no final Actual"."""
    return (
        f"{count} line has no final Actual" if count == 1 else f"{count} lines have no final Actual"
    )
