"""Only evidence that cannot be anything else stops a plan.

The rules used to treat a login-looking URL, a header login form and a `Just a moment…` title as
walls. All three are ordinary on pages nobody is challenging — a slow page prints that title
while it paints, and every publisher prints a "Sign in" link — so reads were dropped for walls
not see (2026-11-25, reported twice). Hints are now recorded in `last_note` and ignored; only a
visible captcha widget and an outright HTTP refusal stop the run.
"""

from __future__ import annotations

from pathlib import Path

from scholar_search.core.contracts import Action, ActionOutcome
from scholar_search.core.risk import RiskGuard, RiskSignal


def guard(tmp_path: Path) -> RiskGuard:
    return RiskGuard(state_path=tmp_path / "cooldown.json")


def outcome(
    *, url: str = "", error: str = "", data: dict[str, object] | None = None
) -> ActionOutcome:
    return ActionOutcome(
        action=Action("goto", {"url": url or "https://example.org/"}),
        ok=not error,
        error=error or None,
        url=url,
        data=data or {},
        duration_ms=1,
    )


# -- the two things that stop -------------------------------------------------


def test_a_visible_captcha_stops_the_plan(tmp_path: Path) -> None:
    signal = guard(tmp_path).inspect(outcome(data={"captcha_visible": True}))
    assert signal is RiskSignal.CAPTCHA


def test_http_403_stops_the_plan(tmp_path: Path) -> None:
    assert guard(tmp_path).inspect(outcome(error="http 403 forbidden")) is RiskSignal.HTTP_403
    assert guard(tmp_path).inspect(outcome(data={"status": 403})) is RiskSignal.HTTP_403


def test_http_429_stops_the_plan(tmp_path: Path) -> None:
    assert guard(tmp_path).inspect(outcome(data={"status": 429})) is RiskSignal.RATE_LIMITED


# -- the hints that no longer stop --------------------------------------------


def test_a_login_url_stops_the_plan_without_cooling_down(tmp_path: Path) -> None:
    """AGENTS.md §3: a login redirect terminates the plan and cools nothing down (ADR 0022 r1).

    The URL itself is the evidence — no text matching is involved — so this is attributable.
    """

    instance = guard(tmp_path)

    assert instance.inspect(outcome(url="https://fsso.cnki.net/login")) is RiskSignal.LOGIN_REDIRECT
    blocked = instance.trip(RiskSignal.LOGIN_REDIRECT)
    assert blocked.cooldown_until is None


def test_a_page_that_asks_for_a_login_stops_the_plan(tmp_path: Path) -> None:
    instance = guard(tmp_path)

    assert instance.inspect(outcome(data={"auth_required": True})) is RiskSignal.LOGIN_REDIRECT


def test_an_explicit_verification_path_stops_the_plan(tmp_path: Path) -> None:
    instance = guard(tmp_path)

    assert instance.inspect(outcome(url="https://kns.cnki.net/verify/home")) is (
        RiskSignal.VERIFY_REDIRECT
    )


def test_a_url_that_merely_contains_captcha_is_not_a_verification_page(tmp_path: Path) -> None:
    """ACS hops through such a URL and lands on the article (measured 2026-11-25)."""

    instance = guard(tmp_path)

    assert instance.inspect(outcome(url="https://pubs.acs.org/doi?captcha=1")) is None


def test_a_challenge_looking_title_is_only_a_note(tmp_path: Path) -> None:
    """`Just a moment…` is also what a slow page shows while it paints."""

    instance = guard(tmp_path)
    assert instance.inspect(outcome(data={"title": "Just a moment..."})) is None
    assert instance.last_note is not None and instance.last_note.startswith("title:")


def test_a_verification_url_with_an_article_title_is_not_a_wall(tmp_path: Path) -> None:
    """ACS hops through `…?captcha=…` and lands on the article."""

    instance = guard(tmp_path)
    signal = instance.inspect(
        outcome(
            url="https://pubs.acs.org/inocaj/article/60/22/16922?captcha=1",
            data={"title": "Hydrolysis-Promoted Building Block Assembly | Inorganic Chemistry"},
        )
    )
    assert signal is None
    assert instance.last_note is None


def test_an_ordinary_article_page_produces_no_signal_and_no_note(tmp_path: Path) -> None:
    instance = guard(tmp_path)
    signal = instance.inspect(
        outcome(url="https://www.mdpi.com/1424-8220/26/4/1303", data={"title": "A paper"})
    )
    assert signal is None
    assert instance.last_note is None
