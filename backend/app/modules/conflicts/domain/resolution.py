"""The system's reason when a rule's Conflict is no longer present after a run (AD-27). Pure.

The reason names the sources whose position changed: "No longer present in PM Assessment
v2", "… in Engineering Assessment v3 and Estimate v4". When no position reads differently
(e.g. the Requirement is no longer active), it names the sources at a newer version, and
failing that every source's current version."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.modules.conflicts.domain.conflicts import PositionSource, agent_role
from app.modules.conflicts.domain.rules import RuleInputs, current_summary

NO_LONGER_PRESENT = "No longer present in"
CARRIED_FORWARD = "Still present: carried forward to a later run."


@dataclass(frozen=True, slots=True)
class StoredPosition:
    source: PositionSource
    agent: str | None
    assessment_version: int | None
    estimate_version: int | None
    requirement_id: UUID | None
    summary: str = field(repr=False)


def _current_source(position: StoredPosition, inputs: RuleInputs) -> tuple[str, int] | None:
    """The position's source now, as (name, version); None when it has none."""
    if position.source == PositionSource.ESTIMATE:
        return None if inputs.estimate is None else ("Estimate", inputs.estimate.version)
    assessment = None if position.agent is None else inputs.assessment_of(position.agent)
    if assessment is None:
        return None
    return f"{agent_role(assessment.agent)} Assessment", assessment.version


def _stored_version(position: StoredPosition) -> int | None:
    if position.source == PositionSource.ESTIMATE:
        return position.estimate_version
    return position.assessment_version


def no_longer_present_reason(
    fingerprint: str, positions: Sequence[StoredPosition], inputs: RuleInputs
) -> str:
    changed: list[tuple[str, int]] = []
    newer: list[tuple[str, int]] = []
    every: list[tuple[str, int]] = []
    for position in positions:
        now = _current_source(position, inputs)
        if now is None or now in every:
            continue
        every.append(now)
        reads = current_summary(
            fingerprint, inputs, agent=position.agent, requirement_id=position.requirement_id
        )
        if reads is not None and reads != position.summary:
            changed.append(now)
        if _stored_version(position) != now[1]:
            newer.append(now)
    named = changed or newer or every
    if not named:
        return f"{NO_LONGER_PRESENT} the current Assessments"
    return f"{NO_LONGER_PRESENT} " + " and ".join(f"{name} v{version}" for name, version in named)
