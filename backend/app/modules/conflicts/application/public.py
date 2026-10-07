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
from app.modules.conflicts.application.models import (
    ConflictPosition,
    ConflictRequirement,
    ConflictsView,
    ConflictView,
    OpenConflict,
)
from app.modules.conflicts.domain.conflicts import ConflictType, DetectedBy
from app.modules.conflicts.domain.rules import (
    AssessmentSnapshot,
    ConflictCandidate,
    EffortSnapshot,
    EstimateLineSnapshot,
    EstimateSnapshot,
    PositionCandidate,
)

__all__ = [
    "AssessmentSnapshot",
    "ConflictCandidate",
    "ConflictPosition",
    "ConflictRequirement",
    "ConflictType",
    "ConflictView",
    "ConflictsView",
    "DetectedBy",
    "EffortSnapshot",
    "EstimateLineSnapshot",
    "EstimateSnapshot",
    "OpenConflict",
    "PositionCandidate",
    "RaisedConflict",
    "RequirementConflict",
    "detect_for_run",
    "get_conflicts",
    "list_open",
    "open_by_requirement",
    "raise_conflict",
]
