"""Knowledge Source rules (Story 3.2): the file allowlist, field validation, the derived
stale flag and the rejection sentences. Pure, no I/O.

A Source's last-reviewed date is stored; whether it is stale is not: it is computed from
the date, today and `PSA_KNOWLEDGE_STALE_MONTHS`."""

import calendar
from datetime import date
from enum import StrEnum

from app.platform.upload_validation import extension

SUBJECT_TYPE = "knowledge.source"
TITLE_MAX = 200
PRODUCT_MAX = 120
PRODUCT_VERSION_MAX = 60
REASON_MAX = 500
TAGS_MAX = 50

ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".pdf", ".docx", ".txt", ".md"})
"""The Knowledge Source file types; `.md` is Knowledge-only."""

NO_TAGS_MESSAGE = "Choose at least one Integration Type."
TOO_MANY_TAGS_MESSAGE = f"Choose at most {TAGS_MAX} Integration Types."
RETIRED_TAG_MESSAGE = "A retired or unknown Integration Type can't be chosen."


class Status(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


def allowed(filename: str) -> bool:
    """True when the file's extension is one a Knowledge Source may have."""
    return extension(filename) in ALLOWED_EXTENSIONS


def _bounded(value: str, label: str, maximum: int) -> str:
    trimmed = value.strip()
    if "\x00" in trimmed:
        raise ValueError(f"The {label} contains characters that can't be saved.")
    if not trimmed:
        raise ValueError(f"The {label} is required.")
    if len(trimmed) > maximum:
        raise ValueError(f"The {label} must be at most {maximum:,} characters.")
    return trimmed


def source_title(value: str) -> str:
    return _bounded(value, "title", TITLE_MAX)


def source_product(value: str) -> str:
    return _bounded(value, "product", PRODUCT_MAX)


def product_version(value: str) -> str:
    return _bounded(value, "product version", PRODUCT_VERSION_MAX)


def retire_reason(value: str) -> str:
    return _bounded(value, "reason", REASON_MAX)


def distinct_tags[T](tags: list[T]) -> list[T]:
    """The tags without repeats, in order. Raises `ValueError` (the sentence to show) when
    none are left or there are too many."""
    unique = list(dict.fromkeys(tags))
    if not unique:
        raise ValueError(NO_TAGS_MESSAGE)
    if len(unique) > TAGS_MAX:
        raise ValueError(TOO_MANY_TAGS_MESSAGE)
    return unique


def subtract_months(today: date, months: int) -> date:
    """`today` minus whole calendar months, clamped to the month's last day."""
    index = today.year * 12 + (today.month - 1) - months
    year, month = divmod(index, 12)
    month += 1
    day = min(today.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def stale_cutoff(today: date, months: int) -> date:
    """Sources last reviewed before this date are stale."""
    return subtract_months(today, months)


def is_stale(last_reviewed_on: date, today: date, months: int) -> bool:
    """True when the Source was last reviewed more than `months` months before `today`."""
    return last_reviewed_on < stale_cutoff(today, months)
