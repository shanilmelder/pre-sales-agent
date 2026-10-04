"""Source file rules (Story 2.1): the extension allowlist, magic-byte and text checks, the
filename rules and the UI's rejection sentences. Pure domain tests, no DB."""

import io
import zipfile

import pytest

from app.modules.intake.domain.sources import (
    EMPTY_MESSAGE,
    FILENAME_MAX,
    InvalidFilenameError,
    SourceKind,
    clean_filename,
    content_matches,
    extension,
    kind_for,
    mismatch_message,
    too_large_message,
    type_rejected_message,
)

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 32
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 504


def zip_bytes(*names: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, "<x/>")
    return buffer.getvalue()


DOCX = zip_bytes("[Content_Types].xml", "word/document.xml")
VALID: dict[str, bytes] = {
    ".pdf": b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n",
    ".docx": DOCX,
    ".msg": OLE,
    ".vtt": b"WEBVTT\n\n00:00.000 --> 00:01.000\nHello\n",
    ".txt": "Notes from the call: Größe, 東京, ok.\n".encode(),
    ".eml": b"From: [CUSTOMER]\r\nSubject: Hi\r\n\r\nBody\r\n",
}


def matches(ext: str, data: bytes) -> bool:
    return content_matches(ext, io.BytesIO(data))


@pytest.mark.parametrize(
    ("filename", "kind"),
    [
        ("mail.eml", SourceKind.EMAIL),
        ("mail.msg", SourceKind.EMAIL),
        ("notes.txt", SourceKind.NOTE),
        ("call.vtt", SourceKind.TRANSCRIPT),
        ("spec.docx", SourceKind.DOCUMENT),
        ("rfp.pdf", SourceKind.DOCUMENT),
        ("RFP.PDF", SourceKind.DOCUMENT),
        ("Call.Vtt", SourceKind.TRANSCRIPT),
        ("archive.v2.final.docx", SourceKind.DOCUMENT),
    ],
)
def test_allowed_extensions_map_to_kinds_ignoring_case(filename: str, kind: SourceKind) -> None:
    assert kind_for(filename) is kind


@pytest.mark.parametrize(
    "filename", ["setup.exe", "image.png", "notes", ".txt", "notes.", "spec.doc", "a.pdf.exe"]
)
def test_other_extensions_are_not_allowed(filename: str) -> None:
    assert kind_for(filename) is None


def test_extension_is_lowercase_with_dot() -> None:
    assert extension("Setup.EXE") == ".exe"
    assert extension("noext") == ""
    assert extension(".hidden") == ""


def test_rejection_sentences_match_the_ui_copy() -> None:
    assert type_rejected_message("setup.exe") == "Rejected: .exe files aren't allowed"
    assert type_rejected_message("SETUP.EXE") == "Rejected: .exe files aren't allowed"
    assert type_rejected_message("README") == "Rejected: files without an extension aren't allowed"
    assert too_large_message(50 * 1024 * 1024) == "Rejected: larger than 50 MB"
    assert mismatch_message(".pdf") == "Rejected: the content doesn't match .pdf"
    assert EMPTY_MESSAGE == "Rejected: the file is empty"


@pytest.mark.parametrize("ext", sorted(VALID))
def test_valid_content_matches(ext: str) -> None:
    assert matches(ext, VALID[ext])


@pytest.mark.parametrize("junk", [b" ", b"\r\n", b"\x00" * 100, b"x" * (1024 - 5)])
def test_pdf_header_may_follow_junk_within_the_first_1024_bytes(junk: bytes) -> None:
    assert matches(".pdf", junk + b"%PDF-1.7\n")


def test_vtt_may_start_with_a_utf8_bom() -> None:
    assert matches(".vtt", b"\xef\xbb\xbfWEBVTT\n\n")


@pytest.mark.parametrize(
    ("ext", "data"),
    [
        (".pdf", PNG),
        (".pdf", b" " * 1024 + b"%PDF-1.7"),  # header past the first 1024 bytes
        (".docx", zip_bytes("xl/workbook.xml")),  # a ZIP, but not a Word document
        (".docx", b"PK\x03\x04 not really a zip"),
        (".docx", VALID[".pdf"]),
        (".msg", VALID[".pdf"]),
        (".msg", OLE[:7]),
        (".vtt", b"WEBVT"),
        (".vtt", b"\n\nWEBVTT"),
        (".txt", b"caf\xe9"),  # Latin-1, not UTF-8
        (".txt", b"abc\x00def"),
        (".txt", b"ok" + b"\xe2\x82"),  # truncated multi-byte sequence
        (".eml", PNG),
        (".exe", b"MZ\x90\x00"),
    ],
)
def test_mismatched_content_does_not_match(ext: str, data: bytes) -> None:
    assert not matches(ext, data)


def test_large_text_is_checked_to_the_end() -> None:
    data = b"a" * (200 * 1024) + b"\x00"
    assert not matches(".txt", data)
    assert matches(".txt", b"a" * (200 * 1024) + "é".encode())


def test_multibyte_character_split_across_read_chunks_is_valid() -> None:
    data = b"a" * (64 * 1024 - 1) + "€".encode() + b"tail"
    assert matches(".txt", data)


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("  notes.txt  ", "notes.txt"),
        ("C:\\Users\\me\\Desktop\\notes.txt", "notes.txt"),
        ("../../etc/passwd.txt", "passwd.txt"),
        ("dir/sub/call.vtt", "call.vtt"),
        ("Größe 東京.pdf", "Größe 東京.pdf"),
        ("x" * (FILENAME_MAX - 4) + ".txt", "x" * (FILENAME_MAX - 4) + ".txt"),
    ],
)
def test_filenames_are_trimmed_without_path_components(raw: str, clean: str) -> None:
    assert clean_filename(raw) == clean


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "dir/",
        "..",
        "a\x00b.txt",
        "a\nb.txt",
        "a\x7fb.txt",
        "a\x85b.txt",  # C1 control (NEL)
        "a\x9bb.txt",  # C1 control (CSI)
        "invoice\u202etxt.exe",  # right-to-left override: shows as "invoiceexe.txt"
        "notes\u200b.txt",  # zero-width space
        "\ufeffnotes.txt",  # zero-width no-break space
    ],
)
def test_unusable_filenames_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidFilenameError) as caught:
        clean_filename(raw)
    assert caught.value.message == "Rejected: the file name isn't valid"


def test_filenames_longer_than_255_are_rejected() -> None:
    with pytest.raises(InvalidFilenameError) as caught:
        clean_filename("x" * FILENAME_MAX + ".txt")
    assert "255" in caught.value.message
