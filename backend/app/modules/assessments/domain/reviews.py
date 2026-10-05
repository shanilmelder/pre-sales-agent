"""Red Team Review rules (Story 6.5): review, run and Finding states, the Finding categories
and severities, and the validation of the agent's proposed Findings. Pure."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

REVIEW_SUBJECT_TYPE = "assessments.review"
"""The trace subject of a Review."""


class ReviewKind(StrEnum):
    RED_TEAM = "red_team"


class ReviewStatus(StrEnum):
    CURRENT = "current"
    SUPERSEDED = "superseded"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


IN_PROGRESS = frozenset({RunStatus.QUEUED, RunStatus.RUNNING})


class RunErrorCode(StrEnum):
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_TIMEOUT = "model_timeout"
    OUTPUT_INVALID = "output_invalid"


class FindingCategory(StrEnum):
    INTEGRATION_HARDER = "integration_harder"
    REQUIREMENT_INCOMPLETE = "requirement_incomplete"
    CAPABILITY_OVERSTATED = "capability_overstated"
    HIDDEN_DEPENDENCY = "hidden_dependency"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


SEVERITY_ORDER: tuple[Severity, ...] = (
    Severity.CRITICAL,
    Severity.HIGH,
    Severity.MEDIUM,
    Severity.LOW,
)
"""Most severe first: the order Findings are listed in."""


def severity_rank(severity: str) -> int:
    """A severity's place in `SEVERITY_ORDER`; unknown values sort last."""
    try:
        return SEVERITY_ORDER.index(Severity(severity))
    except ValueError:
        return len(SEVERITY_ORDER)


def severity_counts(severities: Iterable[Severity]) -> dict[Severity, int]:
    """How many Findings have each severity, every severity present (0 when none)."""
    counts = dict.fromkeys(SEVERITY_ORDER, 0)
    for severity in severities:
        counts[severity] += 1
    return counts


# --- validating the agent's Findings --------------------------------------------------------

TITLE_MAX = 160
ARGUMENT_MAX = 800
"""Limits in Unicode code points, on the trimmed text."""
EXCERPT_MAX = 140


@dataclass(frozen=True, slots=True)
class FindingCandidate:
    """One Finding as the agent proposed it, before validation."""

    category: str
    severity: str
    title: str = field(repr=False)
    argument: str = field(repr=False)
    requirements: tuple[str, ...]
    """Requirement labels, `R<n>`."""
    lines: tuple[str, ...] = ()
    """Estimate line labels, `L<n>`."""


@dataclass(frozen=True, slots=True)
class ValidFinding[R, L]:
    category: FindingCategory
    severity: Severity
    title: str = field(repr=False)
    argument: str = field(repr=False)
    requirements: tuple[R, ...]
    """The resolved Requirements, without duplicates, in the order cited."""
    lines: tuple[L, ...]
    """The resolved Estimate lines, without duplicates, in the order cited."""


@dataclass(frozen=True, slots=True)
class FindingValidation[R, L]:
    findings: tuple[ValidFinding[R, L], ...]
    dropped: int
    """Findings dropped: an unknown category or severity, a title or argument missing, blank
    or too long, or no Requirement label that resolves."""


def bounded(raw: str, limit: int) -> str | None:
    """`raw` trimmed, or None when that is empty or longer than `limit` code points."""
    trimmed = raw.strip()
    return trimmed if 0 < len(trimmed) <= limit else None


def resolve_labels[K](labels: Sequence[str], known: Mapping[str, K]) -> tuple[K, ...]:
    """The values of the labels found in `known` (trimmed), without duplicates, in order."""
    found: list[K] = []
    for label in labels:
        value = known.get(label.strip())
        if value is not None and value not in found:
            found.append(value)
    return tuple(found)


def validate_finding[R, L](
    candidate: FindingCandidate,
    requirements: Mapping[str, R],
    lines: Mapping[str, L],
) -> ValidFinding[R, L] | None:
    """The Finding checked against the rules, its labels resolved through `requirements` and
    `lines` (label to Requirement or line); None if it breaks a rule. Requirement labels that
    don't resolve are ignored as long as at least one does; line labels that don't resolve
    are ignored."""
    try:
        category = FindingCategory(candidate.category.strip())
        severity = Severity(candidate.severity.strip())
    except ValueError:
        return None
    title = bounded(candidate.title, TITLE_MAX)
    argument = bounded(candidate.argument, ARGUMENT_MAX)
    cited = resolve_labels(candidate.requirements, requirements)
    if title is None or argument is None or not cited:
        return None
    return ValidFinding(
        category=category,
        severity=severity,
        title=title,
        argument=argument,
        requirements=cited,
        lines=resolve_labels(candidate.lines, lines),
    )


def validate_findings[R, L](
    candidates: Sequence[FindingCandidate],
    requirements: Mapping[str, R],
    lines: Mapping[str, L],
) -> FindingValidation[R, L]:
    """Validate every Finding; invalid ones are dropped and counted."""
    kept: list[ValidFinding[R, L]] = []
    dropped = 0
    for candidate in candidates:
        valid = validate_finding(candidate, requirements, lines)
        if valid is None:
            dropped += 1
        else:
            kept.append(valid)
    return FindingValidation(tuple(kept), dropped)


def excerpt(text: str, limit: int = EXCERPT_MAX) -> str:
    """At most `limit` code points of `text` on one line, cut at whitespace where possible,
    ending in `…` when cut."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    cut = flat[: limit - 1]
    space = cut.rfind(" ")
    if space >= limit // 2:
        cut = cut[:space]
    return cut.rstrip() + "…"
