"""Assumption rules (Story 8.4): kinds, the proposal job's states, and the validation of
`estimating_agent`'s proposals. Pure.

Every open Gap of an Opportunity gets one proposal per draft Estimate Version: a **Condition**
(something the customer must provide or decide, in proposal-ready wording, no hours) or a
**Contingency** (uncertainty we absorb, with hours, optionally linked to the line it affects).
Proposals are stored unaccepted; a person accepts them.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from app.modules.estimates.domain.estimates import round_effort

ASSUMPTION_SUBJECT_TYPE = "estimates.assumption"
"""The trace subject of an Assumption."""

ORIGIN_GAP = "gap"
"""`origin_ref.kind` of an Assumption made from a Gap (the only origin in the demo)."""

WORDING_MAX = 500
"""In Unicode code points, on the trimmed text."""
HOURS_MIN = Decimal("0.5")
HOURS_MAX = Decimal("1000")


class AssumptionKind(StrEnum):
    CONDITION = "condition"
    CONTINGENCY = "contingency"


class ProposalStatus(StrEnum):
    """The state of an Estimate Version's `estimates.propose_assumptions` job."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


PROPOSING = frozenset({ProposalStatus.QUEUED, ProposalStatus.RUNNING})


@dataclass(frozen=True, slots=True)
class ProposalCandidate:
    """One Assumption as the agent proposed it, before validation."""

    gap: str
    """A Gap label, `G<n>`."""
    kind: str
    wording: str = field(repr=False)
    hours: float | None = None
    line: str | None = None
    """A line label, `L<n>`, or None."""


@dataclass(frozen=True, slots=True)
class ValidProposal[G, L]:
    gap: G
    kind: AssumptionKind
    wording: str = field(repr=False)
    hours: Decimal | None
    """Rounded to 0.1 h for a Contingency; None for a Condition."""
    line: L | None


@dataclass(frozen=True, slots=True)
class ProposalValidation[G, L]:
    proposals: tuple[ValidProposal[G, L], ...]
    """At most one per Gap, in the order proposed."""
    dropped: int
    """Proposals that broke a rule: a Gap label that doesn't resolve to an open Gap, an
    unknown kind, wording missing, blank or too long, a Condition with hours, a Contingency
    without hours or with hours out of range, or a Contingency's line label that doesn't
    resolve."""
    duplicates: int
    """Valid proposals for a Gap that already had one (dropped too)."""
    missing: tuple[G, ...]
    """The open Gaps with no valid proposal, in the order given."""


def valid_hours(raw: float | int | Decimal | str) -> Decimal | None:
    """The hours rounded half-up to 0.1, if they lie in 0.5-1,000; None otherwise."""
    hours = round_effort(raw)
    if hours is None or not HOURS_MIN <= hours <= HOURS_MAX:
        return None
    return hours


def validate_proposal[G, L](
    candidate: ProposalCandidate, gaps: Mapping[str, G], lines: Mapping[str, L]
) -> ValidProposal[G, L] | None:
    """The proposal checked against the rules, its labels resolved through `gaps` (label to
    open Gap) and `lines` (label to line); None if it breaks a rule."""
    gap = gaps.get(candidate.gap.strip())
    if gap is None:
        return None
    try:
        kind = AssumptionKind(candidate.kind)
    except ValueError:
        return None
    wording = candidate.wording.strip()
    if not 0 < len(wording) <= WORDING_MAX:
        return None
    line: L | None = None
    hours: Decimal | None = None
    if kind is AssumptionKind.CONDITION:
        # A Condition carries no hours; a line label on one is ignored (it prices nothing).
        if candidate.hours is not None:
            return None
    else:
        if candidate.hours is None:
            return None
        hours = valid_hours(candidate.hours)
        if hours is None:
            return None
        if candidate.line is not None and candidate.line.strip():
            line = lines.get(candidate.line.strip())
            if line is None:
                return None
    return ValidProposal(gap=gap, kind=kind, wording=wording, hours=hours, line=line)


def validate_proposals[G, L](
    candidates: Sequence[ProposalCandidate],
    gaps: Mapping[str, G],
    lines: Mapping[str, L],
) -> ProposalValidation[G, L]:
    """Validate every proposal. Invalid ones are dropped and counted; of several valid ones
    for the same Gap the first is kept and the rest are dropped and counted as duplicates."""
    kept: list[ValidProposal[G, L]] = []
    seen: list[G] = []
    dropped = duplicates = 0
    for candidate in candidates:
        valid = validate_proposal(candidate, gaps, lines)
        if valid is None:
            dropped += 1
            continue
        if valid.gap in seen:
            duplicates += 1
            continue
        seen.append(valid.gap)
        kept.append(valid)
    missing = tuple(g for g in dict.fromkeys(gaps.values()) if g not in seen)
    return ProposalValidation(tuple(kept), dropped, duplicates, missing)


# --- carrying Assumptions to a re-draft (Story 8.7, demo slice) ------------------------------


def _line_key(section: str, title: str) -> tuple[str, str]:
    return section, title.strip().casefold()


def carried_line[L](section: str, title: str, candidates: Sequence[tuple[L, str, str]]) -> L | None:
    """The line a carried Contingency links to in the new version: the one candidate
    (`(line, section, title)`) with the same section and the same title, trimmed and
    case-insensitive. None when no candidate or more than one matches: the Contingency is
    then Unallocated."""
    key = _line_key(section, title)
    found = [line for line, s, t in candidates if _line_key(s, t) == key]
    return found[0] if len(found) == 1 else None
