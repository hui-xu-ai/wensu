"""A verification wall is a wall everywhere — CNKI's slider is the same event as Cloudflare's.

ADR 0004 cooled the whole tool for 24 h on any risk signal. ADR 0022 removed that for the
signals a person clears in seconds, first only on `page:*`, then (same day, revision 1) on
every channel: a locked tool after one slider is an outage, and it is the exact mistake the
amendment exists to prevent.
"""

from __future__ import annotations

from scholar_search.core.contracts import RiskSignal
from scholar_search.core.planner import _stops_without_cooldown


def test_a_captcha_stops_without_cooling_on_any_channel() -> None:
    assert _stops_without_cooldown(RiskSignal.CAPTCHA) is True


def test_a_verify_redirect_stops_without_cooling() -> None:
    """`/verify/home` on CNKI is the case this exists for."""

    assert _stops_without_cooldown(RiskSignal.VERIFY_REDIRECT) is True


def test_an_expired_session_stops_without_cooling() -> None:
    """Signing back in fixes it; waiting a day does not."""

    assert _stops_without_cooldown(RiskSignal.LOGIN_REDIRECT) is True


def test_a_refusal_still_cools_down() -> None:
    """403/429 mean "stop coming back today", and that judgement stays (ADR 0004)."""

    assert _stops_without_cooldown(RiskSignal.HTTP_403) is False
    assert _stops_without_cooldown(RiskSignal.RATE_LIMITED) is False


def test_the_advice_no_longer_sends_a_cleared_session_to_reset() -> None:
    from scholar_search.core.errors import RiskBlocked

    payload = RiskBlocked("session ended", signal="login_redirect").to_payload()

    assert "cooldown_until" not in payload, payload
    assert "reset" not in payload["advice"], payload
