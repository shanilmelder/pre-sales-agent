"""conflicts' public API. Other modules import conflicts only from here.

The detector's inputs (`AssessmentSnapshot`, `EffortSnapshot`, `EstimateSnapshot`,
`EstimateLineSnapshot`) are plain data the caller builds from its own records, so
`conflicts` imports neither `assessments` nor `estimates`."""

from app.modules.conflicts.application.conflicts import (
    RaisedConflict,
    RequirementConflict,
    detect_for_run,
    get_conflicts,
    list_open,
    open_by_requirement,
    raise_conflict,
)
from app.modules.conflicts.application.decisions import (
    AppliedDecision,
    EstimateLink,
    escalate_conflict,
    resolve_conflict,
)
from app.modules.conflicts.application.models import (
    ConflictEscalation,
    ConflictPosition,
    ConflictRequirement,
    ConflictResolution,
    ConflictsView,
    ConflictView,
    OpenConflict,
)
from app.modules.conflicts.domain.conflicts import ConflictType, DetectedBy
from app.modules.conflicts.domain.decisions import NotApplied
from app.modules.conflicts.domain.rules import (
    AssessmentSnapshot,
    ConflictCandidate,
    EffortSnapshot,
    EstimateLineSnapshot,
    EstimateSnapshot,
    PositionCandidate,
)

__all__ = [
    "AppliedDecision",
    "AssessmentSnapshot",
    "ConflictCandidate",
    "ConflictEscalation",
    "ConflictPosition",
    "ConflictRequirement",
    "ConflictResolution",
    "ConflictType",
    "ConflictView",
    "ConflictsView",
    "DetectedBy",
    "EffortSnapshot",
    "EstimateLineSnapshot",
    "EstimateLink",
    "EstimateSnapshot",
    "NotApplied",
    "OpenConflict",
    "PositionCandidate",
    "RaisedConflict",
    "RequirementConflict",
    "detect_for_run",
    "escalate_conflict",
    "get_conflicts",
    "list_open",
    "open_by_requirement",
    "raise_conflict",
    "resolve_conflict",
]
