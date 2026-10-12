"""Rule (a), scope (`medium`): Engineering or PM sizes an active Requirement and the other,
though it has a current Assessment, has no effort row for it. One Conflict per Requirement,
with the sizing agent's hours and the other's "Not sized"."""

from uuid import UUID

from app.modules.conflicts.domain.conflicts import (
    ConflictSeverity,
    ConflictType,
    PositionSource,
    agent_role,
    hours_label,
    tenth,
)
from app.modules.conflicts.domain.rules.inputs import (
    ConflictCandidate,
    PositionCandidate,
    RuleInputs,
)

RULE_ID = "scope"
AGENTS: tuple[str, str] = ("engineering_agent", "pm_agent")
NOT_SIZED = "Not sized"


def fingerprint(requirement_id: UUID) -> str:
    return f"{RULE_ID}:{requirement_id}:{'+'.join(sorted(AGENTS))}"


def detect(inputs: RuleInputs) -> list[ConflictCandidate]:
    pair = [inputs.assessment_of(agent) for agent in AGENTS]
    if any(a is None for a in pair):
        return []
    found: list[ConflictCandidate] = []
    for requirement in inputs.requirements:
        rows = [a.hours_for(requirement.id) if a else None for a in pair]
        if (rows[0] is None) == (rows[1] is None):
            continue
        positions: list[PositionCandidate] = []
        sizing = ""
        for assessment, row in zip(pair, rows, strict=True):
            assert assessment is not None
            if row is None:
                positions.append(
                    PositionCandidate(
                        source=PositionSource.ASSESSMENT,
                        summary=NOT_SIZED,
                        agent=assessment.agent,
                        assessment_id=assessment.assessment_id,
                        assessment_version=assessment.version,
                        requirement_id=requirement.id,
                        requirement_version=requirement.version,
                    )
                )
            else:
                sizing = agent_role(assessment.agent)
                positions.append(
                    PositionCandidate(
                        source=PositionSource.ASSESSMENT,
                        summary=hours_label(row.hours),
                        value=tenth(row.hours),
                        agent=assessment.agent,
                        assessment_id=assessment.assessment_id,
                        assessment_version=assessment.version,
                        requirement_id=requirement.id,
                        requirement_version=row.requirement_version,
                    )
                )
        other = next(agent_role(p.agent) for p in positions if p.summary == NOT_SIZED and p.agent)
        found.append(
            ConflictCandidate(
                rule=RULE_ID,
                type=ConflictType.SCOPE,
                severity=ConflictSeverity.MEDIUM,
                fingerprint=fingerprint(requirement.id),
                summary=f"{sizing} sizes this Requirement; {other} does not.",
                positions=tuple(positions),
            )
        )
    return found


def current_summary(
    inputs: RuleInputs, *, agent: str | None, requirement_id: UUID | None, **_: object
) -> str | None:
    """What that agent's position would read now (None: it has no current Assessment)."""
    assessment = None if agent is None else inputs.assessment_of(agent)
    if assessment is None or requirement_id is None:
        return None
    row = assessment.hours_for(requirement_id)
    return NOT_SIZED if row is None else hours_label(row.hours)
