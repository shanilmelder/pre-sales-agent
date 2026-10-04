"""Estimate arithmetic (Story 8.1, AD-10): every number the Estimate shows is calculated
here, by pure functions, never by a model. No endpoint accepts a total.

Hours are `Decimal` with one decimal place (person-hours, `numeric(10,1)`). Internally the
functions work in whole tenths of an hour, so every sum is exact.

- **Per-role hours:** a line's effort times each role's share of the mix, rounded to 0.1 h by
  the largest-remainder method, so the role hours sum exactly to the line's effort.
- **Contingency:** a line's Contingency is the sum of its linked Contingency amounts,
  accepted or not (Story 8.4: the grid shows what the Estimate would be). A line's total is
  its effort plus its Contingency.
- **Unallocated contingency:** Contingency amounts linked to no line add up in a
  version-level "Unallocated contingency", which counts in the overall Contingency and total
  (not in any section, and not split by role).
- **Totals:** per section (effort, Contingency, total and per-role hours), per role, and
  overall (effort, Contingency, total). Each is the sum of its parts.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from app.modules.estimates.domain.estimates import ROLES, SECTIONS, TENTH, EstimateRole, Section

ZERO = Decimal("0.0")


def to_tenths(hours: Decimal) -> int:
    """Whole tenths of an hour. `hours` must already be a multiple of 0.1."""
    tenths = hours * 10
    if tenths != tenths.to_integral_value():
        raise ValueError("hours must be a multiple of 0.1")
    return int(tenths)


def from_tenths(tenths: int) -> Decimal:
    return (Decimal(tenths) * TENTH).quantize(TENTH)


def split_tenths(total: int, weights: Sequence[int]) -> list[int]:
    """`total` split in proportion to `weights` (non-negative, not all zero) into whole
    parts that sum exactly to `total`: each part is first rounded down, then the remaining
    units go one each to the largest remainders (ties to the earlier weight)."""
    if total < 0 or any(w < 0 for w in weights) or sum(weights) <= 0:
        raise ValueError("a non-negative total and non-negative weights with a positive sum")
    whole = sum(weights)
    parts = [total * w // whole for w in weights]
    remainders = [total * w % whole for w in weights]
    left = total - sum(parts)
    order = sorted(range(len(weights)), key=lambda i: (-remainders[i], i))
    for i in order[:left]:
        parts[i] += 1
    return parts


def role_hours(effort: Decimal, mix: Mapping[EstimateRole, int]) -> dict[EstimateRole, Decimal]:
    """The line's effort split over the template's roles by its mix, rounded to 0.1 h by the
    largest-remainder method: the role hours sum exactly to `effort`."""
    parts = split_tenths(to_tenths(effort), [mix.get(role, 0) for role in ROLES])
    return {role: from_tenths(part) for role, part in zip(ROLES, parts, strict=True)}


def line_contingency(amounts: Iterable[Decimal]) -> Decimal:
    """A line's Contingency: the sum of its linked Contingency amounts (0 with none)."""
    return from_tenths(sum(to_tenths(a) for a in amounts))


@dataclass(frozen=True, slots=True)
class LineInput:
    section: Section
    effort: Decimal
    mix: Mapping[EstimateRole, int]
    contingencies: tuple[Decimal, ...] = ()
    """The line's linked Contingency amounts, in hours."""


@dataclass(frozen=True, slots=True)
class LineTotals:
    role_hours: Mapping[EstimateRole, Decimal]
    effort: Decimal
    contingency: Decimal
    total: Decimal


@dataclass(frozen=True, slots=True)
class Totals:
    """Effort, Contingency and total, and the effort per role."""

    effort: Decimal = ZERO
    contingency: Decimal = ZERO
    total: Decimal = ZERO
    role_hours: Mapping[EstimateRole, Decimal] = field(
        default_factory=lambda: dict.fromkeys(ROLES, ZERO)
    )


@dataclass(frozen=True, slots=True)
class EstimateTotals:
    lines: tuple[LineTotals, ...]
    """In the order given."""
    sections: Mapping[Section, Totals]
    """Only the sections that have lines, in template order."""
    unallocated: Decimal
    """The sum of the Contingency amounts linked to no line."""
    overall: Totals
    """The sections' sums plus the unallocated Contingency."""


def line_totals(line: LineInput) -> LineTotals:
    contingency = line_contingency(line.contingencies)
    return LineTotals(
        role_hours=role_hours(line.effort, line.mix),
        effort=line.effort,
        contingency=contingency,
        total=from_tenths(to_tenths(line.effort) + to_tenths(contingency)),
    )


def sum_totals(parts: Iterable[LineTotals | Totals]) -> Totals:
    """The sum of lines' or subtotals' effort, Contingency, total and role hours."""
    effort = contingency = total = 0
    roles = dict.fromkeys(ROLES, 0)
    for part in parts:
        effort += to_tenths(part.effort)
        contingency += to_tenths(part.contingency)
        total += to_tenths(part.total)
        for role in ROLES:
            roles[role] += to_tenths(part.role_hours.get(role, ZERO))
    return Totals(
        effort=from_tenths(effort),
        contingency=from_tenths(contingency),
        total=from_tenths(total),
        role_hours={role: from_tenths(value) for role, value in roles.items()},
    )


def estimate_totals(
    lines: Sequence[LineInput], unallocated: Iterable[Decimal] = ()
) -> EstimateTotals:
    """Every line's totals, the section subtotals, the unallocated Contingency (the sum of
    `unallocated`, the amounts linked to no line) and the overall totals, which include it."""
    per_line = tuple(line_totals(line) for line in lines)
    sections: dict[Section, Totals] = {}
    for section in SECTIONS:
        members = [t for line, t in zip(lines, per_line, strict=True) if line.section == section]
        if members:
            sections[section] = sum_totals(members)
    loose = line_contingency(unallocated)
    lines_only = sum_totals(per_line)
    overall = Totals(
        effort=lines_only.effort,
        contingency=from_tenths(to_tenths(lines_only.contingency) + to_tenths(loose)),
        total=from_tenths(to_tenths(lines_only.total) + to_tenths(loose)),
        role_hours=lines_only.role_hours,
    )
    return EstimateTotals(lines=per_line, sections=sections, unallocated=loose, overall=overall)
