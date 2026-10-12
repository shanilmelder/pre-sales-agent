"""Opportunity import rules (Story 1.7, import from file). Pure, no I/O.

An import is one uploaded file whose text the worker reads to suggest the New Opportunity
form's fields. Every suggestion the model proposes passes the form's own field rules
(`domain.opportunity`) and carries a quote that must appear in the file's text, or it is
dropped: a field the text doesn't support stays empty.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from app.modules.opportunities.domain.opportunity import (
    CUSTOMER_NAME_MAX,
    INDUSTRY_MAX,
    PRODUCT_NAME_MAX,
    check_target_date,
    optional_title,
    required_text,
)

IMPORT_TTL = timedelta(hours=24)
"""How long an import can be used to create an Opportunity."""
IMPORT_PRODUCTS_MAX = 5
QUOTE_MAX = 300
"""The longest quote kept (characters, once trimmed); a longer one drops its suggestion."""
QUOTE_MIN = 3
"""The fewest non-space characters a quote needs; a shorter one drops its suggestion."""
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ImportStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


IN_PROGRESS = frozenset({ImportStatus.QUEUED, ImportStatus.RUNNING})


class ImportErrorCode(StrEnum):
    UNREADABLE = "unreadable"
    """The file couldn't be turned into text (corrupt, no text, unsupported, too slow)."""
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_TIMEOUT = "model_timeout"
    OUTPUT_INVALID = "output_invalid"


@dataclass(frozen=True, slots=True)
class Candidate:
    """One field as the model proposed it, unchecked."""

    value: str | None
    quote: str | None


@dataclass(frozen=True, slots=True)
class Suggestion:
    """A checked suggestion and the quote it came from."""

    value: str
    quote: str


@dataclass(frozen=True, slots=True)
class Suggestions:
    title: Suggestion | None = None
    customer_name: Suggestion | None = None
    industry: Suggestion | None = None
    products: tuple[Suggestion, ...] = ()
    target_proposal_date: Suggestion | None = None
    industry_inferred: bool = False
    """The industry isn't named in the file but inferred from what the customer does."""


def is_expired(created_at: datetime, now: datetime) -> bool:
    return now - created_at >= IMPORT_TTL


def _squash(text: str) -> str:
    """Whitespace runs as one space, case folded: how quotes are matched against the text."""
    return " ".join(text.split()).casefold()


def _quote(quote: str | None, squashed_text: str) -> str | None:
    """The trimmed quote when it is short enough and appears in the text, else None."""
    if quote is None:
        return None
    trimmed = " ".join(quote.split())
    if len("".join(trimmed.split())) < QUOTE_MIN or len(trimmed) > QUOTE_MAX:
        return None
    if trimmed.casefold() not in squashed_text:
        return None
    return trimmed


def _text_field(candidate: Candidate, squashed_text: str, max_length: int) -> Suggestion | None:
    if candidate.value is None:
        return None
    quote = _quote(candidate.quote, squashed_text)
    if quote is None:
        return None
    try:
        value = required_text(candidate.value, max_length=max_length)
    except ValueError:
        return None
    return Suggestion(value=value, quote=quote)


def _customer(candidate: Candidate, squashed_text: str) -> Suggestion | None:
    """The customer must also be named in its own quote: a real sentence about something
    else doesn't support it."""
    suggestion = _text_field(candidate, squashed_text, CUSTOMER_NAME_MAX)
    if suggestion is None or _squash(suggestion.value) not in _squash(suggestion.quote):
        return None
    return suggestion


def _title(candidate: Candidate, squashed_text: str) -> Suggestion | None:
    if candidate.value is None:
        return None
    quote = _quote(candidate.quote, squashed_text)
    if quote is None:
        return None
    try:
        value = optional_title(candidate.value)
    except ValueError:
        return None
    return None if value is None else Suggestion(value=value, quote=quote)


def _target_date(candidate: Candidate, squashed_text: str, today: date) -> Suggestion | None:
    if candidate.value is None or not _DATE_RE.match(candidate.value.strip()):
        return None
    quote = _quote(candidate.quote, squashed_text)
    if quote is None:
        return None
    try:
        value = check_target_date(date.fromisoformat(candidate.value.strip()), today=today)
    except ValueError:  # not a calendar date, or in the past
        return None
    return Suggestion(value=value.isoformat(), quote=quote)


def _products(candidates: Iterable[Candidate], squashed_text: str) -> tuple[Suggestion, ...]:
    seen: set[str] = set()
    kept: list[Suggestion] = []
    for candidate in candidates:
        suggestion = _text_field(candidate, squashed_text, PRODUCT_NAME_MAX)
        if suggestion is None or suggestion.value.casefold() in seen:
            continue
        seen.add(suggestion.value.casefold())
        kept.append(suggestion)
        if len(kept) == IMPORT_PRODUCTS_MAX:
            break
    return tuple(kept)


def validate_suggestions(
    *,
    title: Candidate,
    customer_name: Candidate,
    industry: Candidate,
    products: Iterable[Candidate],
    target_proposal_date: Candidate,
    text: str,
    today: date,
    industry_inferred: bool = False,
) -> Suggestions:
    """The suggestions that pass the New Opportunity form's rules and quote the text (a quote
    of at least 3 non-space characters; the customer named in its quote): text is
    trimmed and within its limit, products are de-duplicated ignoring case and at most 5, the
    date is `YYYY-MM-DD` and not before `today`. Anything else is dropped (left empty).

    The industry may be inferred from what the customer does (its quote must still be real
    text from the file, but needn't contain the value). It is marked inferred when the model
    says so, or whenever its value doesn't appear in its quote, so the form never presents
    an inferred label as quoted."""
    squashed = _squash(text)
    industry_suggestion = _text_field(industry, squashed, INDUSTRY_MAX)
    inferred = industry_suggestion is not None and (
        industry_inferred
        or _squash(industry_suggestion.value) not in _squash(industry_suggestion.quote)
    )
    return Suggestions(
        title=_title(title, squashed),
        customer_name=_customer(customer_name, squashed),
        industry=industry_suggestion,
        products=_products(products, squashed),
        target_proposal_date=_target_date(target_proposal_date, squashed, today),
        industry_inferred=inferred,
    )


def suggestion_count(suggestions: Suggestions) -> int:
    """How many fields were suggested (products count once each)."""
    singles = (
        suggestions.title,
        suggestions.customer_name,
        suggestions.industry,
        suggestions.target_proposal_date,
    )
    return sum(1 for s in singles if s is not None) + len(suggestions.products)
