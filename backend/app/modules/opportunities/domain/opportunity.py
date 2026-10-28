"""Opportunity domain rules (Story 1.7). Pure, no I/O.

Field rules are checked when a new Opportunity is built (`NewOpportunity` in the
application layer calls these), so every path that creates one applies them.
"""

from collections.abc import Iterable
from datetime import date, datetime
from enum import StrEnum

SUBJECT_TYPE = "opportunities.opportunity"

TITLE_MAX = 200
CUSTOMER_NAME_MAX = 200
INDUSTRY_MAX = 100
PRODUCTS_MIN = 1
PRODUCTS_MAX = 20
PRODUCT_NAME_MAX = 100


class OpportunityStatus(StrEnum):
    """Lifecycle status. Derived by a query from the Opportunity's state, never stored
    (AD-26)."""

    INTAKE = "intake"
    GAPS_OPEN = "gaps_open"
    ASSESSING = "assessing"
    ESTIMATING = "estimating"
    IN_REVIEW = "in_review"
    BASELINED = "baselined"
    DELIVERED = "delivered"
    CLOSED = "closed"


class Outcome(StrEnum):
    """Story 10.5: how an Opportunity ended. Null (no outcome) while it is open."""

    WON = "won"
    LOST = "lost"


LOST_RETENTION_YEARS = 3
"""Story 10.5: a lost Opportunity's data is kept this many years after the outcome."""
WON_RETENTION_YEARS = 7
"""Story 10.5: a won Opportunity's data is kept this many years after contract end."""
REASON_MAX = 1000
"""Story 10.5: the longest reason for an outcome command, once trimmed."""


def derived_status(
    has_baseline: bool = False, delivered: bool = False, outcome: Outcome | None = None
) -> OpportunityStatus:
    """The status of an Opportunity. Story 10.5: `closed` once it is recorded as lost (highest
    precedence; a won Opportunity keeps the status its data gives it). Story 10.1: otherwise
    `delivered` once delivery is closed (`actuals_deliveries` has a row for it). Story 9.7:
    otherwise `baselined` once a Baseline is set (`estimates_baselines` has a row for it);
    otherwise `intake` (the other statuses arrive in later stories)."""
    if outcome is Outcome.LOST:
        return OpportunityStatus.CLOSED
    if delivered:
        return OpportunityStatus.DELIVERED
    return OpportunityStatus.BASELINED if has_baseline else OpportunityStatus.INTAKE


def add_years(value: date, years: int) -> date:
    """`value` moved by whole calendar years; 29 February becomes 28 February in a year
    that has none. Raises ValueError past the last representable year."""
    year = value.year + years
    try:
        return value.replace(year=year)
    except ValueError:
        if value.month == 2 and value.day == 29:
            return value.replace(year=year, day=28)
        raise


def retention_until(
    outcome: Outcome | None,
    recorded_at: date | datetime | None,
    contract_end_date: date | None,
) -> date | None:
    """Story 10.5: the last day the Opportunity's data is kept. Lost: the date the outcome
    was recorded (`recorded_at`, a UTC timestamp's date) plus 3 years; won: the contract end
    date plus 7 years; open (no outcome): None, never purged. Calendar years (29 Feb to
    28 Feb). None when the date it needs is missing."""
    if outcome is Outcome.LOST:
        if recorded_at is None:
            return None
        day = recorded_at.date() if isinstance(recorded_at, datetime) else recorded_at
        return add_years(day, LOST_RETENTION_YEARS)
    if outcome is Outcome.WON:
        if contract_end_date is None:
            return None
        return add_years(contract_end_date, WON_RETENTION_YEARS)
    return None


def check_contract_end_date(value: date) -> date:
    """A contract end date whose retention date (plus 7 years) can be represented."""
    if value.year > date.max.year - WON_RETENTION_YEARS:
        raise ValueError(f"must be before {date.max.year - WON_RETENTION_YEARS + 1}")
    return value


def outcome_reason(value: str | None) -> str:
    """An outcome command's reason, trimmed, 1 to `REASON_MAX` characters. Raises ValueError
    otherwise."""
    if value is None:
        raise ValueError("a reason is required")
    return required_text(value, max_length=REASON_MAX)


def required_text(value: str, *, max_length: int) -> str:
    """Trimmed text, 1..max_length characters. Raises ValueError otherwise."""
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("must not be empty")
    if len(trimmed) > max_length:
        raise ValueError(f"must be at most {max_length} characters")
    return trimmed


def optional_title(value: str | None) -> str | None:
    """Trimmed title, or None when blank (the customer name is then used)."""
    if value is None or not value.strip():
        return None
    return required_text(value, max_length=TITLE_MAX)


def edited_title(value: str) -> str:
    """An edited title, trimmed, at most TITLE_MAX characters. Blank is allowed and comes
    back empty: the caller then falls back to the customer name, as on create."""
    trimmed = value.strip()
    if len(trimmed) > TITLE_MAX:
        raise ValueError(f"must be at most {TITLE_MAX} characters")
    return trimmed


def normalize_products(values: Iterable[str]) -> list[str]:
    """Trim each name (1..100 characters) and drop case-insensitive duplicates, keeping the
    first spelling. 1..20 names are required (counted as given)."""
    given = list(values)
    if len(given) < PRODUCTS_MIN:
        raise ValueError("at least one product is required")
    if len(given) > PRODUCTS_MAX:
        raise ValueError(f"at most {PRODUCTS_MAX} products are allowed")
    seen: set[str] = set()
    products: list[str] = []
    for value in given:
        name = required_text(value, max_length=PRODUCT_NAME_MAX)
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            products.append(name)
    return products


def check_target_date(value: date, *, today: date) -> date:
    """The target proposal date may not be in the past."""
    if value < today:
        raise ValueError("must not be in the past")
    return value
