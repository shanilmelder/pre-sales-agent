"""reviews' API models (Stories 9.1, 9.3 and 9.4)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from app.modules.assessments.application.public import AssessmentView
from app.modules.estimates.application.public import EstimateVersion, VersionDiff
from app.modules.reviews.domain.decisions import Decision
from app.modules.reviews.domain.replies import REPLY_EVIDENCE_MAX, REPLY_MAX
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


REASON_BACKSTOP = 4000
"""A request-size backstop on a decision's reason; the 1,000 rule is checked after (422)."""


class ReviewDecisionCreate(BaseModel):
    """Record a Review Decision. Every decision but `approved` needs a reason (1 to 1,000
    characters, trimmed); `escalated_to` (the user who then holds the request) is required
    for, and only for, `escalated`. `challenged` arrives with Story 9.5."""

    model_config = ConfigDict(extra="forbid")

    decision: Decision
    reason: StrictStr | None = Field(
        default=None,
        max_length=REASON_BACKSTOP,
        description=f"Why. Trimmed, at most {REASON_MAX:,} characters; optional to approve.",
    )
    escalated_to: UUID | None = Field(
        default=None, description="Escalate only: the reviewer to hand the request to."
    )


class ReviewDecisionView(BaseModel):
    """A Review Decision: what was decided (`label` in words), why, by whom, when, on which
    version of the target, and for an escalation who the request went to."""

    id: str
    decision: Decision
    label: str
    reason: str | None
    decided_by: ReviewPerson
    escalated_to: ReviewPerson | None
    target_version: int
    decided_at: datetime


class ReviewRequestView(BaseModel):
    """A Review Request as the Estimate tab lists it. `row_version` is also the `ETag`
    (`If-Match` of a cancel or a decision); `can_cancel`: whether the caller may cancel it
    now; `latest_decision` (Story 9.3): its most recent Review Decision, null before the
    first."""

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
    latest_decision: ReviewDecisionView | None = None
    linked_request_id: str | None = Field(
        description="Story 9.4: the request on an older version this one is the alternative to.",
    )


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
    superseded_by: int | None = None
    """Story 9.4: for a superseded request, the number of the version that replaced it."""


class RecordedDecision(BaseModel):
    """Story 9.3: the decision just recorded, the request as it is now (its new `row_version`
    is also the `ETag`), and the status of the Estimate Version it counts towards."""

    decision: ReviewDecisionView
    request: ReviewRequestView
    version_status: str


# --- replies (Story 9.4) --------------------------------------------------------------------


class ReplyEvidenceIn(BaseModel):
    """Evidence to cite in a reply: a Requirement or a Source document of the Opportunity, with
    its id and version (as the Evidence picker lists them)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["requirement", "source_document"]
    id: UUID
    version: int = Field(ge=1, le=2**31 - 1)

    @property
    def span(self) -> None:
        """No span: a whole Requirement version or Source version is cited."""
        return None


class ReviewReplyCreate(BaseModel):
    """Reply to the reviewer's request for evidence or an alternative: a message (1 to 2,000
    characters, trimmed), up to 20 Evidence references and, after `alternative_requested`
    only, this Opportunity's draft Estimate Version (numbered above the one under review) as
    the alternative."""

    model_config = ConfigDict(extra="forbid")

    message: StrictStr = Field(
        max_length=4 * REPLY_MAX, description=f"Trimmed, 1 to {REPLY_MAX:,} characters."
    )
    evidence: list[ReplyEvidenceIn] = Field(default_factory=list, max_length=REPLY_EVIDENCE_MAX)
    alternative_version_id: UUID | None = Field(
        default=None, description="The draft Estimate Version offered as the alternative."
    )


class ReviewEvidence(BaseModel):
    """Evidence cited in a reply, with its label: `R<n>` (`Superseded` once no longer active)
    or `S<n> · <file name>`."""

    kind: str
    id: str
    version: int | None
    label: str


class VersionRef(BaseModel):
    """An Estimate Version by id and number."""

    id: str
    version: int


class LinkedRequest(BaseModel):
    """The request a linked one is the alternative to, and the number of its version."""

    id: str
    version_number: int


class ReviewReplyView(BaseModel):
    """A reply: the message, its Evidence, the alternative draft it names (if any), who
    replied and when."""

    id: str
    message: str
    evidence: list[ReviewEvidence]
    alternative: VersionRef | None
    replied_by: ReviewPerson
    replied_at: datetime


class RecordedReply(BaseModel):
    """The reply just recorded and the request as it is now (still `pending`; its new
    `row_version` is also the `ETag`)."""

    reply: ReviewReplyView
    request: ReviewRequestView


class ReviewPanel(BaseModel):
    """Story 9.3: the review panel of one Review Request.

    - `request` (with its message, sender, status and `row_version`), the Opportunity's
      title, and its `decisions`, newest first.
    - `version_status`: the status of the Estimate Version the request counts towards;
      `superseded_by`: the number of the version that replaced it, null unless superseded.
    - `can_decide`: whether the caller may record a decision now (the request's current
      reviewer, holding the review type's role, on a pending request); `can_approve`:
      whether Approve is among them, else `approve_blocked_reason` says why (the author).
    - `escalation_candidates`: who an escalation may go to (holding the type's role, minus
      the author and the current reviewer); empty unless `can_decide`.
    - The target: an Estimate Version's lines, totals, Assumptions Register and Risks
      (`estimate`) with its `diff` against the version before; or an Assessment at that
      version (`assessment`) with its Findings and their Evidence. The other side is null.

    Story 9.4, the author's side:

    - `is_author`: the caller sent the request or owns the Opportunity (and isn't its
      reviewer); `can_reply`: they may reply now (the latest decision requests evidence or an
      alternative, on a pending request); `can_link_alternative`: the reply may name
      `alternative_draft` (the Opportunity's draft, numbered above this version) as the
      alternative; `can_create_version`: they may start a new draft from this rejected or
      approved version.
    - `replies`, newest first, with their Evidence labels; `linked_request`: the request this
      one is the alternative to; `escalated_to`: who the latest escalation handed it to.

    The UI only uses the flags to show or hide controls; the API decides."""

    request: ReviewRequestView
    opportunity_title: str | None
    decisions: list[ReviewDecisionView]
    version_status: str
    superseded_by: int | None
    can_decide: bool
    can_approve: bool
    approve_blocked_reason: str | None
    escalation_candidates: list[ReviewPerson]
    estimate: EstimateVersion | None
    diff: VersionDiff | None
    assessment: AssessmentView | None
    is_author: bool
    can_reply: bool
    can_link_alternative: bool
    can_create_version: bool
    alternative_draft: VersionRef | None
    replies: list[ReviewReplyView]
    linked_request: LinkedRequest | None
    escalated_to: ReviewPerson | None
