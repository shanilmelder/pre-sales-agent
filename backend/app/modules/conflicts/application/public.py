"""conflicts' public API. Other modules import conflicts only from here.

The detector's inputs (`AssessmentSnapshot`, `EffortSnapshot`, `EstimateSnapshot`,
`EstimateLineSnapshot`) are plain data the caller builds from its own records, so
`conflicts` imports neither `assessments` nor `estimates`."""

from app.modules.conflicts.application.conflicts import (
    RaisedConflict,
    detect_for_run,
    get_conflicts,
    list_open,
    raise_conflict,
)
from app.modules.conflicts.application.models import (
    ConflictPosition,
    ConflictRequirement,
    ConflictsView,
    ConflictView,
    OpenConflict,
)
from app.modules.conflicts.domain.conflicts import DetectedBy
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
    "ConflictView",
    "ConflictsView",
    "DetectedBy",
    "EffortSnapshot",
    "EstimateLineSnapshot",
    "EstimateSnapshot",
    "OpenConflict",
    "PositionCandidate",
    "RaisedConflict",
    "detect_for_run",
    "get_conflicts",
    "list_open",
    "raise_conflict",
]
