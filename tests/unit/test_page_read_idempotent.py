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


def test_a_capture_without_a_judge_stamp_is_not_served(tmp_path: Path) -> None:
    """Entries written before the rule set changed must not outlive it.

    Report 2026-11-26 (P0-2): the browser could show the full article while `page_read` kept
    answering from an hour-old abstract capture, and nothing the caller could pass would help.
    """

    import json

    from test_page_read import build_service

    blob = _write_mhtml(tmp_path / "page.mhtml", ARTICLE_HTML)
    service = build_service(tmp_path, [_one_capture(blob), _one_capture(blob)])

    first = service.read_page(doi=DOI)
    assert first["status"] == "ok", first

    # Rewrite the entry the way the previous release wrote it: no stamp, no evidence.
    state = json.loads((tmp_path / "page-read.json").read_text(encoding="utf-8"))
    key = next(iter(state))
    for field in ("judge", "reason", "prose_words", "final_url", "captured_url"):
        state[key].pop(field, None)
    (tmp_path / "page-read.json").write_text(json.dumps(state), encoding="utf-8")

    second = service.read_page(doi=DOI)

    assert not second.get("cached"), second
    assert second["status"] == "ok", second


def test_refresh_navigates_again_on_request(tmp_path: Path) -> None:
    """The caller needs a way to say "the cached verdict is wrong" — and only that way."""

    from test_page_read import build_service

    blob = _write_mhtml(tmp_path / "page.mhtml", ARTICLE_HTML)
    service = build_service(tmp_path, [_one_capture(blob), _one_capture(blob)])

    assert service.read_page(doi=DOI)["status"] == "ok"
    assert service.read_page(doi=DOI)["cached"] is True

    refreshed = service.read_page(doi=DOI, refresh=True)

    assert not refreshed.get("cached"), refreshed
    assert refreshed["status"] == "ok", refreshed
    assert refreshed["quota_charged"] > 0, refreshed


def test_doi_case_does_not_create_a_second_entry(tmp_path: Path) -> None:
    """DOIs are case-insensitive; two spellings used to be two entries, neither protecting the
    other (measured 2026-11-26: the same DOI sat in `page-read.json` twice)."""

    import json

    from test_page_read import build_service

    blob = _write_mhtml(tmp_path / "page.mhtml", ARTICLE_HTML)
    service = build_service(tmp_path, [_one_capture(blob), _one_capture(blob)])

    service.read_page(doi=DOI.upper())

    state = json.loads((tmp_path / "page-read.json").read_text(encoding="utf-8"))
    assert list(state) == [f"https://doi.org/{DOI.lower()}"], list(state)
    assert service.read_page(doi=DOI)["cached"] is True
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
