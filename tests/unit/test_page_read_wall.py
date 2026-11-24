"""A wall must be recognized before the capture, not after it.

Cloudflare's interstitial arrives as a normal 200 response with a title like 「请稍候…」, so
`page_read` used to capture it (one quota point, ~73 KB that is not the article) and only then
classify the body — which also replaced a body that had already been captured (2026-11-24,
report D1/D2). The title travels with the `goto` reply, so the wall costs nothing to spot.
"""

from __future__ import annotations

import base64
import email.mime.multipart
import email.mime.text
from pathlib import Path

from scholar_search.core.pageprobe import challenge_in_title

DOI = "10.1002/pen.23634"
URL = "https://onlinelibrary.wiley.com/doi/10.1002/pen.23634"


def _goto(title: str) -> list[dict[str, object]]:
    return [{"verb": "goto", "data": {"url": URL, "title": title, "ok": True}}]


def test_the_wiley_interstitial_title_is_recognized() -> None:
    assert challenge_in_title("请稍候…") == "请稍候"
    assert challenge_in_title("Just a moment...") == "just a moment"


def test_an_article_title_is_not_a_wall() -> None:
    assert challenge_in_title("Directional Confinement Governed Ion Transport") is None
    assert challenge_in_title("") is None


def test_page_read_stops_at_the_wall_and_captures_nothing(tmp_path: Path) -> None:
    from test_page_read import build_service

    # Exactly one script (the `goto`): a capture would pop from an empty list and fail.
    service = build_service(tmp_path, [_goto("请稍候…")])

    result = service.read_page(doi=DOI)

    assert result["status"] == "blocked", result
    assert result["signal"] == "title:请稍候", result
    assert result["mhtml_path"] is None, result
    assert result["quota_charged"] == 1, result
    assert "snapshot" in result["next"]
    assert not list(tmp_path.rglob("page.mhtml")), "a wall must not be saved as a page"


def test_an_ordinary_page_still_goes_through_the_capture(tmp_path: Path) -> None:
    """The wall check must not skip the capture for a normal article page."""

    from test_page_read import build_service

    html = (
        "<html><body><article><h1>A paper</h1><section id='s1'>"
        "<h2>1. Introduction</h2><p>Body text.</p></section></article></body></html>"
    )
    part = email.mime.text.MIMEText(html, "html", "utf-8")
    outer = email.mime.multipart.MIMEMultipart("related")
    outer.attach(part)
    blob = outer.as_bytes()

    script = [
        *_goto("Directional Confinement Governed Ion Transport"),
        {"verb": "sleep", "data": {"ms": 1}},  # the settle action the plan declares
        {
            "verb": "snapshot",
            "data": {
                "token": "t1",
                "total": len(blob),
                "base64": base64.b64encode(blob).decode("ascii"),
                "url": URL,
                "title": "Directional Confinement Governed Ion Transport",
                "captcha_visible": False,
            },
        },
    ]
    service = build_service(tmp_path, [script])

    result = service.read_page(doi=DOI)

    assert result["status"] != "blocked", result
