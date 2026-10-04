"""Source parsers (Story 2.2 Part B): one module per format, each a pure function
`bytes -> str` that raises `ParseError(code)` when the file can't be turned into text.

Only the parse child process (`app.modules.intake.adapters.parse_cli`) runs them, under its
time and memory limits; the api and the worker's own process never import this package.
Customer files are untrusted: nothing here follows links, runs macros or fetches anything.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.modules.intake.adapters.parsers import docx, eml, pdf, txt, vtt
from app.modules.intake.domain.parsing import ParseError, ParseErrorCode, finish


@dataclass(frozen=True, slots=True)
class Parser:
    name: str
    """`<name>@<version>`, recorded on the parse row."""
    parse: Callable[[bytes], str]


def _not_supported(data: bytes) -> str:
    raise ParseError(ParseErrorCode.NOT_SUPPORTED)


PARSERS: dict[str, Parser] = {
    ".txt": Parser(txt.NAME, txt.parse),
    ".eml": Parser(eml.NAME, eml.parse),
    ".vtt": Parser(vtt.NAME, vtt.parse),
    ".docx": Parser(docx.NAME, docx.parse),
    ".pdf": Parser(pdf.NAME, pdf.parse),
    # `.msg` waits for a permissively licensed parser (`extract-msg` is GPL-3.0) [post-demo].
    ".msg": Parser("msg@0", _not_supported),
}


@dataclass(frozen=True, slots=True)
class ParsedText:
    text: str
    """Normalised (`domain.parsing.normalise`), non-blank, at most `MAX_TEXT_CHARS`."""
    parser: str


def parser_for(ext: str) -> Parser:
    """The parser for a lowercase extension with its dot. Unknown ones are `not_supported`."""
    return PARSERS.get(ext, Parser("none@0", _not_supported))


def parse(data: bytes, ext: str) -> ParsedText:
    """The file's text as it is stored. Raises `ParseError`; any other failure inside a
    parser is reported as `unreadable`."""
    parser = parser_for(ext)
    try:
        raw = parser.parse(data)
    except ParseError:
        raise
    except Exception:
        raise ParseError(ParseErrorCode.UNREADABLE) from None
    return ParsedText(text=finish(raw), parser=parser.name)


__all__ = ["PARSERS", "ParseError", "ParseErrorCode", "ParsedText", "Parser", "parse"]
