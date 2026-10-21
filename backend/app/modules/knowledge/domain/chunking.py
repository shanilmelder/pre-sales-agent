"""Splitting a Source version's extracted text into citable chunks (Story 3.3). Pure, no I/O.

Offsets are Unicode code points (Python `str` indexes) into the extracted text, so every
chunk satisfies `text[chunk.start:chunk.end] == chunk.text`.

1. **Sections.** A Markdown heading line (`#` to `######`) starts a new section, except
   inside a fenced code block (``` or ~~~), where `#` lines are code. A heading
   with no body before the next heading is not a section of its own: it is merged into the
   next one, so a chunk never holds a heading alone; trailing headings with no body are
   dropped. Text before the first heading is a section too.
2. **Chunks.** A section up to `max_chars` (after trimming surrounding whitespace) is one
   chunk. A longer one is cut into windows of at most `max_chars`, each ending at the last
   paragraph break, else line break, else whitespace in the window's second half (a hard cut
   only when there is none), and each starting `overlap` characters before the previous
   window's end, moved forward to the start of a word. Chunks never cross a section.
3. Surrounding whitespace is trimmed from every chunk, and whitespace-only pieces are
   dropped, so no chunk is empty.
"""

import re
from dataclasses import dataclass

_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}(?:[ \t]+.*)?$", re.MULTILINE)
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")
_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class Chunk:
    ordinal: int
    start: int
    end: int
    text: str

    def __repr__(self) -> str:  # never echo Source text into logs or tracebacks
        return f"Chunk(ordinal={self.ordinal}, start={self.start}, end={self.end})"


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    """`[start, end)` without leading or trailing whitespace (empty when all whitespace)."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _has_body(text: str, start: int, end: int) -> bool:
    """True when `[start, end)` holds something other than heading lines and whitespace."""
    for line in text[start:end].splitlines():
        if line.strip() and not _HEADING.fullmatch(line):
            return True
    return False


def _fenced(text: str) -> list[tuple[int, int]]:
    """`[start, end)` of every fenced code block (``` or ~~~, closed by a fence of the same
    character at least as long; an unclosed one runs to the end)."""
    blocks: list[tuple[int, int]] = []
    opener: str | None = None
    start = 0
    for match in _FENCE.finditer(text):
        fence = match.group(1)
        if opener is None:
            opener, start = fence, match.start()
        elif fence[0] == opener[0] and len(fence) >= len(opener):
            line_end = text.find("\n", match.end())
            blocks.append((start, len(text) if line_end == -1 else line_end))
            opener = None
    if opener is not None:
        blocks.append((start, len(text)))
    return blocks


def _sections(text: str) -> list[tuple[int, int]]:
    fenced = _fenced(text)
    heading_starts = [
        m.start()
        for m in _HEADING.finditer(text)
        if not any(start <= m.start() < end for start, end in fenced)
    ]
    sections: list[tuple[int, int]] = []
    begin = 0
    for heading in heading_starts:
        if heading == begin:
            continue
        if _has_body(text, begin, heading):
            sections.append((begin, heading))
            begin = heading
        elif not text[begin:heading].strip():
            begin = heading  # only whitespace before this heading: start at the heading
        # else: headings without a body so far; merge them into the next section
    if _has_body(text, begin, len(text)):
        sections.append((begin, len(text)))
    return sections


def _cut(text: str, start: int, limit: int) -> int:
    """Where a window `[start, limit)` should end: the last paragraph break, line break or
    whitespace in its second half, else `limit`."""
    half = start + (limit - start) // 2
    window = text[half:limit]
    breaks = list(_PARAGRAPH_BREAK.finditer(window))
    if breaks:
        return half + breaks[-1].start()
    newline = window.rfind("\n")
    if newline > 0:
        return half + newline
    for index in range(limit - 1, half, -1):
        if text[index].isspace():
            return index
    return limit


def _word_start(text: str, position: int, floor: int) -> int:
    """The first word start at or after `position` (not before `floor`)."""
    position = max(position, floor)
    if position > 0 and not text[position - 1].isspace():
        while position < len(text) and not text[position].isspace():
            position += 1
    while position < len(text) and text[position].isspace():
        position += 1
    return position


def _windows(
    text: str, start: int, end: int, max_chars: int, overlap: int
) -> list[tuple[int, int]]:
    pieces: list[tuple[int, int]] = []
    position = start
    while position < end:
        position, _ = _trim(text, position, end)
        if position >= end:
            break
        if end - position <= max_chars:
            pieces.append((position, end))
            break
        cut = _cut(text, position, position + max_chars)
        piece = _trim(text, position, cut)
        if piece[1] > piece[0]:
            pieces.append(piece)
        # The next window starts up to `overlap` before the cut, at a word start; never past
        # the cut (no text is skipped) and never back at or before this window's start.
        following = min(_word_start(text, cut - overlap, position + 1), cut)
        position = following if following > position else cut
    return pieces


def chunk_text(text: str, *, max_chars: int, overlap: int) -> list[Chunk]:
    """The chunks of `text` (module docstring). `0 <= overlap` and `2 * overlap < max_chars`."""
    if max_chars < 1 or overlap < 0 or 2 * overlap >= max_chars:
        raise ValueError("need max_chars >= 1 and 0 <= overlap < max_chars / 2")
    chunks: list[Chunk] = []
    for section_start, section_end in _sections(text):
        start, end = _trim(text, section_start, section_end)
        for piece_start, piece_end in _windows(text, start, end, max_chars, overlap):
            chunks.append(
                Chunk(
                    ordinal=len(chunks),
                    start=piece_start,
                    end=piece_end,
                    text=text[piece_start:piece_end],
                )
            )
    return chunks
