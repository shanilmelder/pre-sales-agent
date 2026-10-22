"""Checklist rules (Story 3.4): field rules, the publishable check, item ids and scope
matching. Pure."""

from uuid import uuid4

import pytest

from app.modules.knowledge.domain import checklists as rules
from app.modules.knowledge.domain.checklists import DraftItem


def test_name_is_trimmed_and_bounded() -> None:
    assert rules.checklist_name("  Security baseline ") == "Security baseline"
    for bad in ("", "   ", "x" * 201, "a\x00b"):
        with pytest.raises(ValueError):
            rules.checklist_name(bad)


def test_products_are_trimmed_and_deduplicated_ignoring_case() -> None:
    assert rules.normalize_products([" AutoStore ", "autostore", "SAP", "AUTOSTORE"]) == [
        "AutoStore",
        "SAP",
    ]
    assert rules.normalize_products([]) == []
    with pytest.raises(ValueError):
        rules.normalize_products(["  "])
    with pytest.raises(ValueError):
        rules.normalize_products([f"P{i}" for i in range(21)])


def test_industry_is_optional() -> None:
    assert rules.normalize_industry(None) is None
    assert rules.normalize_industry("   ") is None
    assert rules.normalize_industry(" Retail ") == "Retail"
    with pytest.raises(ValueError):
        rules.normalize_industry("x" * 101)


def test_draft_items_may_be_blank_but_not_too_long() -> None:
    assert rules.item_text("  ") == ""
    assert rules.why_it_matters(" Because ") == "Because"
    with pytest.raises(ValueError):
        rules.item_text("x" * 2001)


def test_publish_needs_a_scope_entry_and_a_complete_item() -> None:
    item = DraftItem(id=uuid4(), text="Q?", why_it_matters="It matters")
    type_id = uuid4()
    assert (
        rules.publish_problem(products=[], industry=None, integration_type_ids=[], items=[item])
        == rules.NOT_PUBLISHABLE_MESSAGE
    )
    assert (
        rules.publish_problem(products=["P"], industry=None, integration_type_ids=[], items=[])
        == rules.NOT_PUBLISHABLE_MESSAGE
    )
    for scope in (
        {"products": ["P"], "industry": None, "integration_type_ids": []},
        {"products": [], "industry": "Retail", "integration_type_ids": []},
        {"products": [], "industry": None, "integration_type_ids": [type_id]},
    ):
        assert rules.publish_problem(**scope, items=[item]) is None  # type: ignore[arg-type]
    blank = DraftItem(id=uuid4(), text="Q?", why_it_matters=" ")
    assert (
        rules.publish_problem(
            products=["P"], industry=None, integration_type_ids=[], items=[item, blank]
        )
        == rules.INCOMPLETE_ITEM_MESSAGE
    )


def test_item_ids_must_be_distinct_and_known() -> None:
    a, b = uuid4(), uuid4()
    rules.check_item_ids([a, None, None, b], {a, b})
    with pytest.raises(ValueError, match="twice"):
        rules.check_item_ids([a, a], {a})
    with pytest.raises(ValueError, match="belong"):
        rules.check_item_ids([uuid4()], {a})


def test_scope_matching_is_any_of_trimmed_and_case_insensitive() -> None:
    t1, t2 = uuid4(), uuid4()

    def matches(**want: object) -> bool:
        return rules.scope_matches(
            products=["AutoStore", "SAP"],
            industry="Retail",
            integration_type_ids=[t1],
            want_products=want.get("products", set()),  # type: ignore[arg-type]
            want_industry=want.get("industry"),  # type: ignore[arg-type]
            want_types=want.get("types", set()),  # type: ignore[arg-type]
        )

    assert matches(products={rules.match_key("  autostore ")})
    assert matches(industry=rules.match_key(" RETAIL"))
    assert matches(types={t2, t1})
    assert not matches(products={"other"}, industry="banking", types={t2})
    assert not matches()


def test_retire_reason_is_one_to_five_hundred_characters() -> None:
    assert rules.retire_reason(" Superseded ") == "Superseded"
    for bad in ("", "x" * 501):
        with pytest.raises(ValueError):
            rules.retire_reason(bad)
