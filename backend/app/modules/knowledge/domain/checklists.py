"""Checklist rules (Story 3.4): domains, item kinds and impacts, field validation, the
publishable check and scope matching. Pure, no I/O.

A Checklist's draft may be incomplete (an item just added has no text yet), so saving a
draft checks lengths and shapes only; Publish then needs a name, at least one scope entry
(a product, the industry or an Integration Type), at least one item, and every item's text
and "why it matters". Products and the industry are free text, trimmed and compared ignoring
case, as Opportunities store them."""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.modules.knowledge.domain.catalogue import retire_reason as catalogue_retire_reason

SUBJECT_TYPE = "knowledge.checklist"
NAME_MAX = 200
PRODUCT_MAX = 100
PRODUCTS_MAX = 20
INDUSTRY_MAX = 100
TAGS_MAX = 50
ITEMS_MAX = 200
ITEM_TEXT_MAX = 2000
WHY_MAX = 2000
REASON_MAX = 500

NOT_PUBLISHABLE_MESSAGE = "A Checklist needs a scope tag and an item before it can be published."
INCOMPLETE_ITEM_MESSAGE = "Every item needs its text and why it matters before publishing."
RETIRED_TAG_MESSAGE = "A retired or unknown Integration Type can't be chosen."
RETIRED_AREA_MESSAGE = "A retired or unknown Integration Type or Work Package can't be chosen."
TOO_MANY_TAGS_MESSAGE = f"Choose at most {TAGS_MAX} Integration Types."
TOO_MANY_ITEMS_MESSAGE = f"A Checklist can have at most {ITEMS_MAX} items."
DUPLICATE_ITEM_MESSAGE = "An item appears twice in the draft."
UNKNOWN_ITEM_MESSAGE = "An item id doesn't belong to this Checklist."


class Domain(StrEnum):
    ENGINEERING = "engineering"
    DELIVERY = "delivery"
    SECURITY = "security"
    COMMERCIAL = "commercial"
    GENERAL = "general"


class ItemKind(StrEnum):
    QUESTION = "question"
    RISK = "risk"


class Impact(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Status(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


def _clean(value: str, label: str) -> str:
    trimmed = value.strip()
    if "\x00" in trimmed:
        raise ValueError(f"The {label} contains characters that can't be saved.")
    return trimmed


def _bounded(value: str, label: str, maximum: int) -> str:
    trimmed = _clean(value, label)
    if not trimmed:
        raise ValueError(f"The {label} is required.")
    if len(trimmed) > maximum:
        raise ValueError(f"The {label} must be at most {maximum:,} characters.")
    return trimmed


def _optional(value: str, label: str, maximum: int) -> str:
    """Trimmed text that may be blank (a draft item still being written)."""
    trimmed = _clean(value, label)
    if len(trimmed) > maximum:
        raise ValueError(f"The {label} must be at most {maximum:,} characters.")
    return trimmed


def checklist_name(value: str) -> str:
    return _bounded(value, "name", NAME_MAX)


def item_text(value: str) -> str:
    return _optional(value, "item text", ITEM_TEXT_MAX)


def why_it_matters(value: str) -> str:
    return _optional(value, "“why it matters”", WHY_MAX)


def retire_reason(value: str) -> str:
    return catalogue_retire_reason(value)


def normalize_products(values: Iterable[str]) -> list[str]:
    """Trim each product (1-100 characters) and drop case-insensitive repeats, keeping the
    first spelling. At most 20 (counted as given); none is fine."""
    given = list(values)
    if len(given) > PRODUCTS_MAX:
        raise ValueError(f"A Checklist can name at most {PRODUCTS_MAX} products.")
    seen: set[str] = set()
    products: list[str] = []
    for value in given:
        name = _bounded(value, "product", PRODUCT_MAX)
        key = match_key(name)
        if key not in seen:
            seen.add(key)
            products.append(name)
    return products


def normalize_industry(value: str | None) -> str | None:
    """The trimmed industry (at most 100 characters), or None when blank."""
    if value is None:
        return None
    trimmed = _clean(value, "industry")
    if not trimmed:
        return None
    if len(trimmed) > INDUSTRY_MAX:
        raise ValueError(f"The industry must be at most {INDUSTRY_MAX:,} characters.")
    return trimmed


def distinct_tags[T](tags: Iterable[T]) -> list[T]:
    """The tags without repeats, in order; none is fine (the products or industry may scope
    the Checklist). Raises `ValueError` when there are too many."""
    unique = list(dict.fromkeys(tags))
    if len(unique) > TAGS_MAX:
        raise ValueError(TOO_MANY_TAGS_MESSAGE)
    return unique


def match_key(value: str) -> str:
    """What scope matching compares: trimmed, case-folded."""
    return value.strip().casefold()


@dataclass(frozen=True, slots=True)
class DraftItem:
    id: UUID
    text: str
    why_it_matters: str


def publish_problem(
    *,
    products: list[str],
    industry: str | None,
    integration_type_ids: list[UUID],
    items: list[DraftItem],
) -> str | None:
    """The sentence saying why the draft can't be published, or None when it can."""
    if not (products or industry or integration_type_ids) or not items:
        return NOT_PUBLISHABLE_MESSAGE
    if any(not i.text.strip() or not i.why_it_matters.strip() for i in items):
        return INCOMPLETE_ITEM_MESSAGE
    return None


def check_item_ids(ids: list[UUID | None], known: set[UUID]) -> None:
    """Every given id is distinct and one of `known` (the draft's or a published version's);
    None marks a new item. Raises `ValueError` with the sentence to show."""
    given = [i for i in ids if i is not None]
    if len(set(given)) != len(given):
        raise ValueError(DUPLICATE_ITEM_MESSAGE)
    if any(i not in known for i in given):
        raise ValueError(UNKNOWN_ITEM_MESSAGE)


def scope_matches(
    *,
    products: Iterable[str],
    industry: str | None,
    integration_type_ids: Iterable[UUID],
    want_products: set[str],
    want_industry: str | None,
    want_types: set[UUID],
) -> bool:
    """True when the Checklist's scope shares a product, the industry or an Integration Type
    with what is asked. `want_products` and `want_industry` are `match_key`s."""
    if want_products and any(match_key(p) in want_products for p in products):
        return True
    if want_industry and industry is not None and match_key(industry) == want_industry:
        return True
    return bool(want_types) and any(t in want_types for t in integration_type_ids)
