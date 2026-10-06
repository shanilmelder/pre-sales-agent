"""Catalogue rules (Story 3.1): field validation and the duplicate rule. Pure."""

from collections.abc import Callable
from uuid import uuid4

import pytest

from app.modules.knowledge.domain.catalogue import (
    ActiveEntry,
    Kind,
    duplicate_message,
    entry_code,
    entry_definition,
    entry_name,
    is_duplicate,
    retire_reason,
)


def test_fields_are_trimmed() -> None:
    assert entry_code("  SAP-IDOC ") == "SAP-IDOC"
    assert entry_name("  SAP IDoc\n") == "SAP IDoc"


@pytest.mark.parametrize(
    ("rule", "limit"),
    [(entry_code, 40), (entry_name, 120), (entry_definition, 2000), (retire_reason, 500)],
)
def test_bounds(rule: Callable[[str], str], limit: int) -> None:
    assert rule("x" * limit) == "x" * limit
    with pytest.raises(ValueError, match="at most"):
        rule("x" * (limit + 1))
    with pytest.raises(ValueError, match="required"):
        rule("   ")


def test_length_counts_after_trimming() -> None:
    assert entry_code(" " + "x" * 40 + " ") == "x" * 40


def test_duplicate_messages_name_the_kind() -> None:
    assert duplicate_message(Kind.INTEGRATION_TYPE) == (
        "An active Integration Type with this name already exists"
    )
    assert duplicate_message(Kind.WORK_PACKAGE) == (
        "An active Work Package with this name already exists"
    )


def test_duplicate_by_name_or_code_ignores_case() -> None:
    other = ActiveEntry(uuid4(), "SAP", "SAP IDoc")
    assert is_duplicate([other], code="x", name="sap idoc")
    assert is_duplicate([other], code="sap", name="Other")
    assert not is_duplicate([other], code="Other", name="Other")


def test_duplicate_ignores_the_entry_itself_and_unchecked_parts() -> None:
    mine = ActiveEntry(uuid4(), "SAP", "SAP IDoc")
    assert not is_duplicate([mine], code=None, name="SAP IDoc", ignore=mine.id)
    assert not is_duplicate([mine], code=None, name=None)
