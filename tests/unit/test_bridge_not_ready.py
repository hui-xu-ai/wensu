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


def test_bridge_remediation_forbids_touching_the_browser() -> None:
    """The one instruction that keeps an agent from improvising.

    A caller was left to interpret `bridge_ready: false` on its own; it read the host
    log, concluded Edge was "stuck in the background", killed every `msedge` process
    and restarted the browser. The extension lived in one profile, so the restart
    brought up a different one and the bridge never came back.
    """

    from scholar_search.core.service import ScholarService

    text = ScholarService.BRIDGE_REMEDIATION.casefold()
    assert "do not" in text
    for forbidden in ("start", "stop", "kill", "reload"):
        assert forbidden in text, f"the remediation should forbid {forbidden!r}"
    assert "profile" in text, "the reason matters: the extension lives in one profile"
