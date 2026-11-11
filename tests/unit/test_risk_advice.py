"""A blocked response has to say what the person in front of the browser should do.

The 0.12.48 acceptance hit `signal: login_redirect` on the first WoS call and stopped
there. The payload was:

    {"status": "blocked", "signal": "login_redirect",
     "cooldown_until": "2026-11-12T01:04:06+00:00", "action_required": "manual_verification"}

Nothing in it says the session expired, nothing says waiting is pointless, and the way
out (`wensu reset --confirm`) appears in no field the caller reads. A 24-hour cooldown is
the correct *stop*; it is the wrong *instruction* for a login problem.

The stop itself is not negotiable — AGENTS.md requires it and this change does not weaken
it. Only the guidance is per-signal, because one message cannot fit a captcha (seconds to
fix), an expired session (one sign-in), and a 403 (stop for the day).
"""

from __future__ import annotations

import pytest

from scholar_search.core.errors import RiskBlocked
from scholar_search.core.risk import RiskSignal

SIGNALS = [signal.value for signal in RiskSignal]


def _payload(signal: str) -> dict[str, str]:
    return RiskBlocked("x", signal=signal, cooldown_until="2026-11-12T01:04:06+00:00").to_payload()


@pytest.mark.parametrize("signal", SIGNALS)
def test_every_signal_explains_itself(signal: str) -> None:
    advice = _payload(signal).get("advice")
    assert advice, f"{signal} blocks the tool for 24 h with no explanation"
    assert len(advice) > 40, "advice that says nothing is worse than none"


def test_a_login_redirect_names_the_session_and_the_way_out() -> None:
    """The exact case that reached the user as a bare timestamp."""

    advice = _payload("login_redirect")["advice"]
    assert "session" in advice.casefold()
    assert "reset --confirm" in advice
    assert "wait" in advice.casefold(), "it must say that waiting does not help"


def test_a_captcha_is_not_told_to_wait_a_day() -> None:
    advice = _payload("captcha")["advice"]
    assert "captcha" in advice.casefold()
    assert "reset --confirm" in advice
    assert "never automate" in advice.casefold()


def test_a_403_is_told_to_stop_rather_than_to_sign_in() -> None:
    """Different signals must not collapse into one message."""

    advice = _payload("http_403")["advice"]
    assert "reset --confirm" not in advice, "signing in does not fix a refusal"
    assert "stop" in advice.casefold()


def test_the_stop_itself_is_unchanged() -> None:
    """Only the guidance was added; the block is still a block."""

    payload = _payload("login_redirect")
    assert payload["status"] == "blocked"
    assert payload["action_required"] == "manual_verification"
    assert payload["cooldown_until"] == "2026-11-12T01:04:06+00:00"


def test_an_unknown_signal_gets_no_invented_advice() -> None:
    """A signal added later without guidance must stay silent, not guess."""

    assert "advice" not in _payload("some_future_signal")
