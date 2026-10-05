"""Read models for Gaps and their Clarification Questions (Story 4.3)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from app.modules.gaps.domain.gaps import (
    QUESTION_MAX,
    TOPIC_MAX,
    ConvertedTo,
    DetectionErrorCode,
    DetectionStatus,
    GapCategory,
    GapOrigin,
    GapStatus,
    Impact,
    QuestionStatus,
)
from app.modules.opportunities.application.public import UserRef


class GapTrigger(BaseModel):
    """What raised the Gap. In the demo, always the agent, by category."""

    kind: Literal["agent_category"]
    category: GapCategory


class GapRequirement(BaseModel):
    """A Requirement the Gap relates to, at the version it was raised against. `label` is
    `R<n>`, the Requirement's position among the Opportunity's active Requirements (oldest
    first), or `Superseded` once it is no longer active. `excerpt`: up to 140 characters of
    that version's text, with `…` when cut."""

    id: str
    version: int = Field(ge=1)
    label: str
    excerpt: str


class ClarificationQuestion(BaseModel):
    """A Gap's Clarification Question. `status` is `drafted` or `approved` (Story 4.5);
    `status_changed_at` moves on every status change. `approved_by` / `approved_at` are set
    only while `approved`. `edited_by_human`: a person changed its text or topic.
    `last_changed_by`: the person behind its latest edit or approval (null for the agent's
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


class Gap(BaseModel):
    """A Gap with the Requirements it relates to and its drafted question. `status` is `open`,
    or `converted` once an Assumption made from it was accepted (Story 8.4); `converted_to`
    then names the Assumption's kind (`condition` or `contingency`), and is null otherwise."""

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


class Detection(BaseModel):
    """The Opportunity's latest Gap detection. `error_code` is set only when `failed`."""

    status: DetectionStatus
    error_code: DetectionErrorCode | None


class GapList(BaseModel):
    """The Opportunity's open Gaps, high impact first, then medium, then low, oldest first
    within an impact, followed by its converted Gaps in the same order (Story 8.4); and its
    latest detection (null when none has been queued yet).
    `can_start_detection`: whether the caller may start (retry) a detection;
    `can_edit_questions`: whether the caller may edit and approve Clarification Questions
    (Story 4.5). The UI only uses them to hide controls; the API decides. A sales
    representative sees only approved questions: other Gaps come with `question` null."""

    items: list[Gap]
    detection: Detection | None
    can_start_detection: bool
    can_edit_questions: bool
