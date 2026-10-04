"""Estimate rules and arithmetic (Stories 8.1 and 8.4): the demo template, line validation,
and the pure totals (with linked and unallocated Contingency), with property-based tests
(`hypothesis`) that every total is the sum of its parts."""

from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.modules.estimates.domain import arithmetic as ar
from app.modules.estimates.domain.estimates import (
    COLUMNS,
    DEMO_TEMPLATE,
    ROLES,
    SECTIONS,
    TEMPLATE_VERSION,
    EstimateRole,
    LineCandidate,
    Section,
    round_effort,
    section_rank,
    uncovered,
    valid_effort,
    valid_mix,
    validate_line,
    validate_lines,
)

D = Decimal
E, PM, QA = EstimateRole.ENGINEER, EstimateRole.PROJECT_MANAGER, EstimateRole.QA
REQS = {"R1": "a", "R2": "b", "R3": "c"}


def line(**overrides: Any) -> LineCandidate:
    fields: dict[str, Any] = {
        "section": "integration",
        "title": "SAP order interface",
        "covers": ("R1",),
        "effort_hours": 40.0,
        "role_mix": {"engineer": 70, "project_manager": 10, "qa": 20},
        "basis": "Two message types at 20 h each.",
    }
    fields.update(overrides)
    return LineCandidate(**fields)


# --- the template ---------------------------------------------------------------------------


def test_the_demo_template() -> None:
    assert TEMPLATE_VERSION == "demo-1"
    assert [s.value for s in SECTIONS] == [
        "functional",
        "integration",
        "data",
        "security",
        "non_functional",
        "commercial",
    ]
    assert [r.value for r in ROLES] == ["engineer", "project_manager", "qa"]
    assert COLUMNS == (
        "Line",
        "Covers",
        "Role mix (%)",
        "Effort (h)",
        "Contingency (h)",
        "Total (h)",
    )
    assert DEMO_TEMPLATE.version == TEMPLATE_VERSION
    assert section_rank("functional") == 0
    assert section_rank("commercial") == 5
    assert section_rank("nope") == 6


def test_sections_follow_the_requirement_classifications() -> None:
    from app.modules.intake.domain.requirements import Classification

    assert [s.value for s in Section] == [c.value for c in Classification]


# --- line rules -----------------------------------------------------------------------------


def test_a_valid_line() -> None:
    valid = validate_line(line(covers=("R2", " R1 ", "R2", "R99")), REQS)
    assert valid is not None
    assert valid.section is Section.INTEGRATION
    assert valid.covers == ("b", "a")
    assert valid.effort_hours == D("40.0")
    assert valid.role_mix == {E: 70, PM: 10, QA: 20}
    assert valid.title == "SAP order interface"


@pytest.mark.parametrize(
    "overrides",
    [
        {"section": "catalogue"},
        {"title": "  "},
        {"title": "x" * 161},
        {"basis": ""},
        {"basis": "x" * 501},
        {"covers": ("R99",)},
        {"covers": ()},
        {"effort_hours": 0.4},
        {"effort_hours": 2000.1},
        {"effort_hours": float("nan")},
        {"effort_hours": float("inf")},
        {"role_mix": {"engineer": 60, "project_manager": 20, "qa": 10}},  # sums to 90
        {"role_mix": {"engineer": 110, "project_manager": -10, "qa": 0}},
        {"role_mix": {"engineer": 100, "project_manager": 0}},
        {"role_mix": {"engineer": 50, "project_manager": 25, "qa": 25, "ux": 0}},
        {"role_mix": {"engineer": 50.5, "project_manager": 24.5, "qa": 25}},
        {"role_mix": {"engineer": True, "project_manager": 49, "qa": 50}},
    ],
)
def test_a_line_breaking_a_rule_is_invalid(overrides: dict[str, Any]) -> None:
    assert validate_line(line(**overrides), REQS) is None


def test_limits_are_inclusive_and_effort_is_rounded_to_a_tenth() -> None:
    assert validate_line(line(title="x" * 160, basis="y" * 500), REQS) is not None
    assert valid_effort(0.5) == D("0.5")
    assert valid_effort(2000) == D("2000.0")
    assert valid_effort(0.45) == D("0.5")  # rounds half up into range
    assert valid_effort(0.44) is None
    assert valid_effort(12.34) == D("12.3")
    assert valid_effort(12.35) == D("12.4")
    assert round_effort("x") is None
    assert round_effort(True) is None
    assert valid_mix({"engineer": 0, "project_manager": 0, "qa": 100}) == {E: 0, PM: 0, QA: 100}


def test_a_huge_finite_effort_drops_only_its_line() -> None:
    assert round_effort(1e30) is None
    validation = validate_lines([line(effort_hours=1e30), line()], REQS)
    assert len(validation.lines) == 1
    assert validation.dropped == 1


def test_invalid_lines_are_dropped_and_counted() -> None:
    validation = validate_lines(
        [
            line(),
            line(role_mix={"engineer": 60, "project_manager": 20, "qa": 10}),
            line(covers=("R99",)),
            line(section="data", covers=("R3",)),
        ],
        REQS,
    )
    assert [v.section for v in validation.lines] == [Section.INTEGRATION, Section.DATA]
    assert validation.dropped == 2


def test_uncovered_counts_the_active_requirements_no_line_covers() -> None:
    validation = validate_lines([line(covers=("R1", "R2"))], REQS)
    assert uncovered(validation.lines, ["a", "b", "c"]) == 1
    assert uncovered(validation.lines, ["a", "b"]) == 0
    assert uncovered((), ["a", "a"]) == 1


def test_the_line_hides_its_text_from_repr() -> None:
    candidate = line(title="[SECRET]", basis="[BASIS]")
    assert "[SECRET]" not in repr(candidate)
    assert "[BASIS]" not in repr(validate_line(candidate, REQS))


# --- arithmetic -----------------------------------------------------------------------------


def test_role_hours_use_the_largest_remainder() -> None:
    assert ar.role_hours(D("10.0"), {E: 33, PM: 33, QA: 34}) == {
        E: D("3.3"),
        PM: D("3.3"),
        QA: D("3.4"),
    }
    # 1.0 h at 33/33/34: 0.33, 0.33, 0.34 tenths-wise 3.3/3.3/3.4 → floors 3,3,3, one left
    # goes to the largest remainder (QA's .4).
    assert ar.role_hours(D("1.0"), {E: 33, PM: 33, QA: 34}) == {
        E: D("0.3"),
        PM: D("0.3"),
        QA: D("0.4"),
    }
    # Equal remainders: the earlier role wins.
    assert ar.role_hours(D("0.5"), {E: 50, PM: 50, QA: 0}) == {
        E: D("0.3"),
        PM: D("0.2"),
        QA: D("0.0"),
    }
    assert ar.role_hours(D("2000.0"), {E: 0, PM: 0, QA: 100})[QA] == D("2000.0")


def test_split_tenths_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="weights"):
        ar.split_tenths(10, [0, 0, 0])
    with pytest.raises(ValueError, match="weights"):
        ar.split_tenths(-1, [1])
    with pytest.raises(ValueError, match="multiple"):
        ar.to_tenths(D("0.05"))


def test_line_contingency_and_totals() -> None:
    assert ar.line_contingency([]) == D("0.0")
    assert ar.line_contingency([D("4.0"), D("1.5")]) == D("5.5")
    totals = ar.line_totals(
        ar.LineInput(Section.DATA, D("10.0"), {E: 33, PM: 33, QA: 34}, (D("2.5"),))
    )
    assert (totals.effort, totals.contingency, totals.total) == (D("10.0"), D("2.5"), D("12.5"))


def test_estimate_totals_per_section_role_and_overall() -> None:
    lines = [
        ar.LineInput(Section.INTEGRATION, D("40.0"), {E: 70, PM: 10, QA: 20}),
        ar.LineInput(Section.FUNCTIONAL, D("10.0"), {E: 33, PM: 33, QA: 34}),
        ar.LineInput(Section.INTEGRATION, D("8.5"), {E: 100, PM: 0, QA: 0}, (D("1.0"),)),
    ]
    totals = ar.estimate_totals(lines)
    assert list(totals.sections) == [Section.FUNCTIONAL, Section.INTEGRATION]
    integration = totals.sections[Section.INTEGRATION]
    assert (integration.effort, integration.contingency, integration.total) == (
        D("48.5"),
        D("1.0"),
        D("49.5"),
    )
    assert integration.role_hours == {E: D("36.5"), PM: D("4.0"), QA: D("8.0")}
    overall = totals.overall
    assert (overall.effort, overall.contingency, overall.total) == (
        D("58.5"),
        D("1.0"),
        D("59.5"),
    )
    assert overall.role_hours == {E: D("39.8"), PM: D("7.3"), QA: D("11.4")}
    empty = ar.estimate_totals([])
    assert empty.sections == {}
    assert (empty.overall.effort, empty.overall.total) == (D("0.0"), D("0.0"))
    assert empty.unallocated == D("0.0")


def test_unallocated_contingency_counts_in_the_overall_totals_only() -> None:
    lines = [
        ar.LineInput(Section.INTEGRATION, D("40.0"), {E: 70, PM: 10, QA: 20}, (D("8.0"),)),
        ar.LineInput(Section.FUNCTIONAL, D("10.0"), {E: 33, PM: 33, QA: 34}),
    ]
    totals = ar.estimate_totals(lines, [D("12.0"), D("0.5")])
    assert totals.unallocated == D("12.5")
    assert totals.sections[Section.INTEGRATION].contingency == D("8.0")
    assert totals.sections[Section.FUNCTIONAL].contingency == D("0.0")
    overall = totals.overall
    assert (overall.effort, overall.contingency, overall.total) == (
        D("50.0"),
        D("20.5"),
        D("70.5"),
    )
    assert sum(overall.role_hours.values(), D(0)) == overall.effort  # not split by role
    only = ar.estimate_totals([], [D("3.0")])
    assert (only.overall.contingency, only.overall.total) == (D("3.0"), D("3.0"))


# --- properties -----------------------------------------------------------------------------

efforts = st.integers(min_value=5, max_value=20_000).map(lambda t: ar.from_tenths(t))
amounts = st.integers(min_value=0, max_value=5_000).map(lambda t: ar.from_tenths(t))


@st.composite
def mixes(draw: st.DrawFn) -> dict[EstimateRole, int]:
    engineer = draw(st.integers(min_value=0, max_value=100))
    project_manager = draw(st.integers(min_value=0, max_value=100 - engineer))
    return {E: engineer, PM: project_manager, QA: 100 - engineer - project_manager}


line_inputs = st.builds(
    ar.LineInput,
    section=st.sampled_from(SECTIONS),
    effort=efforts,
    mix=mixes(),
    contingencies=st.lists(amounts, max_size=3).map(tuple),
)


@given(effort=efforts, mix=mixes())
def test_role_hours_always_sum_to_the_effort(effort: Decimal, mix: dict[EstimateRole, int]) -> None:
    hours = ar.role_hours(effort, mix)
    assert sum(hours.values(), D(0)) == effort
    for role in ROLES:
        exact = effort * mix[role] / 100
        assert abs(hours[role] - exact) < D("0.1")  # never off by a full tenth
        assert hours[role] >= 0
        assert hours[role] == hours[role].quantize(D("0.1"))


@given(lines=st.lists(line_inputs, max_size=25), unallocated=st.lists(amounts, max_size=5))
def test_totals_equal_the_sum_of_their_parts(
    lines: list[ar.LineInput], unallocated: list[Decimal]
) -> None:
    totals = ar.estimate_totals(lines, unallocated)

    for given_line, line_total in zip(lines, totals.lines, strict=True):
        assert line_total.contingency == sum(given_line.contingencies, D(0))
        assert line_total.total == line_total.effort + line_total.contingency
        assert sum(line_total.role_hours.values(), D(0)) == line_total.effort

    for section, subtotal in totals.sections.items():
        members = [t for g, t in zip(lines, totals.lines, strict=True) if g.section == section]
        assert members
        assert subtotal.effort == sum((t.effort for t in members), D(0))
        assert subtotal.contingency == sum((t.contingency for t in members), D(0))
        assert subtotal.total == subtotal.effort + subtotal.contingency
        for role in ROLES:
            assert subtotal.role_hours[role] == sum((t.role_hours[role] for t in members), D(0))
    assert set(totals.sections) == {g.section for g in lines}
    assert list(totals.sections) == sorted(totals.sections, key=SECTIONS.index)

    assert totals.unallocated == sum(unallocated, D(0))
    overall = totals.overall
    assert overall.effort == sum((g.effort for g in lines), D(0))
    assert overall.effort == sum((s.effort for s in totals.sections.values()), D(0))
    assert overall.contingency == (
        sum((s.contingency for s in totals.sections.values()), D(0)) + totals.unallocated
    )
    assert overall.contingency == (
        sum((c for g in lines for c in g.contingencies), D(0)) + sum(unallocated, D(0))
    )
    assert overall.total == (
        sum((s.total for s in totals.sections.values()), D(0)) + totals.unallocated
    )
    assert overall.total == overall.effort + overall.contingency
    assert sum(overall.role_hours.values(), D(0)) == overall.effort
    for role in ROLES:
        assert overall.role_hours[role] == sum(
            (s.role_hours[role] for s in totals.sections.values()), D(0)
        )
