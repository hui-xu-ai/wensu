"""A transaction must not switch browsers halfway through.

The fourth review (item 1) found the lock alone was not enough. `_run` built a new
adapter each time and re-discovered a host, so a search could submit to browser A and
read from browser B if A disappeared in between — and the page it read was cached as
if it answered A's query.

Pinning the adapter turns that into a bridge error. These tests cover the decision
that pinning makes, without needing two real browsers: `pin()` is where the endpoint
is chosen, so that is where the behaviour is asserted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scholar_search.adapters.bridge import BridgeAdapter
from scholar_search.core.errors import BridgeAmbiguous, BridgeError


def _endpoint(root: Path, name: str, *, port: int, profile: str | None, pid: int) -> Path:
    payload: dict[str, object] = {"port": port, "token": "t", "pid": pid}
    if profile is not None:
        payload["profile_dir"] = profile
    path = root / "hosts" / f"{name}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture()
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "host"
    (root / "hosts").mkdir(parents=True)
    monkeypatch.setattr("scholar_search.adapters.bridge.host_runtime_dir", lambda: root)
    return root


def _live(monkeypatch: pytest.MonkeyPatch, ports: set[int]) -> None:
    monkeypatch.setattr(
        BridgeAdapter,
        "_ping",
        lambda self, path: (
            (json.loads(path.read_text(encoding="utf-8"))["port"], "t")
            if json.loads(path.read_text(encoding="utf-8"))["port"] in ports
            else None
        ),
    )


def test_pin_keeps_one_endpoint_for_the_whole_transaction(
    runtime: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once pinned, later discovery must not wander to another host.

    This is the property the review showed was missing: `_candidates` is what
    `_connect` consults, and it returns the pinned endpoint alone.
    """

    _endpoint(runtime, "a", port=1, profile=r"E:\ProfileA", pid=11)
    _endpoint(runtime, "b", port=2, profile=r"E:\ProfileB", pid=22)
    monkeypatch.setenv("WENSU_PROFILE", r"E:\ProfileA")
    _live(monkeypatch, {1, 2})

    adapter = BridgeAdapter()
    assert adapter.pin() == (1, "t")
    assert [path.name for path in adapter._candidates()] == ["a.json"]


def test_a_requested_profile_that_is_not_running_fails_instead_of_substituting(
    runtime: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Disconnecting the chosen browser must not promote another one.

    Falling back here is how the wrong page gets read: the caller asked for A, A went
    away, and B happened to be open.
    """

    _endpoint(runtime, "a", port=1, profile=r"E:\ProfileA", pid=11)
    _endpoint(runtime, "b", port=2, profile=r"E:\ProfileB", pid=22)
    monkeypatch.setenv("WENSU_PROFILE", r"E:\ProfileA")
    _live(monkeypatch, {2})

    with pytest.raises(BridgeError) as caught:
        BridgeAdapter().pin()
    assert "ProfileA" in str(caught.value)
    assert "browser start" in str(caught.value)


def test_no_requested_profile_still_uses_any_live_host(
    runtime: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The single-browser case has no preference and must keep working."""

    _endpoint(runtime, "a", port=1, profile=None, pid=11)
    monkeypatch.delenv("WENSU_PROFILE", raising=False)
    monkeypatch.setattr("scholar_search.core.browser.load", lambda: None)
    _live(monkeypatch, {1})

    assert BridgeAdapter().pin() == (1, "t")


def test_no_live_host_at_all_is_a_bridge_error(
    runtime: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _endpoint(runtime, "a", port=1, profile=None, pid=11)
    monkeypatch.delenv("WENSU_PROFILE", raising=False)
    monkeypatch.setattr("scholar_search.core.browser.load", lambda: None)
    _live(monkeypatch, set())

    with pytest.raises(BridgeError):
        BridgeAdapter().pin()


def test_two_live_hosts_that_agree_on_a_profile_are_ambiguous(
    runtime: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _endpoint(runtime, "a", port=1, profile=r"E:\ProfileA", pid=11)
    _endpoint(runtime, "b", port=2, profile=r"E:\ProfileA", pid=22)
    monkeypatch.setenv("WENSU_PROFILE", r"E:\ProfileA")
    _live(monkeypatch, {1, 2})

    with pytest.raises(BridgeAmbiguous):
        BridgeAdapter().pin()
