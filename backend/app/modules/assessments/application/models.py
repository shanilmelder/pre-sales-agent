"""Read models for the Red Team Review (Story 6.5) and the specialist Assessments (Epic 5
slice 5A)."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.assessments.domain.assessments import (
    AssessmentAgent,
    AssessmentRunStatus,
    AssessmentStatus,
    AssessmentTaskStatus,
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
    `R<n>`, the Requirement's position among the Opportunity's active Requirements (oldest
    first), or `Superseded` once it is no longer active. `excerpt`: up to 140 characters of
    that version's text, with `…` when cut."""

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


class AssessmentTask(BaseModel):
    """One agent's task in an assessment run. `error_code` is set only when `failed`."""

    agent: AssessmentAgent
    status: AssessmentTaskStatus
    error_code: RunErrorCode | None


class AssessmentRun(BaseModel):
    """An assessment run: its status and one task per agent, in agent order."""

    id: str
    status: AssessmentRunStatus
    created_at: datetime
    tasks: list[AssessmentTask]


class AssessmentFinding(BaseModel):
    """A specialist Finding: its kind, severity, specific title and detail, with the
    Requirements it cites."""

    id: str
    position: int = Field(ge=1)
    kind: FindingKind
    severity: Severity
    title: str
    detail: str
    requirements: list[FindingRequirement]


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


class AssessmentsView(BaseModel):
    """The Opportunity's latest assessment run (null before the first) with its tasks, and
    one entry per agent (Engineering, PM, Security) with its current Assessment or null.
    `can_start`: whether the caller may start a run or retry a task. The UI only uses it to
    hide controls; the API decides."""

    run: AssessmentRun | None
    assessments: list[AgentAssessment]
    can_start: bool
