"""What a person's decision on a Conflict must look like (Story 6.3). Pure.

- The reason (resolving or escalating): trimmed, 1-1,000 characters.
- A different position entered in words: trimmed, 1-200 characters; for an `effort` Conflict
  it must be hours from 0 to 2,000 to 0.1 h ("48", "48.5", "48 h").
- Why an `effort` decision changed no Estimate line (`NotApplied`).
"""

import re
from decimal import Decimal
from enum import StrEnum

REASON_MAX = 1000
ENTERED_MAX = 200
HOURS_MAX = Decimal(2000)

REASON_RULE = "Give a reason of 1 to 1,000 characters."
ENTERED_RULE = "Enter a position of 1 to 200 characters."
HOURS_RULE = "For an effort Conflict, enter hours from 0 to 2,000, to 0.1 h (for example 48)."
CHOICE_RULE = "Choose one of this Conflict's positions."
REVIEWER_RULE = "Choose a reviewer who is the Opportunity's owner or a collaborator, not you."

_HOURS_RE = re.compile(r"^(\d{1,4}(?:\.\d)?)\s*h?$")


def _bounded(raw: str | None, limit: int) -> str | None:
    if raw is None:
        return None
    text = raw.strip()
    return text if 1 <= len(text) <= limit else None


def decision_reason(raw: str | None) -> str | None:
    """The reason trimmed, if it is 1-1,000 characters; None otherwise."""
    return _bounded(raw, REASON_MAX)


def entered_text(raw: str | None) -> str | None:
    """The entered position trimmed, if it is 1-200 characters; None otherwise."""
    return _bounded(raw, ENTERED_MAX)


def entered_hours(text: str) -> Decimal | None:
    """The hours an entered position names ("48", "48.5", "48 h"), if 0-2,000 to 0.1 h;
    None otherwise."""
    match = _HOURS_RE.match(text.strip())
    if match is None:
        return None
    hours = Decimal(match.group(1))
    return hours if hours <= HOURS_MAX else None


class NotApplied(StrEnum):
    """Why an `effort` decision changed no Estimate line."""

    NO_LINE = "no_line"
    """No line of the current draft covers the Requirement (or there is no draft)."""
    SHARED_LINE = "shared_line"
    """The line covering it covers other Requirements too."""
    SEVERAL_LINES = "several_lines"
    """More than one line covers it."""
    NOT_PERMITTED = "not_permitted"
    """The person who resolved it may not edit Estimate lines (FR-64)."""
