"""Opportunity Source rules (Story 2.1): the file allowlist, content checks, the pasted-text
rules and the exact rejection sentences the UI shows. Pure: reads only the file object it
is given.

A file's kind comes from its extension, matched ignoring case. Its bytes must then match
that extension (magic bytes for binary formats, valid UTF-8 without NUL bytes for text).
Customer content is untrusted, so nothing here parses more than these checks need.
"""

from enum import StrEnum

from app.platform.upload_validation import (
    EMPTY_MESSAGE,
    FILENAME_INVALID_MESSAGE,
    FILENAME_MAX,
    FILENAME_TOO_LONG_MESSAGE,
    OLE_MAGIC,
    PDF_HEADER_WINDOW,
    PDF_MAGIC,
    UTF8_BOM,
    VTT_MAGIC,
    ZIP_MAGIC,
    InvalidFilenameError,
    clean_filename,
    content_matches,
    extension,
    mismatch_message,
    too_large_message,
    type_rejected_message,
)

SUBJECT_TYPE = "intake.source"

__all__ = [
    "EMPTY_MESSAGE",
    "EXTENSION_KINDS",
    "FILENAME_INVALID_MESSAGE",
    "FILENAME_MAX",
    "FILENAME_TOO_LONG_MESSAGE",
    "OLE_MAGIC",
    "PASTED_TEXT_FILENAME",
    "PASTED_TEXT_KIND",
    "PDF_HEADER_WINDOW",
    "PDF_MAGIC",
    "SUBJECT_TYPE",
    "TEXT_EMPTY_MESSAGE",
    "TEXT_MAX_CHARS",
    "TEXT_TOO_LONG_MESSAGE",
    "TEXT_UNSUPPORTED_MESSAGE",
    "UTF8_BOM",
    "VTT_MAGIC",
    "ZIP_MAGIC",
    "InvalidFilenameError",
    "PastedTextEmptyError",
    "PastedTextError",
    "PastedTextTooLongError",
    "PastedTextUnsupportedError",
    "SourceKind",
    "clean_filename",
    "clean_pasted_text",
    "content_matches",
    "extension",
    "kind_for",
    "mismatch_message",
    "too_large_message",
    "type_rejected_message",
]


class SourceKind(StrEnum):
    EMAIL = "email"
    NOTE = "note"
    TRANSCRIPT = "transcript"
    DOCUMENT = "document"


EXTENSION_KINDS: dict[str, SourceKind] = {
    ".eml": SourceKind.EMAIL,
    ".msg": SourceKind.EMAIL,
    ".txt": SourceKind.NOTE,
    ".vtt": SourceKind.TRANSCRIPT,
    ".docx": SourceKind.DOCUMENT,
    ".pdf": SourceKind.DOCUMENT,
}

PASTED_TEXT_FILENAME = "Pasted text"
"""The version filename of a Source added by pasting text (Story 2.1 Part B)."""
PASTED_TEXT_KIND = SourceKind.NOTE
TEXT_MAX_CHARS = 1_000_000
TEXT_EMPTY_MESSAGE = "Rejected: the text is empty"
TEXT_TOO_LONG_MESSAGE = f"Rejected: longer than {TEXT_MAX_CHARS:,} characters"
TEXT_UNSUPPORTED_MESSAGE = "Rejected: the text contains unsupported characters"


class PastedTextError(ValueError):
    """Pasted text that can't be stored. `message` is the UI sentence."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class PastedTextEmptyError(PastedTextError):
    """Nothing is left once the text is trimmed."""

    def __init__(self) -> None:
        super().__init__(TEXT_EMPTY_MESSAGE)


class PastedTextTooLongError(PastedTextError):
    """The trimmed text is longer than `TEXT_MAX_CHARS` code points."""

    def __init__(self) -> None:
        super().__init__(TEXT_TOO_LONG_MESSAGE)


class PastedTextUnsupportedError(PastedTextError):
    """The text has a NUL character or a lone surrogate, so it can't be stored as UTF-8
    text the way a `.txt` upload must be."""

    def __init__(self) -> None:
        super().__init__(TEXT_UNSUPPORTED_MESSAGE)


def clean_pasted_text(raw: str) -> str:
    """The pasted text trimmed of leading and trailing whitespace (`str.strip`). It must
    then be 1 to `TEXT_MAX_CHARS` code points (Python `len`) with no NUL character and no
    lone surrogate; otherwise the matching `PastedTextError` is raised."""
    text = raw.strip()
    if not text:
        raise PastedTextEmptyError
    if len(text) > TEXT_MAX_CHARS:
        raise PastedTextTooLongError
    if "\x00" in text:
        raise PastedTextUnsupportedError
    try:
        text.encode("utf-8")  # fails only on a lone surrogate
    except UnicodeEncodeError:
        raise PastedTextUnsupportedError from None
    return text


def kind_for(filename: str) -> SourceKind | None:
    """The Source kind for an allowed extension, or None when it isn't allowed."""
    return EXTENSION_KINDS.get(extension(filename))
