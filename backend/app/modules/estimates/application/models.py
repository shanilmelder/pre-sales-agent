"""Read models for the Estimate (Stories 8.1 and 8.4). Every number is calculated on the
server by `domain/arithmetic.py`; hours are person-hours with one decimal place."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.estimates.domain.assumptions import AssumptionKind, ProposalStatus
from app.modules.estimates.domain.estimates import (
    DraftErrorCode,
    DraftStatus,
    EstimateRole,
    Section,
    VersionStatus,
)
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
    `R<n>`, the Requirement's position among the Opportunity's active Requirements (oldest
    first), or `Superseded` once it is no longer active. `excerpt`: up to 140 characters of
    that version's text, with `…` when cut."""

    id: str
    version: int = Field(ge=1)
    label: str
    excerpt: str


class EstimateLine(BaseModel):
    """A work item: its effort and role mix as drafted, and its server-calculated role
    hours, Contingency (the sum of its linked Contingency Assumptions' hours, accepted or
    not) and total (effort plus Contingency)."""

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


class EstimateSection(BaseModel):
    """A template section with its lines (in position order) and their subtotal."""

    section: Section
    lines: list[EstimateLine]
    subtotal: Totals


class OriginGap(BaseModel):
    """The Gap an Assumption was made from, as it is now. `status` is `open`, `converted`
    (once an Assumption made from it was accepted) or `superseded`."""

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
    `row_version` goes back in `If-Match` to accept it."""

    id: str
    kind: AssumptionKind
    wording: str
    amount_hours: float | None
    line: AssumptionLine | None
    origin_kind: Literal["gap"]
    origin: OriginGap
    accepted_by: UserRef | None
    accepted_at: datetime | None
    row_version: int = Field(ge=1)


class AssumptionGroups(BaseModel):
    """The version's Assumptions in proposal order, grouped by kind. `contingency_hours`: the
    Contingencies' total, accepted or not."""

    conditions: list[Assumption]
    contingencies: list[Assumption]
    contingency_hours: float


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
    the open Gaps without an Assumption in it, once proposals have finished (empty before)."""

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


class EstimateDraft(BaseModel):
    """The Opportunity's latest Estimate draft. `error_code` is set only when `failed`."""

    status: DraftStatus
    error_code: DraftErrorCode | None


class EstimateView(BaseModel):
    """The Opportunity's current (draft) Estimate Version, null before the first, and its
    latest draft run, null before the first. `can_start_draft`: whether the caller may start
    (retry) a draft; `can_accept_assumptions`: whether the caller may accept Assumptions. The
    UI only uses them to hide controls; the API decides."""

    version: EstimateVersion | None
    draft: EstimateDraft | None
    can_start_draft: bool
    can_accept_assumptions: bool


class AcceptAllResult(BaseModel):
    """How many Assumptions were accepted."""

    count: int = Field(ge=0)
