"""What the Conflict rules read (Story 6.1), and what they propose. Plain, frozen data:
the caller (the assessments module, at the end of a run) builds the inputs from its own
records and the Estimate's, so `conflicts` imports neither module."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from app.modules.conflicts.domain.conflicts import ConflictSeverity, ConflictType, PositionSource


@dataclass(frozen=True, slots=True)
class EffortSnapshot:
    """One effort row of an Assessment: hours for a Requirement at the version it read."""

    requirement_id: UUID
    requirement_version: int
    hours: Decimal


@dataclass(frozen=True, slots=True)
class AssessmentSnapshot:
    """An agent's current Assessment: its id, version, recommendation and effort rows."""

    assessment_id: UUID
    agent: str
    version: int
    recommendation: str
    effort: tuple[EffortSnapshot, ...] = ()

    def hours_for(self, requirement_id: UUID) -> EffortSnapshot | None:
        """The effort row for that Requirement (any version), if any."""
        return next((e for e in self.effort if e.requirement_id == requirement_id), None)


@dataclass(frozen=True, slots=True)
class EstimateLineSnapshot:
    """A line of the Estimate: its effort hours and the Requirements it covers."""

    effort_hours: Decimal
    requirement_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class EstimateSnapshot:
    """The current Estimate draft as read when detection ran."""

    version_id: UUID
    version: int
    lines: tuple[EstimateLineSnapshot, ...] = ()


@dataclass(frozen=True, slots=True)
class ActiveRequirement:
    """An active Requirement at its current version, in Requirement order."""

    id: UUID
    version: int


@dataclass(frozen=True, slots=True)
class RuleInputs:
    """Everything the rules read."""

    assessments: Sequence[AssessmentSnapshot]
    estimate: EstimateSnapshot | None
    requirements: Sequence[ActiveRequirement]

    def assessment_of(self, agent: str) -> AssessmentSnapshot | None:
        return next((a for a in self.assessments if a.agent == agent), None)


@dataclass(frozen=True, slots=True)
class PositionCandidate:
    """One side of a Conflict. An Assessment position names its agent and Assessment
    version; the Estimate position its Estimate Version. `value`: hours, or None."""

    source: PositionSource
    summary: str = field(repr=False)
    value: Decimal | None = None
    agent: str | None = None
    assessment_id: UUID | None = None
    assessment_version: int | None = None
    estimate_version_id: UUID | None = None
    estimate_version: int | None = None
    requirement_id: UUID | None = None
    requirement_version: int | None = None


@dataclass(frozen=True, slots=True)
class ConflictCandidate:
    """A Conflict a rule proposes. `fingerprint` identifies the same disagreement across
    runs; it starts with the rule id."""

    rule: str
    type: ConflictType
    severity: ConflictSeverity
    fingerprint: str
    summary: str = field(repr=False)
    positions: tuple[PositionCandidate, ...] = ()
