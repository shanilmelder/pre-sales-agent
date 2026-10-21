"""The Knowledge chunker (Story 3.3), pure: every chunk is exactly `text[start:end]`, never
empty, never longer than the limit, in order, and together they cover every non-whitespace
character; headings start sections and a heading with no body never forms a chunk alone."""

from itertools import pairwise

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.knowledge.domain.chunking import Chunk, chunk_text
from app.modules.knowledge.domain.embedding import search_query, span_inside


def _check(text: str, chunks: list[Chunk], max_chars: int) -> None:
    previous_start = -1
    for index, chunk in enumerate(chunks):
        assert chunk.ordinal == index
        assert text[chunk.start : chunk.end] == chunk.text
        assert chunk.text.strip() and chunk.text == chunk.text.strip()
        assert 0 <= chunk.start < chunk.end <= len(text)
        assert chunk.end - chunk.start <= max_chars
        assert chunk.start > previous_start
        previous_start = chunk.start
    covered = set()
    for chunk in chunks:
        covered.update(range(chunk.start, chunk.end))
    body = "\n".join(
        line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")
    )
    if body.strip():
        missing = [i for i, ch in enumerate(text) if not ch.isspace() and i not in covered]
        # Only characters of trailing body-less headings may be left out.
        assert all(text[text.rfind("\n", 0, i) + 1 :].lstrip().startswith("#") for i in missing)


_WORDS = st.sampled_from(
    ["alpha", "beta", "Größe", "日本語", "🙂", "x" * 30, "port", "40", "-", "é", "\t"]
)
_LINES = st.one_of(
    st.lists(_WORDS, min_size=0, max_size=30).map(" ".join),
    st.sampled_from(["# Heading", "## Sub heading", "###", "   ", "", "#no-space"]),
)
_TEXTS = st.lists(_LINES, min_size=0, max_size=60).map("\n".join)


@settings(max_examples=300, deadline=None)
@given(
    text=st.one_of(_TEXTS, st.text(max_size=600)),
    max_chars=st.integers(min_value=8, max_value=400),
    overlap_share=st.floats(min_value=0, max_value=0.49),
)
def test_chunks_slice_the_text_exactly(text: str, max_chars: int, overlap_share: float) -> None:
    overlap = min(int(max_chars * overlap_share), (max_chars - 1) // 2)
    chunks = chunk_text(text, max_chars=max_chars, overlap=overlap)
    _check(text, chunks, max_chars)


def test_headings_start_sections_and_empty_headings_merge_forward() -> None:
    text = "# Title\n\n## Empty\n\n## Install\n\nStep one.\n\n## Ports\n\nUse 40.\n\n# Trailing\n"
    chunks = chunk_text(text, max_chars=1500, overlap=200)
    assert [c.text for c in chunks] == [
        "# Title\n\n## Empty\n\n## Install\n\nStep one.",
        "## Ports\n\nUse 40.",
    ]
    _check(text, chunks, 1500)


def test_hash_lines_inside_code_fences_are_not_headings() -> None:
    text = (
        "## Config\n\nSet these:\n\n```sh\n# comment\nexport A=1\n## also code\n```\n\n"
        "~~~\n# tilde fence\n~~~\n\n## Next\n\nBody.\n"
    )
    chunks = chunk_text(text, max_chars=1500, overlap=200)
    assert [c.text.splitlines()[0] for c in chunks] == ["## Config", "## Next"]
    assert "# comment" in chunks[0].text and "# tilde fence" in chunks[0].text
    _check(text, chunks, 1500)


def test_whitespace_and_heading_only_text_gives_no_chunks() -> None:
    assert chunk_text("", max_chars=200, overlap=0) == []
    assert chunk_text(" \n\n\t\n", max_chars=200, overlap=0) == []
    assert chunk_text("# A\n\n## B\n", max_chars=200, overlap=0) == []


def test_a_long_section_is_split_at_paragraphs_with_overlap() -> None:
    paragraphs = [f"Paragraph {i} " + "word " * 40 for i in range(6)]
    text = "## Long\n\n" + "\n\n".join(p.strip() for p in paragraphs)
    chunks = chunk_text(text, max_chars=500, overlap=100)
    assert len(chunks) > 2
    _check(text, chunks, 500)
    for first, second in pairwise(chunks):
        assert second.start < first.end  # consecutive windows overlap
        assert first.end - second.start <= 100 + 1
        assert not text[second.start - 1].isalnum() or second.start == 0  # a word start


def test_offsets_count_code_points_not_bytes() -> None:
    text = "🙂 Größe 日本語\n\nport 40"
    (chunk,) = chunk_text(text, max_chars=200, overlap=0)
    assert (chunk.start, chunk.end) == (0, len(text))


def test_a_word_longer_than_the_limit_is_cut_without_losing_text() -> None:
    text = "y" * 50
    chunks = chunk_text(text, max_chars=20, overlap=5)
    _check(text, chunks, 20)
    assert chunks[-1].end == 50


def test_invalid_sizes_are_rejected() -> None:
    with pytest.raises(ValueError):
        chunk_text("x", max_chars=10, overlap=5)
    with pytest.raises(ValueError):
        chunk_text("x", max_chars=0, overlap=0)


def test_the_chunk_repr_never_shows_text() -> None:
    (chunk,) = chunk_text("SECRET-passage", max_chars=200, overlap=0)
    assert "SECRET" not in repr(chunk)


def test_search_query_and_span_rules() -> None:
    assert search_query("  ports ") == "ports"
    with pytest.raises(ValueError):
        search_query("   ")
    with pytest.raises(ValueError):
        search_query("x" * 2001)
    assert span_inside(10, 20, 10, 20)
    assert span_inside(12, 15, 10, 20)
    assert not span_inside(9, 15, 10, 20)
    assert not span_inside(12, 21, 10, 20)
    assert not span_inside(12, 12, 10, 20)
