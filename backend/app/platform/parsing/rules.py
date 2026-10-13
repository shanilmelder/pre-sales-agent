"""Parsing rules (Stories 2.2 Part B and 3.2): parse states, failure codes, and the
normalisation every extracted text goes through. Pure.

The extracted text is stored once and never changes: Story 2.5's Unicode code-point offsets
index exactly the string `normalise` returns.
"""

import unicodedata
from enum import StrEnum

MAX_TEXT_CHARS = 5_000_000
"""The most characters (code points) an extracted text may have (`too_large_output`)."""


class ParseStatus(StrEnum):
    QUEUED = "queued"
    PARSING = "parsing"
    PARSED = "parsed"
    FAILED = "failed"


class ParseErrorCode(StrEnum):
    UNREADABLE = "unreadable"
    """Corrupt, encrypted, or the parser failed."""
    NOT_SUPPORTED = "not_supported"
    """A format with no parser yet (`.msg`)."""
    NO_TEXT = "no_text"
    """Parsed, but nothing but whitespace came out (e.g. a scanned PDF)."""
    TIMEOUT = "timeout"
    """The parser ran past its time limit on the job's final attempt."""
    TOO_LARGE_OUTPUT = "too_large_output"
    """More than `MAX_TEXT_CHARS` characters."""


PERMANENT_CODES = frozenset(
    {
        ParseErrorCode.UNREADABLE,
        ParseErrorCode.NOT_SUPPORTED,
        ParseErrorCode.NO_TEXT,
        ParseErrorCode.TOO_LARGE_OUTPUT,
    }
)
"""Failures that retrying the same bytes cannot fix: the job finishes without a retry."""


class ParseError(Exception):
    """A Source version's file can't be turned into text. `code` says why; the message is
    the code too, never content."""

    def __init__(self, code: ParseErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


def normalise(text: str) -> str:
    """CRLF and lone CR become LF, then NFC. Idempotent."""
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def finish(text: str) -> str:
    """The text as stored: normalised, and checked for content and size. Raises
    `ParseError(no_text)` when only whitespace is left, `ParseError(too_large_output)` past
    `MAX_TEXT_CHARS`."""
    result = normalise(text)
    if not result.strip():
        raise ParseError(ParseErrorCode.NO_TEXT)
    if len(result) > MAX_TEXT_CHARS:
        raise ParseError(ParseErrorCode.TOO_LARGE_OUTPUT)
    return result
