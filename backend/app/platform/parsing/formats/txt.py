"""`.txt` (and pasted text): the UTF-8 text as is, without a leading byte order mark."""

from app.platform.parsing.rules import ParseError, ParseErrorCode

NAME = "text@1"


def parse(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ParseError(ParseErrorCode.UNREADABLE) from None
