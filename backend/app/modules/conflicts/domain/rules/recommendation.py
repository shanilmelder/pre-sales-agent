"""Rule (b), recommendation clash (type `assumption`, `high`): at least one agent recommends
`proceed` and another `do_not_proceed`. One Opportunity-level Conflict (no Requirement) with
a position per agent that has a current Assessment, each showing its recommendation."""

from uuid import UUID

from app.modules.conflicts.domain.conflicts import (
    ConflictSeverity,
    ConflictType,
    PositionSource,
    agent_rank,
)
from app.modules.conflicts.domain.rules.inputs import (
    ConflictCandidate,
    PositionCandidate,
    RuleInputs,
)

RULE_ID = "recommendation_clash"
PROCEED = "proceed"
DO_NOT_PROCEED = "do_not_proceed"
LABELS: dict[str, str] = {
    "proceed": "Proceed",
    "proceed_with_conditions": "Proceed with conditions",
    "do_not_proceed": "Do not proceed",
}


def label(recommendation: str) -> str:
    return LABELS.get(recommendation, recommendation.replace("_", " ").capitalize())


def fingerprint() -> str:
    return RULE_ID


def detect(inputs: RuleInputs) -> list[ConflictCandidate]:
    recommendations = {a.recommendation for a in inputs.assessments}
    if not {PROCEED, DO_NOT_PROCEED} <= recommendations:
        return []
    positions = tuple(
        PositionCandidate(
            source=PositionSource.ASSESSMENT,
            summary=label(a.recommendation),
            agent=a.agent,
            assessment_id=a.assessment_id,
            assessment_version=a.version,
        )
        for a in sorted(inputs.assessments, key=lambda a: agent_rank(a.agent))
    )
    return [
        ConflictCandidate(
            rule=RULE_ID,
            type=ConflictType.ASSUMPTION,
            severity=ConflictSeverity.HIGH,
            fingerprint=fingerprint(),
            summary="The agents' recommendations clash: proceed and do not proceed.",
            positions=positions,
        )
    ]


def current_summary(
    inputs: RuleInputs, *, agent: str | None, requirement_id: UUID | None, **_: object
) -> str | None:
    assessment = None if agent is None else inputs.assessment_of(agent)
    return None if assessment is None else label(assessment.recommendation)
