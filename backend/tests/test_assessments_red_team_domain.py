"""Red Team Finding rules (Story 6.5): validation, severity order and counts. No DB."""

import pytest

from app.agents.red_team_agent.schema import CATEGORIES, SEVERITIES, RedTeamOutput
from app.modules.assessments.domain.reviews import (
    ARGUMENT_MAX,
    TITLE_MAX,
    FindingCandidate,
    FindingCategory,
    Severity,
    excerpt,
    severity_counts,
    severity_rank,
    validate_finding,
    validate_findings,
)

REQS = {"R1": "req-1", "R2": "req-2"}
LINES = {"L1": "line-1", "L2": "line-2"}


def candidate(**overrides: object) -> FindingCandidate:
    values: dict[str, object] = {
        "category": "integration_harder",
        "severity": "high",
        "title": "ERP custom fields — no evidence the connector supports them",
        "argument": "The connector's field list is not in the Requirements.",
        "requirements": ("R1",),
        "lines": (),
    }
    values.update(overrides)
    return FindingCandidate(**values)  # type: ignore[arg-type]


def test_a_valid_finding_is_trimmed_and_resolved() -> None:
    valid = validate_finding(
        candidate(
            title="  ERP custom fields  ",
            requirements=(" R2 ", "R99", "R2", "R1"),
            lines=("L2", "L99", "L2"),
        ),
        REQS,
        LINES,
    )

    assert valid is not None
    assert (valid.category, valid.severity) == (FindingCategory.INTEGRATION_HARDER, Severity.HIGH)
    assert valid.title == "ERP custom fields"
    assert valid.requirements == ("req-2", "req-1")
    assert valid.lines == ("line-2",)


@pytest.mark.parametrize(
    "overrides",
    [
        {"category": "vague"},
        {"severity": "urgent"},
        {"title": "   "},
        {"title": "x" * (TITLE_MAX + 1)},
        {"argument": ""},
        {"argument": "x" * (ARGUMENT_MAX + 1)},
        {"requirements": ("R99",)},
        {"requirements": ("G1", "L1")},
        {"requirements": ()},
    ],
)
def test_a_finding_breaking_a_rule_is_dropped(overrides: dict[str, object]) -> None:
    assert validate_finding(candidate(**overrides), REQS, LINES) is None


def test_the_limits_are_inclusive() -> None:
    valid = validate_finding(
        candidate(title="t" * TITLE_MAX, argument="a" * ARGUMENT_MAX), REQS, LINES
    )
    assert valid is not None


def test_unknown_lines_never_drop_a_finding() -> None:
    valid = validate_finding(candidate(lines=("L99",)), REQS, LINES)
    assert valid is not None and valid.lines == ()


def test_validate_findings_counts_the_dropped() -> None:
    validation = validate_findings(
        [candidate(), candidate(requirements=("R99",)), candidate(severity="?")], REQS, LINES
    )
    assert len(validation.findings) == 1
    assert validation.dropped == 2


def test_severities_rank_critical_first() -> None:
    ranked = sorted(["low", "critical", "medium", "high", "bogus"], key=severity_rank)
    assert ranked == ["critical", "high", "medium", "low", "bogus"]
    assert severity_counts([Severity.HIGH, Severity.HIGH, Severity.LOW]) == {
        Severity.CRITICAL: 0,
        Severity.HIGH: 2,
        Severity.MEDIUM: 0,
        Severity.LOW: 1,
    }


def test_the_schema_lists_the_domain_values_but_parses_any_string() -> None:
    assert set(CATEGORIES) == {c.value for c in FindingCategory}
    assert set(SEVERITIES) == {s.value for s in Severity}
    schema = RedTeamOutput.model_json_schema()
    props = schema["$defs"]["RedTeamFindingCandidate"]["properties"]
    assert props["category"]["enum"] == list(CATEGORIES)
    assert props["severity"]["enum"] == list(SEVERITIES)
    parsed = RedTeamOutput.model_validate(
        {
            "findings": [
                {
                    "category": "vague",
                    "severity": "urgent",
                    "title": "t",
                    "argument": "a",
                    "requirements": ["R1"],
                }
            ]
        }
    )
    assert parsed.findings[0].lines == []


def test_excerpts_are_cut_at_whitespace() -> None:
    assert excerpt("Short  text\n here") == "Short text here"
    long = "word " * 60
    cut = excerpt(long)
    assert len(cut) <= 140 and cut.endswith("…")
