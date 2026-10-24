"""Read models for the Red Team Review (Story 6.5) and the specialist Assessments (Epic 5
slice 5A)."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.assessments.domain.assessments import (
    AssessmentAgent,
    AssessmentStatus,
    Confidence,
    FindingKind,
    Recommendation,
)
from app.modules.assessments.domain.reviews import (
    FindingCategory,
    ReviewStatus,
    RunErrorCode,
    RunStatus,
    Severity,
)


class FindingRequirement(BaseModel):
    """A Requirement a Finding (or an effort row) cites, at the version the agent read. `label` is
    `R<n>`, the Requirement's stable number within the Opportunity, or `Superseded` once it
    is no longer active. `excerpt`: up to 140 characters of that version's text, with `…`
    when cut."""

    id: str
    version: int = Field(ge=1)
    label: str
    excerpt: str


class FindingLine(BaseModel):
    """A line of the reviewed Estimate Version the Finding challenges."""

    id: str
    section: str
    title: str
    effort_hours: float


class RedTeamFinding(BaseModel):
    """A Red Team Finding: its category, severity, specific title and argument, with the
    Requirements and Estimate lines it challenges."""

    id: str
    position: int = Field(ge=1)
    category: FindingCategory
    severity: Severity
    title: str
    argument: str
    requirements: list[FindingRequirement]
    lines: list[FindingLine]


class SeverityCounts(BaseModel):
    critical: int = Field(ge=0)
    high: int = Field(ge=0)
    medium: int = Field(ge=0)
    low: int = Field(ge=0)


class RedTeamReviewView(BaseModel):
    """The Opportunity's current Red Team Review. `findings`: critical first, then high,
    medium and low, then in the order the Red Team raised them. `estimate_version` is the
    number of the Estimate Version reviewed (null when there was none). `dropped_count`:
    proposed Findings that broke a rule."""

    id: str
    version: int = Field(ge=1)
    status: ReviewStatus
    estimate_version_id: str | None
    estimate_version: int | None
    dropped_count: int = Field(ge=0)
    created_at: datetime
    counts: SeverityCounts
    findings: list[RedTeamFinding]


class RedTeamRun(BaseModel):
    """The Opportunity's latest Red Team run. `error_code` is set only when `failed`."""

    status: RunStatus
    error_code: RunErrorCode | None


class RedTeamView(BaseModel):
    """The Opportunity's current Red Team Review (null before the first) and its latest Red
    Team run (null before the first). `can_start`: whether the caller may start (retry) a
    review. The UI only uses it to hide controls; the API decides."""

    review: RedTeamReviewView | None
    run: RedTeamRun | None
    can_start: bool


# --- specialist Assessments (Epic 5 slice 5A) ----------------------------------------------


class AssessmentFinding(BaseModel):
    """A specialist Finding: its kind, severity, specific title and detail, with the
    Requirements it cites. `injection_suspected` (Story 5.4): a cited Requirement's text
    read like an injected instruction when the agent read it (the UI marks the row)."""

    id: str
    position: int = Field(ge=1)
    kind: FindingKind
    severity: Severity
    title: str
    detail: str
    requirements: list[FindingRequirement]
    injection_suspected: bool


class AssessmentEffort(BaseModel):
    """The agent's effort for one Requirement, in person-hours (0.1 h precision)."""

    requirement: FindingRequirement
    hours: float
    basis: str


class AssessmentView(BaseModel):
    """An agent's current Assessment. `findings`: critical first, then high, medium and low,
    then in the order the agent raised them. `effort`: in Requirement order (Requirements
    no longer active last), with `total_hours` their sum, calculated here. `dropped_count`:
    proposed Findings and effort rows that broke a rule."""

    id: str
    agent: AssessmentAgent
    version: int = Field(ge=1)
    status: AssessmentStatus
    run_id: str
    config_version_id: str
    """The Agent Registry config version that produced it (Story 7.1)."""
    recommendation: Recommendation
    confidence: Confidence
    confidence_basis: str
    dropped_count: int = Field(ge=0)
    created_at: datetime
    counts: SeverityCounts
    findings: list[AssessmentFinding]
    effort: list[AssessmentEffort]
    total_hours: float


class AgentAssessment(BaseModel):
    """One agent's slot: its current Assessment, null before its first."""

    agent: AssessmentAgent
    assessment: AssessmentView | None


class OutdatedAssessment(BaseModel):
    """A current Assessment that used a Requirement version that has changed since (Story
    2.7): a newer version, or the Requirement is no longer active. `label`: the agent's role
    in words. `requirement_labels`: those Requirements, `R<n>` in Requirement order (one no
    longer active reads `Superseded`, last)."""

    id: str
    agent: AssessmentAgent
    label: str
    requirement_labels: list[str]


class OutdatedAssessments(BaseModel):
    """The Opportunity's current Assessments that used outdated Requirement versions, in agent
    order (Story 2.7). Empty when none did. Nothing is rerun automatically."""

    items: list[OutdatedAssessment]
