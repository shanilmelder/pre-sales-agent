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


WORDING_RULE = f"The wording must be 1 to {WORDING_MAX} characters."
KIND_RULE = "The kind must be a Condition or a Contingency."
CONDITION_HOURS_RULE = "A Condition has no hours."
CONTINGENCY_HOURS_RULE = "A Contingency needs 0.5 to 1,000 hours."
CONDITION_LINE_RULE = "A Condition is not linked to a line."
LINE_RULE = "The line must be a line of this Estimate Version."


@dataclass(frozen=True, slots=True)
class AssumptionFields:
    """An Assumption's kind, wording (trimmed) and hours (0.1 h; None for a Condition), as the
    rules allow them."""

    kind: AssumptionKind
    wording: str = field(repr=False)
    hours: Decimal | None


def check_assumption(
    kind: str, wording: str, hours: float | int | Decimal | None
) -> AssumptionFields | str:
    """The Story 8.4 rules shared by a proposal and a person's edit (Story 8.5): a known kind,
    wording of 1-500 characters (trimmed), no hours on a Condition, and 0.5-1,000 hours
    (rounded half up to 0.1) on a Contingency. The fields as allowed, or the broken rule's
    sentence."""
    try:
        valid_kind = AssumptionKind(kind)
    except ValueError:
        return KIND_RULE
    trimmed = wording.strip()
    if not 0 < len(trimmed) <= WORDING_MAX:
        return WORDING_RULE
    if valid_kind is AssumptionKind.CONDITION:
        return (
            CONDITION_HOURS_RULE
            if hours is not None
            else AssumptionFields(valid_kind, trimmed, None)
        )
    rounded = None if hours is None else valid_hours(hours)
    if rounded is None:
        return CONTINGENCY_HOURS_RULE
    return AssumptionFields(valid_kind, trimmed, rounded)


def validate_proposal[G, L](
    candidate: ProposalCandidate, gaps: Mapping[str, G], lines: Mapping[str, L]
) -> ValidProposal[G, L] | None:
    """The proposal checked against the rules, its labels resolved through `gaps` (label to
    open Gap) and `lines` (label to line); None if it breaks a rule."""
    gap = gaps.get(candidate.gap.strip())
    if gap is None:
        return None
    checked = check_assumption(candidate.kind, candidate.wording, candidate.hours)
    if isinstance(checked, str):
        return None
    line: L | None = None
    # A Condition's line label is ignored (it prices nothing).
    if (
        checked.kind is AssumptionKind.CONTINGENCY
        and candidate.line is not None
        and candidate.line.strip()
    ):
        line = lines.get(candidate.line.strip())
        if line is None:
            return None
    return ValidProposal(
        gap=gap, kind=checked.kind, wording=checked.wording, hours=checked.hours, line=line
    )


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


# --- the origin's state (Story 8.5) ---------------------------------------------------------


def origin_superseded(status: str, row_version: int, made_at_row_version: object) -> bool:
    """Whether an Assumption's (or a Risk's) origin Gap has moved on since it was made from
    it: the Gap is neither `open` nor `converted`, or it is open but at another row version
    than `origin_ref.row_version`. A converted Gap is the conversion itself (converting bumps
    its row version and it never changes again but for that), so it is current."""
    if status == "converted":
        return False
    if status != "open":
        return True
    return row_version != made_at_row_version
