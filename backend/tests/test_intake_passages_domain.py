"""`context_window` (Story 2.5 Part B), without a DB."""

import pytest

from app.modules.intake.domain.passages import CONTEXT_WIDTH, ELLIPSIS, context_window


def _words(n: int, word: str = "word") -> str:
    return " ".join(f"{word}{i:03d}" for i in range(n))


def test_the_span_is_exact_and_each_side_is_cut_at_whitespace() -> None:
    text = _words(125)  # 999 code points, "word000 word001 …"
    text += "."  # 1,000
    assert len(text) == 1000
    window = context_window(text, 120, 160)

    assert window.text == text[120:160]
    assert len(window.before) <= CONTEXT_WIDTH
    assert len(window.after) <= CONTEXT_WIDTH
    assert window.before == text[:120]  # within 300 of the start: whole, no ellipsis
    assert window.after.endswith(ELLIPSIS)
    body = window.after.removesuffix(ELLIPSIS)
    assert text[160:].startswith(body)
    # Cut at whitespace: the next character in the text is a space, and no trailing space.
    assert text[160 + len(body)] == " "
    assert not body.endswith(" ")


def test_a_long_before_is_cut_at_whitespace_with_an_ellipsis() -> None:
    text = _words(125)
    start = 800
    window = context_window(text, start, start + 10)

    assert window.before.startswith(ELLIPSIS)
    assert len(window.before) <= CONTEXT_WIDTH
    body = window.before.removeprefix(ELLIPSIS)
    assert text[:start].endswith(body)
    first = start - len(body)
    assert text[first - 1] == " "  # a whole word starts the context
    assert not body.startswith(" ")


def test_the_side_touching_the_span_is_kept_as_is() -> None:
    text = "a " * 400 + "SPAN" + "  \n b" * 100
    start = text.index("SPAN")
    window = context_window(text, start, start + 4)
    assert window.text == "SPAN"
    assert window.before.endswith("a ")
    assert window.after.startswith("  \n b")


def test_a_passage_at_offset_0_has_an_empty_before() -> None:
    text = _words(125) + "."
    window = context_window(text, 0, 7)
    assert (window.before, window.text) == ("", "word000")
    assert window.after.endswith(ELLIPSIS)


def test_a_passage_ending_at_the_last_character_has_an_empty_after() -> None:
    text = _words(125) + "."
    window = context_window(text, 992, 1000)
    assert (window.text, window.after) == ("word124.", "")
    assert window.before.startswith(ELLIPSIS)


def test_a_passage_covering_the_whole_text_has_no_context() -> None:
    window = context_window("All of it.", 0, 10)
    assert (window.before, window.text, window.after) == ("", "All of it.", "")


def test_context_reaching_the_edge_exactly_is_whole() -> None:
    text = "x" * CONTEXT_WIDTH + "SPAN" + "y" * CONTEXT_WIDTH
    window = context_window(text, CONTEXT_WIDTH, CONTEXT_WIDTH + 4)
    assert window.before == "x" * CONTEXT_WIDTH
    assert window.after == "y" * CONTEXT_WIDTH


def test_one_word_longer_than_the_window_leaves_only_the_ellipsis() -> None:
    text = "x" * 500 + " SPAN " + "y" * 500
    start = text.index("SPAN")
    window = context_window(text, start, start + 4)
    # The whitespace touching the span is kept.
    assert window.before == ELLIPSIS + " "
    assert window.after == " " + ELLIPSIS


def test_offsets_are_code_points_with_non_bmp_characters() -> None:
    emoji = "\U0001f600\U0001f680"  # outside the BMP: 2 code points, 4 UTF-16 units
    text = f"Hi {emoji} we need SAP integration {emoji} soon."
    quote = "we need SAP integration"
    start = text.index(quote)
    assert start == 6  # code points, not UTF-16 units
    window = context_window(text, start, start + len(quote))
    assert window.text == quote
    assert window.before == f"Hi {emoji} "
    assert window.after == f" {emoji} soon."


def test_long_non_bmp_context_stays_within_the_width_in_code_points() -> None:
    text = ("\U0001f600 " * 400) + "SPAN" + (" \U0001f680" * 400)
    start = text.index("SPAN")
    window = context_window(text, start, start + 4)
    assert len(window.before) <= CONTEXT_WIDTH
    assert len(window.after) <= CONTEXT_WIDTH
    assert window.before.startswith(ELLIPSIS + "\U0001f600")
    assert window.after.endswith("\U0001f680" + ELLIPSIS)


@pytest.mark.parametrize(("start", "end"), [(-1, 2), (3, 3), (2, 11), (5, 4)])
def test_a_span_outside_the_text_is_rejected(start: int, end: int) -> None:
    with pytest.raises(ValueError, match="span"):
        context_window("0123456789", start, end)
