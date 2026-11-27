"""The snapshot path's two real-machine lessons (0.14.58 run, F58-01) and the corrections after.

A 2.9 MB ScienceDirect page was still being captured at 17.034 s when the 15 s budget expired, so
`snapshot()` answered `bridge.error: timed out`. The first fix (0.14.59) raised the budget and
declared every snapshot timeout retryable; the second half was wrong — a capture that was *sent*
may still be running, and a retry would put two `saveAsMHTML` calls on one tab.
"""

from __future__ import annotations

from scholar_search.core.errors import ActionError, BridgeTimeout, RiskBlocked
from scholar_search.core.service import SNAPSHOT_TIMEOUT_MS
from scholar_search.server import _retryable


def _capture_error(issued: bool | None) -> ActionError:
    error = ActionError(
        "the page could not be saved",
        verb="snapshot",
        code="bridge.timeout",
        stage="snapshot",
        operation_issued=issued,
    )
    error.stage = "snapshot"
    return error


def test_the_capture_budget_sits_below_the_host_ceiling() -> None:
    """Above 60 000 ms the host refuses the request outright (`native-host/main.py`)."""

    assert 15_000 < SNAPSHOT_TIMEOUT_MS < 60_000, SNAPSHOT_TIMEOUT_MS


def test_a_capture_that_was_sent_is_not_safe_to_repeat() -> None:
    """It may still be running in the browser: a second one would overlap the first."""

    assert _retryable(_capture_error(True)) is False
    assert _retryable(_capture_error(None)) is False, "unknown is not permission"


def test_a_capture_that_never_left_may_be_asked_for_again() -> None:
    assert _retryable(_capture_error(False)) is True


def test_a_timed_out_read_stays_not_retryable() -> None:
    """Its navigation may already have been issued: repeating could charge again."""

    error = ActionError("the page did not answer", verb="goto", code="bridge.timeout")
    error.stage = "navigate"

    assert _retryable(error) is False


def test_a_capture_timeout_is_not_reported_as_a_navigation_problem() -> None:
    """`_page_stage` could not tell which timeout it was, so a capture read as `navigate`:

    "the page never arrived" for a page that had arrived and been captured.
    """

    from scholar_search.core.service import _page_stage

    assert _page_stage({"status": "timeout", "reason": "capture_unconfirmed"}) == "navigate"
    assert _page_stage({"status": "timeout", "stage": "capture"}) == "capture"
    # An exit that knows its stage says it; the derivation is the fallback, not the authority.
    assert _page_stage({"status": "no_page", "reason": "capture_mismatch"}) == "identity"
    assert _page_stage({"status": "no_page", "reason": "capture_mismatch", "stage": "publish"}) == (
        "publish"
    )
    # Unknown values do not become a stage by accident.
    assert _page_stage({"status": "timeout", "stage": "banana"}) == "navigate"


def test_the_other_answers_keep_their_meanings() -> None:
    assert _retryable(BridgeTimeout("timed out")) is True
    assert _retryable(RiskBlocked("captcha", signal="captcha")) is False
    assert (
        _retryable(ActionError("blocked", verb="goto", code="policy.domain", stage="navigate"))
        is False
    )
