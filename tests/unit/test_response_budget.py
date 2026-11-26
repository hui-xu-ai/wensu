"""No tool answer may carry bulk text.

Fidelity is decided by deterministic code (`core/pageprobe.py`) on bytes that stay on disk;
the model only ever sees counts, verdicts and paths. This file pins that budget so a future
change cannot quietly start returning the page itself — an MHTML of 73 KB was already handed
to a caller once, as a "successful" capture of a challenge wall (2026-11-24).
"""

from __future__ import annotations

import base64
import email.mime.multipart
import email.mime.text
import json
from pathlib import Path

MAX_STRING = 300
MAX_PAYLOAD = 4096
BULK_MARKERS = ("<html", "<body", "<!doctype", "<meta", "<div")


def _saved_page(path: Path, html: str) -> Path:
    part = email.mime.text.MIMEText(html, "html", "utf-8")
    outer = email.mime.multipart.MIMEMultipart("related")
    outer.attach(part)
    path.write_bytes(outer.as_bytes())
    return path


def _assert_budget(name: str, payload: dict) -> None:
    blob = json.dumps(payload, ensure_ascii=False)
    assert len(blob) <= MAX_PAYLOAD, f"{name}: {len(blob)} bytes of answer is too much"

    def walk(value: object, where: str) -> None:
        if isinstance(value, str):
            assert len(value) <= MAX_STRING, f"{name}.{where}: {len(value)} chars"
            lowered = value.casefold()
            for marker in BULK_MARKERS:
                assert marker not in lowered, f"{name}.{where} carries markup: {marker}"
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{where}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{where}[{index}]")

    walk(payload, name)


def test_a_page_read_answer_carries_counts_not_bytes(tmp_path: Path) -> None:
    from test_page_read import build_service

    url = "https://onlinelibrary.wiley.com/doi/10.1002/pen.23634"
    blob = _saved_page(
        tmp_path / "page.mhtml",
        "<html><body><article><h1>A paper</h1><section id='s1'>"
        "<h2>1. Introduction</h2>"
        "<p>Body text a reader came for.</p></section></article></body></html>",
    ).read_bytes()
    script = [
        {"verb": "goto", "data": {"url": url, "title": "Directional Confinement Governed"}},
        {"verb": "sleep", "data": {"ms": 1}},
        {
            "verb": "snapshot",
            "data": {
                "token": "t1",
                "total": len(blob),
                "base64": base64.b64encode(blob).decode("ascii"),
                "url": url,
                "title": "Directional Confinement Governed",
                "captcha_visible": False,
            },
        },
    ]
    service = build_service(tmp_path, [script])

    _assert_budget("page_read", service.read_page(doi="10.1002/pen.23634"))


def test_a_wall_answer_is_small_and_says_nothing_else(tmp_path: Path) -> None:
    from test_page_read import build_service

    url = "https://onlinelibrary.wiley.com/doi/10.1002/pen.23634"
    service = build_service(
        tmp_path,
        [
            [
                {"verb": "goto", "data": {"url": url, "title": "请稍候…"}},
                {"verb": "wait_for", "ok": False, "error": "action.timeout"},
            ]
        ],
    )

    _assert_budget("page_read.blocked", service.read_page(doi="10.1002/pen.23634"))


def test_the_converter_answer_is_paths_and_warnings_only(tmp_path: Path) -> None:
    from scholar_search.bootstrap import build_service as bootstrap_service

    page = _saved_page(
        tmp_path / "page.mhtml",
        "<html><body><article><h1>A paper</h1><section id='s1'>"
        "<h2>1. Introduction</h2>"
        "<p>Body text a reader came for.</p></section></article></body></html>",
    )

    _assert_budget("page2md", bootstrap_service().page2md(mhtml_path=str(page)))
