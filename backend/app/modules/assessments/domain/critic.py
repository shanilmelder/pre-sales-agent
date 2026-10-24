"""Critic Review rules (Story 6.4): the Critic's Finding categories, the coverage computation,
the validation of its proposed Findings and the coverage backstop. Pure.

- **Coverage** is computed by code before the agent is called: the active Requirements that
  no Finding and no effort row of the run's Assessments cites (by Requirement id).
- **Finding rules:** a known category and severity, a title of 1-160 and an argument of
  1-800 code points (trimmed), and at least one cited `F<n>` or `R<n>` that resolves. A
  `coverage` Finding must cite an uncovered Requirement. Labels that don't resolve are
  ignored as long as one does; invalid Findings are dropped and counted.
- **Backstop:** each uncovered Requirement no valid `coverage` Finding cites gets a
  code-written `coverage` Finding (`medium`, "No specialist Assessment covers R<n>").
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from app.modules.assessments.domain.reviews import (
    ARGUMENT_MAX,
    TITLE_MAX,
    Severity,
    bounded,
    resolve_labels,
)

CRITIC_AGENT = "critic_agent"
"""The Agent that reviews a run's Assessments; its config comes from the Agent Registry."""


class CriticCategory(StrEnum):
    COVERAGE = "coverage"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    TIMELINE = "timeline"
    DEPENDENCY = "dependency"
    RISK_COVERAGE = "risk_coverage"


BACKSTOP_SEVERITY = Severity.MEDIUM


def backstop_title(label: str) -> str:
    return f"No specialist Assessment covers {label}"


def backstop_argument(label: str) -> str:
    return (
        f"None of this run's specialist Assessments cites {label} in a Finding or an effort "
        "row, so no agent has sized or discussed it. Assess it before the Estimate is built "
        "on these Assessments."
    )


def uncovered[R](requirements: Sequence[tuple[str, R]], cited: Collection[R]) -> list[str]:
    """The labels of `requirements` (label, Requirement id) whose id is not in `cited`, in
    the order given."""
    return [label for label, requirement_id in requirements if requirement_id not in cited]


@dataclass(frozen=True, slots=True)
class CriticFindingCandidate:
    """One Finding as the agent proposed it, before validation."""

    category: str
    severity: str
    title: str = field(repr=False)
    argument: str = field(repr=False)
    findings: tuple[str, ...] = ()
    """Specialist Finding labels, `F<n>`."""
    requirements: tuple[str, ...] = ()
    """Requirement labels, `R<n>`."""


@dataclass(frozen=True, slots=True)
class ValidCriticFinding[F, R]:
    category: CriticCategory
    severity: Severity
    title: str = field(repr=False)
    argument: str = field(repr=False)
    findings: tuple[F, ...] = ()
    """The resolved specialist Findings, without duplicates, in the order cited."""
    requirements: tuple[R, ...] = ()
    """The resolved Requirements, without duplicates, in the order cited."""
    backstop: bool = False
    """Written by code (an uncovered Requirement the agent did not report)."""


@dataclass(frozen=True, slots=True)
class CriticValidation[F, R]:
    findings: tuple[ValidCriticFinding[F, R], ...]
    """The valid proposed Findings in the order proposed, then the backstops."""
    dropped: int
    backstopped: int


def validate_critic_finding[F, R](
    candidate: CriticFindingCandidate,
    findings: Mapping[str, F],
    requirements: Mapping[str, R],
    uncovered_requirements: Collection[R],
) -> ValidCriticFinding[F, R] | None:
    """The Finding checked against the rules (module docstring); None if it breaks one."""
    try:
        category = CriticCategory(candidate.category.strip())
        severity = Severity(candidate.severity.strip())
    except ValueError:
        return None
    title = bounded(candidate.title, TITLE_MAX)
    argument = bounded(candidate.argument, ARGUMENT_MAX)
    if title is None or argument is None:
        return None
    cited_findings = resolve_labels(candidate.findings, findings)
    cited_requirements = resolve_labels(candidate.requirements, requirements)
    if not cited_findings and not cited_requirements:
        return None
    if category == CriticCategory.COVERAGE and not any(
        r in uncovered_requirements for r in cited_requirements
    ):
        return None
    return ValidCriticFinding(
        category=category,
        severity=severity,
        title=title,
        argument=argument,
        findings=cited_findings,
        requirements=cited_requirements,
    )


def validate_critic_findings[F, R](
    candidates: Sequence[CriticFindingCandidate],
    findings: Mapping[str, F],
    requirements: Mapping[str, R],
    uncovered_labels: Sequence[str],
) -> CriticValidation[F, R]:
    """Validate every proposed Finding (invalid ones dropped and counted), then backstop each
    uncovered Requirement (`uncovered_labels`, resolved through `requirements`) that no valid
    `coverage` Finding cites."""
    gaps = [(label, requirements[label]) for label in uncovered_labels if label in requirements]
    uncovered_set = {r for _, r in gaps}
    kept: list[ValidCriticFinding[F, R]] = []
    dropped = 0
    for candidate in candidates:
        valid = validate_critic_finding(candidate, findings, requirements, uncovered_set)
        if valid is None:
            dropped += 1
        else:
            kept.append(valid)
    reported = {r for f in kept if f.category == CriticCategory.COVERAGE for r in f.requirements}
    backstops = [
        ValidCriticFinding[F, R](
            category=CriticCategory.COVERAGE,
            severity=BACKSTOP_SEVERITY,
            title=backstop_title(label),
            argument=backstop_argument(label),
            requirements=(requirement,),
            backstop=True,
        )
        for label, requirement in gaps
        if requirement not in reported
    ]
    return CriticValidation(tuple(kept + backstops), dropped, len(backstops))
