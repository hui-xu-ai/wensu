"""Reading the same page twice must not navigate twice.

Re-navigation is what replaced a good capture with a challenge page (2026-11-24 report,
D1/D2), and it also charged another two quota points for a page already on disk. The second
call answers from the stored capture, and the blocked hint stops telling callers to do the
one thing that makes it worse.
"""

from __future__ import annotations

import base64
import email.mime.multipart
import email.mime.text
from pathlib import Path

from scholar_search.core.service import _page_next

DOI = "10.1016/j.cej.2023.145123"
URL = "https://www.sciencedirect.com/science/article/pii/X"

ARTICLE_HTML = """<!DOCTYPE html><html><body><article>
<h1>A paper about actuators</h1>
<section id="s1"><h2>1. Introduction</h2>
<p>Ionic transport decides how a soft actuator performs, which is the whole point.</p>
</section>
</article></body></html>"""


def _write_mhtml(path: Path, html: str) -> bytes:
    part = email.mime.text.MIMEText(html, "html", "utf-8")
    outer = email.mime.multipart.MIMEMultipart("related")
    outer.attach(part)
    path.write_bytes(outer.as_bytes())
    return path.read_bytes()


def _one_capture(blob: bytes) -> list[dict[str, object]]:
    return [
        {"verb": "goto", "data": {"url": URL}},
        {"verb": "sleep", "data": {"ms": 1_200}},
        {
            "verb": "snapshot",
            "data": {
                "token": "t1",
                "total": len(blob),
                "base64": base64.b64encode(blob).decode("ascii"),
                "url": URL,
                "title": "A paper about actuators",
                "captcha_visible": False,
            },
        },
    ]


def test_a_second_read_of_the_same_page_does_not_navigate_again(tmp_path: Path) -> None:
    from test_page_read import build_service

    blob = _write_mhtml(tmp_path / "page.mhtml", ARTICLE_HTML)
    # Exactly one script: a second navigation would pop from an empty list and fail loudly.
    service = build_service(tmp_path, [_one_capture(blob)])

    first = service.read_page(doi=DOI)
    assert first["status"] == "ok", first
    assert not first.get("cached")

    second = service.read_page(doi=DOI)

    assert second["status"] == "ok", second
    assert second["cached"] is True
    assert second["quota_charged"] == 0
    assert second["mhtml_path"] == first["mhtml_path"]


def test_the_capture_is_not_reused_after_it_disappears_from_disk(tmp_path: Path) -> None:
    from test_page_read import build_service

    blob = _write_mhtml(tmp_path / "page.mhtml", ARTICLE_HTML)
    service = build_service(tmp_path, [_one_capture(blob), _one_capture(blob)])

    first = service.read_page(doi=DOI)
    Path(first["mhtml_path"]).unlink()

    second = service.read_page(doi=DOI)

    assert not second.get("cached"), second


def test_blocked_tells_the_caller_to_read_again_once_the_wall_is_solved() -> None:
    """ADR 0022 rev 1: a solved wall leaves the article in the tab, so a second call is free.

    The first version of this hint said "do NOT call page_read again". It was written before
    the open-tab reuse existed, and following it leads away from the behaviour that makes a
    solved wall cheap — the 2026-11-25 acceptance run had to try `page_read` against the hint
    to find that out (P5 in the report).
    """

    hint = _page_next({"status": "blocked", "reason": "challenge"})

    assert "then call `page_read` again" in hint, hint
    assert "0 quota" in hint, hint
    assert "Do NOT" not in hint, hint
