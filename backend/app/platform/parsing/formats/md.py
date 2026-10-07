"""`.md` (Knowledge Sources only): the UTF-8 Markdown source as is, without a leading byte
order mark. Markup is kept, so cited spans are exact spans of what the author wrote."""

from app.platform.parsing.rules import ParseError, ParseErrorCode

NAME = "markdown@1"


def parse(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ParseError(ParseErrorCode.UNREADABLE) from None
