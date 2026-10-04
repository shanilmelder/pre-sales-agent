"""Assumption proposal rules (Story 8.4): one proposal per open Gap, a Condition without
hours, a Contingency with 0.5-1,000 h rounded to 0.1, an optional line of the version; and
the line a carried Contingency links to in a re-draft (Story 8.7). Pure."""

from decimal import Decimal
from typing import Any

import pytest

from app.modules.estimates.domain.assumptions import (
    AssumptionKind,
    ProposalCandidate,
    carried_line,
    valid_hours,
    validate_proposal,
    validate_proposals,
)

GAPS = {"G1": "gap-1", "G2": "gap-2", "G3": "gap-3"}
LINES = {"L1": "line-1", "L2": "line-2"}


def cand(**overrides: Any) -> ProposalCandidate:
    fields: dict[str, Any] = {
        "gap": "G2",
        "kind": "contingency",
        "wording": "Contingency for up to three more message types.",
        "hours": 8,
        "line": "L2",
    }
    fields.update(overrides)
    return ProposalCandidate(**fields)


def test_a_valid_contingency_and_condition() -> None:
    kept = validate_proposal(cand(hours=7.96), GAPS, LINES)
    assert kept is not None
    assert (kept.gap, kept.kind, kept.hours, kept.line) == (
        "gap-2",
        AssumptionKind.CONTINGENCY,
        Decimal("8.0"),
        "line-2",
    )
    condition = validate_proposal(
        cand(kind="condition", hours=None, line=None, wording="  The estimate assumes X.  "),
        GAPS,
        LINES,
    )
    assert condition is not None
    assert (condition.kind, condition.hours, condition.line, condition.wording) == (
        AssumptionKind.CONDITION,
        None,
        None,
        "The estimate assumes X.",
    )
    unlinked = validate_proposal(cand(line=None), GAPS, LINES)
    assert unlinked is not None and unlinked.line is None
    assert validate_proposal(cand(line=" "), GAPS, LINES) is not None


def test_a_condition_ignores_a_line() -> None:
    kept = validate_proposal(cand(kind="condition", hours=None, line="L9"), GAPS, LINES)
    assert kept is not None and kept.line is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"gap": "G9"},
        {"gap": "R1"},
        {"kind": "risk"},
        {"wording": ""},
        {"wording": "   "},
        {"wording": "x" * 501},
        {"kind": "condition", "hours": 4},
        {"kind": "condition", "hours": 0},
        {"hours": None},
        {"hours": 0.44},
        {"hours": 1000.05},
        {"hours": float("nan")},
        {"hours": float("inf")},
        {"line": "L9"},
    ],
)
def test_a_proposal_breaking_a_rule_is_invalid(overrides: dict[str, Any]) -> None:
    assert validate_proposal(cand(**overrides), GAPS, LINES) is None


def test_limits_are_inclusive() -> None:
    assert valid_hours(0.45) == Decimal("0.5")
    assert valid_hours(1000) == Decimal("1000.0")
    assert valid_hours(1000.04) == Decimal("1000.0")
    assert valid_hours(1e30) is None
    assert validate_proposal(cand(wording="x" * 500), GAPS, LINES) is not None


def test_one_proposal_per_gap_and_the_missing_gaps() -> None:
    result = validate_proposals(
        [
            cand(gap="G2"),
            cand(gap="G2", hours=3),  # a duplicate
            cand(gap="G1", kind="condition", hours=None, line=None),
            cand(gap="G3", hours=None),  # invalid
            cand(gap="G9"),  # invalid
        ],
        GAPS,
        LINES,
    )
    assert [p.gap for p in result.proposals] == ["gap-2", "gap-1"]
    assert result.proposals[0].hours == Decimal("8.0")
    assert (result.dropped, result.duplicates) == (2, 1)
    assert result.missing == ("gap-3",)
    empty = validate_proposals([], GAPS, LINES)
    assert empty.missing == ("gap-1", "gap-2", "gap-3")
    assert validate_proposals([], {}, LINES).missing == ()


def test_the_proposal_hides_its_wording_from_repr() -> None:
    assert "message types" not in repr(cand())


NEW_LINES = [
    ("a", "integration", "WMS interface"),
    ("b", "integration", "SAP interface"),
    ("c", "functional", "WMS interface"),
    ("d", "commercial", "Training"),
    ("e", "commercial", " training "),
]


@pytest.mark.parametrize(
    ("section", "title", "expected"),
    [
        ("integration", "WMS interface", "a"),
        ("integration", "  wms INTERFACE ", "a"),  # trimmed, case-insensitive
        ("functional", "WMS interface", "c"),  # the section counts
        ("security", "WMS interface", None),  # no line in that section
        ("integration", "WMS interfaces", None),  # not the same title
        ("commercial", "Training", None),  # two lines match
    ],
)
def test_a_carried_contingency_links_to_the_one_matching_line(
    section: str, title: str, expected: str | None
) -> None:
    assert carried_line(section, title, NEW_LINES) == expected
