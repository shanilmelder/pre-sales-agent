"""The deterministic Conflict rules (Story 6.1). Pure: unit-tested without DB or LLM.

- (a) `scope`: Engineering or PM sizes a Requirement the other doesn't.
- (b) `recommendation_clash`: one agent says proceed, another do not proceed.
- (c) `effort`: the Estimate's allocated hours for a Requirement are more than 30% away from
  the agents' sum.

`detect` runs them all; `current_summary` says what a stored position of a rule's Conflict
would read now, to name what changed when a Conflict is no longer present.
"""

from collections.abc import Callable
from uuid import UUID

from app.modules.conflicts.domain.rules import effort, recommendation, scope
from app.modules.conflicts.domain.rules.inputs import (
    ActiveRequirement,
    AssessmentSnapshot,
    ConflictCandidate,
    EffortSnapshot,
    EstimateLineSnapshot,
    EstimateSnapshot,
    PositionCandidate,
    RuleInputs,
)

_Detect = Callable[[RuleInputs], list[ConflictCandidate]]
_Current = Callable[..., str | None]

RULES: dict[str, tuple[_Detect, _Current]] = {
    scope.RULE_ID: (scope.detect, scope.current_summary),
    recommendation.RULE_ID: (recommendation.detect, recommendation.current_summary),
    effort.RULE_ID: (effort.detect, effort.current_summary),
}


def detect(inputs: RuleInputs) -> list[ConflictCandidate]:
    """Every rule's Conflicts, rule by rule, in Requirement order within a rule."""
    return [conflict for run, _ in RULES.values() for conflict in run(inputs)]


def rule_of(fingerprint: str) -> str:
    return fingerprint.split(":", 1)[0]


def current_summary(
    fingerprint: str, inputs: RuleInputs, *, agent: str | None, requirement_id: UUID | None
) -> str | None:
    """What a position (an agent's, or the Estimate's when `agent` is None) of the Conflict
    with this fingerprint would read now; None when it has no current source or the rule is
    unknown."""
    rule = RULES.get(rule_of(fingerprint))
    if rule is None:
        return None
    return rule[1](inputs, agent=agent, requirement_id=requirement_id)


__all__ = [
    "RULES",
    "ActiveRequirement",
    "AssessmentSnapshot",
    "ConflictCandidate",
    "EffortSnapshot",
    "EstimateLineSnapshot",
    "EstimateSnapshot",
    "PositionCandidate",
    "RuleInputs",
    "current_summary",
    "detect",
    "rule_of",
]
