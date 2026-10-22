"""Requirement rules (Story 2.5 Part A): classifications, statuses, extraction states and
error codes, the input budget, and quote resolution; and the reconciliation of a new
extraction with the active Requirements (Story 2.7), never reviving a deleted one (Story
2.6). Pure.

`resolve_quote` turns a verbatim quote from the model into Unicode code-point offsets
`[start, end)` into the Source version's extracted text (Python `str` indices are code
points). An exact match wins; failing that, a match that ignores runs of whitespace and
case, mapped back to the original offsets.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

SUBJECT_TYPE = "intake.extraction"
"""The trace subject of an extraction run."""
REQUIREMENT_SUBJECT_TYPE = "intake.requirement"
"""The trace subject of a Requirement (Story 2.6)."""

REQUIREMENT_TEXT_MAX = 2_000
"""The most characters (Unicode code points) a Requirement's text may have once trimmed."""


class Classification(StrEnum):
    """A Requirement's classification, in the order the Requirements tab groups them."""

    FUNCTIONAL = "functional"
    INTEGRATION = "integration"
    DATA = "data"
    SECURITY = "security"
    NON_FUNCTIONAL = "non_functional"
    COMMERCIAL = "commercial"


class RequirementOrigin(StrEnum):
    EXTRACTED = "extracted"
    HUMAN = "human"


class RequirementStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    """Replaced: by a later extraction (before Story 2.7), or split or merged away (Story 2.6)."""
    DELETED = "deleted"
    """Removed by a person with a reason (Story 2.6). Never revived by re-extraction."""


class ExtractionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


IN_PROGRESS = frozenset({ExtractionStatus.QUEUED, ExtractionStatus.RUNNING})


class ExtractionErrorCode(StrEnum):
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_TIMEOUT = "model_timeout"
    OUTPUT_INVALID = "output_invalid"
    INPUT_TOO_LARGE = "input_too_large"
    AGENT_DISABLED = "registry_agent_disabled"
    """The Agent is `disabled` or `eval_only` in the Agent Registry (Story 7.1)."""


CHARS_PER_TOKEN = 3.5
"""The rough characters-per-token ratio the input budget is measured with."""
PROMPT_RESERVE_TOKENS = 2_000
"""Room for the instructions, the data-block delimiters and the retry message."""
OUTPUT_RESERVE_TOKENS = 5_000
"""Room for one reply. Reserved twice: the quote-resolution retry resends the first reply."""


def input_budget_chars(num_ctx: int) -> int:
    """The most Source characters (code points) one extraction call may carry for a
    profile with this context window."""
    tokens = num_ctx - PROMPT_RESERVE_TOKENS - 2 * OUTPUT_RESERVE_TOKENS
    return max(0, int(tokens * CHARS_PER_TOKEN))


def _folded(text: str) -> tuple[str, list[int]]:
    """`text` with every run of whitespace collapsed to one space and lower-cased, plus the
    original index of each resulting character. Lower-casing can lengthen a character
    (`İ`), so the map is per output character."""
    out: list[str] = []
    origin: list[int] = []
    in_space = False
    for index, ch in enumerate(text):
        if ch.isspace():
            if not in_space:
                out.append(" ")
                origin.append(index)
            in_space = True
            continue
        in_space = False
        for lowered in ch.lower():
            out.append(lowered)
            origin.append(index)
    return "".join(out), origin


def resolve_quote(text: str, quote: str) -> tuple[int, int] | None:
    """The code-point span `[start, end)` of `quote` in `text`, or None.

    An exact match (first occurrence) wins. Otherwise the quote, trimmed, is matched with
    whitespace runs collapsed and case ignored, and the span covers the original characters
    from the first to the last matched one. A quote with no visible character never
    resolves."""
    if not quote.strip():
        return None
    start = text.find(quote)
    if start != -1:
        return start, start + len(quote)
    folded_quote, _ = _folded(quote.strip())
    folded_text, origin = _folded(text)
    found = folded_text.find(folded_quote)
    if found == -1:
        return None
    last = found + len(folded_quote) - 1
    return origin[found], origin[last] + 1


# --- resolving a proposed extraction --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProposedCitation:
    source: str
    """The Source block label, `S<n>`."""
    quote: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProposedRequirement:
    text: str = field(repr=False)
    classification: str
    citations: tuple[ProposedCitation, ...]


@dataclass(frozen=True, slots=True)
class ResolvedSpan:
    source: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class ResolvedRequirement:
    text: str = field(repr=False)
    classification: Classification
    spans: tuple[ResolvedSpan, ...]
    """At least one, without duplicates, in citation order."""


@dataclass(frozen=True, slots=True)
class Resolution:
    requirements: tuple[ResolvedRequirement, ...]
    failing: tuple[int, ...]
    """Indices (into the proposal) of items that lost a citation or were dropped."""
    dropped: int
    """Proposed Requirements dropped: no citation resolved (or no text, or an unknown
    classification)."""


def resolve_requirements(
    proposed: Sequence[ProposedRequirement], texts: Mapping[str, str]
) -> Resolution:
    """Resolve every citation's quote in the text of the Source it names (`texts`, by label).
    An unresolved citation (unknown label, quote not found) is dropped; a Requirement left
    with no resolved citation is dropped."""
    kept: list[ResolvedRequirement] = []
    failing: list[int] = []
    dropped = 0
    for index, item in enumerate(proposed):
        statement = item.text.strip()
        classification: Classification | None
        try:
            classification = Classification(item.classification)
        except ValueError:
            classification = None
        spans: list[ResolvedSpan] = []
        lost = False
        for citation in item.citations:
            text = texts.get(citation.source)
            found = None if text is None else resolve_quote(text, citation.quote)
            if found is None:
                lost = True
                continue
            span = ResolvedSpan(citation.source, *found)
            if span not in spans:
                spans.append(span)
        if not statement or classification is None or not spans:
            dropped += 1
            failing.append(index)
            continue
        if lost:
            failing.append(index)
        kept.append(ResolvedRequirement(statement, classification, tuple(spans)))
    return Resolution(tuple(kept), tuple(failing), dropped)


# --- human edits (Story 2.6) ----------------------------------------------------------------


def requirement_text(raw: str) -> str:
    """A Requirement's text as a person entered it: trimmed, 1 to `REQUIREMENT_TEXT_MAX`
    code points. Raises `ValueError` (with the sentence to show) otherwise."""
    trimmed = raw.strip()
    if not trimmed:
        raise ValueError("The Requirement text can't be blank.")
    if len(trimmed) > REQUIREMENT_TEXT_MAX:
        raise ValueError(
            f"The Requirement text can be at most {REQUIREMENT_TEXT_MAX:,} characters."
        )
    return trimmed


# --- incremental intake (Story 2.7) ---------------------------------------------------------

REJECT_REASON_MAX = 500
"""The most characters (Unicode code points) a pending change's rejection reason may have."""


class ChangeStatus(StrEnum):
    """A pending Requirement change's state."""

    OPEN = "open"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


def reject_reason(raw: str) -> str:
    """A rejection reason as a person entered it: trimmed, 1 to `REJECT_REASON_MAX` code
    points. Raises `ValueError` (with the sentence to show) otherwise."""
    trimmed = raw.strip()
    if not trimmed:
        raise ValueError("Give a reason for rejecting the change.")
    if len(trimmed) > REJECT_REASON_MAX:
        raise ValueError(f"The reason can be at most {REJECT_REASON_MAX} characters.")
    return trimmed


# --- shaping the list (Story 2.6) -----------------------------------------------------------

MERGE_MIN = 2
"""The fewest Requirements one merge takes."""
MERGE_MAX = 20
"""The most Requirements one merge takes."""
SPLIT_PARTS = 2
"""How many Requirements a split makes."""


def delete_reason(raw: str) -> str:
    """Why a person deletes a Requirement: the `reject_reason` rule (trimmed, 1 to
    `REJECT_REASON_MAX` code points). Raises `ValueError` (with the sentence to show)."""
    trimmed = raw.strip()
    if not trimmed:
        raise ValueError("Give a reason for deleting the Requirement.")
    if len(trimmed) > REJECT_REASON_MAX:
        raise ValueError(f"The reason can be at most {REJECT_REASON_MAX} characters.")
    return trimmed


def normalised_text(text: str) -> str:
    """`text` case-folded, with every run of whitespace collapsed to one space and trimmed:
    what the fallback match compares."""
    return " ".join(text.casefold().split())


@dataclass(frozen=True, slots=True, order=True)
class PassageKey:
    """A passage: a code-point span `[start, end)` in one Source version's text. `text`: the
    quoted text, normalised (`normalised_text`), when known; not part of its identity."""

    source_id: UUID
    version: int
    start: int
    end: int
    text: str | None = field(default=None, compare=False, repr=False)

    def overlaps(self, other: "PassageKey") -> bool:
        """Shared: overlapping spans in the same Source version, or (Story 2.7 review
        decision) equal normalised text in different versions of the same Source."""
        if self.source_id != other.source_id:
            return False
        if self.version == other.version:
            return self.start < other.end and other.start < self.end
        return self.text is not None and self.text == other.text


@dataclass(frozen=True, slots=True)
class ReconcileProposal:
    """A resolved proposal of the current extraction, its spans as passages."""

    text: str = field(repr=False)
    classification: Classification
    passages: tuple[PassageKey, ...]


@dataclass(frozen=True, slots=True)
class ExistingRequirement:
    """An active Requirement with the passages it already cites."""

    id: UUID
    text: str = field(repr=False)
    classification: str
    locked: bool
    passages: tuple[PassageKey, ...]


class ReconcileOutcome(StrEnum):
    ADD = "add"
    """Unmatched: a new Requirement."""
    VERSION = "version"
    """Changed and unlocked: the same Requirement at its next version."""
    PROPOSE = "propose"
    """Changed and locked by a human: a pending change."""
    UNCHANGED = "unchanged"
    """Matched, nothing new: nothing is written."""
    REMOVED = "removed"
    """Its best match is a Requirement a person deleted, split or merged away (Story 2.6):
    nothing is written, so re-extraction never revives it."""


@dataclass(frozen=True, slots=True)
class ReconcileStep:
    outcome: ReconcileOutcome
    proposal: ReconcileProposal
    requirement_id: UUID | None
    """The matched Requirement (the deleted one for `removed`); None for `add`."""
    new_passages: tuple[PassageKey, ...]
    """The proposal's passages the Requirement doesn't cite yet (overlapping none of its
    passages), in proposal order; every passage for `add`."""


def _shared(proposal: ReconcileProposal, existing: ExistingRequirement) -> int:
    return sum(1 for p in proposal.passages if any(p.overlaps(e) for e in existing.passages))


def reconcile(
    proposals: Sequence[ReconcileProposal],
    existing: Sequence[ExistingRequirement],
    removed: Sequence[ExistingRequirement] = (),
) -> tuple[ReconcileStep, ...]:
    """What to do with each proposal (one step per proposal, in proposal order), given the
    active Requirements, oldest first, and the ones a person removed: deleted, split or
    merged away (Story 2.6).

    Matching is one-to-one, over the active and the removed Requirements together (the
    removed after the active ones, so an active one wins a tie). A proposal matches the
    Requirement it shares the most cited passages with (overlapping spans in the same Source
    version, or equal normalised text in different versions of the same Source:
    `PassageKey.overlaps`); the pairs sharing most are matched first, ties going to the
    oldest Requirement (then the earliest proposal). Failing that, it matches the oldest
    unmatched Requirement with equal normalised text.

    A proposal whose match is a removed Requirement is `removed`: nothing is written. A
    match with an active one is changed when the proposal cites a passage the Requirement
    doesn't (one sharing none of its passages) and its normalised text or its classification
    differs; anything else is unchanged. Active Requirements no proposal matches are kept:
    nothing is ever removed."""
    candidates = [*existing, *removed]
    gone = len(existing)
    pairs = sorted(
        (
            (-shared, r_index, p_index)
            for p_index, proposal in enumerate(proposals)
            for r_index, requirement in enumerate(candidates)
            if (shared := _shared(proposal, requirement)) > 0
        )
    )
    matched: dict[int, int] = {}
    taken: set[int] = set()
    for _, r_index, p_index in pairs:
        if p_index in matched or r_index in taken:
            continue
        matched[p_index] = r_index
        taken.add(r_index)
    for p_index, proposal in enumerate(proposals):
        if p_index in matched:
            continue
        wanted = normalised_text(proposal.text)
        for r_index, requirement in enumerate(candidates):
            if r_index not in taken and normalised_text(requirement.text) == wanted:
                matched[p_index] = r_index
                taken.add(r_index)
                break

    steps: list[ReconcileStep] = []
    for p_index, proposal in enumerate(proposals):
        found = matched.get(p_index)
        if found is None:
            steps.append(ReconcileStep(ReconcileOutcome.ADD, proposal, None, proposal.passages))
            continue
        requirement = candidates[found]
        if found >= gone:
            steps.append(ReconcileStep(ReconcileOutcome.REMOVED, proposal, requirement.id, ()))
            continue
        new: list[PassageKey] = []
        for p in proposal.passages:
            if p not in new and not any(p.overlaps(e) for e in requirement.passages):
                new.append(p)
        differs = (
            normalised_text(proposal.text) != normalised_text(requirement.text)
            or proposal.classification.value != requirement.classification
        )
        if not (new and differs):
            outcome = ReconcileOutcome.UNCHANGED
        elif requirement.locked:
            outcome = ReconcileOutcome.PROPOSE
        else:
            outcome = ReconcileOutcome.VERSION
        steps.append(ReconcileStep(outcome, proposal, requirement.id, tuple(new)))
    return tuple(steps)
