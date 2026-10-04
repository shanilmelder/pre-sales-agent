"""`.docx`: `word/document.xml` read with the stdlib (`zipfile` plus ElementTree).

One line per `w:p` paragraph in document order (table cells included), its `w:t` texts
concatenated, `w:tab` as a tab and `w:br`/`w:cr` as a newline. A paragraph nested inside
another (e.g. in a text box) is its own line, not repeated in its parent. Markup-
compatibility `mc:Fallback` content (an older copy of an `mc:Choice`, e.g. a text box) is
skipped, so it isn't read twice. A `document.xml` with a DOCTYPE or entity declaration is
refused as `unreadable` before parsing (no entity expansion).
"""

import io
import zipfile
from xml.etree import ElementTree as ET

from app.modules.intake.domain.parsing import ParseError, ParseErrorCode

NAME = "docx@1"
DOCUMENT = "word/document.xml"
MAX_DOCUMENT_BYTES = 256 * 1024 * 1024
"""Refuse a `document.xml` that would inflate past this (a zip bomb)."""
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_P, _T, _TAB, _BR, _CR = f"{_W}p", f"{_W}t", f"{_W}tab", f"{_W}br", f"{_W}cr"
_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
_DECLARATIONS = (b"<!DOCTYPE", b"<!ENTITY")


def _paragraphs(element: ET.Element) -> list[ET.Element]:
    """Every `w:p` in document order, outside `mc:Fallback` subtrees."""
    found: list[ET.Element] = []

    def walk(node: ET.Element) -> None:
        for child in node:
            if child.tag == _FALLBACK:
                continue
            if child.tag == _P:
                found.append(child)
            walk(child)

    walk(element)
    return found


def _paragraph_text(paragraph: ET.Element) -> str:
    parts: list[str] = []

    def walk(element: ET.Element) -> None:
        for child in element:
            if child.tag in (_P, _FALLBACK):
                continue  # a nested paragraph is its own line; a fallback is a copy
            if child.tag == _T:
                parts.append(child.text or "")
            elif child.tag == _TAB:
                parts.append("\t")
            elif child.tag in (_BR, _CR):
                parts.append("\n")
            else:
                walk(child)

    walk(paragraph)
    return "".join(parts)


def parse(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo(DOCUMENT)
            if info.file_size > MAX_DOCUMENT_BYTES:
                raise ParseError(ParseErrorCode.UNREADABLE)
            xml = archive.read(info)
    except ParseError:
        raise
    except (zipfile.BadZipFile, KeyError, RuntimeError, ValueError, OSError, EOFError):
        # RuntimeError: an encrypted entry.
        raise ParseError(ParseErrorCode.UNREADABLE) from None
    if any(declaration in xml for declaration in _DECLARATIONS):
        raise ParseError(ParseErrorCode.UNREADABLE)
    try:
        root = ET.fromstring(xml)  # noqa: S314 (sandboxed child; expat refuses external entities)
    except ET.ParseError:
        raise ParseError(ParseErrorCode.UNREADABLE) from None
    return "\n".join(_paragraph_text(p) for p in _paragraphs(root))
