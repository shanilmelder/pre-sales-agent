"""Read models for the Red Team Review (Story 6.5), the Critic Review (Story 6.4), their
Findings' statuses, resolutions and overrides (Story 6.6), and the specialist Assessments
(Epic 5 slice 5A)."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.assessments.domain.assessments import (
    AssessmentAgent,
    AssessmentStatus,
    Confidence,
    FindingKind,
    Recommendation,
)
from app.modules.assessments.domain.critic import CriticCategory
from app.modules.assessments.domain.findings import (
    EVIDENCE_MAX,
    FindingStatus,
    ResolutionKind,
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


# --- Finding status, resolution and override (Story 6.6) -----------------------------------

OverrideBasisName = Literal["owner", "head_of_delivery", "security_reviewer"]


class FindingPerson(BaseModel):
    """A person who resolved or overrode a Finding: their user id and name."""

    id: str
    name: str


class FindingEvidence(BaseModel):
    """An Evidence reference supplied to resolve a Finding: `requirement` (`label` `R<n>`, or
    `Superseded` once no longer active) or `source_document` (`S<n> · <file name>`)."""

    kind: str
    id: str
    version: int | None
    label: str


class FindingResolution(BaseModel):
    """How a `resolved` Finding was resolved: Evidence supplied (with the person's note as
    `reason`) or addressed with a reason; by whom and when."""

    kind: ResolutionKind
    reason: str
    by: FindingPerson
    at: datetime
    evidence: list[FindingEvidence]


class FindingOverride(BaseModel):
    """An override: who, when and why, the Review version of the Finding it overrode, and the
    grant that allowed it (`owner`, `head_of_delivery` or `security_reviewer`)."""

    id: str
    reason: str
    by: FindingPerson
    at: datetime
    review_version: int = Field(ge=1)
    policy_basis: OverrideBasisName


class PolicyRef(BaseModel):
    """The mandatory item of a `security` Checklist version a Finding is tied to (decided by
    code): such a Finding can't be overridden by any role."""

    kind: Literal["checklist_item"]
    checklist_id: str
    version: int
    item_id: str


class FindingState(BaseModel):
    """A Critic or Red Team Finding's status and what the caller may do with it.

    - `status`: `open`, `resolved` or `overridden`. An open `critical` Finding of a current
      Review blocks submission.
    - `resolution` (when resolved), `override` (when overridden).
    - `previous_override`: the override of an earlier Finding with the same fingerprint
      (shown, never applied: this Finding starts `open`).
    - `overridable`: false when `policy_ref` ties it to a mandatory security Checklist item.
    - `can_resolve`, `can_override`: whether the caller may now supply Evidence or mark it
      resolved, and override (or re-apply the previous override). The UI only uses them to
      hide controls; the API decides.
    - `row_version`: for `If-Match`."""

    id: str
    status: FindingStatus
    resolution: FindingResolution | None
    override: FindingOverride | None
    previous_override: FindingOverride | None
    policy_ref: PolicyRef | None
    overridable: bool
    can_resolve: bool
    can_override: bool
    row_version: int = Field(ge=1)


REASON_BACKSTOP = 4000
"""A request-size backstop on a reason or note; the 1-1,000 rule is checked after (422)."""


class EvidenceRefIn(BaseModel):
    """An Evidence reference to cite: `requirement` or `source_document`, with its id and
    version (as the Evidence picker lists them)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["requirement", "source_document"]
    id: UUID
    version: int = Field(ge=1, le=2**31 - 1)

    @property
    def span(self) -> None:
        """No span: a whole Requirement version or Source version is cited."""
        return None


class FindingEvidenceSubmission(BaseModel):
    """Supply Evidence: 1-20 references and a note (1-1,000 characters)."""

    model_config = ConfigDict(extra="forbid")

    refs: list[EvidenceRefIn] = Field(min_length=1, max_length=EVIDENCE_MAX)
    note: str = Field(max_length=REASON_BACKSTOP)


class FindingReason(BaseModel):
    """Mark resolved or override: a reason (1-1,000 characters)."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(max_length=REASON_BACKSTOP)


@dataclass(frozen=True, slots=True)
class BlockingFinding:
    """An `open`, `critical` Finding of a current Critic or Red Team Review: it blocks
    submission (`assessments.get_blocking_findings`, for Epic 8's submission blockers)."""

    finding_id: UUID
    review_kind: str
    review_version: int
    title: str = field(repr=False)


class RedTeamFinding(FindingState):
    """A Red Team Finding: its category, severity, specific title and argument, with the
    Requirements and Estimate lines it challenges, and (Story 6.6) its status."""

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
    review. The UI only uses it to hide controls; the API decides. `blocking_count` (Story
    6.6): the Review's open critical Findings."""

    review: RedTeamReviewView | None
    run: RedTeamRun | None
    can_start: bool
    blocking_count: int = Field(ge=0)


# --- the Critic Review (Story 6.4) ---------------------------------------------------------


class CitedFinding(BaseModel):
    """A specialist Finding a Critic Finding cites, at the Assessment version it was read:
    the agent and its role in words, the Assessment's id and version, and the Finding's
    title."""

    id: str
    agent: AssessmentAgent
    role: str
    assessment_id: str
    assessment_version: int = Field(ge=1)
    title: str


class CriticFinding(FindingState):
    """A Critic Finding: its category, severity, specific title and argument, with the
    Requirements and the specialist Findings it cites, and (Story 6.6) its status."""

    position: int = Field(ge=1)
    category: CriticCategory
    severity: Severity
    title: str
    argument: str
    requirements: list[FindingRequirement]
    findings: list[CitedFinding]


class CriticReviewView(BaseModel):
    """The Opportunity's current Critic Review. `findings`: critical first, then high, medium
    and low, then in the order they were raised (code-written coverage Findings last).
    `run_id`: the assessment run reviewed. `dropped_count`: proposed Findings that broke a
    rule."""

    id: str
    version: int = Field(ge=1)
    status: ReviewStatus
    run_id: str | None
    dropped_count: int = Field(ge=0)
    created_at: datetime
    counts: SeverityCounts
    findings: list[CriticFinding]


class CriticView(BaseModel):
    """The Opportunity's current Critic Review, null before the first. `blocking_count`
    (Story 6.6): its open critical Findings."""

    review: CriticReviewView | None
    blocking_count: int = Field(ge=0)


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
