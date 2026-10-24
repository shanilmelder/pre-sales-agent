"""Fenced data blocks for prompts (Story 5.4, AD-9): the one way tool and customer text
reaches a model prompt.

A block is

    <<<KIND label attr=value … token=T>>>
    text
    <<<END label token=T>>>

with `T` a random per-call token (`new_token`), so the text can't close its own block. On
top of that, `fence` neutralises every run of three or more `<` or `>` inside the text (each
becomes `U+2039` or `U+203A`), so text holding a delimiter, even one with the right token, can't
open or close a block. The label and attribute values are reduced to a safe character set.

`fence` also runs `injection_suspected`, the heuristic that flags text reading like an
instruction to the platform rather than data (moved here from `gaps.domain.gaps`, which
re-exports it). The flag only marks: it never changes the text or any status. Pure.
"""

import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field

_OPENERS = re.compile(r"<{3,}")
_CLOSERS = re.compile(r">{3,}")
_KIND = re.compile(r"^[A-Z][A-Z_]*$")
_UNSAFE = re.compile(r"[^A-Za-z0-9_.:/@-]")
_OPEN_MARK = chr(0x2039)  # SINGLE LEFT-POINTING ANGLE QUOTATION MARK
_CLOSE_MARK = chr(0x203A)  # SINGLE RIGHT-POINTING ANGLE QUOTATION MARK


def new_token() -> str:
    """A fresh per-call fence token (16 hex characters)."""
    return secrets.token_hex(8)


def neutralise(text: str) -> str:
    """`text` with every run of three or more `<` or `>` replaced, character for character,
    by `U+2039` or `U+203A`: it can no longer hold a block delimiter."""
    text = _OPENERS.sub(lambda m: _OPEN_MARK * len(m.group()), text)
    return _CLOSERS.sub(lambda m: _CLOSE_MARK * len(m.group()), text)


def _safe(value: str) -> str:
    """A label or attribute value with anything outside `[A-Za-z0-9_.:/@-]` made `_`."""
    return _UNSAFE.sub("_", value) or "_"


@dataclass(frozen=True, slots=True)
class Fenced:
    """One rendered block and whether its text reads like an injected instruction."""

    block: str = field(repr=False)
    injection_suspected: bool


def fence(
    kind: str,
    label: str,
    text: str,
    token: str,
    attrs: Mapping[str, str] | None = None,
) -> Fenced:
    """The data block for `text` (module docstring). `kind` is upper case (`REQUIREMENT`);
    `attrs` are rendered in order after the label, before the token."""
    if not _KIND.match(kind):
        raise ValueError("a data block kind is upper case, e.g. REQUIREMENT")
    if not re.fullmatch(r"[A-Za-z0-9]{1,64}", token):
        raise ValueError("a fence token is 1 to 64 letters and digits")
    name = _safe(label)
    head = " ".join(
        [f"<<<{kind} {name}", *(f"{_safe(k)}={_safe(v)}" for k, v in (attrs or {}).items())]
    )
    block = f"{head} token={token}>>>\n{neutralise(text)}\n<<<END {name} token={token}>>>"
    return Fenced(block=block, injection_suspected=injection_suspected(text))


# --- the injection heuristic (Story 4.7; moved here in Story 5.4) ----------------------------

_STATE_WORDS = (
    r"(?:answered|resolved|closed|open|dismissed|done|complete|completed|approved|sent|"
    r"irrelevant|not relevant)"
)
_INJECTION_PATTERNS = (
    # "Ignore previous instructions", "disregard the rules above".
    re.compile(
        r"\b(?:ignore|disregard|forget|override|bypass)\b[^.!?\n]{0,40}?"
        r"\b(?:instructions?|prompts?|rules?|directions?|guidelines?|context)\b"
    ),
    # "Mark all Gaps as answered", "set every question to resolved".
    re.compile(
        r"\b(?:mark|set|flag|change|update|move|treat|consider|record|close|resolve|dismiss|"
        r"reopen|approve)\b[^.!?\n]{0,60}?"
        r"\b(?:gaps?|questions?|clarifications?|status(?:es)?|requirements?|unknowns?)\b"
        rf"[^.!?\n]{{0,40}}?\b(?:as|to|is|are)\b[^.!?\n]{{0,20}}?\b{_STATE_WORDS}\b"
    ),
    # "All Gaps are answered", "every question has been resolved".
    re.compile(
        r"\b(?:all|every|each|any)\b[^.!?\n]{0,20}?\b(?:gaps?|questions?)\b[^.!?\n]{0,20}?"
        rf"\b(?:is|are|has been|have been|should be|must be)\b\s+{_STATE_WORDS}\b"
    ),
    # Talking to the model rather than to the vendor.
    re.compile(
        r"\b(?:you are now|from now on you|act as|pretend to be|system prompt|"
        r"new instructions?|developer message|as an ai)\b"
    ),
)


def injection_suspected(text: str) -> bool:
    """Whether `text` reads like an instruction to the platform rather than data: an
    imperative about statuses, Gaps, questions or instructions (e.g. "Mark all Gaps as
    answered", "Ignore previous instructions"). A heuristic that only flags: it never
    changes what is stored or any status."""
    folded = " ".join(text.casefold().split())
    return any(pattern.search(folded) for pattern in _INJECTION_PATTERNS)
