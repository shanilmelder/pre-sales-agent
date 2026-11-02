"""Build the .docx and .pdf demo Sources from the Markdown-ish text in tools/doc-sources/.

Usage (from the repo root):

    cd backend
    uv run python ../demo-data/tools/build_docs.py

Each tools/doc-sources/<folder>/<name>.docx.md becomes demo-data/<folder>/<name>.docx and each
<name>.pdf.md becomes <name>.pdf. Supported markup: "# " title, "## " heading, "- " bullet,
"| a | b |" table rows (printed as one line per row, header row dropped), blank line = new
paragraph.
The PDF writer is a small built-in one (Helvetica, A4, text only), so no extra library is
needed; the app's parser reads its text layer.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from docx import Document

ROOT = Path(__file__).resolve().parent.parent
SOURCES = Path(__file__).resolve().parent / "doc-sources"


def _blocks(text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    for line in text.splitlines():
        if line.startswith("# "):
            blocks.append(("title", line[2:]))
        elif line.startswith("## "):
            blocks.append(("heading", line[3:]))
        elif line.startswith("- "):
            blocks.append(("bullet", line[2:]))
        elif line.startswith("|"):
            blocks.append(("row", line))
        elif line.strip():
            if blocks and blocks[-1][0] == "para":
                blocks[-1] = ("para", blocks[-1][1] + " " + line.strip())
            else:
                blocks.append(("para", line.strip()))
        else:
            blocks.append(("blank", ""))
    return [b for b in blocks if b[0] != "blank"]


def build_docx(text: str, out: Path) -> None:
    """Tables become one paragraph per row ("ID - text (priority)"): the app's docx parser
    puts every table cell on its own line, which splits a requirement across passages."""
    doc = Document()
    header_seen = False
    for kind, value in _blocks(text):
        if kind != "row":
            header_seen = False
        if kind == "title":
            doc.add_heading(value, level=0)
        elif kind == "heading":
            doc.add_heading(value, level=1)
        elif kind == "bullet":
            doc.add_paragraph(value, style="List Bullet")
        elif kind == "para":
            doc.add_paragraph(value)
        elif kind == "row":
            cells = [c.strip() for c in value.strip().strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):
                continue
            if not header_seen:
                header_seen = True
                continue
            line = f"{cells[0]} - {cells[1]}" if len(cells) > 1 else cells[0]
            if len(cells) > 2:
                line += f" ({', '.join(cells[2:])})"
            doc.add_paragraph(line)
    doc.core_properties.author = "Demo data generator"
    doc.save(out)


def _pdf_escape(s: str) -> str:
    s = s.replace("–", "-").replace("—", "-").replace("’", "'")
    s = s.replace("“", '"').replace("”", '"').replace("£", "GBP ")
    s = s.encode("latin-1", "replace").decode("latin-1")
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(text: str, out: Path) -> None:
    lines: list[tuple[str, int]] = []  # (text, font size)
    for kind, value in _blocks(text):
        if kind == "title":
            lines += [(value, 16), ("", 10)]
        elif kind == "heading":
            lines += [("", 10), (value, 12)]
        elif kind == "row":
            cells = [c.strip() for c in value.strip().strip("|").split("|")]
            if not set("".join(cells)) <= set("-: ") and cells[0] not in ("ID", "Item", "Name"):
                lines.append((" - ".join(cells), 10))
        else:
            prefix = "- " if kind == "bullet" else ""
            for i, part in enumerate(textwrap.wrap(value, 92)):
                lines.append(((prefix if i == 0 else "  " if prefix else "") + part, 10))
            if kind == "para":
                lines.append(("", 10))

    pages: list[list[tuple[str, int]]] = [[]]
    y = 800
    for line in lines:
        step = line[1] + 4
        if y - step < 50:
            pages.append([])
            y = 800
        pages[-1].append(line)
        y -= step

    objects: list[bytes] = []
    kids = []
    for page in pages:
        ops = ["BT", "50 800 Td"]
        for content, size in page:
            ops.append(f"/F1 {size} Tf 0 -{size + 4} Td ({_pdf_escape(content)}) Tj")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        content_id = len(objects) + 4
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page_id = len(objects) + 4
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % content_id
        )
        kids.append(page_id)

    head = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [%s] /Count %d >>"
        % (b" ".join(b"%d 0 R" % k for k in kids), len(kids)),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    body = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(head + objects, start=1):
        offsets.append(len(body))
        body += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(body)
    body += b"xref\n0 %d\n0000000000 65535 f \n" % (len(offsets) + 1)
    body += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    body += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(offsets) + 1,
        xref,
    )
    out.write_bytes(body)


def main() -> None:
    for src in sorted(SOURCES.rglob("*.md")):
        folder = src.parent.relative_to(SOURCES)
        name = src.name[: -len(".md")]  # "x.docx" or "x.pdf"
        out = ROOT / folder / name
        out.parent.mkdir(parents=True, exist_ok=True)
        text = src.read_text(encoding="utf-8")
        if name.endswith(".docx"):
            build_docx(text, out)
        elif name.endswith(".pdf"):
            build_pdf(text, out)
        else:
            continue
        print(f"built {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
