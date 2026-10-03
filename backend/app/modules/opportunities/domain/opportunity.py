"""Opportunity domain rules (Story 1.7). Pure, no I/O.

Field rules are checked when a new Opportunity is built (`NewOpportunity` in the
application layer calls these), so every path that creates one applies them.
"""

from collections.abc import Iterable
from datetime import date
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


def derived_status() -> OpportunityStatus:
    """The status of an Opportunity. Nothing after intake exists yet (sources, gaps,
    assessments and estimates arrive in later epics), so every Opportunity is `intake`."""
    return OpportunityStatus.INTAKE


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
