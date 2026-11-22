"""A challenge wall must be recognised, and nothing may be read after it.

Real run (2026-11-22, Wiley / `10.1002/adma.75384`): the controlled browser was shown a
Cloudflare interstitial. `page_read` answered

    status="no_html", reason="abstract_only", sections=0, headings=0, paywall_hits=0

which is wrong twice over:

* the page was not an abstract shell, it was a human-verification wall — the answer sent
  the caller off to "sign in to the publisher", a dead end;
* that exact probe shape satisfies `service._still_rendering()`, so the service slept and
  took a **second snapshot** of the challenge page. Nothing may be fetched after a wall
  is recognised; the page is the browser's problem now, not the tool's.

The desired contract these tests encode:

1. `classify_mhtml` names the wall (`blocked` / `challenge`) before it considers paywall
   or "abstract only" — a wall is neither;
2. `_still_rendering()` is False for it, so no second look is taken;
3. `_page_next()` tells the caller to solve the challenge in the browser, never to sign in.

Marked `xfail(strict=True)`: each one is a defect being pinned, and the marker must be
removed (not relaxed) when the behaviour is fixed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scholar_search.core.pageprobe import classify_mhtml
from scholar_search.core.service import _page_next, _still_rendering

_FIX = (
    "defect 1 (0.13.2): a Cloudflare/hCaptcha wall is classified as an abstract shell, "
    "which triggers a second snapshot and a 'sign in to the publisher' advice"
)


def _desired() -> pytest.MarkDecorator:
    """The behaviour is the contract; it is simply not implemented yet."""

    return pytest.mark.xfail(strict=True, reason=_FIX)


_WALL = """From: <Saved by Blink>
MIME-Version: 1.0
Content-Type: multipart/related; boundary="----WALL"

------WALL
Content-Type: text/html; charset=utf-8
Content-Transfer-Encoding: 8bit

<!DOCTYPE html><html><head><title>请稍候…</title></head><body>
<div id="challenge-stage"><div id="challenge-body-text">Verifying you are human.</div></div>
<script>window._cf_chl_opt={cvId:'3',cRay:'a5e7b09678d6e2f6',cZone:'wiley.com'};</script>
<noscript>Enable JavaScript and cookies to continue / challenge-platform</noscript>
<p>Ray ID: a5e7b09678d6e2f6</p>
<p>Performance &amp; security by Cloudflare</p>
</body></html>
------WALL--
"""

_ARTICLE = """From: <Saved by Blink>
MIME-Version: 1.0
Content-Type: multipart/related; boundary="----ART"

------ART
Content-Type: text/html; charset=utf-8
Content-Transfer-Encoding: 8bit

<!DOCTYPE html><html><head><title>Directional Confinement Governed Ion Transport</title></head>
<body><article>
<h2>1. Introduction</h2><p>Soft actuators are artificial muscles.</p>
<section id="s1"><p>Ion transport kinetics.</p></section>
<section id="s2"><p>Tortuosity.</p></section>
<h2>2. Results</h2><section id="s3"><p>Oriented channels.</p></section>
<section id="s4"><p>Actuation.</p></section>
<section id="s5"><p>Applications.</p></section>
<section id="s6"><p>Discussion.</p></section>
<h2>3. Conclusion</h2><p>Done.</p>
</article></body></html>
------ART--
"""

# No challenge marker, no numbered heading, no paywall wording, fewer than six section
# wrappers: the ONE shape that legitimately means "abstract shell, look again".
_ABSTRACT_SHELL = """From: <Saved by Blink>
MIME-Version: 1.0
Content-Type: multipart/related; boundary="----ABS"

------ABS
Content-Type: text/html; charset=utf-8
Content-Transfer-Encoding: 8bit

<!DOCTYPE html><html><head><title>Journal article</title></head><body>
<section id="highlights"><p>Highlights.</p></section>
<p>Abstract only, the body has not painted yet.</p>
</body></html>
------ABS--
"""


def _saved(tmp_path: Path, body: str, name: str = "page.mhtml") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_a_challenge_page_is_not_an_abstract_shell(tmp_path: Path) -> None:
    probe = classify_mhtml(_saved(tmp_path, _WALL))

    assert probe["status"] == "blocked", probe
    assert probe["reason"] == "challenge", probe
    assert probe.get("signal"), "a wall must name the marker that identified it"


def test_the_caller_is_told_to_solve_it_in_the_browser(tmp_path: Path) -> None:
    probe = classify_mhtml(_saved(tmp_path, _WALL))

    advice = _page_next(probe).lower()
    assert "sign in" not in advice, advice
    assert "challenge" in advice or "verification" in advice or "browser" in advice, advice


def test_no_second_look_is_taken_on_a_challenge_page(tmp_path: Path) -> None:
    probe = classify_mhtml(_saved(tmp_path, _WALL))

    assert _still_rendering(probe) is False, (
        "a challenge wall is not a late-rendering page; the second snapshot is a fetch "
        "of the wall and must not happen"
    )


# -- guards: the fix must not swallow the legitimate cases --------------------


def test_a_real_article_page_is_still_ok(tmp_path: Path) -> None:
    probe = classify_mhtml(_saved(tmp_path, _ARTICLE))

    assert probe["status"] == "ok", probe


def test_an_ordinary_abstract_shell_still_gets_a_second_look(tmp_path: Path) -> None:
    """Removing the second look entirely would break 0.12.59's real fix."""

    probe = classify_mhtml(_saved(tmp_path, _ABSTRACT_SHELL))

    assert probe["reason"] == "abstract_only", probe
    assert _still_rendering(probe) is True


def test_a_paywall_is_not_mistaken_for_a_wall(tmp_path: Path) -> None:
    body = _ABSTRACT_SHELL.replace(
        "<p>Abstract only, the body has not painted yet.</p>",
        "<p>Get access through your organization or purchase PDF</p>",
    )
    probe = classify_mhtml(_saved(tmp_path, body))

    assert probe["status"] == "no_html", probe
    assert probe["reason"] == "paywall", probe


@pytest.mark.parametrize("marker", ["Ray ID", "challenge-platform", "__cf_chl_opt", "请稍候"])
def test_each_known_marker_alone_is_enough(tmp_path: Path, marker: str) -> None:
    """The wall is recognised by content, not only by URL: the run's `final_url` was clean.

    Wiley answered the plain DOI URL with the interstitial, so a URL-only rule would have
    missed exactly the case that produced this file.
    """

    body = _ABSTRACT_SHELL.replace("<title>Journal article</title>", f"<title>{marker}</title>")
    probe = classify_mhtml(_saved(tmp_path, body))

    assert probe["status"] == "blocked", (marker, probe)


def test_a_challenge_url_alone_is_enough(tmp_path: Path) -> None:
    """The address bar is checked before the body: a redirect leaves the marker there."""

    probe = classify_mhtml(
        _saved(tmp_path, _ABSTRACT_SHELL),
        url="https://example.org/__cf_chl_rt_tk=abc",
    )

    assert probe["status"] == "blocked", probe
    assert probe["signal"] == "url:__cf_chl_rt_tk", probe


def test_the_service_takes_one_snapshot_and_reports_the_wall(tmp_path: Path) -> None:
    """End to end: a wall costs the two navigations, one capture, and no retry.

    `tests/unit/test_page_read.py` owns the service fixture; reusing it keeps the fake
    adapter (which fails loudly on an unexpected action) as the assertion.
    """

    import base64

    from test_page_read import build_service, write_mhtml

    wall = write_mhtml(tmp_path / "wall.mhtml", _WALL).read_bytes()
    scripts = [
        [
            {"verb": "goto", "data": {"url": "https://onlinelibrary.wiley.com/"}},
            {
                "verb": "goto",
                "data": {"url": "https://onlinelibrary.wiley.com/doi/10.1002/adma.75384"},
            },
            {"verb": "sleep", "data": {"ms": 1_200}},
            {
                "verb": "snapshot",
                "data": {
                    "token": "t1",
                    "total": len(wall),
                    "base64": base64.b64encode(wall).decode("ascii"),
                    "url": "https://onlinelibrary.wiley.com/doi/10.1002/adma.75384",
                    "title": "请稍候…",
                    "captcha_visible": False,
                },
            },
        ]
    ]
    service = build_service(tmp_path, scripts)

    result = service.read_page(doi="10.1002/adma.75384")

    assert result["status"] == "blocked", result
    assert result["reason"] == "challenge", result
    assert result["signal"], result
    assert result["quota_charged"] == 2, result
    assert "sign in" not in result["next"].lower(), result["next"]
