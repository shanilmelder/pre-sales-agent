"""Requirement rules (Story 2.5 Part A): classifications, statuses, extraction states and
error codes, the input budget, and quote resolution. Pure.

`resolve_quote` turns a verbatim quote from the model into Unicode code-point offsets
`[start, end)` into the Source version's extracted text (Python `str` indices are code
points). An exact match wins; failing that, a match that ignores runs of whitespace and
case, mapped back to the original offsets.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

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
