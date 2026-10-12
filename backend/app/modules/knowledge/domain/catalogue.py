"""Catalogue rules (Story 3.1): kinds, statuses, field validation and the duplicate rule.
Pure, no I/O."""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

CODE_MAX = 40
NAME_MAX = 120
DEFINITION_MAX = 2000
REASON_MAX = 500
SUBJECT_TYPE = "knowledge.catalogue_entry"


class Kind(StrEnum):
    INTEGRATION_TYPE = "integration_type"
    WORK_PACKAGE = "work_package"


class Status(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


_LABELS = {Kind.INTEGRATION_TYPE: "Integration Type", Kind.WORK_PACKAGE: "Work Package"}


def kind_label(kind: Kind) -> str:
    return _LABELS[kind]


def duplicate_message(kind: Kind, field: str = "name") -> str:
    return f"An active {kind_label(kind)} with this {field} already exists"


def _bounded(value: str, label: str, maximum: int) -> str:
    trimmed = value.strip()
    if "\x00" in trimmed:
        raise ValueError(f"The {label} contains characters that can't be saved.")
    if not trimmed:
        raise ValueError(f"The {label} is required.")
    if len(trimmed) > maximum:
        raise ValueError(f"The {label} must be at most {maximum:,} characters.")
    return trimmed


def entry_code(value: str) -> str:
    return _bounded(value, "code", CODE_MAX)


def entry_name(value: str) -> str:
    return _bounded(value, "name", NAME_MAX)


def entry_definition(value: str) -> str:
    return _bounded(value, "definition", DEFINITION_MAX)


def retire_reason(value: str) -> str:
    return _bounded(value, "reason", REASON_MAX)


def same_text(a: str, b: str) -> bool:
    """Equal ignoring case (and surrounding space)."""
    return a.strip().casefold() == b.strip().casefold()


@dataclass(frozen=True, slots=True)
class ActiveEntry:
    """What the duplicate rule needs to know about an active entry of the same kind."""

    id: UUID
    code: str
    name: str


def duplicate_field(
    active: Iterable[ActiveEntry],
    *,
    code: str | None,
    name: str | None,
    ignore: UUID | None = None,
) -> str | None:
    """`"code"` or `"name"` for the part that equals (case-insensitively) the code or name of
    an active entry other than `ignore`; None if there is no clash. A part left None isn't
    checked."""
    for entry in active:
        if entry.id == ignore:
            continue
        if code is not None and same_text(code, entry.code):
            return "code"
        if name is not None and same_text(name, entry.name):
            return "name"
    return None


def is_duplicate(
    active: Iterable[ActiveEntry],
    *,
    code: str | None,
    name: str | None,
    ignore: UUID | None = None,
) -> bool:
    return duplicate_field(active, code=code, name=name, ignore=ignore) is not None
