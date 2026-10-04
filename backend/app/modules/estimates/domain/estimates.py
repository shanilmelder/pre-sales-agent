"""Estimate rules (Story 8.1): the demo template, Estimate Version and draft states, error
codes, and the validation of the agent's proposed lines. Pure.

**Template `demo-1`.** Sections are the six Requirement classifications, in the order the
Requirements tab lists them; roles are engineer, project manager and QA; the grid's columns
are Line, Covers, Role mix (%), Effort (h), Contingency (h) and Total (h). The template
version is recorded on every Estimate Version.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum

VERSION_SUBJECT_TYPE = "estimates.estimate_version"
"""The trace subject of an Estimate Version."""

TEMPLATE_VERSION = "demo-1"


class Section(StrEnum):
    """The template's sections: the Requirement classifications, in the Requirements tab's
    order."""

    FUNCTIONAL = "functional"
    INTEGRATION = "integration"
    DATA = "data"
    SECURITY = "security"
    NON_FUNCTIONAL = "non_functional"
    COMMERCIAL = "commercial"


SECTIONS: tuple[Section, ...] = tuple(Section)


class EstimateRole(StrEnum):
    """The template's roles, in column order."""

    ENGINEER = "engineer"
    PROJECT_MANAGER = "project_manager"
    QA = "qa"


ROLES: tuple[EstimateRole, ...] = tuple(EstimateRole)

COLUMNS: tuple[str, ...] = (
    "Line",
    "Covers",
    "Role mix (%)",
    "Effort (h)",
    "Contingency (h)",
    "Total (h)",
)


@dataclass(frozen=True, slots=True)
class Template:
    version: str
    sections: tuple[Section, ...]
    roles: tuple[EstimateRole, ...]
    columns: tuple[str, ...]


DEMO_TEMPLATE = Template(TEMPLATE_VERSION, SECTIONS, ROLES, COLUMNS)


def section_rank(section: str) -> int:
    """A section's position in the template; unknown values sort last."""
    try:
        return SECTIONS.index(Section(section))
    except ValueError:
        return len(SECTIONS)


class VersionStatus(StrEnum):
    DRAFT = "draft"
    SUPERSEDED = "superseded"


class DraftStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


IN_PROGRESS = frozenset({DraftStatus.QUEUED, DraftStatus.RUNNING})


class DraftErrorCode(StrEnum):
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_TIMEOUT = "model_timeout"
    OUTPUT_INVALID = "output_invalid"


# --- validating the agent's lines -----------------------------------------------------------

TITLE_MAX = 160
BASIS_MAX = 500
"""Limits in Unicode code points, on the trimmed text."""
EFFORT_MIN = Decimal("0.5")
EFFORT_MAX = Decimal("2000")
TENTH = Decimal("0.1")
MIX_TOTAL = 100


@dataclass(frozen=True, slots=True)
class LineCandidate:
    """One work item as the agent proposed it, before validation."""

    section: str
    title: str = field(repr=False)
    covers: tuple[str, ...]
    """Requirement labels, `R<n>`."""
    effort_hours: float
    role_mix: Mapping[str, object]
    basis: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ValidLine[K]:
    section: Section
    title: str = field(repr=False)
    covers: tuple[K, ...]
    """The resolved Requirements, without duplicates, in the order cited."""
    effort_hours: Decimal
    """Rounded to 0.1 h."""
    role_mix: Mapping[EstimateRole, int]
    """Every role, integers 0-100 summing to exactly 100."""
    basis: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class Validation[K]:
    lines: tuple[ValidLine[K], ...]
    dropped: int
    """Lines dropped: an unknown section, a title or basis missing, blank or too long, no
    covers label that resolves, effort out of range, or a role mix that isn't integers 0-100
    summing to 100."""


def _bounded(raw: str, limit: int) -> str | None:
    trimmed = raw.strip()
    return trimmed if 0 < len(trimmed) <= limit else None


def round_effort(raw: float | int | Decimal | str) -> Decimal | None:
    """`raw` hours rounded half-up to 0.1 h; None if it isn't a finite number."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, float) and not math.isfinite(raw):
        return None
    try:
        value = Decimal(str(raw))
    except InvalidOperation:
        return None
    if not value.is_finite():
        return None
    try:
        return value.quantize(TENTH, rounding=ROUND_HALF_UP)
    except InvalidOperation:  # too many digits for the context, e.g. 1e30
        return None


def valid_effort(raw: float | int | Decimal | str) -> Decimal | None:
    """The effort rounded to 0.1 h, if it lies in 0.5-2,000 h; None otherwise."""
    effort = round_effort(raw)
    if effort is None or not EFFORT_MIN <= effort <= EFFORT_MAX:
        return None
    return effort


def valid_mix(raw: Mapping[str, object]) -> dict[EstimateRole, int] | None:
    """The role mix, if it names exactly the template's roles with integers 0-100 summing to
    exactly 100; None otherwise."""
    if set(raw) != {r.value for r in ROLES}:
        return None
    mix: dict[EstimateRole, int] = {}
    for role in ROLES:
        share = raw[role.value]
        if isinstance(share, bool) or not isinstance(share, int) or not 0 <= share <= 100:
            return None
        mix[role] = share
    return mix if sum(mix.values()) == MIX_TOTAL else None


def validate_line[K](
    candidate: LineCandidate, requirements: Mapping[str, K]
) -> ValidLine[K] | None:
    """The line checked against the rules, its labels resolved through `requirements` (label
    to Requirement); None if it breaks a rule. Labels that don't resolve are ignored as long
    as at least one does."""
    try:
        section = Section(candidate.section)
    except ValueError:
        return None
    title = _bounded(candidate.title, TITLE_MAX)
    basis = _bounded(candidate.basis, BASIS_MAX)
    effort = valid_effort(candidate.effort_hours)
    mix = valid_mix(candidate.role_mix)
    covers: list[K] = []
    for label in candidate.covers:
        found = requirements.get(label.strip())
        if found is not None and found not in covers:
            covers.append(found)
    if title is None or basis is None or effort is None or mix is None or not covers:
        return None
    return ValidLine(
        section=section,
        title=title,
        covers=tuple(covers),
        effort_hours=effort,
        role_mix=mix,
        basis=basis,
    )


def validate_lines[K](
    candidates: Sequence[LineCandidate], requirements: Mapping[str, K]
) -> Validation[K]:
    """Validate every line; invalid ones are dropped and counted."""
    kept: list[ValidLine[K]] = []
    dropped = 0
    for candidate in candidates:
        valid = validate_line(candidate, requirements)
        if valid is None:
            dropped += 1
        else:
            kept.append(valid)
    return Validation(tuple(kept), dropped)


def uncovered[K](lines: Sequence[ValidLine[K]], active: Sequence[K]) -> int:
    """How many of the `active` Requirements no line covers."""
    covered = {k for line in lines for k in line.covers}
    return sum(1 for k in dict.fromkeys(active) if k not in covered)
