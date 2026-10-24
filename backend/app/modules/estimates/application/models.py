"""Read models for the Estimate (Stories 8.1, 8.4 and 8.5). Every number is calculated on the
server by `domain/arithmetic.py`; hours are person-hours with one decimal place."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr

from app.modules.conflicts.application.public import ConflictType
from app.modules.estimates.domain.assumptions import AssumptionKind, ProposalStatus
from app.modules.estimates.domain.estimates import (
    DraftErrorCode,
    DraftStatus,
    EstimateRole,
    Section,
    VersionSource,
    VersionStatus,
)
from app.modules.estimates.domain.risks import RiskLevel
from app.modules.gaps.application.public import GapCategory, Impact
from app.modules.opportunities.application.public import UserRef


class RoleMix(BaseModel):
    """Each role's share of a line's effort, in whole percent, summing to 100."""

    engineer: int = Field(ge=0, le=100)
    project_manager: int = Field(ge=0, le=100)
    qa: int = Field(ge=0, le=100)


class RoleHours(BaseModel):
    """Hours per role (0.1 h), summing exactly to the effort they split."""

    engineer: float
    project_manager: float
    qa: float


class Totals(BaseModel):
    """Effort, Contingency and total hours, and the effort per role."""

    effort_hours: float
    contingency_hours: float
    total_hours: float
    role_hours: RoleHours


class LineRequirement(BaseModel):
    """A Requirement the line covers, at the version it was drafted against. `label` is
    `R<n>`, the Requirement's stable number within the Opportunity, or `Superseded` once it
    is no longer active. `excerpt`: up to 140 characters of that version's text, with `…`
    when cut."""

    id: str
    version: int = Field(ge=1)
    label: str
    excerpt: str


class LineConflict(BaseModel):
    """An open or escalated `effort` or `scope` Conflict whose positions cite a Requirement
    the line covers (Story 8.3): its id and type. The UI marks the line "Open Conflict" and
    links to the Conflicts tab."""

    id: str
    type: ConflictType


class EstimateLine(BaseModel):
    """A work item: its effort and role mix (as drafted, or as a person last edited them),
    and its server-calculated role hours, Contingency (the sum of its linked Contingency
    Assumptions' hours, accepted or not) and total (effort plus Contingency).

    Story 8.2: `row_version` goes back in `If-Match` to edit it. `edited` is true once a
    person changed its effort or role mix (here, or on the earlier version a re-draft
    carried the edit from: `edit_carried_from_version`); `edited_by_name`, `edited_at` and
    `edit_reason` say who, when and why (null when not edited)."""

    id: str
    position: int = Field(ge=1)
    section: Section
    title: str
    basis: str
    role_mix: RoleMix
    effort_hours: float
    contingency_hours: float
    total_hours: float
    role_hours: RoleHours
    requirements: list[LineRequirement]
    row_version: int = Field(ge=1)
    edited: bool
    edited_by_name: str | None
    edited_at: datetime | None
    edit_reason: str | None
    edit_carried_from_version: int | None
    conflicts: list[LineConflict] = Field(
        description="Story 8.3: the open Conflicts about the Requirements it covers."
    )


class EstimateSection(BaseModel):
    """A template section with its lines (in position order) and their subtotal."""

    section: Section
    lines: list[EstimateLine]
    subtotal: Totals


class OriginGap(BaseModel):
    """The Gap an Assumption or a Risk was made from, as it is now. `status` is `open`,
    `converted` (converted to an Assumption, accepted or since edited, or to a Risk) or
    `superseded`."""

    id: str
    title: str
    category: GapCategory
    impact: Impact
    why_it_matters: str
    status: Literal["open", "superseded", "converted"]


class AssumptionLine(BaseModel):
    """The Estimate line a Contingency is linked to."""

    id: str
    title: str


class Assumption(BaseModel):
    """An Assumption of the version: a `condition` (proposal-ready wording, no hours) or a
    `contingency` (`amount_hours`, and the line it is linked to, if any), made from one Gap
    (`origin`). `accepted_by` and `accepted_at` are null until someone accepts it.
    `row_version` goes back in `If-Match` to accept or edit it. `carried_from_version`: the
    number of the earlier version a re-draft carried this Assumption from (Story 8.7), null
    for a proposal.

    Story 8.5: `position` is its register number (`A{position}`); `origin_superseded` is true
    when the Gap is no longer `open` or `converted`, or is open but changed since the
    Assumption was made from it; `origin_is_unknown` is true when the Gap is an Unknown (its
    why it matters opens with "Unknown to the customer:")."""

    id: str
    position: int = Field(ge=1)
    kind: AssumptionKind
    wording: str
    amount_hours: float | None
    line: AssumptionLine | None
    origin_kind: Literal["gap"]
    origin: OriginGap
    origin_superseded: bool
    origin_is_unknown: bool
    accepted_by: UserRef | None
    accepted_at: datetime | None
    row_version: int = Field(ge=1)
    carried_from_version: int | None


class AssumptionGroups(BaseModel):
    """The version's Assumptions in proposal order, grouped by kind. `contingency_hours`: the
    Contingencies' total, accepted or not."""

    conditions: list[Assumption]
    contingencies: list[Assumption]
    contingency_hours: float


class Risk(BaseModel):
    """A Risk of the version (Story 8.5), made from one Gap (`origin`, with
    `origin_superseded` as for an Assumption): a description, a likelihood and an impact. It
    is never accepted and never blocks submission. `position` is its number (`R{position}`);
    `row_version` goes back in `If-Match` to edit it; `carried_from_version`: the number of the
    earlier version a re-draft carried it from, null otherwise."""

    id: str
    position: int = Field(ge=1)
    description: str
    likelihood: RiskLevel
    impact: RiskLevel
    origin_kind: Literal["gap"]
    origin: OriginGap
    origin_superseded: bool
    row_version: int = Field(ge=1)
    carried_from_version: int | None


class AssumptionCounts(BaseModel):
    total: int = Field(ge=0)
    accepted: int = Field(ge=0)
    not_accepted: int = Field(ge=0)


class UnconvertedGap(BaseModel):
    """An open Gap that has no Assumption in this version."""

    id: str
    title: str
    category: GapCategory
    impact: Impact


class EstimateVersion(BaseModel):
    """An Estimate Version. `sections`: only those with lines, in template order.
    `totals`: the overall effort, Contingency and total, with the per-role totals; the
    Contingency includes every Contingency Assumption, accepted or not, and
    `unallocated_contingency_hours` (those linked to no line, in no section).
    `uncovered_count`: active Requirements no line covered when it was drafted;
    `dropped_count`: proposed lines that broke a rule.

    Story 8.4: `proposal_status` is the state of the version's Assumption proposals (null
    when none were queued); `assumptions` and `counts` its Assumptions; `unconverted_gaps`
    the open Gaps without an Assumption in it, once proposals have finished (empty before).

    Story 8.2: `uncarried_edit_count` is how many edited lines of the superseded draft (number
    `uncarried_edits_from_version`, null when the count is 0) had no matching line here; they
    stay in that version and the Trace.

    Story 8.3: `source` is `assessments` for a version built from the specialist Assessments
    when an assessment run finished (`source_run`, that run's number), `model` for an
    accepted model draft.

    Story 8.5: `risks` are its Risks, impact high first, then likelihood high first."""

    id: str
    version: int = Field(ge=1)
    status: VersionStatus
    template_version: str
    roles: list[EstimateRole]
    uncovered_count: int = Field(ge=0)
    dropped_count: int = Field(ge=0)
    row_version: int = Field(ge=1)
    created_at: datetime
    sections: list[EstimateSection]
    totals: Totals
    proposal_status: ProposalStatus | None
    assumptions: AssumptionGroups
    counts: AssumptionCounts
    unconverted_gaps: list[UnconvertedGap]
    unallocated_contingency_hours: float
    risks: list[Risk]
    uncarried_edit_count: int = Field(ge=0)
    uncarried_edits_from_version: int | None
    source: VersionSource
    source_run: int | None = Field(
        description="Story 8.3: for a version from the Assessments, the number of the "
        "assessment run it was built for (the Opportunity's runs, oldest first).",
    )
    submitted_at: datetime | None = Field(
        default=None,
        description="Story 8.6: when it was submitted; null for a version never submitted.",
    )


class EstimateDraft(BaseModel):
    """The Opportunity's latest Estimate draft. `error_code` is set only when `failed`."""

    status: DraftStatus
    error_code: DraftErrorCode | None


class CurrentEstimate(BaseModel):
    """An Opportunity's current Estimate Version number, its status (draft, or submitted:
    Story 8.6) and its total hours, Contingency included, for the Opportunity list."""

    version: int
    status: VersionStatus
    total_hours: float


BlockerKind = Literal[
    "gap", "assumption", "conflict", "finding", "uncovered_requirement", "review_request"
]


class Blocker(BaseModel):
    """One thing that stands between an Estimate Version and its submission (Story 8.6):
    its `kind`, the id of its subject (a Gap, Assumption, Conflict, Finding or Requirement),
    a short `title` and `detail` to show, and `href`, the web path that opens it."""

    kind: BlockerKind
    subject_id: str
    title: str
    detail: str
    href: str


class SubmissionBlockers(BaseModel):
    """`estimates.get_submission_blockers`, the only check of submittability (AD-27).
    `to_submit`: open Gaps (and Unknowns), unaccepted Assumptions, open and escalated
    Conflicts, open critical Findings of the current Critic and Red Team Reviews, and active
    Requirements no line covers, in that order; the version can be submitted when it is
    empty. `to_baseline` (Story 9.1): the version's pending, rejected and challenged Review
    Requests."""

    to_submit: list[Blocker]
    to_baseline: list[Blocker]


class SubmissionVersion(BaseModel):
    """The current Estimate Version the blockers are for: its id, number, status and
    `row_version` (the `If-Match` of a submission)."""

    id: str
    version: int = Field(ge=1)
    status: VersionStatus
    row_version: int = Field(ge=1)
    created_at: datetime
    submitted_at: datetime | None


class SubmissionBlockersView(SubmissionBlockers):
    """The Opportunity's submission blockers (`GET …/submission-blockers`) for the Overview
    card and the header: the blockers, the current version (the draft, else the latest
    submitted; null before the first) and `can_submit`: whether the caller may submit and
    that version is a draft (the blockers still decide; the API re-checks them)."""

    version: SubmissionVersion | None
    can_submit: bool


class EstimateView(BaseModel):
    """The Opportunity's current Estimate Version (its draft, else its latest submitted one:
    Story 8.6), null before the first, and its
    latest draft run, null before the first. `can_start_draft`: whether the caller may start
    (retry) a draft; `can_accept_assumptions`: whether the caller may accept Assumptions;
    `can_export`: whether the caller may export the Estimate (Story 8.8); `can_edit_lines`:
    whether the caller may edit the draft's lines (Story 8.2); `assessment_running` (Story
    8.3): whether an assessment run is queued or running; `can_edit_assumptions`,
    `can_create_risks` and `can_edit_risks` (Story 8.5): whether the caller may edit
    Assumptions, convert Gaps to Risks and edit Risks. The UI only uses them to hide
    controls; the API decides (and no version but the draft can be changed)."""

    version: EstimateVersion | None
    draft: EstimateDraft | None
    can_start_draft: bool
    can_accept_assumptions: bool
    can_export: bool
    can_edit_lines: bool
    can_edit_assumptions: bool
    can_create_risks: bool
    can_edit_risks: bool
    assessment_running: bool = Field(
        description="Story 8.3: whether an assessment run of the Opportunity is queued or "
        "running (the Estimate is built when it finishes).",
    )
    blockers: SubmissionBlockers = Field(
        description="Story 8.6: the current version's submission blockers."
    )
    can_submit: bool = Field(
        description="Story 8.6: whether the caller may submit and the current version is a "
        "draft. Submit is offered only while `blockers.to_submit` is empty; the API re-checks."
    )
    can_request_review: bool = Field(
        default=False,
        description="Story 9.1: whether the caller may send Review Requests and the current "
        "version is submitted or in review.",
    )


class EstimateLineChanges(BaseModel):
    """A person's edit of an Estimate line (Story 8.2): new effort and/or role mix (at least
    one), and why. Fields left out stay as they are."""

    model_config = ConfigDict(extra="forbid")

    effort_hours: StrictInt | StrictFloat | None = Field(
        default=None,
        description="The new effort in hours, 0 to 2,000; rounded half up to 0.1.",
    )
    role_mix: dict[str, object] | None = Field(
        default=None,
        description="The new role mix: a whole percentage (0-100) for exactly each of the "
        "template's roles (`engineer`, `project_manager`, `qa`), summing to 100.",
    )
    reason: StrictStr = Field(description="Why. Trimmed, it must be 1 to 300 characters.")


class SubmittedVersion(BaseModel):
    """A submitted Estimate Version (Story 8.6): its id, number, `submitted` status and new
    `row_version`, and how many earlier submitted versions it superseded."""

    id: str
    version: int = Field(ge=1)
    status: VersionStatus
    row_version: int = Field(ge=1)
    superseded_count: int = Field(ge=0)


class AcceptAllResult(BaseModel):
    """How many Assumptions were accepted."""

    count: int = Field(ge=0)


class AssumptionChanges(BaseModel):
    """A person's edit of an Assumption (Story 8.5): its kind, wording, hours and line, and
    why. Fields left out stay as they are; `amount_hours` and `line_id` may be null (a
    Condition has neither; a Contingency with no line is Unallocated). The whole result must
    keep the Story 8.4 rules."""

    model_config = ConfigDict(extra="forbid")

    kind: AssumptionKind | None = Field(default=None, description="`condition` or `contingency`.")
    wording: StrictStr | None = Field(
        default=None, description="Proposal-ready wording; trimmed, 1 to 500 characters."
    )
    amount_hours: StrictInt | StrictFloat | None = Field(
        default=None,
        description="A Contingency's hours, 0.5 to 1,000, rounded half up to 0.1; null for a "
        "Condition.",
    )
    line_id: UUID | None = Field(
        default=None,
        description="The line of this version a Contingency is linked to; null for none "
        "(Unallocated) and for a Condition.",
    )
    reason: StrictStr = Field(description="Why. Trimmed, it must be 1 to 300 characters.")


class RiskCreate(BaseModel):
    """Convert an open Gap to a Risk of the current draft (Story 8.5)."""

    model_config = ConfigDict(extra="forbid")

    gap_id: UUID
    description: StrictStr = Field(description="Trimmed, 1 to 500 characters.")
    likelihood: RiskLevel
    impact: RiskLevel


class RiskChanges(BaseModel):
    """A person's edit of a Risk (Story 8.5); fields left out stay as they are."""

    model_config = ConfigDict(extra="forbid")

    description: StrictStr | None = Field(default=None, description="Trimmed, 1 to 500 characters.")
    likelihood: RiskLevel | None = None
    impact: RiskLevel | None = None
    reason: StrictStr = Field(description="Why. Trimmed, it must be 1 to 300 characters.")
