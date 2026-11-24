"""The last link of "read the paper" must not depend on a shell.

`page2md` shipped as a command line only, so a session whose shell could not be provisioned
lost the whole chain *after* the page had been captured — and the failure looked like the
plugin demanding full access (2026-11-24 report, D3 + D7). It is now a tool that runs inside
the server, which this file pins: reachable without a shell, honest about a missing file, and
present in the server's tool list.
"""

from __future__ import annotations

import asyncio
import base64
from email.message import EmailMessage
from pathlib import Path

import pytest

from scholar_search.bootstrap import build_service
from scholar_search.server import build_server

_HTML = (
    "<html><body><article>"
    "<h1>A paper</h1>"
    '<section id="sec1"><h2>1. Introduction</h2>'
    "<p>The body text a reader came for.</p></section>"
    "</article></body></html>"
)


def _saved_page(path: Path) -> Path:
    outer = EmailMessage()
    outer["MIME-Version"] = "1.0"
    outer.set_type("multipart/related")
    part = EmailMessage()
    part["Content-Type"] = 'text/html; charset="utf-8"'
    part["Content-Location"] = "https://example.org/paper"
    part.set_payload(base64.b64encode(_HTML.encode("utf-8")).decode("ascii"))
    part["Content-Transfer-Encoding"] = "base64"
    outer.attach(part)
    path.write_bytes(outer.as_bytes())
    return path


def test_a_saved_page_is_converted_without_a_shell(tmp_path: Path) -> None:
    page = _saved_page(tmp_path / "page.mhtml")

    result = build_service().page2md(mhtml_path=str(page), out_dir=str(tmp_path / "md"))

    assert result["status"] == "ok", result
    markdown = Path(result["page_md"])
    assert markdown.is_file(), result
    text = markdown.read_text(encoding="utf-8")
    assert "1. Introduction" in text
    assert isinstance(result["warnings"], list)
    assert result["engine"], result


def test_a_missing_page_is_an_error_rather_than_a_blank_markdown(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build_service().page2md(mhtml_path=str(tmp_path / "nothing.mhtml"))


def test_something_that_is_not_a_page_is_refused(tmp_path: Path) -> None:
    other = tmp_path / "notes.txt"
    other.write_text("not a page", encoding="utf-8")

    with pytest.raises(ValueError):
        build_service().page2md(mhtml_path=str(other))


def test_the_server_offers_page2md() -> None:
    tools = asyncio.run(build_server(build_service()).list_tools())

    assert "page2md" in {tool.name for tool in tools}
