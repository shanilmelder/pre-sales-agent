"""Pasted-text rules (Story 2.1 Part B): trimming, the length limit in code points, the
unsupported characters and the UI's rejection sentences. Pure domain tests, no DB."""

import pytest

from app.modules.intake.domain.sources import (
    PASTED_TEXT_FILENAME,
    PASTED_TEXT_KIND,
    TEXT_EMPTY_MESSAGE,
    TEXT_MAX_CHARS,
    TEXT_TOO_LONG_MESSAGE,
    TEXT_UNSUPPORTED_MESSAGE,
    PastedTextEmptyError,
    PastedTextError,
    PastedTextTooLongError,
    PastedTextUnsupportedError,
    SourceKind,
    clean_pasted_text,
)

BOM = chr(0xFEFF)  # not whitespace, so it is kept
IDEOGRAPHIC_SPACE = chr(0x3000)
NBSP = chr(0xA0)


def test_constants_and_sentences() -> None:
    assert PASTED_TEXT_FILENAME == "Pasted text"
    assert PASTED_TEXT_KIND is SourceKind.NOTE
    assert TEXT_MAX_CHARS == 1_000_000
    assert TEXT_EMPTY_MESSAGE == "Rejected: the text is empty"
    assert TEXT_TOO_LONG_MESSAGE == "Rejected: longer than 1,000,000 characters"
    assert TEXT_UNSUPPORTED_MESSAGE == "Rejected: the text contains unsupported characters"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Customer needs SAP sync\n", "Customer needs SAP sync"),
        (BOM + IDEOGRAPHIC_SPACE + " note" + NBSP, BOM + IDEOGRAPHIC_SPACE + " note"),
        ("a\n\nb", "a\n\nb"),
        ("Größe", "Größe"),
        ("emoji 😀", "emoji 😀"),
    ],
)
def test_text_is_trimmed_and_kept(raw: str, expected: str) -> None:
    assert clean_pasted_text(raw) == expected


@pytest.mark.parametrize("raw", ["", "   \n\t", IDEOGRAPHIC_SPACE + NBSP + "\r\n"])
def test_blank_text_is_empty(raw: str) -> None:
    with pytest.raises(PastedTextEmptyError) as caught:
        clean_pasted_text(raw)
    assert caught.value.message == TEXT_EMPTY_MESSAGE


def test_length_is_counted_in_code_points_after_trimming() -> None:
    at_limit = "é" + "😀" * (TEXT_MAX_CHARS - 2) + "x"
    assert len(at_limit) == TEXT_MAX_CHARS
    assert clean_pasted_text(f"  {at_limit}\n") == at_limit

    with pytest.raises(PastedTextTooLongError) as caught:
        clean_pasted_text(at_limit + "y")
    assert caught.value.message == TEXT_TOO_LONG_MESSAGE


@pytest.mark.parametrize("raw", ["bad\x00text", "lone \ud800 surrogate", "low \udfff", "\x00"])
def test_nul_and_lone_surrogates_are_unsupported(raw: str) -> None:
    with pytest.raises(PastedTextUnsupportedError) as caught:
        clean_pasted_text(raw)
    assert caught.value.message == TEXT_UNSUPPORTED_MESSAGE


def test_every_rejection_is_a_pasted_text_error() -> None:
    for cls in (PastedTextEmptyError, PastedTextTooLongError, PastedTextUnsupportedError):
        assert issubclass(cls, PastedTextError)
