"""The platform's parsers: one pure function `bytes -> str` per format, each raising
`ParseError(code)` when the file can't be turned into text. Imported only by the parse
child process (`app.platform.parsing.cli`)."""

from collections.abc import Callable
from dataclasses import dataclass

from app.platform.parsing.formats import docx, md, pdf, txt
from app.platform.parsing.rules import ParseError, ParseErrorCode, finish


@dataclass(frozen=True, slots=True)
class Parser:
    name: str
    """`<name>@<version>`, recorded on the parse row."""
    parse: Callable[[bytes], str]


def _not_supported(data: bytes) -> str:
    raise ParseError(ParseErrorCode.NOT_SUPPORTED)


PARSERS: dict[str, Parser] = {
    ".txt": Parser(txt.NAME, txt.parse),
    ".md": Parser(md.NAME, md.parse),
    ".docx": Parser(docx.NAME, docx.parse),
    ".pdf": Parser(pdf.NAME, pdf.parse),
}


@dataclass(frozen=True, slots=True)
class ParsedText:
    text: str
    """Normalised (`rules.normalise`), non-blank, at most `MAX_TEXT_CHARS`."""
    parser: str


def parse(data: bytes, ext: str) -> ParsedText:
    """The file's text as it is stored. Raises `ParseError`; any other failure inside a
    parser is reported as `unreadable`."""
    parser = PARSERS.get(ext, Parser("none@0", _not_supported))
    try:
        raw = parser.parse(data)
    except ParseError:
        raise
    except Exception:
        raise ParseError(ParseErrorCode.UNREADABLE) from None
    return ParsedText(text=finish(raw), parser=parser.name)
