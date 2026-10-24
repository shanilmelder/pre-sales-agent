"""`.html` (Research Snapshots, Story 5.4): the page's visible text, with the stdlib
`html.parser`. `script`, `style`, `noscript`, `template`, `head` metadata other than the
title, and comments are dropped; block elements and `<br>` end a line; runs of spaces and
tabs collapse to one space and blank-line runs to one blank line. Character references are
decoded. Bytes are UTF-8 (a BOM is dropped); a page that isn't valid UTF-8 is read as
Windows-1252 (every byte maps), so no page fails to decode.
"""

import re
from html.parser import HTMLParser

NAME = "html@1"

_DROPPED = frozenset({"script", "style", "noscript", "template", "svg", "iframe", "object"})
_BLOCKS = frozenset(
    {
        "address", "article", "aside", "blockquote", "body", "dd", "details", "div", "dl",
        "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4",
        "h5", "h6", "header", "hr", "html", "li", "main", "nav", "ol", "p", "pre", "section",
        "summary", "table", "tbody", "td", "tfoot", "th", "thead", "title", "tr", "ul",
    }
)  # fmt: skip
_VOID = frozenset({"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "wbr"})
_SPACES = re.compile(r"[ \t\f\v\u00a0]+")
_BLANK_LINES = re.compile(r"\n{3,}")


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._dropped = 0
        self._in_head = False
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _DROPPED:
            if tag not in _VOID:
                self._dropped += 1
            return
        if tag == "head":
            self._in_head = True
        if tag == "title":
            self._in_title = True
        if tag in _BLOCKS or tag == "br":
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCKS or tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROPPED:
            self._dropped = max(0, self._dropped - 1)
            return
        if tag == "head":
            self._in_head = False
        if tag == "title":
            self._in_title = False
        if tag in _BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._dropped or (self._in_head and not self._in_title):
            return
        self.parts.append(data)


def _decode(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def parse(data: bytes) -> str:
    parser = _TextParser()
    parser.feed(_decode(data))
    parser.close()
    lines = [_SPACES.sub(" ", line).strip() for line in "".join(parser.parts).split("\n")]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()
