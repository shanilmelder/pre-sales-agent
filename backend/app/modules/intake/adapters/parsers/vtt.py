"""`.vtt` (WebVTT transcripts), in-house.

Drops the `WEBVTT` header block, NOTE, STYLE and REGION blocks, cue identifiers and timing
lines. In cue text, `<v Name>text` becomes `Name: text`, other tags are stripped and
character references decoded. Each cue's text lines are kept, and cues are joined with
newlines.
"""

import re
from html import unescape

from app.modules.intake.domain.parsing import ParseError, ParseErrorCode

NAME = "vtt@1"
_VOICE = re.compile(r"<v(?:\.[^\s>]*)?(?:\s+([^>]*))?>")
_TAG = re.compile(r"<[^>]*>")
_SKIPPED_BLOCKS = ("NOTE", "STYLE", "REGION")


def _is_block(first_line: str, keyword: str) -> bool:
    return first_line == keyword or first_line.startswith((f"{keyword} ", f"{keyword}\t"))


def _cue_line(line: str) -> str:
    def voice(match: re.Match[str]) -> str:
        name = (match.group(1) or "").strip()
        return f"{name}: " if name else ""

    text = _VOICE.sub(voice, line)
    text = _TAG.sub("", text)
    return unescape(text).strip()


def parse(data: bytes) -> str:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ParseError(ParseErrorCode.UNREADABLE) from None
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n[ \t]*\n", text)
    if not blocks or not blocks[0].startswith("WEBVTT"):
        raise ParseError(ParseErrorCode.UNREADABLE)
    cues: list[str] = []
    for block in blocks[1:]:
        lines = block.strip("\n").split("\n")
        if not lines or not lines[0].strip():
            continue
        if any(_is_block(lines[0], keyword) for keyword in _SKIPPED_BLOCKS):
            continue
        timing = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing is None:
            continue  # not a cue
        payload = [_cue_line(line) for line in lines[timing + 1 :]]
        cue = "\n".join(line for line in payload if line)
        if cue:
            cues.append(cue)
    return "\n".join(cues)
