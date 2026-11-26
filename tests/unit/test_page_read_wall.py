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

    # Exactly one navigation, then one wait that expires: a capture would pop from an empty list
    # and fail. (The wait is free — it is how a transient interstitial is told apart from a wall.)
    service = build_service(
        tmp_path,
        [[*_goto("请稍候…"), *_wall_steps(URL)]],
    )

    result = service.read_page(doi=DOI)

    assert result["status"] == "blocked", result
    # The wall is named by the risk rules (a gate title), so the answer carries the signal —
    # and no cooldown, because a click clears it (ADR 0022).
    assert result["signal"], result
    assert not result.get("cooldown_until"), result
    assert "reset" not in (result.get("advice") or ""), result
    assert result["mhtml_path"] is None, result
    assert result["quota_charged"] == 1, result
    assert "snapshot" in result["next"]
    assert not list(tmp_path.rglob("page.mhtml")), "a wall must not be saved as a page"


def test_a_wall_stops_the_plan_without_cooling_anything_down(tmp_path: Path) -> None:
    """A verification wall is expected traffic, not abuse (ADR 0022).

    The second call is answered from the reader's own tab (0 quota, no navigation), which is
    the whole point: nothing is cooled down, and nothing navigates again.
    """

    from test_page_read import build_service

    wall = b"<html>please wait</html>"
    service = build_service(
        tmp_path,
        [
            [
                *_goto("Just a moment..."),
                *_wall_steps(URL),
            ],
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
    service.read_page(doi=DOI)

    again = service.read_page(doi=DOI)

    assert again["status"] == "blocked", again
    assert not again.get("cooldown_until"), again
    assert again["quota_charged"] == 0, again


def _snapshot_reply(blob: bytes, title: str, *, captcha: bool) -> dict[str, object]:
    return {
        "verb": "snapshot",
        "data": {
            "token": "t1",
            "total": len(blob),
            "base64": base64.b64encode(blob).decode("ascii"),
            "url": URL,
            "title": title,
            "captcha_visible": captcha,
        },
    }


def test_snapshot_refuses_to_save_a_wall(tmp_path: Path) -> None:
    """`snapshot` is user-driven, so it does not cool down — but it must not save a wall."""

    from test_page_read import build_service

    blob = b"<html>please wait</html>"
    service = build_service(tmp_path, [[_snapshot_reply(blob, "请稍候…", captcha=True)]])

    result = service.snapshot()

    assert result["status"] == "blocked", result
    assert result["path"] is None, result
    assert result["bytes"] == 0 and result["discarded_bytes"] == len(blob), result
    assert not list(tmp_path.rglob("page.mhtml")), "a wall must not reach the disk"


def test_snapshot_still_works_after_a_wall(tmp_path: Path) -> None:
    """The recovery path is "solve it, then snapshot" — nothing may close it."""

    from test_page_read import build_service

    html = (
        "<html><body><article><h1>A paper</h1><section id='s1'>"
        "<h2>1. Introduction</h2><p>Body text.</p></section></article></body></html>"
    )
    service = build_service(
        tmp_path,
        [
            [
                *_goto("请稍候…"),
                *_wall_steps(URL),
            ],
            [_snapshot_reply(html.encode("utf-8"), "Directional Confinement", captcha=False)],
        ],
    )
    assert service.read_page(doi=DOI)["status"] == "blocked"

    result = service.snapshot()

    assert result.get("status") != "blocked", result
    assert result["path"], result
    assert Path(result["path"]).is_file()


def test_an_ordinary_page_still_goes_through_the_capture(tmp_path: Path) -> None:

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


# --- 证据必须属于本次导航（T0 2026-11-26：四条误判路径） --------------------------------
#
# `page_read` used to judge a wall from *any* title it happened to see: the last non-empty title
# across every outcome of the navigation (two `goto`s once the warmup patch navigates through the
# publisher's home page), or the title of whichever tab was in front. Both produced `blocked` for
# pages that were readable — L26 in the 2026-11-26 report answered a RSC DOI with a `science.org`
# URL. The rules below only make evidence *belong* to this read; they do not relax ADR 0004.

ACS_DOI = "10.1021/jacs.4c07518"
ACS_ARTICLE = "https://pubs.acs.org/doi/10.1021/jacs.4c07518"
ACS_HOME = "https://pubs.acs.org/"
FOREIGN = "https://www.science.org/doi/10.1126/scirobotics.adh4060"
BODY_HTML = (
    '<html><body><article><h1>A paper</h1><section id="s1">'
    "<h2>1. Introduction</h2><p>Body text.</p></section></article></body></html>"
)


def _goto_at(url: str, title: str, **extra: object) -> dict[str, object]:
    return {"verb": "goto", "data": {"url": url, "title": title, "ok": True, **extra}}


def _reply_at(html: str, url: str, title: str, *, captcha: bool = False) -> dict[str, object]:
    part = email.mime.text.MIMEText(html, "html", "utf-8")
    outer = email.mime.multipart.MIMEMultipart("related")
    outer.attach(part)
    blob = outer.as_bytes()
    return {
        "verb": "snapshot",
        "data": {
            "token": "t1",
            "total": len(blob),
            "base64": base64.b64encode(blob).decode("ascii"),
            "url": url,
            "title": title,
            "captcha_visible": captcha,
        },
    }


def _warmup_navigation(monkeypatch: object) -> None:
    """The private warmup patch: home page first, then the article (two `goto`s).

    Pinned as a test because the patch replaces `page_nav.py` on the installed build, so whatever
    the kernel decides must stay correct when one read performs two navigations.
    """

    import scholar_search.core.service as service_module
    from scholar_search.core.contracts import Action

    def navigation(service: object, target: str, publisher: object) -> tuple[Action, ...]:
        del service, publisher
        return (Action("goto", {"url": ACS_HOME}), Action("goto", {"url": target}))

    monkeypatch.setattr(service_module, "article_navigation", navigation)  # type: ignore[attr-defined]


def _mark_walled(service: object, doi: str) -> None:
    """Record "this URL met a wall just now" the way a previous `blocked` answer would."""

    import json
    import time as clock

    path = service._page_cache_path()  # what the previous call wrote
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({f"https://doi.org/{doi}": {"status": "blocked", "at": clock.time()}}),
        encoding="utf-8",
    )


def test_two_navigations_do_not_lend_each_other_titles(tmp_path: Path, monkeypatch: object) -> None:
    """The article's own title is empty after `goto` when the page is still painting.

    The home page's 「请稍候…」 is a different page's title, so it is not evidence — with the old
    "last non-empty title wins" loop this read returned `blocked` (T0 1a).
    """

    from test_page_read import build_service

    _warmup_navigation(monkeypatch)
    service = build_service(
        tmp_path,
        [
            [
                _goto_at(ACS_HOME, "请稍候…", halted=True),
                _goto_at(ACS_ARTICLE, "", halted=True),
                {"verb": "sleep", "data": {"ms": 1}},
                _reply_at(BODY_HTML, ACS_ARTICLE, "A paper"),
            ]
        ],
    )

    result = service.read_page(doi=ACS_DOI)

    assert result["status"] != "blocked", result
    assert result["status"] == "ok", result
    assert int(result["bytes"] or 0) > 0, result


def test_a_wall_on_another_site_is_not_evidence(tmp_path: Path) -> None:
    """After a wall marker the read looks at the tab in front — which may be another site.

    Measured 2026-11-26 (report L26): asking for an RSC DOI answered with the `science.org` URL of
    whatever tab happened to be in front. A different site's challenge page says nothing about
    this DOI, so the read must go back to navigating instead of reporting a wall.
    """

    from test_page_read import build_service

    service = build_service(
        tmp_path,
        [
            # One transaction: probe of the tab in front (another site here), then the
            # navigation. The probe runs under the browser lock, so it shares the adapter.
            [
                _reply_at("<html>请稍候</html>", FOREIGN, "请稍候…", captcha=True),
                _goto_at(ACS_ARTICLE, "A paper", halted=True),
                {"verb": "sleep", "data": {"ms": 1}},
                _reply_at(BODY_HTML, ACS_ARTICLE, "A paper"),
            ]
        ],
    )
    _mark_walled(service, ACS_DOI)

    result = service.read_page(doi=ACS_DOI)

    assert result["status"] != "blocked", result
    assert "science.org" not in str(result.get("final_url")), result


def test_a_gate_title_that_did_not_persist_is_not_a_wall(tmp_path: Path) -> None:
    """The extension already times the gate title (`halted`, 1.5 s) — the kernel must read it.

    Measured live 2026-11-26: the ACS interstitial clears itself in ~40 s, so a title sampled at
    `goto` return is not the page's verdict. When `halted` is false, capture and classify instead.
    """

    from test_page_read import build_service

    service = build_service(
        tmp_path,
        [
            [
                _goto_at(ACS_ARTICLE, "请稍候…", halted=False),
                {"verb": "sleep", "data": {"ms": 1}},
                _reply_at(BODY_HTML, ACS_ARTICLE, "A paper"),
            ]
        ],
    )

    result = service.read_page(doi=ACS_DOI)

    assert result["status"] != "blocked", result
    assert int(result["bytes"] or 0) > 0, result


def test_the_probe_of_the_tab_in_front_holds_the_browser_lock(
    tmp_path: Path, monkeypatch: object
) -> None:
    """That probe is the only tab this read touches without navigating it.

    It used to run *outside* the browser lock, so another read could navigate the shared tab
    between the probe and the verdict — that is how one DOI's answer carried another article's
    URL (2026-11-26 report L26/L27). The lock is the fix, so the lock is what the test pins.
    """

    from test_page_read import build_service

    from scholar_search.core.locking import interprocess_lock

    service = build_service(
        tmp_path,
        [
            # One transaction: probe of the tab in front (another site here), then the
            # navigation. The probe runs under the browser lock, so it shares the adapter.
            [
                _reply_at("<html>请稍候</html>", FOREIGN, "请稍候…", captcha=True),
                _goto_at(ACS_ARTICLE, "A paper", halted=True),
                {"verb": "sleep", "data": {"ms": 1}},
                _reply_at(BODY_HTML, ACS_ARTICLE, "A paper"),
            ]
        ],
    )
    _mark_walled(service, ACS_DOI)

    seen: list[str] = []
    original = service._snapshot_locked

    def probing(*, tab: str = "active") -> dict[str, object]:
        lock = service._page_cache_path().parent / "browser.lock"
        try:
            with interprocess_lock(lock, timeout_s=0.05):
                seen.append("unlocked")
        except Exception:  # the transaction that called us holds the lock
            seen.append("locked")
        return original(tab=tab)

    monkeypatch.setattr(service, "_snapshot_locked", probing)
    service.read_page(doi=ACS_DOI)

    assert seen, "the tab in front was never probed"
    assert set(seen) == {"locked"}, seen


def test_the_answer_names_the_page_it_captured(tmp_path: Path) -> None:
    """A caller can check what it got instead of trusting `status: ok`."""

    from test_page_read import build_service

    service = build_service(
        tmp_path,
        [
            [
                _goto_at(ACS_ARTICLE, "A paper", halted=True),
                {"verb": "sleep", "data": {"ms": 1}},
                _reply_at(BODY_HTML, ACS_ARTICLE, "A paper"),
            ]
        ],
    )

    result = service.read_page(doi=ACS_DOI)

    assert result["captured_url"] == ACS_ARTICLE, result


def test_a_wait_that_could_not_run_is_not_a_slow_click(tmp_path: Path) -> None:
    """A protocol fault must not be reported as "the person did not click" (F33-02).

    The P5 acceptance saw `verification_timeout` on a read whose whole life was 3.3 s and which
    executed no wait at all: the capability gate had refused the action, and the caller was told
    the user had been given ten seconds.
    """

    from test_page_read import build_service

    service = build_service(
        tmp_path,
        [
            [
                _goto_at(ACS_ARTICLE, "请稍候…", halted=True),
                {"verb": "await_gate_clear", "ok": False, "error": "action.unsupported"},
            ]
        ],
    )

    result = service.read_page(doi=ACS_DOI)

    assert result["terminal"] == "blocked", result
    assert result["reason"] != "verification_timeout", result
    assert result["waited"] is False, result
    assert result["stage"] == "wall", result
    assert "capabilities" in result["next"], result["next"]


def test_a_gate_title_on_a_page_that_is_not_a_wall_is_not_a_wall(tmp_path: Path) -> None:
    """Measured 2026-11-26 on ACS: the title said 「请稍候…」 while the page was the article.

    The title is a claim about the tab at the instant `goto` returned; the capture is the page
    itself, costs no quota, and a real wall is discarded before it reaches the disk. Without
    this the read called a readable page a challenge (the report's N1).
    """

    from test_page_read import build_service

    service = build_service(
        tmp_path,
        [
            [
                _goto_at(ACS_ARTICLE, "请稍候…", halted=True),
                *_cleared_steps(ACS_ARTICLE, "A paper"),
                {"verb": "sleep", "data": {"ms": 1}},
                _reply_at(BODY_HTML, ACS_ARTICLE, "A paper"),
            ]
        ],
    )

    result = service.read_page(doi=ACS_DOI)

    assert result["status"] != "blocked", result
    assert result["status"] == "ok", result


def test_a_gate_title_that_never_clears_is_still_a_wall(tmp_path: Path) -> None:
    """The capture must not turn a real wall into an article."""

    from test_page_read import build_service

    service = build_service(
        tmp_path,
        [
            [
                _goto_at(ACS_ARTICLE, "请稍候…", halted=True),
                *_wall_steps(ACS_ARTICLE),
            ]
        ],
    )

    result = service.read_page(doi=ACS_DOI)

    assert result["status"] == "blocked", result
    assert result["quota_charged"] == 1, result
    assert not list(tmp_path.rglob("page.mhtml")), "a wall must not be saved"


def _wall_steps(url: str, title: str = "请稍候…") -> list[dict[str, object]]:
    """What follows a gate title: one bounded wait for the person, which does not clear.

    The kernel brings the window forward and asks the extension to watch the tab title for ten
    seconds (ADR 0027). Nothing is captured here on purpose: an uncleared gate stops the read.
    """

    return [
        {
            "verb": "await_gate_clear",
            "data": {
                "cleared": False,
                "url": url,
                "title": title,
                "reason": "verification_timeout",
            },
        }
    ]


def _cleared_steps(url: str, title: str = "请稍候…") -> list[dict[str, object]]:
    """The same wait, but the person clicked: the article is on screen now."""

    return [{"verb": "await_gate_clear", "data": {"cleared": True, "url": url, "title": title}}]


def test_a_plain_title_that_merely_mentions_the_marker_is_not_a_wall() -> None:
    """Substring matching called this article a wall (T0 1c); `risk.py` had the strict rule."""

    assert (
        challenge_in_title(
            "Loading: Just a moment please — Journal of the American Chemical Society"
        )
        is None
    )
    assert (
        challenge_in_title("Checking your browser before reading the whole article in full") is None
    )
    # The samples the rule exists for still match.
    assert challenge_in_title("请稍候…") == "请稍候"
    assert challenge_in_title("Just a moment...") == "just a moment"
    assert challenge_in_title("Attention Required! | Cloudflare") == "attention required"
