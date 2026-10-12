"""The Conflict rules (Story 6.1): pure, without DB or LLM. Rule (a) scope, (b) the
recommendation clash, (c) agents vs Estimate with the 30% boundary, and the reason a
Conflict is no longer present."""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.modules.conflicts.domain import rules
from app.modules.conflicts.domain.conflicts import (
    ConflictSeverity,
    ConflictType,
    PositionSource,
    excerpt,
    hours_label,
)
from app.modules.conflicts.domain.resolution import StoredPosition, no_longer_present_reason
from app.modules.conflicts.domain.rules import (
    ActiveRequirement,
    AssessmentSnapshot,
    EffortSnapshot,
    EstimateLineSnapshot,
    EstimateSnapshot,
    RuleInputs,
    effort,
    recommendation,
    scope,
)

R = [UUID(int=n) for n in range(1, 6)]
REQUIREMENTS = [ActiveRequirement(id=r, version=1) for r in R]


def agent(
    name: str,
    *hours: tuple[UUID, float],
    recommendation: str = "proceed_with_conditions",
    version: int = 1,
) -> AssessmentSnapshot:
    return AssessmentSnapshot(
        assessment_id=uuid4(),
        agent=name,
        version=version,
        recommendation=recommendation,
        effort=tuple(EffortSnapshot(r, 1, Decimal(str(h))) for r, h in hours),
    )


def estimate(*lines: tuple[float, tuple[UUID, ...]], version: int = 3) -> EstimateSnapshot:
    return EstimateSnapshot(
        version_id=uuid4(),
        version=version,
        lines=tuple(EstimateLineSnapshot(Decimal(str(h)), ids) for h, ids in lines),
    )


def inputs(
    *assessments: AssessmentSnapshot,
    estimate: EstimateSnapshot | None = None,
    requirements: list[ActiveRequirement] | None = None,
) -> RuleInputs:
    return RuleInputs(
        assessments=list(assessments),
        estimate=estimate,
        requirements=REQUIREMENTS if requirements is None else requirements,
    )


# --- display helpers ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "label"),
    [("24", "24 h"), ("24.0", "24 h"), ("24.25", "24.3 h"), ("0.5", "0.5 h"), ("130", "130 h")],
)
def test_hours_read_to_a_tenth_without_a_trailing_zero(value: str, label: str) -> None:
    assert hours_label(Decimal(value)) == label


def test_an_excerpt_is_cut_at_whitespace() -> None:
    assert excerpt("Connect   to\nSAP.") == "Connect to SAP."
    cut = excerpt("word " * 60)
    assert len(cut) <= 140 and cut.endswith("…")


# --- (a) scope ------------------------------------------------------------------------------


def test_engineering_sizes_a_requirement_pm_does_not() -> None:
    eng = agent("engineering_agent", (R[3], 24))
    pm = agent("pm_agent", (R[0], 8))

    found = scope.detect(inputs(eng, pm))

    assert [c.fingerprint for c in found] == [
        f"scope:{R[0]}:engineering_agent+pm_agent",
        f"scope:{R[3]}:engineering_agent+pm_agent",
    ]
    r4 = found[1]
    assert (r4.type, r4.severity, r4.rule) == (ConflictType.SCOPE, ConflictSeverity.MEDIUM, "scope")
    assert r4.summary == "Engineering sizes this Requirement; PM does not."
    assert [(p.agent, p.summary, p.value) for p in r4.positions] == [
        ("engineering_agent", "24 h", Decimal("24.0")),
        ("pm_agent", "Not sized", None),
    ]
    assert all(p.source == PositionSource.ASSESSMENT for p in r4.positions)
    assert [(p.assessment_id, p.assessment_version) for p in r4.positions] == [
        (eng.assessment_id, 1),
        (pm.assessment_id, 1),
    ]
    assert {(p.requirement_id, p.requirement_version) for p in r4.positions} == {(R[3], 1)}


def test_both_sizing_or_neither_is_no_scope_conflict() -> None:
    eng = agent("engineering_agent", (R[0], 24), (R[1], 4))
    pm = agent("pm_agent", (R[0], 8), (R[1], 1))
    assert scope.detect(inputs(eng, pm)) == []


def test_scope_needs_both_agents_to_have_an_assessment() -> None:
    eng = agent("engineering_agent", (R[3], 24))
    assert scope.detect(inputs(eng)) == []
    assert scope.detect(inputs(eng, agent("security_agent"))) == []


def test_scope_ignores_requirements_no_longer_active() -> None:
    eng = agent("engineering_agent", (R[3], 24))
    pm = agent("pm_agent")
    assert scope.detect(inputs(eng, pm, requirements=REQUIREMENTS[:3])) == []


# --- (b) recommendation clash ---------------------------------------------------------------


def test_proceed_against_do_not_proceed_is_one_high_assumption_conflict() -> None:
    eng = agent("engineering_agent", recommendation="proceed")
    pm = agent("pm_agent", recommendation="proceed_with_conditions")
    sec = agent("security_agent", recommendation="do_not_proceed")

    (found,) = recommendation.detect(inputs(sec, eng, pm))

    assert (found.type, found.severity, found.fingerprint) == (
        ConflictType.ASSUMPTION,
        ConflictSeverity.HIGH,
        "recommendation_clash",
    )
    assert [(p.agent, p.summary, p.value, p.requirement_id) for p in found.positions] == [
        ("engineering_agent", "Proceed", None, None),
        ("pm_agent", "Proceed with conditions", None, None),
        ("security_agent", "Do not proceed", None, None),
    ]


@pytest.mark.parametrize(
    "recommendations",
    [
        ("proceed", "proceed", "proceed_with_conditions"),
        ("do_not_proceed", "proceed_with_conditions", "do_not_proceed"),
        ("proceed",),
    ],
)
def test_no_clash_without_both_extremes(recommendations: tuple[str, ...]) -> None:
    agents = ("engineering_agent", "pm_agent", "security_agent")
    snapshots = [agent(a, recommendation=r) for a, r in zip(agents, recommendations, strict=False)]
    assert recommendation.detect(inputs(*snapshots)) == []


# --- (c) agents vs Estimate -----------------------------------------------------------------


@pytest.mark.parametrize(("estimated", "conflict"), [(130, False), (131, True), (70, False)])
def test_more_than_30_percent_apart_is_an_effort_conflict(estimated: float, conflict: bool) -> None:
    eng = agent("engineering_agent", (R[1], 60))
    pm = agent("pm_agent", (R[1], 40))
    found = effort.detect(inputs(eng, pm, estimate=estimate((estimated, (R[1],)))))
    assert bool(found) is conflict


def test_below_70_percent_is_an_effort_conflict_too() -> None:
    eng = agent("engineering_agent", (R[1], 100))
    assert effort.detect(inputs(eng, estimate=estimate((69.9, (R[1],))))) != []


def test_an_effort_conflict_has_agent_positions_and_the_estimate() -> None:
    eng = agent("engineering_agent", (R[1], 60))
    pm = agent("pm_agent", (R[1], 40))
    sec = agent("security_agent")
    est = estimate((131, (R[1],)))

    (found,) = effort.detect(inputs(sec, pm, eng, estimate=est))

    assert (found.type, found.severity, found.fingerprint) == (
        ConflictType.EFFORT,
        ConflictSeverity.MEDIUM,
        f"effort:{R[1]}",
    )
    assert [(p.source, p.agent, p.summary, p.value) for p in found.positions] == [
        (PositionSource.ASSESSMENT, "engineering_agent", "60 h", Decimal("60.0")),
        (PositionSource.ASSESSMENT, "pm_agent", "40 h", Decimal("40.0")),
        (PositionSource.ESTIMATE, None, "131 h", Decimal("131.0")),
    ]
    estimate_position = found.positions[-1]
    assert (estimate_position.estimate_version_id, estimate_position.estimate_version) == (
        est.version_id,
        3,
    )
    assert estimate_position.assessment_id is None
    assert found.summary == (
        "The Estimate allocates 131 h to this Requirement; the agents size it at 100 h."
    )


def test_a_shared_line_is_split_equally_among_the_active_requirements_it_covers() -> None:
    eng = agent("engineering_agent", (R[0], 10), (R[1], 10))
    # 30 h over R1, R2 and an inactive Requirement: 15 h each for R1 and R2 (> 13 h).
    inactive = uuid4()
    est = estimate((30, (R[0], R[1], inactive)))
    found = effort.detect(inputs(eng, estimate=est))
    assert [c.fingerprint for c in found] == [f"effort:{R[0]}", f"effort:{R[1]}"]
    assert found[0].positions[-1].value == Decimal("15.0")
    # 26 h shared: 13 h each, exactly 30% above 10 h: no Conflict.
    assert effort.detect(inputs(eng, estimate=estimate((26, (R[0], R[1]))))) == []


def test_allocation_sums_every_line_covering_the_requirement() -> None:
    allocated = effort.allocated_hours(
        estimate((10, (R[0],)), (9, (R[0], R[1], R[2])), (5, ())), set(R)
    )
    assert allocated == {R[0]: 13, R[1]: 3, R[2]: 3}


def test_no_estimate_or_zero_on_either_side_raises_nothing() -> None:
    eng = agent("engineering_agent", (R[1], 60))
    assert effort.detect(inputs(eng)) == []
    assert effort.detect(inputs(eng, estimate=estimate((50, (R[0],))))) == []  # E = 0
    assert effort.detect(inputs(agent("pm_agent"), estimate=estimate((50, (R[1],))))) == []


# --- all rules ------------------------------------------------------------------------------


def test_agreeing_assessments_raise_nothing() -> None:
    eng = agent("engineering_agent", (R[0], 20), recommendation="proceed")
    pm = agent("pm_agent", (R[0], 10), recommendation="proceed")
    sec = agent("security_agent", recommendation="proceed_with_conditions")
    assert rules.detect(inputs(eng, pm, sec, estimate=estimate((32, (R[0],))))) == []


def test_every_rule_runs_and_the_estimate_is_optional() -> None:
    eng = agent("engineering_agent", (R[3], 24), recommendation="proceed")
    pm = agent("pm_agent", recommendation="do_not_proceed")
    without = rules.detect(inputs(eng, pm))
    assert [c.rule for c in without] == ["scope", "recommendation_clash"]
    with_estimate = rules.detect(inputs(eng, pm, estimate=estimate((100, (R[3],)))))
    assert [c.rule for c in with_estimate] == ["scope", "recommendation_clash", "effort"]
    assert rules.rule_of(with_estimate[0].fingerprint) == "scope"


# --- no longer present ----------------------------------------------------------------------


def _stored(candidate: rules.ConflictCandidate) -> list[StoredPosition]:
    return [
        StoredPosition(
            source=p.source,
            agent=p.agent,
            assessment_version=p.assessment_version,
            estimate_version=p.estimate_version,
            requirement_id=p.requirement_id,
            summary=p.summary,
        )
        for p in candidate.positions
    ]


def test_the_reason_names_the_agent_whose_position_changed() -> None:
    (before,) = scope.detect(inputs(agent("engineering_agent", (R[3], 24)), agent("pm_agent")))
    later = inputs(
        agent("engineering_agent", (R[3], 24), version=2),
        agent("pm_agent", (R[3], 16), version=2),
    )
    assert before.fingerprint not in {c.fingerprint for c in scope.detect(later)}
    reason = no_longer_present_reason(before.fingerprint, _stored(before), later)
    assert reason == "No longer present in PM Assessment v2"


def test_the_reason_names_the_estimate_when_it_changed() -> None:
    eng = agent("engineering_agent", (R[1], 100))
    (before,) = effort.detect(inputs(eng, estimate=estimate((131, (R[1],)))))
    later = inputs(eng, estimate=estimate((120, (R[1],)), version=4))
    assert effort.detect(later) == []
    assert no_longer_present_reason(before.fingerprint, _stored(before), later) == (
        "No longer present in Estimate v4"
    )


def test_the_reason_names_every_changed_agent_of_a_clash() -> None:
    eng = agent("engineering_agent", recommendation="proceed")
    sec = agent("security_agent", recommendation="do_not_proceed")
    (before,) = recommendation.detect(inputs(eng, sec))
    later = inputs(eng, agent("security_agent", recommendation="proceed", version=2))
    assert no_longer_present_reason(before.fingerprint, _stored(before), later) == (
        "No longer present in Security Assessment v2"
    )


def test_without_a_changed_position_the_reason_names_newer_versions() -> None:
    eng = agent("engineering_agent", (R[3], 24))
    pm = agent("pm_agent")
    (before,) = scope.detect(inputs(eng, pm))
    # R4 is no longer active; the agents re-ran with the same positions.
    later = inputs(
        agent("engineering_agent", (R[3], 24), version=2),
        agent("pm_agent"),
        requirements=REQUIREMENTS[:3],
    )
    assert no_longer_present_reason(before.fingerprint, _stored(before), later) == (
        "No longer present in Engineering Assessment v2"
    )


def test_with_nothing_changed_or_newer_the_reason_names_every_current_source() -> None:
    eng = agent("engineering_agent", (R[1], 100))
    pm = agent("pm_agent", (R[1], 1))
    est = estimate((140, (R[1],)))
    (before,) = effort.detect(inputs(eng, pm, estimate=est))
    # Same Assessments and Estimate, but R2 is no longer active.
    later = inputs(eng, pm, estimate=est, requirements=[REQUIREMENTS[0]])
    assert no_longer_present_reason(before.fingerprint, _stored(before), later) == (
        "No longer present in Engineering Assessment v1 and PM Assessment v1 and Estimate v3"
    )
