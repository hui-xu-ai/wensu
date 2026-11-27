"""The snapshot path's two real-machine lessons (0.14.58 run, F58-01).

A 2.9 MB ScienceDirect page took the browser more than 17 s to produce its MHTML, so `snapshot()`
answered `bridge.error: timed out` with `retryable: false` — a correct page reported as unavailable,
and no honest next step for the caller.
"""

from __future__ import annotations

from scholar_search.core.errors import ActionError, BridgeTimeout, RiskBlocked
from scholar_search.core.service import SNAPSHOT_TIMEOUT_MS
from scholar_search.server import _retryable


def test_the_capture_budget_covers_a_heavy_page() -> None:
    """15 s was measured to be too short; the budget is for `pageCapture`, not the transport."""

    assert SNAPSHOT_TIMEOUT_MS >= 45_000, SNAPSHOT_TIMEOUT_MS


def test_a_timed_out_capture_may_be_asked_for_again() -> None:
    """It costs no quota and writes nothing before the bytes arrive, so nothing was lost."""

    error = ActionError("the page could not be saved", verb="snapshot", code="bridge.timeout")
    error.stage = "snapshot" if not error.stage else error.stage

    assert _retryable(error) is True


def test_a_timed_out_read_stays_not_retryable() -> None:
    """Its navigation may already have been issued: repeating could charge again."""

    error = ActionError("the page did not answer", verb="goto", code="bridge.timeout")
    error.stage = "navigate" if not error.stage else error.stage

    assert _retryable(error) is False


def test_the_other_answers_keep_their_meanings() -> None:
    assert _retryable(BridgeTimeout("timed out")) is True
    assert _retryable(RiskBlocked("captcha", signal="captcha")) is False
    assert (
        _retryable(ActionError("blocked", verb="goto", code="policy.domain", stage="navigate"))
        is False
    )
