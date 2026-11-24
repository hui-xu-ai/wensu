"""`page_read` answers with a next step — that step has to exist for a pip user.

The hint named `tools/page2md.py`: a path inside the source checkout and **not** in the
wheel (`packages = ["src/scholar_search"]`, and `tools/` is not in the sdist either), so
every `pip install wensu` user was told to run a file they did not have (2026-11-24).

Two behaviours are pinned: the converter ships with the package and runs through the CLI,
and the hint names that command rather than a checkout path.
"""

from __future__ import annotations

import base64
from email.message import EmailMessage
from pathlib import Path

from scholar_search.cli import build_parser, main
from scholar_search.core.service import _page_next

_HTML = (
    "<html><body><article>"
    "<h1>Directional Confinement</h1>"
    '<section id="sec1"><h2>1. Introduction</h2>'
    "<p>Ionic transport decides how a soft actuator performs.</p></section>"
    "</article></body></html>"
)


def _write_mhtml(path: Path) -> Path:
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


def test_the_cli_offers_page2md() -> None:
    args = build_parser().parse_args(["page2md", "--in", "a.mhtml", "--out", "out"])

    assert args.command == "page2md"
    assert (args.source, args.out) == ("a.mhtml", "out")


def test_page2md_turns_a_saved_page_into_markdown(tmp_path: Path) -> None:
    page = _write_mhtml(tmp_path / "page.mhtml")

    code = main(["page2md", "--in", str(page), "--out", str(tmp_path / "out")])

    markdown = tmp_path / "out" / "page.md"
    assert code == 0, code
    assert markdown.is_file(), list((tmp_path / "out").iterdir())
    text = markdown.read_text(encoding="utf-8")
    # The section heading and body are what a reader needs; the `<h1>` title is dropped by
    # the extractor, which is its documented behaviour rather than something to pin here.
    assert "1. Introduction" in text, text
    assert "Ionic transport decides" in text, text


def test_the_hint_names_the_command_not_a_checkout_path() -> None:
    hint = _page_next({"status": "ok"})

    assert "wensu page2md" in hint, hint
    assert "tools/page2md.py" not in hint, hint
