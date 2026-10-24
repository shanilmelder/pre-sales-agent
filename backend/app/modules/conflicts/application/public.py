"""conflicts' public API. Other modules import conflicts only from here.

The detector's inputs (`AssessmentSnapshot`, `EffortSnapshot`, `EstimateSnapshot`,
`EstimateLineSnapshot`, and Story 6.2's `FindingSnapshot` and `FindingTitle`) are plain data
the caller builds from its own records, so `conflicts` imports neither `assessments` nor
`estimates` at module level."""

from app.modules.conflicts.application.conflicts import (
    Detection,
    RaisedConflict,
    RequirementConflict,
    detect_for_run,
    get_conflicts,
    list_open,
    open_by_requirement,
    open_conflict_counts,
    raise_conflict,
)
from app.modules.conflicts.application.critic import CriticConflicts, raise_critic_conflicts
from app.modules.conflicts.application.decisions import (
    AppliedDecision,
    EstimateLink,
    escalate_conflict,
    resolve_conflict,
)
from app.modules.conflicts.application.models import (
    ConflictEscalation,
    ConflictFinding,
    ConflictPosition,
    ConflictRequirement,
    ConflictResolution,
    ConflictsView,
    ConflictView,
    OpenConflict,
)
from app.modules.conflicts.application.semantic import (
    SEMANTIC_DETECTION,
    accept_semantic_conflicts,
    evaluate_semantic,
    queue_semantic_detection,
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
from app.modules.conflicts.domain.semantic import (
    FindingSnapshot,
    FindingTitle,
    SemanticCandidate,
    SemanticValidation,
    StanceCandidate,
    ValidSemantic,
)

__all__ = [
    "SEMANTIC_DETECTION",
    "AppliedDecision",
    "AssessmentSnapshot",
    "ConflictCandidate",
    "ConflictEscalation",
    "ConflictFinding",
    "ConflictPosition",
    "ConflictRequirement",
    "ConflictResolution",
    "ConflictType",
    "ConflictView",
    "ConflictsView",
    "CriticConflicts",
    "DetectedBy",
    "Detection",
    "EffortSnapshot",
    "EstimateLineSnapshot",
    "EstimateLink",
    "EstimateSnapshot",
    "FindingSnapshot",
    "FindingTitle",
    "NotApplied",
    "OpenConflict",
    "PositionCandidate",
    "RaisedConflict",
    "RequirementConflict",
    "SemanticCandidate",
    "SemanticValidation",
    "StanceCandidate",
    "ValidSemantic",
    "accept_semantic_conflicts",
    "detect_for_run",
    "escalate_conflict",
    "evaluate_semantic",
    "get_conflicts",
    "list_open",
    "open_by_requirement",
    "open_conflict_counts",
    "queue_semantic_detection",
    "raise_conflict",
    "raise_critic_conflicts",
    "resolve_conflict",
]
