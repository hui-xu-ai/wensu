"""Article HTML -> Markdown, one call at a time (audit 2026-11-26, F09).

Sections used to travel through the module-level `_LAST_SECTIONS`, which `convert` read *after*
the extraction returned. Two conversions in parallel produced one document's `page.md` next to
the other document's `index.json`. A lock now covers the counters that are still module state,
and the sections are a return value.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from scholar_search import page2md

A_HTML = (
    "<html><body><article><h1>Alpha</h1>"
    '<section id="a1"><h2>1. Alpha methods</h2>'
    "<p>Alpha body text, long enough to be kept.</p></section>"
    '<section id="a2"><h2>2. Alpha results</h2>'
    "<p>More alpha text, also long enough.</p></section>"
    "</article></body></html>"
)
B_HTML = (
    "<html><body><article><h1>Beta</h1>"
    '<section id="b1"><h2>1. Beta methods</h2>'
    "<p>Beta body text, long enough to be kept.</p></section>"
    '<section id="b2"><h2>2. Beta results</h2>'
    "<p>More beta text, also long enough.</p></section>"
    "</article></body></html>"
)


def _convert(html: str, path: Path) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return page2md.convert(path, path.with_suffix(""))


def _sections(out: Path) -> list[dict[str, object]]:
    return json.loads((out / "index.json").read_text(encoding="utf-8"))["sections"]


def test_convert_keeps_one_documents_sections_out_of_the_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the explicit return, B's headings landed in A's index.json.

    The window is widened on purpose: the extraction is fast, so a plain race almost never
    interleaves. Sleeping where the old design stashed its sections — between computing them and
    reading them back — makes the defect deterministic instead of probabilistic.
    """

    real = page2md._section_markdown

    def slow(html: str):  # type: ignore[no-untyped-def]
        result = real(html)
        time.sleep(0.05)
        return result

    monkeypatch.setattr(page2md, "_section_markdown", slow)
    errors: list[BaseException] = []

    def run(html: str, name: str) -> None:
        try:
            for round_number in range(6):
                _convert(html, tmp_path / f"{name}-{round_number}" / "page.html")
        except BaseException as error:  # a thread must not die silently
            errors.append(error)

    alpha = threading.Thread(target=run, args=(A_HTML, "alpha"))
    beta = threading.Thread(target=run, args=(B_HTML, "beta"))
    alpha.start()
    beta.start()
    alpha.join()
    beta.join()

    assert not errors, errors
    for name, own in (("alpha", "Alpha"), ("beta", "Beta")):
        for round_number in range(6):
            out = tmp_path / f"{name}-{round_number}" / "page"
            titles = [str(section["title"]) for section in _sections(out)]
            assert titles, (name, round_number)
            assert all(own in title for title in titles), (name, round_number, titles)
            markdown = (out / "page.md").read_text(encoding="utf-8")
            assert own in markdown
