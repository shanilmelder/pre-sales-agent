"""Shared upload checks (Stories 2.1 and 3.2): the file-name rules, the extension of a
file, and whether its bytes match that extension (magic bytes for binary formats, valid
UTF-8 without NUL bytes for text), with the exact rejection sentences the UI shows.

Opportunity Sources (`intake`) and Knowledge Sources (`knowledge`) each keep their own
allowlist of extensions; the checks below are generic. Pure: reads only the file object it
is given. Customer content is untrusted, so nothing here parses more than these checks need.
"""

import codecs
import unicodedata
import zipfile
from typing import BinaryIO

FILENAME_MAX = 255
_TEXT_CHUNK = 64 * 1024
PDF_HEADER_WINDOW = 1024

PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
VTT_MAGIC = b"WEBVTT"
UTF8_BOM = b"\xef\xbb\xbf"

TEXT_EXTENSIONS = frozenset({".txt", ".eml", ".md"})
"""Extensions whose bytes must be valid UTF-8 without NUL bytes."""

EMPTY_MESSAGE = "Rejected: the file is empty"
FILENAME_TOO_LONG_MESSAGE = f"Rejected: the file name is longer than {FILENAME_MAX} characters"
FILENAME_INVALID_MESSAGE = "Rejected: the file name isn't valid"


class InvalidFilenameError(ValueError):
    """The filename can't be stored. `message` is the UI sentence."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def clean_filename(raw: str) -> str:
    """The filename as given, without any path components and trimmed. Raises
    `InvalidFilenameError` when nothing is left, it has control or format characters
    (Unicode Cc/Cf, e.g. a bidi override that could disguise the extension), or it is
    longer than `FILENAME_MAX` characters."""
    name = raw.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if (
        not name
        or name in {".", ".."}
        or any(unicodedata.category(ch) in {"Cc", "Cf"} for ch in name)
    ):
        raise InvalidFilenameError(FILENAME_INVALID_MESSAGE)
    if len(name) > FILENAME_MAX:
        raise InvalidFilenameError(FILENAME_TOO_LONG_MESSAGE)
    return name


def extension(filename: str) -> str:
    """The lowercase extension with its dot (`.pdf`), or "" when there is none."""
    stem, dot, ext = filename.rpartition(".")
    if not dot or not stem or not ext:
        return ""
    return f".{ext.lower()}"


def type_rejected_message(filename: str) -> str:
    ext = extension(filename)
    if not ext:
        return "Rejected: files without an extension aren't allowed"
    return f"Rejected: {ext} files aren't allowed"


def too_large_message(max_bytes: int) -> str:
    megabytes = max_bytes / (1024 * 1024)
    shown = f"{megabytes:.0f}" if megabytes.is_integer() else f"{megabytes:.1f}"
    return f"Rejected: larger than {shown} MB"


def mismatch_message(ext: str) -> str:
    return f"Rejected: the content doesn't match {ext}"


def _is_docx(stream: BinaryIO) -> bool:
    if stream.read(len(ZIP_MAGIC)) != ZIP_MAGIC:
        return False
    stream.seek(0)
    try:
        with zipfile.ZipFile(stream) as archive:
            return any(name.startswith("word/") for name in archive.namelist())
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ValueError, OSError, EOFError):
        return False


def _is_utf8_text(stream: BinaryIO) -> bool:
    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    try:
        while chunk := stream.read(_TEXT_CHUNK):
            if b"\x00" in chunk:
                return False
            decoder.decode(chunk)
        decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        return False
    return True


def content_matches(ext: str, stream: BinaryIO) -> bool:
    """True if the bytes in `stream` (positioned at the start) match the extension: pdf
    has `%PDF-` within its first 1024 bytes; docx is a ZIP with a `word/` entry; msg is
    an OLE compound file; vtt starts with `WEBVTT` after an optional UTF-8 BOM; txt, md
    and eml are valid UTF-8 with no NUL bytes. Unknown extensions never match."""
    if ext in TEXT_EXTENSIONS:
        return _is_utf8_text(stream)
    if ext == ".docx":
        return _is_docx(stream)
    if ext == ".pdf":
        # The PDF spec lets the header sit anywhere in the first 1024 bytes.
        return PDF_MAGIC in stream.read(PDF_HEADER_WINDOW)
    head = stream.read(len(UTF8_BOM) + len(VTT_MAGIC))
    if ext == ".msg":
        return head.startswith(OLE_MAGIC)
    if ext == ".vtt":
        return head.removeprefix(UTF8_BOM).startswith(VTT_MAGIC)
    return False
