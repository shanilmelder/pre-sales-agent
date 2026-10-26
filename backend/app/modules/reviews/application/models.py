"""reviews' API models (Story 9.1)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from app.modules.reviews.domain.requests import (
    MESSAGE_MAX,
    REASON_MAX,
    REVIEWERS_MAX,
    RequestStatus,
    ReviewType,
    TargetKind,
)


class AssessmentRef(BaseModel):
    """One of the Opportunity's current Assessments, at the version the caller saw."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    version: int = Field(ge=1)


class ReviewRequestCreate(BaseModel):
    """Send Review Requests for an Estimate Version: one per reviewer and per picked
    Assessment, or one per reviewer for the whole version when no Assessment is picked."""

    model_config = ConfigDict(extra="forbid")

    version_id: UUID = Field(description="The submitted or in-review Estimate Version.")
    review_type: ReviewType
    reviewer_ids: list[UUID] = Field(
        min_length=1,
        max_length=REVIEWERS_MAX,
        description="The reviewers, each holding the review type's role; not the version's author.",
    )
    assessment_refs: list[AssessmentRef] = Field(
        default_factory=list,
        max_length=10,
        description="Assessments to review; leave empty to review the whole Estimate Version.",
    )
    message: StrictStr | None = Field(
        default=None, description=f"Optional; trimmed, at most {MESSAGE_MAX:,} characters."
    )


class ReviewRequestCancel(BaseModel):
    """Cancel a pending Review Request, with a reason."""

    model_config = ConfigDict(extra="forbid")

    reason: StrictStr = Field(description=f"Why. Trimmed, 1 to {REASON_MAX:,} characters.")


class ReviewPerson(BaseModel):
    id: str
    name: str


class ReviewTarget(BaseModel):
    """What a request asks to review: `kind`, `id`, `version`, and a `label` such as
    "Estimate v3" or "Security Assessment v2"."""

    kind: TargetKind
    id: str
    version: int
    label: str


class ReviewRequestView(BaseModel):
    """A Review Request as the Estimate tab lists it. `row_version` is also the `ETag`
    (`If-Match` of a cancel); `can_cancel`: whether the caller may cancel it now."""

    id: str
    review_type: ReviewType
    target: ReviewTarget
    estimate_version_id: str
    estimate_version: int
    reviewer: ReviewPerson
    requested_by: ReviewPerson
    message: str | None
    status: RequestStatus
    cancel_reason: str | None
    row_version: int
    created_at: datetime
    updated_at: datetime
    can_cancel: bool


class AssessmentOption(BaseModel):
    """A current Assessment that a request may target."""

    id: str
    agent: str
    version: int
    label: str


class ReviewRequestsView(BaseModel):
    """The Review Requests of an Estimate Version, oldest first, the version they are for
    (null before the first version), the current Assessments a new request may target, and
    `can_create`: whether the caller may send requests for this version now."""

    version_id: str | None
    version: int | None
    items: list[ReviewRequestView]
    assessments: list[AssessmentOption]
    can_create: bool


class CreatedReviewRequests(BaseModel):
    """The requests just sent, and the Estimate Version's status and `row_version` now."""

    items: list[ReviewRequestView]
    version_status: str
    version_row_version: int


class OpenReviewRequest(BaseModel):
    """`reviews.public.list_open_requests`: a pending, rejected or challenged request."""

    id: UUID
    review_type: ReviewType
    reviewer_id: UUID
    reviewer_name: str
    status: RequestStatus
    target_kind: TargetKind
    target_id: UUID
    target_version: int
    message: str | None
    created_at: datetime


class ReviewRequestState(BaseModel):
    """`reviews.public.request_status` (Story 9.2): a request's status now, its sender and
    its reviewer."""

    id: UUID
    status: RequestStatus
    requested_by: UUID
    reviewer_id: UUID
