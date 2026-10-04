"""`.eml`: stdlib `email` with the default policy.

The text is the Subject, From, To and Date lines (those present), a blank line, then the
text/plain body parts. With no text/plain part, the text/html parts with their tags
stripped. Attachments (and anything inside them, e.g. an attached message) are ignored.
"""

import email
import email.policy
import re
from collections.abc import Iterator
from email.message import Message
from html.parser import HTMLParser

NAME = "email@1"
HEADERS = ("Subject", "From", "To", "Date")
_BLOCK_TAGS = frozenset(
    {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol"}
)
_SKIP_TAGS = frozenset({"script", "style", "head", "title"})
_SPACES = re.compile("[ \\t\\u00a0]+")  # spaces, tabs and no-break spaces


def _leaves(part: Message) -> Iterator[Message]:
    """Body parts in order, not descending into attachments."""
    disposition = part.get_content_disposition()
    if disposition == "attachment":
        return
    if part.is_multipart():
        for sub in part.get_payload():
            if isinstance(sub, Message):
                yield from _leaves(sub)
        return
    yield part


def _content(part: Message) -> str:
    raw = part.get_payload(decode=True)
    if not isinstance(raw, bytes):
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:  # an unknown charset name
        return raw.decode("utf-8", errors="replace")


class _HtmlText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skipping += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skipping = max(0, self._skipping - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """Tags stripped; block elements become line breaks, runs of blank lines one."""
    parser = _HtmlText()
    parser.feed(html)
    parser.close()
    text = "".join(parser.parts)  # character references already decoded (convert_charrefs)
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def parse(data: bytes) -> str:
    message = email.message_from_bytes(data, policy=email.policy.default)
    header_lines = [f"{name}: {message[name]}" for name in HEADERS if message.get(name) is not None]
    leaves = list(_leaves(message))
    plain = [_content(p) for p in leaves if p.get_content_type() == "text/plain"]
    if plain:
        body = "\n\n".join(text.strip("\r\n") for text in plain)
    else:
        html = [_content(p) for p in leaves if p.get_content_type() == "text/html"]
        body = "\n\n".join(html_to_text(text) for text in html)
    return "\n".join(header_lines) + "\n\n" + body
