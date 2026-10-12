"""Rule (c), agents vs Estimate (type `effort`, `medium`). Per active Requirement:

- A: the sum of the agents' hours for it (each agent's effort row, at any version), as in the
  Effort comparison (Story 5.3);
- E: the Estimate's allocated hours: each line's effort hours split equally among the active
  Requirements it covers, summed (as Story 5.3 does).

A Conflict when both are above 0 and |E - A| > 30% of A (exactly 30% is not one). Positions:
one per agent with hours, then the Estimate's allocated hours. No Estimate: nothing."""

from decimal import Decimal
from fractions import Fraction
from uuid import UUID

from app.modules.conflicts.domain.conflicts import (
    ConflictSeverity,
    ConflictType,
    PositionSource,
    agent_rank,
    hours_label,
    tenth,
)
from app.modules.conflicts.domain.rules.inputs import (
    ConflictCandidate,
    EstimateSnapshot,
    PositionCandidate,
    RuleInputs,
)

RULE_ID = "effort"
THRESHOLD = Fraction(3, 10)
"""More than this share of the agents' hours apart is a Conflict."""


def fingerprint(requirement_id: UUID) -> str:
    return f"{RULE_ID}:{requirement_id}"


def allocated_hours(estimate: EstimateSnapshot, active: set[UUID]) -> dict[UUID, Fraction]:
    """The Estimate's hours per active Requirement (0 when no line covers it is left out)."""
    allocated: dict[UUID, Fraction] = {}
    for line in estimate.lines:
        covered = sorted({r for r in line.requirement_ids if r in active}, key=str)
        if not covered:
            continue
        share = Fraction(line.effort_hours) / len(covered)
        for requirement_id in covered:
            allocated[requirement_id] = allocated.get(requirement_id, Fraction(0)) + share
    return allocated


def differs(agents: Fraction, estimate: Fraction) -> bool:
    """Both above 0 and more than 30% of the agents' hours apart."""
    return agents > 0 and estimate > 0 and abs(estimate - agents) > THRESHOLD * agents


def _to_decimal(value: Fraction) -> Decimal:
    """Hours to 0.1 (half up)."""
    return tenth(Decimal(value.numerator) / Decimal(value.denominator))


def detect(inputs: RuleInputs) -> list[ConflictCandidate]:
    estimate = inputs.estimate
    if estimate is None:
        return []
    active = {r.id for r in inputs.requirements}
    allocated = allocated_hours(estimate, active)
    agents = sorted(inputs.assessments, key=lambda a: agent_rank(a.agent))
    found: list[ConflictCandidate] = []
    for requirement in inputs.requirements:
        rows = [(a, a.hours_for(requirement.id)) for a in agents]
        sized = [(a, row) for a, row in rows if row is not None]
        total = sum((Fraction(row.hours) for _, row in sized), Fraction(0))
        e = allocated.get(requirement.id, Fraction(0))
        if not differs(total, e):
            continue
        positions = [
            PositionCandidate(
                source=PositionSource.ASSESSMENT,
                summary=hours_label(row.hours),
                value=tenth(row.hours),
                agent=a.agent,
                assessment_id=a.assessment_id,
                assessment_version=a.version,
                requirement_id=requirement.id,
                requirement_version=row.requirement_version,
            )
            for a, row in sized
        ]
        e_hours = _to_decimal(e)
        positions.append(
            PositionCandidate(
                source=PositionSource.ESTIMATE,
                summary=hours_label(e_hours),
                value=e_hours,
                estimate_version_id=estimate.version_id,
                estimate_version=estimate.version,
                requirement_id=requirement.id,
                requirement_version=requirement.version,
            )
        )
        found.append(
            ConflictCandidate(
                rule=RULE_ID,
                type=ConflictType.EFFORT,
                severity=ConflictSeverity.MEDIUM,
                fingerprint=fingerprint(requirement.id),
                summary=(
                    f"The Estimate allocates {hours_label(e_hours)} to this Requirement; "
                    f"the agents size it at {hours_label(_to_decimal(total))}."
                ),
                positions=tuple(positions),
            )
        )
    return found


def current_summary(
    inputs: RuleInputs, *, agent: str | None, requirement_id: UUID | None, **_: object
) -> str | None:
    """What that position would read now: the agent's hours ("Not sized" without a row), or
    the Estimate's allocated hours (None without an Estimate or an active Requirement)."""
    if requirement_id is None:
        return None
    if agent is None:
        if inputs.estimate is None:
            return None
        active = {r.id for r in inputs.requirements}
        if requirement_id not in active:
            return None
        allocated = allocated_hours(inputs.estimate, active)
        return hours_label(_to_decimal(allocated.get(requirement_id, Fraction(0))))
    assessment = inputs.assessment_of(agent)
    if assessment is None:
        return None
    row = assessment.hours_for(requirement_id)
    return "Not sized" if row is None else hours_label(row.hours)
