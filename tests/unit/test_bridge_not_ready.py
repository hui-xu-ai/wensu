"""A dead bridge must cost nothing and must say what to do about it."""

from __future__ import annotations

import pytest

from scholar_search.adapters.bridge import BridgeAdapter
from scholar_search.core.errors import ActionError


def test_ensure_bridge_refuses_before_any_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard must fire before anything can spend quota.

    `_ensure_bridge` sits at the top of `_run`, ahead of `planner.run`, which is where
    `wait_turn` reserves a slot. Testing the guard directly keeps the assertion about
    behaviour: going through the whole `search` path pulls in the plan lock and then
    fails on file permissions instead of on the thing under test.
    """

    from scholar_search.bootstrap import build_service
    from scholar_search.core.policy import PolicyEngine

    service = build_service()
    reservations: list[str] = []
    monkeypatch.setattr(
        PolicyEngine,
        "wait_turn",
        lambda self: reservations.append("wait_turn") or 0.0,
    )
    monkeypatch.setattr(BridgeAdapter, "probe", classmethod(lambda cls: False))

    with pytest.raises(ActionError) as caught:
        service._ensure_bridge()

    assert caught.value.code == "bridge.not_ready"
    assert reservations == [], "the guard must not reserve quota"


def test_ensure_bridge_passes_when_an_extension_is_listening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scholar_search.bootstrap import build_service

    service = build_service()
    monkeypatch.setattr(BridgeAdapter, "probe", classmethod(lambda cls: True))
    service._ensure_bridge()  # must not raise


def test_bridge_remediation_does_not_assert_a_cause_it_cannot_know() -> None:
    """A `bridge.timeout` says an action got no reply — nothing more.

    The static remediation used to state "the browser extension is not connected" and
    send the user to `wensu browser start`. The acceptance run that hit this had
    `bridge_ready: true` immediately before and after the failure; restarting a
    working browser was the wrong instruction, and it was stated as fact.

    The connection, the content script in that tab, and the page itself are all
    candidates. So the payload names a check and a human step, and leaves the
    diagnosis open.
    """

    from scholar_search.core.service import ScholarService

    payload = ScholarService.BRIDGE_REMEDIATION
    diagnosis = str(payload["diagnosis"]).casefold()
    assert "extension is not connected" not in diagnosis, "a timeout is not a verdict"

    assert payload["next_action"] == "bring_the_tab_forward"
    assert payload["human_step_required"] is True
    # It still has to name something the caller can run, and still has to forbid
    # touching browser processes.
    assert payload["command"] == "wensu status"

    note = str(payload["note"]).casefold()
    assert "bridge_ready" in note, "the caller needs to know which check settles it"
    for forbidden in ("never", "kill"):
        assert forbidden in note, f"the note should forbid {forbidden!r}"


def test_bridge_remediation_still_points_at_browser_start_when_that_is_the_fix() -> None:
    """`status` keeps its case-by-case guidance — that path can tell the cases apart."""

    from scholar_search.bootstrap import _bridge_remediation

    # Never seen a host at all: starting one is the right action.
    assert _bridge_remediation(None)["next_action"] in {"setup", "browser_start"}


def test_remediation_says_start_the_browser_when_it_is_not_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The branch that the report actually hit.

    It was told to click an extension icon, relayed that to the user, and the user
    answered "did you forget E:\\LiteratureEdgeProfile" — because no browser was
    running to click anything in. The diagnosis has to come from whether the profile
    is in use, not from when a host last logged.
    """

    from scholar_search.core import browser as browser_cfg

    recorded = browser_cfg.BrowserConfig(
        browser="edge",
        executable="msedge.exe",
        profile_dir=r"E:\LiteratureEdgeProfile",
        extension_dir="ext",
    )
    monkeypatch.setattr(browser_cfg, "load", lambda: recorded)
    monkeypatch.setattr(browser_cfg, "profile_is_running", lambda config: False)

    from scholar_search.bootstrap import _bridge_remediation

    result = _bridge_remediation(None)
    assert result["next_action"] == "browser_start"
    assert result["command"] == "wensu browser start"
    assert result["human_step_required"] is False
    assert result["profile_dir"] == r"E:\LiteratureEdgeProfile"


def test_remediation_says_reload_the_extension_when_the_browser_is_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scholar_search.core import browser as browser_cfg

    recorded = browser_cfg.BrowserConfig(
        browser="edge",
        executable="msedge.exe",
        profile_dir=r"E:\LiteratureEdgeProfile",
        extension_dir="ext",
    )
    monkeypatch.setattr(browser_cfg, "load", lambda: recorded)
    monkeypatch.setattr(browser_cfg, "profile_is_running", lambda config: True)

    from scholar_search.bootstrap import _bridge_remediation

    result = _bridge_remediation("2026-11-09 17:09:27")
    assert result["next_action"] == "reload_extension"
    assert result["command"] is None
    assert result["human_step_required"] is True


def test_bridge_error_is_not_retryable() -> None:
    """Retrying a dead bridge cannot work, so saying it can invites a loop.

    The report observed the retry directly: it waited 25 seconds, retried `status`,
    and the bridge was still down. Nothing the caller can do changes that.
    """

    from scholar_search.core.errors import ActionError
    from scholar_search.server import _payload

    payload = _payload(
        ActionError("no live native host", verb="goto", code="bridge.not_ready"),
        channel="cnki",
    )
    assert payload["retryable"] is False
    assert payload["requires"] == "external_state_change"
