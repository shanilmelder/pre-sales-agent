"""Read models for Gaps and their Clarification Questions (Story 4.3)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.gaps.domain.gaps import (
    ConvertedTo,
    DetectionErrorCode,
    DetectionStatus,
    GapCategory,
    GapOrigin,
    GapStatus,
    Impact,
    QuestionStatus,
)


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
    id: str
    text: str
    topic: str
    status: QuestionStatus
    status_changed_at: datetime
    row_version: int = Field(ge=1)


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
    `can_start_detection`: whether the caller may start (retry) a detection. The UI only
    uses it to hide controls; the API decides."""

    items: list[Gap]
    detection: Detection | None
    can_start_detection: bool
