"""Read models for the Estimate (Story 8.1). Every number is calculated on the server by
`domain/arithmetic.py`; hours are person-hours with one decimal place."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.estimates.domain.estimates import (
    DraftErrorCode,
    DraftStatus,
    EstimateRole,
    Section,
    VersionStatus,
)


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
    hours, Contingency (the sum of its linked Contingency amounts; 0 until any are linked)
    and total (effort plus Contingency)."""

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


class EstimateVersion(BaseModel):
    """An Estimate Version. `sections`: only those with lines, in template order.
    `totals`: the overall effort, Contingency and total, with the per-role totals.
    `uncovered_count`: active Requirements no line covered when it was drafted;
    `dropped_count`: proposed lines that broke a rule."""

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


class EstimateDraft(BaseModel):
    """The Opportunity's latest Estimate draft. `error_code` is set only when `failed`."""

    status: DraftStatus
    error_code: DraftErrorCode | None


class EstimateView(BaseModel):
    """The Opportunity's current (draft) Estimate Version, null before the first, and its
    latest draft run, null before the first. `can_start_draft`: whether the caller may start
    (retry) a draft. The UI only uses it to hide controls; the API decides."""

    version: EstimateVersion | None
    draft: EstimateDraft | None
    can_start_draft: bool
