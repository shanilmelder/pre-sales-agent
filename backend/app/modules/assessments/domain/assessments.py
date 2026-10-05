"""Specialist Assessment rules (Epic 5 slice 5A): the agents, run and task states, the
recommendation, confidence, Finding kinds, and the validation of an agent's reply. Pure.

An assessment run has one task per specialist agent. Each succeeded task stores a new
Assessment for its agent (a recommendation, a confidence with its basis, Findings citing
Requirements, and effort per Requirement).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum

from app.modules.assessments.domain.reviews import (
    Severity,
    bounded,
    resolve_labels,
)

ASSESSMENT_SUBJECT_TYPE = "assessments.assessment"
"""The trace subject of an Assessment."""
RUN_SUBJECT_TYPE = "assessments.assessment_run"
"""The trace subject of an assessment run."""


class AssessmentAgent(StrEnum):
    """The specialist agents, in the order they are listed."""

    ENGINEERING = "engineering_agent"
    PM = "pm_agent"
    SECURITY = "security_agent"


AGENTS: tuple[AssessmentAgent, ...] = tuple(AssessmentAgent)


class AssessmentStatus(StrEnum):
    CURRENT = "current"
    SUPERSEDED = "superseded"


class AssessmentRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIALLY_FAILED = "partially_failed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    """Stopped by a person (Story 5.5): set directly by `cancel_run`, never derived from the
    tasks', and final (nothing moves a cancelled run again)."""


RUN_IN_PROGRESS = frozenset({AssessmentRunStatus.QUEUED, AssessmentRunStatus.RUNNING})


class AssessmentTaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    """Unfinished when its run was cancelled (Story 5.5)."""


TASK_IN_PROGRESS = frozenset({AssessmentTaskStatus.QUEUED, AssessmentTaskStatus.RUNNING})


class Recommendation(StrEnum):
    PROCEED = "proceed"
    PROCEED_WITH_CONDITIONS = "proceed_with_conditions"
    DO_NOT_PROCEED = "do_not_proceed"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FindingKind(StrEnum):
    RISK = "risk"
    CONSTRAINT = "constraint"
    DEPENDENCY = "dependency"
    OPPORTUNITY = "opportunity"


def run_status(tasks: Iterable[AssessmentTaskStatus]) -> AssessmentRunStatus:
    """A run's status from its tasks': `queued` while every task is queued, `running` while
    any is still queued or running, then `succeeded` when all succeeded, `failed` when none
    did, otherwise `partially_failed`. A `cancelled` run is never derived: `cancel_run` sets it."""
    statuses = list(tasks)
    if statuses and all(s == AssessmentTaskStatus.QUEUED for s in statuses):
        return AssessmentRunStatus.QUEUED
    if any(s in TASK_IN_PROGRESS for s in statuses):
        return AssessmentRunStatus.RUNNING
    succeeded = sum(1 for s in statuses if s == AssessmentTaskStatus.SUCCEEDED)
    if succeeded == len(statuses):
        return AssessmentRunStatus.SUCCEEDED
    if succeeded == 0:
        return AssessmentRunStatus.FAILED
    return AssessmentRunStatus.PARTIALLY_FAILED


# --- validating an agent's reply ------------------------------------------------------------

CONFIDENCE_BASIS_MAX = 500
TITLE_MAX = 160
DETAIL_MAX = 800
EFFORT_BASIS_MAX = 300
"""Limits in Unicode code points, on the trimmed text."""
HOURS_MIN = Decimal("0.5")
HOURS_MAX = Decimal("2000")
HOURS_STEP = Decimal("0.1")


@dataclass(frozen=True, slots=True)
class AssessmentFindingCandidate:
    """One Finding as the agent proposed it, before validation."""

    kind: str
    severity: str
    title: str = field(repr=False)
    detail: str = field(repr=False)
    requirements: tuple[str, ...]
    """Requirement labels, `R<n>`."""


@dataclass(frozen=True, slots=True)
class EffortCandidate:
    """One effort row as the agent proposed it, before validation."""

    requirement: str
    hours: float
    basis: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class AssessmentCandidate:
    recommendation: str
    confidence: str
    confidence_basis: str = field(repr=False)
    findings: Sequence[AssessmentFindingCandidate] = ()
    effort: Sequence[EffortCandidate] = ()


@dataclass(frozen=True, slots=True)
class ValidAssessmentFinding[R]:
    kind: FindingKind
    severity: Severity
    title: str = field(repr=False)
    detail: str = field(repr=False)
    requirements: tuple[R, ...]
    """The resolved Requirements, without duplicates, in the order cited."""


@dataclass(frozen=True, slots=True)
class ValidEffort[R]:
    requirement: R
    hours: Decimal
    """Rounded to 0.1 h."""
    basis: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class AssessmentValidation[R]:
    recommendation: Recommendation
    confidence: Confidence
    confidence_basis: str = field(repr=False)
    findings: tuple[ValidAssessmentFinding[R], ...] = ()
    effort: tuple[ValidEffort[R], ...] = ()
    dropped_findings: int = 0
    """Findings dropped: an unknown kind or severity, a title or detail missing, blank or
    too long, or no Requirement label that resolves."""
    dropped_effort: int = 0
    """Effort rows dropped: a label that doesn't resolve, a Requirement already sized, hours
    out of range, or a basis missing, blank or too long."""

    @property
    def dropped(self) -> int:
        return self.dropped_findings + self.dropped_effort


def hours_value(raw: float) -> Decimal | None:
    """`raw` rounded to 0.1 h, or None when it isn't a number between 0.5 and 2,000 h."""
    try:
        value = Decimal(str(raw)).quantize(HOURS_STEP, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite() or not HOURS_MIN <= value <= HOURS_MAX:
        return None
    return value


def validate_assessment_finding[R](
    candidate: AssessmentFindingCandidate, requirements: Mapping[str, R]
) -> ValidAssessmentFinding[R] | None:
    """The Finding checked against the rules, its labels resolved through `requirements`;
    None if it breaks a rule. Labels that don't resolve are ignored as long as one does."""
    try:
        kind = FindingKind(candidate.kind.strip())
        severity = Severity(candidate.severity.strip())
    except ValueError:
        return None
    title = bounded(candidate.title, TITLE_MAX)
    detail = bounded(candidate.detail, DETAIL_MAX)
    cited = resolve_labels(candidate.requirements, requirements)
    if title is None or detail is None or not cited:
        return None
    return ValidAssessmentFinding(
        kind=kind, severity=severity, title=title, detail=detail, requirements=cited
    )


def validate_assessment[R](
    candidate: AssessmentCandidate, requirements: Mapping[str, R]
) -> AssessmentValidation[R] | None:
    """The reply checked against the rules; None (the reply is invalid) when its
    recommendation, confidence or confidence basis is missing or invalid. Invalid Findings
    and effort rows are dropped and counted; the caller decides what an Assessment without
    a valid Finding means."""
    try:
        recommendation = Recommendation(candidate.recommendation.strip())
        confidence = Confidence(candidate.confidence.strip())
    except ValueError:
        return None
    basis = bounded(candidate.confidence_basis, CONFIDENCE_BASIS_MAX)
    if basis is None:
        return None

    findings: list[ValidAssessmentFinding[R]] = []
    dropped_findings = 0
    for proposed in candidate.findings:
        valid = validate_assessment_finding(proposed, requirements)
        if valid is None:
            dropped_findings += 1
        else:
            findings.append(valid)

    effort: list[ValidEffort[R]] = []
    sized: list[R] = []
    dropped_effort = 0
    for row in candidate.effort:
        requirement = requirements.get(row.requirement.strip())
        hours = hours_value(row.hours)
        row_basis = bounded(row.basis, EFFORT_BASIS_MAX)
        if requirement is None or requirement in sized or hours is None or row_basis is None:
            dropped_effort += 1
            continue
        sized.append(requirement)
        effort.append(ValidEffort(requirement=requirement, hours=hours, basis=row_basis))

    return AssessmentValidation(
        recommendation=recommendation,
        confidence=confidence,
        confidence_basis=basis,
        findings=tuple(findings),
        effort=tuple(effort),
        dropped_findings=dropped_findings,
        dropped_effort=dropped_effort,
    )


def total_hours(hours: Iterable[Decimal]) -> Decimal:
    """The sum, to 0.1 h."""
    return sum(hours, Decimal("0")).quantize(HOURS_STEP, rounding=ROUND_HALF_UP)
