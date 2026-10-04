"""The context shown around a cited Source passage (Story 2.5 Part B). Pure.

Offsets are Unicode code points (Python `str` indices), the same as the stored passage.
"""

from dataclasses import dataclass, field

CONTEXT_WIDTH = 300
"""The most code points of context on each side of a passage, the ellipsis included."""
ELLIPSIS = "…"


@dataclass(frozen=True, slots=True)
class ContextWindow:
    before: str = field(repr=False)
    text: str = field(repr=False)
    after: str = field(repr=False)


def _before(text: str, start: int, width: int) -> str:
    if start <= width:
        return text[:start]
    # Room for the ellipsis inside `width`.
    first = start - (width - 1)
    window = text[first:start]
    if not text[first - 1].isspace() and not window[0].isspace():
        # The window starts inside a word: drop that word's tail.
        cut = next((i for i, ch in enumerate(window) if ch.isspace()), len(window))
        window = window[cut:]
    return ELLIPSIS + (window.lstrip() or window)


def _after(text: str, end: int, width: int) -> str:
    if len(text) - end <= width:
        return text[end:]
    last = end + (width - 1)  # exclusive
    window = text[end:last]
    if not text[last].isspace() and not window[-1].isspace():
        # The window ends inside a word: drop that word's head.
        cut = next((i + 1 for i in range(len(window) - 1, -1, -1) if window[i].isspace()), 0)
        window = window[:cut]
    return (window.rstrip() or window) + ELLIPSIS


def context_window(text: str, start: int, end: int, width: int = CONTEXT_WIDTH) -> ContextWindow:
    """The span `text[start:end]` with up to `width` code points of context on each side.

    Context that reaches the start or end of `text` is returned whole, without an ellipsis.
    Context that doesn't is cut back to whitespace so no word is split, its outer whitespace
    trimmed (unless that would leave nothing), and `…` added on the cut side; with the
    ellipsis it is at most `width` long.
    The side touching the span is never changed."""
    if not 0 <= start < end <= len(text):
        raise ValueError("span outside the text")
    if width < 2:
        raise ValueError("width too small")
    return ContextWindow(
        before=_before(text, start, width),
        text=text[start:end],
        after=_after(text, end, width),
    )
