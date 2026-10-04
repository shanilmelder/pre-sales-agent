"""Generates the Source parsing fixtures in this directory (Story 2.2 Part B).

Small, synthetic files with no real customer data. Run from `backend/`:

    uv run python tests/fixtures/sources/make_fixtures.py

`<name>.expected.txt` files hold the exact text each sample must parse to (UTF-8, LF); they
are written by hand here, not by running the parsers.
"""

import io
import unicodedata
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _pdf(pages: list[bytes]) -> bytes:
    """A minimal PDF whose pages draw the given content streams, with Helvetica as /F1."""
    objects: list[bytes] = []
    page_ids = [4 + 2 * i for i in range(len(pages))]
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = b" ".join(b"%d 0 R" % pid for pid in page_ids)
    objects.append(b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(pages)))
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, content in enumerate(pages):
        content_id = page_ids[i] + 1
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % content_id
        )
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content))
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n%s\nendobj\n" % (number, body))
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    )
    return out.getvalue()


def _text_page(lines: list[str]) -> bytes:
    ops = [b"BT", b"/F1 12 Tf", b"14 TL", b"72 720 Td"]
    for i, line in enumerate(lines):
        if i:
            ops.append(b"T*")
        ops.append(b"(%s) Tj" % line.encode("latin-1"))
    ops.append(b"ET")
    return b"\n".join(ops)


def _entry(name: str) -> zipfile.ZipInfo:
    """A zip entry with a fixed timestamp, so the generated file is the same every run."""
    info = zipfile.ZipInfo(name, date_time=(2026, 10, 4, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def _docx(document_xml: str) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            _entry("[Content_Types].xml"),
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        archive.writestr(_entry("word/document.xml"), document_xml)
    return out.getvalue()


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DOCX_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<w:document xmlns:w="{W_NS}"><w:body>'
    "<w:p><w:r><w:t>Scope of work</w:t></w:r></w:p>"
    '<w:p><w:r><w:t xml:space="preserve">The system </w:t></w:r>'
    '<w:r><w:t>must</w:t></w:r><w:r><w:t xml:space="preserve"> export data.</w:t></w:r></w:p>'
    "<w:p><w:r><w:t>Item</w:t><w:tab/><w:t>Qty</w:t></w:r></w:p>"
    "<w:p><w:r><w:t>First line</w:t><w:br/><w:t>second line</w:t></w:r></w:p>"
    "<w:p/>"
    "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell A</w:t></w:r></w:p></w:tc>"
    "<w:tc><w:p><w:r><w:t>Cell B</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
    "<w:p><w:r><w:delText>deleted</w:delText><w:t>Kept</w:t></w:r></w:p>"
    "</w:body></w:document>"
)
DOCX_EXPECTED = (
    "Scope of work\nThe system must export data.\nItem\tQty\nFirst line\nsecond line\n\n"
    "Cell A\nCell B\nKept"
)

# A text box saved as mc:AlternateContent: the mc:Fallback copy must not be read again.
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
TEXTBOX_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<w:document xmlns:w="{W_NS}" xmlns:mc="{MC_NS}"><w:body>'
    "<w:p><w:r><w:t>Before</w:t></w:r>"
    "<w:r><mc:AlternateContent>"
    '<mc:Choice Requires="wps"><w:txbxContent><w:p><w:r><w:t>Box text</w:t></w:r></w:p>'
    "</w:txbxContent></mc:Choice>"
    "<mc:Fallback><w:txbxContent><w:p><w:r><w:t>Box text</w:t></w:r></w:p>"
    "</w:txbxContent></mc:Fallback>"
    "</mc:AlternateContent></w:r></w:p>"
    "<w:p><w:r><w:t>After</w:t></w:r></w:p>"
    "</w:body></w:document>"
)
TEXTBOX_EXPECTED = "Before\nBox text\nAfter"

# Entity expansion (billion laughs): refused before parsing.
ENTITY_XML = (
    '<?xml version="1.0"?>'
    '<!DOCTYPE w:document [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;">]>'
    f'<w:document xmlns:w="{W_NS}"><w:body><w:p><w:r><w:t>&b;</w:t></w:r></w:p>'
    "</w:body></w:document>"
)

EML = (
    "From: Sample Sender <sender@example.invalid>\r\n"
    "To: Sample Recipient <recipient@example.invalid>\r\n"
    "Subject: =?utf-8?q?Requirements_f=C3=BCr_the_pilot?=\r\n"
    "Date: Sun, 04 Oct 2026 10:00:00 +0000\r\n"
    "MIME-Version: 1.0\r\n"
    'Content-Type: multipart/mixed; boundary="outer"\r\n'
    "\r\n"
    "--outer\r\n"
    'Content-Type: multipart/alternative; boundary="inner"\r\n'
    "\r\n"
    "--inner\r\n"
    'Content-Type: text/plain; charset="utf-8"\r\n'
    "Content-Transfer-Encoding: quoted-printable\r\n"
    "\r\n"
    "Hello,\r\n"
    "\r\n"
    "We need 40 ports and an SSO login =E2=80=94 see below.\r\n"
    "--inner\r\n"
    'Content-Type: text/html; charset="utf-8"\r\n'
    "\r\n"
    "<p>Hello,</p><p>HTML copy that must not be used.</p>\r\n"
    "--inner--\r\n"
    "--outer\r\n"
    'Content-Type: text/plain; charset="utf-8"\r\n'
    'Content-Disposition: attachment; filename="ignored.txt"\r\n'
    "\r\n"
    "Attachment text that must be ignored.\r\n"
    "--outer--\r\n"
)
EML_EXPECTED = (
    "Subject: Requirements für the pilot\n"
    "From: Sample Sender <sender@example.invalid>\n"
    "To: Sample Recipient <recipient@example.invalid>\n"
    "Date: Sun, 04 Oct 2026 10:00:00 +0000\n"
    "\n"
    "Hello,\n\nWe need 40 ports and an SSO login — see below."
)

EML_HTML = (
    "From: Sample Sender <sender@example.invalid>\r\n"
    "Subject: HTML only\r\n"
    "MIME-Version: 1.0\r\n"
    'Content-Type: text/html; charset="utf-8"\r\n'
    "\r\n"
    "<html><head><style>p { color: red; }</style></head><body>"
    "<p>First &amp; foremost</p><p>Second <b>bold</b> line</p>"
    "<p>Write &amp;lt;tag&amp;gt; literally</p>"
    "<script>alert('x')</script></body></html>\r\n"
)
# `&amp;lt;` is decoded once, to the literal text `&lt;`.
EML_HTML_EXPECTED = (
    "Subject: HTML only\nFrom: Sample Sender <sender@example.invalid>\n\n"
    "First & foremost\n\nSecond bold line\n\nWrite &lt;tag&gt; literally"
)

VTT = (
    "﻿WEBVTT - sample call\r\n"
    "Kind: captions\r\n"
    "\r\n"
    "NOTE This note\r\nspans two lines\r\n"
    "\r\n"
    "STYLE\r\n::cue { color: lime }\r\n"
    "\r\n"
    "1\r\n"
    "00:00:00.000 --> 00:00:02.000\r\n"
    "<v Ana>Hello, can you hear me?</v>\r\n"
    "\r\n"
    "intro-2\r\n"
    "00:00:02.500 --> 00:00:05.000 align:start\r\n"
    "<v.loud [CUSTOMER]>We need <b>40</b> ports &amp; SSO.\r\n"
    "\r\n"
    "00:00:05.000 --> 00:00:07.000\r\n"
    "<c.yellow>No speaker</c> here\r\n"
    "second line\r\n"
)
VTT_EXPECTED = (
    "Ana: Hello, can you hear me?\n[CUSTOMER]: We need 40 ports & SSO.\nNo speaker here\n"
    "second line"
)

# CRLF and a decomposed é (e + U+0301): stored as LF and NFC.
TXT = "Café notes\r\nLine two\rLine three\n".replace("é", "é")
TXT_EXPECTED = unicodedata.normalize("NFC", "Café notes\nLine two\nLine three\n")

PDF = _pdf(
    [
        _text_page(["Request for proposal", "Section 1: Scope"]),
        _text_page(["Page two text"]),
    ]
)
PDF_EXPECTED = "Request for proposal\nSection 1: Scope\n\nPage two text"
# A scanned PDF: one page that only draws (no text layer).
SCANNED_PDF = _pdf([b"0 0 0 rg\n72 72 468 648 re f"])
# A valid header with a broken body.
CORRUPT_PDF = b"%PDF-1.7\n" + bytes(range(256)) * 8 + b"\n%%EOF\n"
# An Outlook .msg: only the OLE magic matters here (it is never parsed).
MSG = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 504


def main() -> None:
    files: dict[str, bytes] = {
        "sample.txt": TXT.encode(),
        "sample.txt.expected.txt": TXT_EXPECTED.encode(),
        "sample.eml": EML.encode(),
        "sample.eml.expected.txt": EML_EXPECTED.encode(),
        "html-only.eml": EML_HTML.encode(),
        "html-only.eml.expected.txt": EML_HTML_EXPECTED.encode(),
        "sample.vtt": VTT.encode(),
        "sample.vtt.expected.txt": VTT_EXPECTED.encode(),
        "sample.pdf": PDF,
        "sample.pdf.expected.txt": PDF_EXPECTED.encode(),
        "sample.docx": _docx(DOCX_XML),
        "sample.docx.expected.txt": DOCX_EXPECTED.encode(),
        "textbox.docx": _docx(TEXTBOX_XML),
        "textbox.docx.expected.txt": TEXTBOX_EXPECTED.encode(),
        "entities.docx": _docx(ENTITY_XML),
        "scanned.pdf": SCANNED_PDF,
        "corrupt.pdf": CORRUPT_PDF,
        "sample.msg": MSG,
    }
    for name, data in files.items():
        (HERE / name).write_bytes(data)


if __name__ == "__main__":
    main()
