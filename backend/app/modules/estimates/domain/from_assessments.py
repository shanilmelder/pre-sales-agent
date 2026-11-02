"""The Estimate built from the specialist Assessments (Story 8.3). Pure.

One line per active Requirement that at least one agent's current Assessment sizes:

- **Hours:** the sum of the Engineering, PM and Security hours for it (the 5.3 "Agents
  total"), matched by Requirement id whatever version the agent sized.
- **Section:** the Requirement's classification (one to one onto the `demo-1` sections).
- **Title:** the Requirement's text on one line, cut to 160 characters at a word boundary
  with `…`.
- **Role mix:** Engineering and Security hours as `engineer`, PM hours as
  `project_manager`, `qa` 0, as whole percentages summing to 100 by largest remainder (ties
  in role order).
- **Basis:** "Engineering: … · PM: … · Security: …" from each sizing agent's basis, cut to
  500 characters.
- **Covers:** that Requirement at its current version.
- **Order:** template section order, then Requirement order.

Active Requirements no agent sized get no line; they are counted as uncovered.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from app.modules.estimates.domain.estimates import (
    BASIS_MAX,
    MIX_TOTAL,
    ROLES,
    TITLE_MAX,
    EstimateRole,
    Section,
    ValidLine,
    section_rank,
)

ENGINEERING = "engineering_agent"
PM = "pm_agent"
SECURITY = "security_agent"
AGENT_ORDER: tuple[str, ...] = (ENGINEERING, PM, SECURITY)
"""The specialist agents in the order their bases are listed."""
AGENT_LABELS: dict[str, str] = {ENGINEERING: "Engineering", PM: "PM", SECURITY: "Security"}
AGENT_ROLES: dict[str, EstimateRole] = {
    ENGINEERING: EstimateRole.ENGINEER,
    PM: EstimateRole.PROJECT_MANAGER,
    SECURITY: EstimateRole.ENGINEER,
}
BASIS_SEPARATOR = " · "
ELLIPSIS = "…"


@dataclass(frozen=True, slots=True)
class SizingRow:
    """One effort row of an agent's current Assessment: the Requirement (at the version the
    agent sized), its hours and why."""

    requirement_id: UUID
    requirement_version: int
    hours: Decimal
    basis: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class AgentSizing:
    """An agent's current Assessment of the Opportunity and its effort rows."""

    agent: str
    assessment_id: UUID
    assessment_version: int
    rows: tuple[SizingRow, ...]


@dataclass(frozen=True, slots=True)
class ActiveRequirement:
    """An active Requirement at its current version, with its position `number` (R<n>)."""

    id: UUID
    version: int
    number: int
    classification: str
    text: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class BuiltLines:
    lines: tuple[ValidLine[tuple[UUID, int]], ...]
    uncovered: int
    """Active Requirements no agent sized."""


def cut(text: str, limit: int) -> str:
    """`text` on one line, at most `limit` code points: cut at the last word boundary that
    fits (or mid-word when there is none in the second half) and ended with `…` when cut."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    head = flat[: limit - 1]
    space = head.rfind(" ")
    if space >= (limit - 1) // 2:
        head = head[:space]
    return head.rstrip() + ELLIPSIS


def role_mix(hours: Mapping[EstimateRole, Decimal]) -> dict[EstimateRole, int]:
    """Each role's share of the hours in whole percent, summing to exactly 100 by the
    largest-remainder method (ties go to the earlier role). All zero hours: all to the
    engineer."""
    total = sum((hours.get(role, Decimal(0)) for role in ROLES), Decimal(0))
    if total <= 0:
        return {role: (MIX_TOTAL if role is EstimateRole.ENGINEER else 0) for role in ROLES}
    exact = {role: hours.get(role, Decimal(0)) * MIX_TOTAL / total for role in ROLES}
    floors = {role: int(exact[role]) for role in ROLES}
    left = MIX_TOTAL - sum(floors.values())
    by_remainder = sorted(
        ROLES, key=lambda role: (-(exact[role] - floors[role]), ROLES.index(role))
    )
    for role in by_remainder[:left]:
        floors[role] += 1
    return floors


def _title(requirement: ActiveRequirement) -> str:
    title = cut(requirement.text, TITLE_MAX)
    return title or f"R{requirement.number}"


def _basis(parts: Sequence[tuple[str, str]]) -> str:
    text = BASIS_SEPARATOR.join(
        f"{AGENT_LABELS.get(agent, agent)}: {' '.join(basis.split())}" for agent, basis in parts
    )
    return cut(text, BASIS_MAX)


def _agent_rank(agent: str) -> int:
    return AGENT_ORDER.index(agent) if agent in AGENT_ORDER else len(AGENT_ORDER)


def build_lines(
    requirements: Sequence[ActiveRequirement], sizings: Sequence[AgentSizing]
) -> BuiltLines:
    """The Estimate lines for the active `requirements` from the agents' current
    Assessments (see the module docstring)."""
    by_requirement: dict[UUID, list[tuple[str, SizingRow]]] = {}
    for sizing in sorted(sizings, key=lambda s: _agent_rank(s.agent)):
        for row in sizing.rows:
            by_requirement.setdefault(row.requirement_id, []).append((sizing.agent, row))
    built: list[tuple[int, int, ValidLine[tuple[UUID, int]]]] = []
    uncovered = 0
    for requirement in requirements:
        sized = by_requirement.get(requirement.id)
        if not sized:
            uncovered += 1
            continue
        role_hours: dict[EstimateRole, Decimal] = {role: Decimal(0) for role in ROLES}
        for agent, row in sized:
            role = AGENT_ROLES.get(agent, EstimateRole.ENGINEER)
            role_hours[role] += row.hours
        section = Section(requirement.classification)
        built.append(
            (
                section_rank(section),
                requirement.number,
                ValidLine(
                    section=section,
                    title=_title(requirement),
                    covers=((requirement.id, requirement.version),),
                    effort_hours=sum(role_hours.values(), Decimal(0)),
                    role_mix=role_mix(role_hours),
                    basis=_basis([(agent, row.basis) for agent, row in sized]),
                ),
            )
        )
    built.sort(key=lambda item: (item[0], item[1]))
    return BuiltLines(lines=tuple(line for _, _, line in built), uncovered=uncovered)


# --- a Challenge's reassessment (Story 9.6) ---------------------------------------------------


def _hours_by_requirement(sizing: AgentSizing | None) -> dict[UUID, Decimal]:
    found: dict[UUID, Decimal] = {}
    for row in () if sizing is None else sizing.rows:
        found[row.requirement_id] = found.get(row.requirement_id, Decimal(0)) + row.hours
    return found


def changed_requirements(
    pairs: Sequence[tuple[AgentSizing | None, AgentSizing]],
) -> frozenset[UUID]:
    """The Requirements whose sizing a rerun changed: for each (previous, rerun) Assessment of
    one agent, every Requirement the two size with different hours (or only one sizes)."""
    changed: set[UUID] = set()
    for previous, rerun in pairs:
        before = _hours_by_requirement(previous)
        after = _hours_by_requirement(rerun)
        changed.update(r for r in before.keys() | after.keys() if before.get(r) != after.get(r))
    return frozenset(changed)


type Line = ValidLine[tuple[UUID, int]]


@dataclass(frozen=True, slots=True)
class ChallengeLines:
    lines: tuple[Line, ...]
    rebuilt: frozenset[tuple[str, str]]
    """The (section, title) of every line that took rebuilt hours: a person's edit of the
    challenged version's line is not carried onto it."""


def _merged(base: Line, sources: Sequence[Line]) -> Line:
    """`base` with the rebuilt hours, role mix and basis of the rebuilt `sources` (one per
    Requirement it covers that is still sized), its covers at their rebuilt versions."""
    role_hours: dict[EstimateRole, Decimal] = {role: Decimal(0) for role in ROLES}
    for source in sources:
        for role, share in source.role_mix.items():
            role_hours[role] += source.effort_hours * share / MIX_TOTAL
    versions = {rid: at for source in sources for rid, at in source.covers}
    basis = BASIS_SEPARATOR.join(source.basis for source in sources)
    return ValidLine(
        section=base.section,
        title=base.title,
        covers=tuple((rid, versions.get(rid, at)) for rid, at in base.covers),
        effort_hours=sum((s.effort_hours for s in sources), Decimal(0)),
        role_mix=role_mix(role_hours),
        basis=cut(basis, BASIS_MAX),
    )


def rebuild_changed(
    base: Sequence[Line], rebuilt: Sequence[Line], changed: frozenset[UUID]
) -> ChallengeLines:
    """The lines of a Challenge's new version (Story 9.6): every line of the challenged
    version (`base`) that covers no `changed` Requirement, verbatim (edits included); each
    one that does takes the `rebuilt` hours, role mix and basis of the Requirements it covers
    (`build_lines` over the current Assessments: one line per Requirement), keeping its
    section and title; one whose Requirements no Assessment sizes any more is dropped. Each
    rebuilt line goes to the first base line covering its Requirement only (no double count):
    a later line whose rebuilt lines are all taken is copied verbatim. A changed Requirement
    no line of `base` covers gets its rebuilt line, at the end."""
    by_requirement = {rid: line for line in rebuilt for rid, _ in line.covers}
    lines: list[Line] = []
    touched: set[tuple[str, str]] = set()
    covered: set[UUID] = set()
    used: list[Line] = []
    for line in base:
        ids = [rid for rid, _ in line.covers]
        covered.update(ids)
        if not changed.intersection(ids):
            lines.append(line)
            continue
        found_any = False
        sources: list[Line] = []
        for rid in ids:
            found = by_requirement.get(rid)
            if found is None:
                continue
            found_any = True
            if all(found is not s for s in (*sources, *used)):
                sources.append(found)
        if not found_any:
            continue
        if not sources:  # another line already took these rebuilt hours
            lines.append(line)
            continue
        used.extend(sources)
        lines.append(_merged(line, sources))
        touched.add((line.section.value, line.title))
    for line in rebuilt:
        ids = [rid for rid, _ in line.covers]
        if changed.intersection(ids) and not covered.intersection(ids):
            lines.append(line)
            touched.add((line.section.value, line.title))
    return ChallengeLines(lines=tuple(lines), rebuilt=frozenset(touched))
