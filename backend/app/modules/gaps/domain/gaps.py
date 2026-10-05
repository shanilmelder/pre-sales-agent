"""Gap rules (Story 4.3): categories, impacts and their order, statuses, detection states and
error codes, and the validation of the agent's candidates. Pure.

A Gap is grounded in the Requirements: it relates to at least one active Requirement (at its
current version) and carries a category. Its trigger is stored as
`{"kind": "agent_category", "category": ...}`, so Checklist and Knowledge triggers can be
added later without a schema change.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

DETECTION_SUBJECT_TYPE = "gaps.detection"
"""The trace subject of a detection run."""
GAP_SUBJECT_TYPE = "gaps.gap"
QUESTION_SUBJECT_TYPE = "gaps.clarification_question"

TITLE_MAX = 200
WHY_MAX = 1_000
IMPACT_BASIS_MAX = 1_000
QUESTION_MAX = 1_000
TOPIC_MAX = 80
"""Limits in Unicode code points, on the trimmed text."""

TRIGGER_KIND = "agent_category"


class GapCategory(StrEnum):
    DATA_VOLUMES = "data_volumes"
    VERSIONS_AND_PLATFORMS = "versions_and_platforms"
    INTEGRATION_DETAILS = "integration_details"
    SECURITY_AND_COMPLIANCE = "security_and_compliance"
    NON_FUNCTIONAL = "non_functional"
    SCOPE_AND_OWNERSHIP = "scope_and_ownership"
    COMMERCIAL = "commercial"
    OTHER = "other"


class Impact(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


IMPACT_RANK: Mapping[Impact, int] = {Impact.HIGH: 0, Impact.MEDIUM: 1, Impact.LOW: 2}
"""Gaps list high first, then medium, then low."""


class GapOrigin(StrEnum):
    DETECTED = "detected"


class GapStatus(StrEnum):
    OPEN = "open"
    SUPERSEDED = "superseded"
    CONVERTED = "converted"
    """Story 8.4: an Assumption made from it was accepted. Only an `open` Gap converts, and a
    converted Gap is final: a later detection never supersedes it."""


class ConvertedTo(StrEnum):
    """The kind of Assumption a converted Gap became."""

    CONDITION = "condition"
    CONTINGENCY = "contingency"


class QuestionStatus(StrEnum):
    DRAFTED = "drafted"
    APPROVED = "approved"
    """Story 4.5: a person approved it. Editing its text or topic returns it to `drafted`."""
    SUPERSEDED = "superseded"
    """Set together with its Gap's `superseded` by a newer detection."""


class DetectionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


IN_PROGRESS = frozenset({DetectionStatus.QUEUED, DetectionStatus.RUNNING})


class DetectionErrorCode(StrEnum):
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_TIMEOUT = "model_timeout"
    OUTPUT_INVALID = "output_invalid"


def trigger(category: GapCategory) -> dict[str, str]:
    """The stored trigger of an agent-raised Gap."""
    return {"kind": TRIGGER_KIND, "category": category.value}


def impact_rank(impact: str) -> int:
    """The sort rank of an impact; unknown values sort last."""
    try:
        return IMPACT_RANK[Impact(impact)]
    except ValueError:
        return len(IMPACT_RANK)


# --- validating the agent's candidates ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Candidate:
    """One Gap as the agent proposed it, before validation."""

    title: str = field(repr=False)
    category: str
    why_it_matters: str = field(repr=False)
    impact: str
    impact_basis: str = field(repr=False)
    related: tuple[str, ...]
    """Requirement labels, `R<n>`."""
    question_text: str = field(repr=False)
    question_topic: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ValidGap[K]:
    title: str = field(repr=False)
    category: GapCategory
    why_it_matters: str = field(repr=False)
    impact: Impact
    impact_basis: str = field(repr=False)
    related: tuple[K, ...]
    """The resolved Requirements, without duplicates, in the order cited."""
    question_text: str = field(repr=False)
    question_topic: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class Validation[K]:
    gaps: tuple[ValidGap[K], ...]
    dropped: int
    """Candidates dropped: a field missing, blank or too long, an unknown category or
    impact, no related label that resolves, or a duplicate of an earlier candidate."""


def _bounded(raw: str, limit: int) -> str | None:
    trimmed = raw.strip()
    return trimmed if 0 < len(trimmed) <= limit else None


def validate_candidate[K](
    candidate: Candidate, requirements: Mapping[str, K]
) -> ValidGap[K] | None:
    """The candidate checked against the rules, its labels resolved through `requirements`
    (label to Requirement); None if it breaks a rule. Labels that don't resolve are ignored
    as long as at least one does."""
    title = _bounded(candidate.title, TITLE_MAX)
    why = _bounded(candidate.why_it_matters, WHY_MAX)
    basis = _bounded(candidate.impact_basis, IMPACT_BASIS_MAX)
    text = _bounded(candidate.question_text, QUESTION_MAX)
    topic = _bounded(candidate.question_topic, TOPIC_MAX)
    try:
        category = GapCategory(candidate.category)
        impact = Impact(candidate.impact)
    except ValueError:
        return None
    related: list[K] = []
    for label in candidate.related:
        found = requirements.get(label.strip())
        if found is not None and found not in related:
            related.append(found)
    if title is None or why is None or basis is None or text is None or topic is None:
        return None
    if not related:
        return None
    return ValidGap(
        title=title,
        category=category,
        why_it_matters=why,
        impact=impact,
        impact_basis=basis,
        related=tuple(related),
        question_text=text,
        question_topic=topic,
    )


def _key[K](gap: ValidGap[K]) -> tuple[str, str]:
    return gap.category.value, " ".join(gap.title.casefold().split())


def validate_candidates[K](
    candidates: Sequence[Candidate], requirements: Mapping[str, K]
) -> Validation[K]:
    """Validate every candidate; invalid ones and repeats of an earlier valid one (same
    category and title, ignoring case and spacing) are dropped and counted."""
    kept: list[ValidGap[K]] = []
    seen: set[tuple[str, str]] = set()
    dropped = 0
    for candidate in candidates:
        valid = validate_candidate(candidate, requirements)
        if valid is None or _key(valid) in seen:
            dropped += 1
            continue
        seen.add(_key(valid))
        kept.append(valid)
    return Validation(tuple(kept), dropped)


# --- editing and approving Clarification Questions (Story 4.5) ------------------------------

QuestionField = Literal["text", "topic"]


class QuestionNotEditableError(ValueError):
    """The question is `superseded`: it can't be edited or approved."""


@dataclass(frozen=True, slots=True)
class QuestionState:
    """What editing and approving change on a Clarification Question."""

    text: str = field(repr=False)
    topic: str = field(repr=False)
    status: QuestionStatus
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    edited_by_human: bool = False


def question_text(raw: str) -> str:
    """The question text trimmed; ValueError (with the sentence to show) unless 1 to
    `QUESTION_MAX` characters."""
    trimmed = _bounded(raw, QUESTION_MAX)
    if trimmed is None:
        raise ValueError(
            f"The question must be 1 to {QUESTION_MAX:,} characters long once trimmed."
        )
    return trimmed


def question_topic(raw: str) -> str:
    """The topic trimmed; ValueError (with the sentence to show) unless 1 to `TOPIC_MAX`
    characters."""
    trimmed = _bounded(raw, TOPIC_MAX)
    if trimmed is None:
        raise ValueError(f"The topic must be 1 to {TOPIC_MAX} characters long once trimmed.")
    return trimmed


def edit_question(
    state: QuestionState, *, text: str | None = None, topic: str | None = None
) -> tuple[QuestionState, tuple[QuestionField, ...]]:
    """The question after a person's edit, and which fields changed (none: `state` itself).
    `text` and `topic` are already validated. A change marks it `edited_by_human` and returns
    an approved question to `drafted`, clearing its approval."""
    if state.status == QuestionStatus.SUPERSEDED:
        raise QuestionNotEditableError("A superseded question can't be edited.")
    changed: list[QuestionField] = []
    if text is not None and text != state.text:
        changed.append("text")
    if topic is not None and topic != state.topic:
        changed.append("topic")
    if not changed:
        return state, ()
    edited = replace(
        state,
        text=state.text if text is None else text,
        topic=state.topic if topic is None else topic,
        status=QuestionStatus.DRAFTED,
        approved_by=None,
        approved_at=None,
        edited_by_human=True,
    )
    return edited, tuple(changed)


def approve_question(state: QuestionState, *, user_id: UUID, at: datetime) -> QuestionState:
    """The question approved by `user_id` at `at`; an approved question stays as it is."""
    if state.status == QuestionStatus.SUPERSEDED:
        raise QuestionNotEditableError("A superseded question can't be approved.")
    if state.status == QuestionStatus.APPROVED:
        return state
    return replace(state, status=QuestionStatus.APPROVED, approved_by=user_id, approved_at=at)


def touched(*, status: str, edited_by_human: bool) -> bool:
    """Whether a person has touched the question (edited or approved it): a later detection
    keeps its Gap instead of superseding it."""
    return edited_by_human or status == QuestionStatus.APPROVED
