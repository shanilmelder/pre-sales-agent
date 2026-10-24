"""Gap rules (Story 4.3): categories, impacts and their order, statuses, detection states and
error codes, and the validation of the agent's candidates. Pure.

A Gap is grounded in the Requirements: it relates to at least one active Requirement (at its
current version) and carries a category. Its trigger is stored as
`{"kind": "agent_category", "category": ...}`, so Checklist and Knowledge triggers can be
added later without a schema change.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from app.platform.prompt_data import injection_suspected as injection_suspected

DETECTION_SUBJECT_TYPE = "gaps.detection"
"""The trace subject of a detection run."""
GAP_SUBJECT_TYPE = "gaps.gap"
QUESTION_SUBJECT_TYPE = "gaps.clarification_question"
ANSWER_MATCH_SUBJECT_TYPE = "gaps.answer_match"


class AnswerMatchStatus(StrEnum):
    """A suggestion by `clarification_agent` that a Source passage answers a question (Story
    4.7). Only a person's Confirm or Not an answer decides it; `superseded` once the question
    is answered another way."""

    SUGGESTED = "suggested"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


TITLE_MAX = 200
WHY_MAX = 1_000
IMPACT_BASIS_MAX = 1_000
QUESTION_MAX = 1_000
TOPIC_MAX = 80
"""Limits in Unicode code points, on the trimmed text."""

UNKNOWN_TO_CUSTOMER = "Unknown to the customer:"
"""Opens the `why_it_matters` of a Gap the customer cannot answer before the work starts;
`estimating_agent` proposes a Contingency for such a Gap."""


def mark_unknown_to_customer(why_it_matters: str) -> str:
    """`why_it_matters` opened with `UNKNOWN_TO_CUSTOMER`, unless it already is or the marked
    text would exceed `WHY_MAX` (then it is returned unchanged)."""
    trimmed = why_it_matters.strip()
    if trimmed.casefold().startswith(UNKNOWN_TO_CUSTOMER.casefold()):
        return trimmed
    marked = f"{UNKNOWN_TO_CUSTOMER} {trimmed}"
    return marked if len(marked) <= WHY_MAX else trimmed


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
    DISMISSED = "dismissed"
    """Story 4.4: a person set it aside with a reason (the domain's `dismissed_with_reason`).
    It can be reopened; a later detection never supersedes or reopens it."""
    ANSWERED = "answered"
    """Story 4.7: a person recorded (or confirmed) the customer's answer to its question,
    which settles it. It can be reopened; a later detection never supersedes or reopens it."""


class ConvertedTo(StrEnum):
    """The kind of Assumption a converted Gap became."""

    CONDITION = "condition"
    CONTINGENCY = "contingency"


class QuestionStatus(StrEnum):
    DRAFTED = "drafted"
    APPROVED = "approved"
    """Story 4.5: a person approved it. Editing its text or topic returns it to `drafted`."""
    SENT = "sent"
    """Story 4.6: a person recorded that it was sent to the customer. It can't be edited or
    approved any more; its approval is kept."""
    UNANSWERED = "unanswered"
    """Story 4.6: sent, and a person recorded that the customer won't answer it ("No answer")."""
    ANSWERED = "answered"
    """Story 4.7: sent (or "No answer"), and a person recorded or confirmed the customer's
    answer. Its approval and sending are kept."""
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
    AGENT_DISABLED = "registry_agent_disabled"
    """The Agent is `disabled` or `eval_only` in the Agent Registry (Story 7.1)."""


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


def gap_key(category: str, title: str) -> tuple[str, str]:
    """A Gap's identity for duplicate checks: its category and its title, ignoring case and
    spacing."""
    return category, " ".join(title.casefold().split())


def _key[K](gap: ValidGap[K]) -> tuple[str, str]:
    return gap_key(gap.category.value, gap.title)


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


class QuestionSentError(ValueError):
    """The question is `sent` or `unanswered` (Story 4.6): it can't be edited or approved."""


class QuestionNotApprovedTransitionError(ValueError):
    """The question is not `approved`: it can't be marked sent (Story 4.6)."""


class QuestionNotSentTransitionError(ValueError):
    """The question is not `sent` (to mark it "No answer", Story 4.6), or not `sent` or
    `unanswered` (to answer it, Story 4.7)."""


OPEN_TO_ANSWER = frozenset({QuestionStatus.SENT, QuestionStatus.UNANSWERED})
"""Statuses of a question that can be answered (Story 4.7)."""
SENT_STATUSES = frozenset({*OPEN_TO_ANSWER, QuestionStatus.ANSWERED})
"""Statuses of a question that left the platform: it can't be edited or approved, and its
approval and sending are kept."""
APPROVED_STATUSES = frozenset({QuestionStatus.APPROVED, *SENT_STATUSES})
"""Statuses of a question whose approval is recorded (and that a sales representative sees)."""


@dataclass(frozen=True, slots=True)
class QuestionState:
    """What editing and approving change on a Clarification Question."""

    text: str = field(repr=False)
    topic: str = field(repr=False)
    status: QuestionStatus
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    edited_by_human: bool = False
    sent_on: date | None = None
    sent_by: UUID | None = None
    answered_on: date | None = None
    answered_by: UUID | None = None
    answer_passage_id: UUID | None = None


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
    if state.status in SENT_STATUSES:
        raise QuestionSentError("A question that was sent can't be edited.")
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
    if state.status in SENT_STATUSES:
        raise QuestionSentError("A question that was sent can't be approved.")
    if state.status == QuestionStatus.APPROVED:
        return state
    return replace(state, status=QuestionStatus.APPROVED, approved_by=user_id, approved_at=at)


def touched(*, status: str, edited_by_human: bool) -> bool:
    """Whether a person has touched the question (edited, approved, sent, marked it "No
    answer" or answered it): a later detection keeps its Gap instead of superseding it."""
    return edited_by_human or status in APPROVED_STATUSES


# --- sending Clarification Questions (Story 4.6) --------------------------------------------


def sent_date(on: date, *, today: date) -> date:
    """The date a question was sent; ValueError (with the sentence to show) if it is after
    `today`."""
    if on > today:
        raise ValueError("The date sent can't be in the future.")
    return on


def mark_sent(state: QuestionState, *, user_id: UUID, on: date) -> QuestionState:
    """The `approved` question marked sent on `on` by `user_id`; its approval is kept."""
    if state.status != QuestionStatus.APPROVED:
        raise QuestionNotApprovedTransitionError("Only an approved question can be marked sent.")
    return replace(state, status=QuestionStatus.SENT, sent_on=on, sent_by=user_id)


def mark_unanswered(state: QuestionState) -> QuestionState:
    """The `sent` question marked "No answer"; when and by whom it was sent is kept."""
    if state.status != QuestionStatus.SENT:
        raise QuestionNotSentTransitionError('Only a sent question can be marked "No answer".')
    return replace(state, status=QuestionStatus.UNANSWERED)


# --- answering Clarification Questions (Story 4.7) ------------------------------------------

ANSWER_MAX = 20_000
"""A recorded answer's text, in Unicode code points, on the trimmed text."""


def answer_text(raw: str) -> str:
    """The answer text trimmed; ValueError (with the sentence to show) unless 1 to
    `ANSWER_MAX` characters."""
    trimmed = _bounded(raw, ANSWER_MAX)
    if trimmed is None:
        raise ValueError(f"The answer must be 1 to {ANSWER_MAX:,} characters long once trimmed.")
    return trimmed


def answered_date(on: date, *, today: date) -> date:
    """The date the customer answered; ValueError (with the sentence to show) if it is after
    `today`."""
    if on > today:
        raise ValueError("The date answered can't be in the future.")
    return on


def answer_question(
    state: QuestionState, *, user_id: UUID, on: date, passage_id: UUID
) -> QuestionState:
    """The `sent` or `unanswered` question answered on `on`, recorded by `user_id`, with the
    answer passage as its Evidence; its approval and sending are kept."""
    if state.status not in OPEN_TO_ANSWER:
        raise QuestionNotSentTransitionError(
            'Only a sent Clarification Question, or one marked "No answer", can be answered.'
        )
    return replace(
        state,
        status=QuestionStatus.ANSWERED,
        answered_on=on,
        answered_by=user_id,
        answer_passage_id=passage_id,
    )


def reopen_question(state: QuestionState) -> QuestionState:
    """The question of a reopened Gap (Story 4.7): an `answered` one is `sent` again with its
    answer cleared; any other stays as it is."""
    if state.status != QuestionStatus.ANSWERED:
        return state
    return replace(
        state,
        status=QuestionStatus.SENT,
        answered_on=None,
        answered_by=None,
        answer_passage_id=None,
    )


# `injection_suspected` (Story 4.7) lives in `app.platform.prompt_data` since Story 5.4, which
# runs it on every fenced data block; it is re-exported here.


# --- changing impact, dismissing and reopening Gaps (Story 4.4) -----------------------------

REASON_MAX = 500
"""Reasons and dismissal notes, in Unicode code points, on the trimmed text."""


class DismissReasonKind(StrEnum):
    NOT_RELEVANT = "not_relevant"
    """The FR-11 live irrelevance measure counts these."""
    OTHER = "other"
    """Needs a note."""


class GapHistoryKind(StrEnum):
    IMPACT_CHANGED = "impact_changed"
    DISMISSED = "dismissed"
    REOPENED = "reopened"
    CONVERTED = "converted"
    ANSWERED = "answered"


class GapNotOpenTransitionError(ValueError):
    """The Gap is not `open`: its impact can't change and it can't be dismissed or
    answered."""


class GapNotReopenableTransitionError(ValueError):
    """The Gap is neither `dismissed` nor `answered`: it can't be reopened."""


REOPENABLE = frozenset({GapStatus.DISMISSED, GapStatus.ANSWERED})
"""Statuses of a Gap a person may reopen (Stories 4.4 and 4.7)."""


@dataclass(frozen=True, slots=True)
class GapState:
    """What a person's impact change, dismissal and reopening change on a Gap."""

    status: GapStatus
    impact: Impact
    dismiss_reason_kind: DismissReasonKind | None = None
    dismiss_note: str | None = field(default=None, repr=False)
    dismissed_by: UUID | None = None
    dismissed_at: datetime | None = None
    touched_by_human: bool = False
    answered_on: date | None = None
    answered_by: UUID | None = None
    answer_passage_id: UUID | None = None


def reason_text(raw: str) -> str:
    """A reason or note trimmed; ValueError (with the sentence to show) unless 1 to
    `REASON_MAX` characters."""
    trimmed = _bounded(raw, REASON_MAX)
    if trimmed is None:
        raise ValueError(f"The reason must be 1 to {REASON_MAX} characters long once trimmed.")
    return trimmed


def dismiss_note(kind: DismissReasonKind, raw: str | None) -> str | None:
    """The dismissal note, validated: required for `other`, optional for `not_relevant` (a
    blank one is then no note); ValueError (with the sentence to show) otherwise."""
    if raw is None or not raw.strip():
        if kind == DismissReasonKind.OTHER:
            raise ValueError('Say why the Gap is dismissed: a note is required for "Other".')
        return None
    trimmed = _bounded(raw, REASON_MAX)
    if trimmed is None:
        raise ValueError(f"The note must be 1 to {REASON_MAX} characters long once trimmed.")
    return trimmed


def change_impact(state: GapState, impact: Impact) -> GapState:
    """The Gap with its impact set by a person (`touched_by_human`); `state` itself when the
    impact is unchanged. Only an `open` Gap's impact changes."""
    if state.status != GapStatus.OPEN:
        raise GapNotOpenTransitionError("Only an open Gap's impact can change.")
    if impact == state.impact:
        return state
    return replace(state, impact=impact, touched_by_human=True)


def dismiss_gap(
    state: GapState,
    *,
    kind: DismissReasonKind,
    note: str | None,
    user_id: UUID,
    at: datetime,
) -> GapState:
    """The `open` Gap dismissed by `user_id` at `at` with its reason. `note` is already
    validated (`dismiss_note`)."""
    if state.status != GapStatus.OPEN:
        raise GapNotOpenTransitionError("Only an open Gap can be dismissed.")
    return replace(
        state,
        status=GapStatus.DISMISSED,
        dismiss_reason_kind=kind,
        dismiss_note=note,
        dismissed_by=user_id,
        dismissed_at=at,
    )


def answer_gap(state: GapState, *, user_id: UUID, on: date, passage_id: UUID) -> GapState:
    """The `open` Gap answered (Story 4.7) on `on`, recorded by `user_id`, with the answer
    passage as its Evidence."""
    if state.status != GapStatus.OPEN:
        raise GapNotOpenTransitionError("Only an open Gap can be answered.")
    return replace(
        state,
        status=GapStatus.ANSWERED,
        answered_on=on,
        answered_by=user_id,
        answer_passage_id=passage_id,
    )


def reopen_gap(state: GapState) -> GapState:
    """The `dismissed` or `answered` Gap open again, its dismissal or answer cleared, and
    marked `touched_by_human` (a later detection keeps it)."""
    if state.status not in REOPENABLE:
        raise GapNotReopenableTransitionError("Only a dismissed or answered Gap can be reopened.")
    return replace(
        state,
        status=GapStatus.OPEN,
        dismiss_reason_kind=None,
        dismiss_note=None,
        dismissed_by=None,
        dismissed_at=None,
        answered_on=None,
        answered_by=None,
        answer_passage_id=None,
        touched_by_human=True,
    )
