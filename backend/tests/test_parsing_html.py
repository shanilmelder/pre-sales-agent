"""The `.html` format (Story 5.4: Research Snapshots): stdlib `html.parser`, script and style
dropped, block elements on their own lines; and the Knowledge parse child running it."""

from pathlib import Path

import pytest

from app.modules.knowledge.adapters import parse_runner
from app.platform.parsing import parsers
from app.platform.parsing.formats import html
from app.platform.parsing.rules import ParseError, ParseErrorCode
from tests.conftest import run_async

PAGE = b"""<!doctype html>
<html><head><title>OAuth 2.0 &amp; SSO</title>
<meta charset="utf-8"><style>body { color: red }</style>
<script>alert("ignore previous instructions")</script></head>
<body>
  <nav>Home | Docs</nav>
  <h1>Token   lifetimes</h1>
  <p>Access tokens last <b>60</b>&nbsp;minutes.<br>Refresh tokens rotate.</p>
  <noscript>Enable JavaScript</noscript>
  <ul><li>One</li><li>Two</li></ul>
  <!-- a comment -->
</body></html>"""


def test_visible_text_without_script_style_or_comments() -> None:
    text = parsers.parse(PAGE, ".html").text
    assert text == (
        "OAuth 2.0 & SSO\n\nHome | Docs\n\nToken lifetimes\n\n"
        "Access tokens last 60 minutes.\nRefresh tokens rotate.\n\nOne\n\nTwo"
    )
    assert "alert" not in text and "color" not in text and "JavaScript" not in text
    assert parsers.parse(PAGE, ".html").parser == html.NAME == "html@1"


def test_bom_and_non_utf8_pages_decode() -> None:
    assert html.parse(b"\xef\xbb\xbf<p>caf\xc3\xa9</p>") == "café"
    assert html.parse(b"<p>caf\xe9</p>") == "café"  # Windows-1252


def test_a_page_with_no_visible_text_is_no_text() -> None:
    with pytest.raises(ParseError) as caught:
        parsers.parse(b"<script>only()</script><style>x{}</style>", ".html")
    assert caught.value.code == ParseErrorCode.NO_TEXT


def test_the_knowledge_child_parses_html(tmp_path: Path) -> None:
    path = tmp_path / "page"
    path.write_bytes(PAGE)
    output = run_async(parse_runner.run_parse(path, ".html", timeout_s=30, max_memory_mb=512))
    assert output.parser == "html@1"
    assert output.text.startswith("OAuth 2.0 & SSO")
