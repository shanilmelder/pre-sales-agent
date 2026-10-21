"""Read models for Gaps and their Clarification Questions (Story 4.3)."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from app.modules.gaps.domain.gaps import (
    ANSWER_MAX,
    QUESTION_MAX,
    REASON_MAX,
    TOPIC_MAX,
    ConvertedTo,
    DetectionErrorCode,
    DetectionStatus,
    DismissReasonKind,
    GapCategory,
    GapOrigin,
    GapStatus,
    Impact,
    QuestionStatus,
)
from app.modules.intake.application.public import RequirementChangeRef
from app.modules.opportunities.application.public import UserRef


class GapTrigger(BaseModel):
    """What raised the Gap. In the demo, always the agent, by category."""

    kind: Literal["agent_category"]
    category: GapCategory


class GapRequirement(BaseModel):
    """A Requirement the Gap relates to, at the version it was raised against. `label` is
    `R<n>`, the Requirement's stable number within the Opportunity, or `Superseded` once it
    is no longer active. `excerpt`: up to 140 characters of that version's text, with `…`
    when cut."""

    id: str
    version: int = Field(ge=1)
    label: str
    excerpt: str


class ClarificationQuestion(BaseModel):
    """A Gap's Clarification Question. `status` is `drafted` or `approved` (Story 4.5), then
    `sent` and `unanswered` ("No answer", Story 4.6), then `answered` (Story 4.7);
    `status_changed_at` moves on every status change. `approved_by` / `approved_at` are set
    while `approved`, `sent`, `unanswered` or `answered`; `sent_on` / `sent_by` while `sent`,
    `unanswered` or `answered`; `answered_on` / `answered_by` (the person who recorded or
    confirmed the answer) while `answered`. `edited_by_human`: a person changed its text or
    topic. `last_changed_by`: the person behind its latest change (null for the agent's
    draft)."""

    id: str
    text: str
    topic: str
    status: QuestionStatus
    status_changed_at: datetime
    row_version: int = Field(ge=1)
    approved_by: UserRef | None
    approved_at: datetime | None
    edited_by_human: bool
    last_changed_by: UserRef | None
    sent_on: date | None
    sent_by: UserRef | None
    answered_on: date | None
    answered_by: UserRef | None


class QuestionChanges(BaseModel):
    """A person's edit of a Clarification Question (Story 4.5). Fields left out stay as they
    are."""

    model_config = ConfigDict(extra="forbid")

    text: StrictStr | None = Field(
        default=None,
        description=f"The new question. Trimmed, it must be 1 to {QUESTION_MAX:,} characters.",
    )
    topic: StrictStr | None = Field(
        default=None,
        description=f"The new topic. Trimmed, it must be 1 to {TOPIC_MAX} characters.",
    )


class QuestionVersion(BaseModel):
    """A drafted question as the client shows it, for **Approve all** (Story 4.5)."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    row_version: int = Field(ge=0)


class ApproveAllResult(BaseModel):
    """How many questions **Approve all** approved (the drafted questions of open Gaps)."""

    count: int = Field(ge=0)


class ApproveSelectedResult(BaseModel):
    """How many questions **Approve N selected** approved (Story 4.4)."""

    count: int = Field(ge=0)


class MarkSentRequest(BaseModel):
    """**Mark sent** (Story 4.6): the approved questions the client shows (1 to 200, `id` and
    `row_version` each) and the date they were sent (not in the future)."""

    model_config = ConfigDict(extra="forbid")

    sent_on: date = Field(description="The date the questions were sent; not in the future.")
    questions: list[QuestionVersion] = Field(min_length=1, max_length=200)


class MarkSentResult(BaseModel):
    """How many questions **Mark sent** marked (Story 4.6)."""

    count: int = Field(ge=0)


QuestionExportFormat = Literal["copy", "docx", "eml"]


class QuestionExportRequest(BaseModel):
    """An export of the approved Clarification Questions (Story 4.6): `copy` (plain text),
    `docx` (Word) or `eml` (an unsent email draft)."""

    model_config = ConfigDict(extra="forbid")

    format: QuestionExportFormat


class QuestionExport(BaseModel):
    """The exported questions (Story 4.6). For `copy`, `text` is the plain text to paste; for
    `docx` and `eml`, `url` (relative to the API origin) is a short-lived signed link to the
    file, downloaded as `file_name`, until `expires_at`. The others are null."""

    format: QuestionExportFormat
    question_count: int = Field(ge=1)
    text: str | None = None
    url: str | None = None
    file_name: str | None = None
    expires_at: datetime | None = None


class ImpactChange(BaseModel):
    """A person's change of an open Gap's impact (Story 4.4), with the reason."""

    model_config = ConfigDict(extra="forbid")

    impact: Impact
    reason: StrictStr = Field(
        description=f"Why the impact changed. Trimmed, it must be 1 to {REASON_MAX} characters."
    )


class GapDismissalRequest(BaseModel):
    """A person's dismissal of an open Gap (Story 4.4). `note` is required for `other` and
    optional for `not_relevant`."""

    model_config = ConfigDict(extra="forbid")

    reason_kind: DismissReasonKind
    note: StrictStr | None = Field(
        default=None,
        description=f"Why it is dismissed. Trimmed, 1 to {REASON_MAX} characters; required "
        "for `other`.",
    )


class GapReopening(BaseModel):
    """A person's reopening of a dismissed Gap (Story 4.4), with the reason."""

    model_config = ConfigDict(extra="forbid")

    reason: StrictStr = Field(
        description=f"Why it is reopened. Trimmed, it must be 1 to {REASON_MAX} characters."
    )


class GapDismissal(BaseModel):
    """Why, by whom and when a Gap was dismissed (Story 4.4). `note` is null for a sales
    representative, and when none was given."""

    reason_kind: DismissReasonKind
    note: str | None
    by: UserRef
    at: datetime


GapHistoryEntryKind = Literal[
    "raised", "impact_changed", "dismissed", "reopened", "converted", "answered"
]


class GapHistoryEntry(BaseModel):
    """One change of a Gap (Story 4.4), oldest first; the first is always `raised` by the
    Clarification Agent at the Gap's `created_at`. `actor` is the person, or `"agent"`.
    `old_impact` / `new_impact` are set for `impact_changed`, `reason_kind` for `dismissed`,
    `reason` (the reason, or the dismissal note) for `impact_changed`, `dismissed` and
    `reopened`; it is null for a sales representative."""

    kind: GapHistoryEntryKind
    at: datetime
    actor: UserRef | Literal["agent"]
    old_impact: Impact | None
    new_impact: Impact | None
    reason_kind: DismissReasonKind | None
    reason: str | None


class IrrelevanceShare(BaseModel):
    """The FR-11 live irrelevance measure (Story 4.4): detected Gaps not superseded, and how
    many of them are dismissed as "Not relevant"."""

    raised: int = Field(ge=0)
    dismissed_not_relevant: int = Field(ge=0)


class AnswerPassage(BaseModel):
    """A Source passage holding a customer's answer (Story 4.7), as Evidence: `label` is
    `S<n> · <file name>`; `excerpt` up to 280 characters of the passage, with `…` when cut
    (empty when its text can't be read)."""

    passage_id: str
    source_id: str
    source_version: int = Field(ge=1)
    filename: str
    label: str
    excerpt: str


class GapAnswer(BaseModel):
    """The customer's answer to the Gap's question (Story 4.7): the date they answered, the
    person who recorded or confirmed it, the answer passage (null if it can't be found) and
    the Requirements that answer's Source added, versioned or proposed changes to."""

    answered_on: date
    answered_by: UserRef
    passage: AnswerPassage | None
    requirement_changes: list[RequirementChangeRef]


class AnswerSuggestion(BaseModel):
    """`clarification_agent`'s suggestion that a passage of a new Source answers the Gap's
    question (Story 4.7): only a person's **Confirm** answers it; **Not an answer** rejects
    it for good. `injection_suspected`: the passage reads like an instruction to the
    platform. `row_version` for `If-Match`."""

    id: str
    question_id: str
    passage: AnswerPassage
    injection_suspected: bool
    row_version: int = Field(ge=1)
    created_at: datetime


class AnswerRequest(BaseModel):
    """**Record answer** (Story 4.7): the customer's answer to a sent question, the date they
    gave it, and whether it settles the Gap (it then becomes `answered` too)."""

    model_config = ConfigDict(extra="forbid")

    text: StrictStr = Field(
        description=f"The customer's answer. Trimmed, it must be 1 to {ANSWER_MAX:,} characters."
    )
    answered_on: date = Field(description="The date the customer answered; not in the future.")
    settles_gap: bool = Field(
        default=True, description="Whether the answer settles the Gap (it becomes `answered`)."
    )


class Gap(BaseModel):
    """A Gap with the Requirements it relates to and its drafted question. `status` is `open`,
    `converted` once an Assumption made from it was accepted (Story 8.4; `converted_to` then
    names the Assumption's kind, `condition` or `contingency`, and is null otherwise),
    `dismissed` (Story 4.4: `dismissal` says why, by whom and when; null otherwise), or
    `answered` (Story 4.7). `answer`: the customer's answer once its question is answered
    (whether or not it settled the Gap), else null; `answer_suggestions`: the open
    suggestions for its question. `history`: its changes, oldest first. `last_changed_by`:
    the person behind its latest change (null until a person changes it)."""

    id: str
    title: str
    category: GapCategory
    trigger: GapTrigger
    why_it_matters: str
    impact: Impact
    impact_basis: str
    origin: GapOrigin
    status: GapStatus
    converted_to: ConvertedTo | None
    row_version: int = Field(ge=1)
    created_at: datetime
    requirements: list[GapRequirement]
    question: ClarificationQuestion | None
    dismissal: GapDismissal | None
    history: list[GapHistoryEntry]
    last_changed_by: UserRef | None
    answer: GapAnswer | None
    answer_suggestions: list[AnswerSuggestion]


class Detection(BaseModel):
    """The Opportunity's latest Gap detection. `error_code` is set only when `failed`."""

    status: DetectionStatus
    error_code: DetectionErrorCode | None


class GapList(BaseModel):
    """The Opportunity's open Gaps, high impact first, then medium, then low, oldest first
    within an impact, followed by its converted Gaps (Story 8.4), then its dismissed Gaps
    (Story 4.4), each group in the same order; and its latest detection (null when none has
    been queued yet). `can_edit_gaps`: whether the caller may change impacts, dismiss and
    reopen Gaps (Story 4.4).
    `can_start_detection`: whether the caller may start (retry) a detection;
    `can_edit_questions`: whether the caller may edit and approve Clarification Questions
    (Story 4.5); `can_send_questions`: whether the caller may export questions, mark them
    sent and "No answer" (Story 4.6), record answers and confirm or reject suggested ones
    (Story 4.7), sales representatives included. The UI only uses them
    to hide controls; the API decides. A sales representative sees only approved, sent and
    unanswered questions: other Gaps come with `question` null."""

    items: list[Gap]
    detection: Detection | None
    can_start_detection: bool
    can_edit_questions: bool
    can_edit_gaps: bool
    can_send_questions: bool
