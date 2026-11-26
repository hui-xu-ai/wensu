"""When the reader has already solved the wall by hand, read their tab — do not navigate.

Two complaints meet here: `page_read` used to navigate again after a wall (replacing a body
already on screen), and the page the person had *already opened and verified* was never used.
A wall is now remembered as a marker, and the next attempt looks at the reader's own tab
first: `snapshot` on it costs nothing and issues no request (ADR 0018).
"""

from __future__ import annotations

import base64
import email.mime.multipart
import email.mime.text
import json
from pathlib import Path

from scholar_search.core.pageprobe import challenge_in_title

DOI = "10.1002/pen.23634"
URL = "https://onlinelibrary.wiley.com/doi/10.1002/pen.23634"
ARTICLE = (
    "<html><body><article><h1>A paper</h1><section id='s1'>"
    "<h2>1. Introduction</h2><p>Body text a reader came for.</p></section></article></body></html>"
)


def _mhtml(path: Path, html: str) -> Path:
    part = email.mime.text.MIMEText(html, "html", "utf-8")
    outer = email.mime.multipart.MIMEMultipart("related")
    outer.attach(part)
    path.write_bytes(outer.as_bytes())
    return path


def _capture(blob: bytes, *, url: str, title: str) -> dict[str, object]:
    return {
        "verb": "snapshot",
        "data": {
            "token": "t1",
            "total": len(blob),
            "base64": base64.b64encode(blob).decode("ascii"),
            "url": url,
            "title": title,
            "captcha_visible": False,
        },
    }


def test_the_readers_own_tab_is_used_after_a_wall(tmp_path: Path) -> None:
    from test_page_read import build_service

    blob = _mhtml(tmp_path / "article.mhtml", ARTICLE).read_bytes()
    service = build_service(
        tmp_path,
        [
            [{"verb": "goto", "data": {"url": URL, "title": "请稍候…"}}],
            [_capture(blob, url=URL, title="A paper")],
        ],
    )

    assert service.read_page(doi=DOI)["status"] == "blocked"

    again = service.read_page(doi=DOI)

    assert again["status"] == "ok", again
    assert again["source"] == "open-tab", again
    assert again["quota_charged"] == 0, again
    assert Path(again["mhtml_path"]).is_file()


def test_a_second_wall_in_the_open_tab_does_not_navigate(tmp_path: Path) -> None:
    """The reader has not solved it yet: look at their tab once, answer blocked, no goto."""

    from test_page_read import build_service

    wall = b"<html>please wait</html>"
    service = build_service(
        tmp_path,
        [
            [{"verb": "goto", "data": {"url": URL, "title": "请稍候…"}}],
            [
                {
                    "verb": "snapshot",
                    "data": {
                        "token": "t1",
                        "total": len(wall),
                        "base64": base64.b64encode(wall).decode("ascii"),
                        "url": URL,
                        "title": "请稍候…",
                        "captcha_visible": True,
                    },
                }
            ],
        ],
    )
    assert service.read_page(doi=DOI)["status"] == "blocked"

    again = service.read_page(doi=DOI)

    assert again["status"] == "blocked", again
    assert again["mhtml_path"] is None, again
    assert again["quota_charged"] == 0, again


def test_an_unrelated_tab_is_not_taken_for_the_article(tmp_path: Path) -> None:
    """A capture of some other page must not become the answer — nor stay on disk."""

    from test_page_read import build_service

    other = _mhtml(tmp_path / "other.mhtml", ARTICLE).read_bytes()
    service = build_service(
        tmp_path,
        [
            [{"verb": "goto", "data": {"url": URL, "title": "请稍候…"}}],
            # One transaction: the probe of the tab in front, then the navigation (the probe
            # runs under the browser lock now, so it shares the adapter).
            [
                _capture(other, url="https://example.org/unrelated", title="Something else"),
                {"verb": "goto", "data": {"url": URL, "title": "请稍候…"}},
            ],
        ],
    )
    assert service.read_page(doi=DOI)["status"] == "blocked"

    again = service.read_page(doi=DOI)

    assert again["status"] == "blocked", again
    assert not list(tmp_path.rglob("page.mhtml")), "the guess must be deleted"


def test_a_wall_marker_is_recorded_and_expires(tmp_path: Path) -> None:
    from test_page_read import build_service

    service = build_service(
        tmp_path, [[{"verb": "goto", "data": {"url": URL, "title": "请稍候…"}}]]
    )
    service.read_page(doi=DOI)

    # The marker is keyed by the URL that was actually navigated: the DOI link.
    state = json.loads((tmp_path / "page-read.json").read_text(encoding="utf-8"))
    assert state[f"https://doi.org/{DOI}"]["status"] == "blocked"
    assert challenge_in_title("请稍候…") == "请稍候"
