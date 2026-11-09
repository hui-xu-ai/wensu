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


def test_an_unrelated_third_host_does_not_unlock_the_ambiguity(
    runtime: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression the fifth review found.

    Two hosts labelled A were refused — until a third host labelled B appeared. The
    check compared the set of distinct labels across the whole machine, so `{A, B}`
    looked like "they can be told apart" and one of the two A's was picked.

    Adding a browser this request never asked for cannot make two indistinguishable
    candidates distinguishable. Eligibility is filtered by the requested profile first,
    and it is that smaller set whose size decides.
    """

    _endpoint(runtime, "a", port=1, profile=r"E:\ProfileA", pid=11)
    _endpoint(runtime, "b", port=2, profile=r"E:\ProfileB", pid=22)
    _endpoint(runtime, "c", port=3, profile=r"E:\ProfileA", pid=33)
    monkeypatch.setenv("WENSU_PROFILE", r"E:\ProfileA")
    _live(monkeypatch, {1, 2, 3})

    with pytest.raises(BridgeAmbiguous):
        BridgeAdapter().pin()


def test_a_unique_match_is_not_blocked_by_another_profile(
    runtime: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The flip side: one A and one B is not ambiguous when A is what was asked for."""

    _endpoint(runtime, "a", port=1, profile=r"E:\ProfileA", pid=11)
    _endpoint(runtime, "b", port=2, profile=r"E:\ProfileB", pid=22)
    monkeypatch.setenv("WENSU_PROFILE", r"E:\ProfileA")
    _live(monkeypatch, {1, 2})

    assert BridgeAdapter().pin() == (1, "t")


def test_an_unlabelled_third_host_does_not_unlock_the_ambiguity(
    runtime: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The third failed attempt at this check, from the v2 matrix (A14).

    Two hosts labelled A, plus one written before the field existed. The eligible set
    was `{A, A, None}`, whose *distinct labels* are `{A, None}` — two values — so the
    "labels differ" test passed and one of the two A's was picked.

    Counting per label is the property that survives every third party: A is claimed
    twice, so the request cannot be routed, whatever else is running.
    """

    _endpoint(runtime, "a", port=1, profile=r"E:\ProfileA", pid=11)
    _endpoint(runtime, "b", port=2, profile=r"E:\ProfileA", pid=22)
    _endpoint(runtime, "legacy", port=3, profile=None, pid=33)
    monkeypatch.setenv("WENSU_PROFILE", r"E:\ProfileA")
    _live(monkeypatch, {1, 2, 3})

    with pytest.raises(BridgeAmbiguous):
        BridgeAdapter().pin()


def test_two_unlabelled_hosts_are_ambiguous_too(
    runtime: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No label is still a group: two members of it cannot be told apart either."""

    _endpoint(runtime, "a", port=1, profile=None, pid=11)
    _endpoint(runtime, "b", port=2, profile=None, pid=22)
    monkeypatch.delenv("WENSU_PROFILE", raising=False)
    monkeypatch.setattr("scholar_search.core.browser.load", lambda: None)
    _live(monkeypatch, {1, 2})

    with pytest.raises(BridgeAmbiguous):
        BridgeAdapter().pin()


def test_one_labelled_and_one_unlabelled_is_not_ambiguous(
    runtime: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A14 sibling: different groups, so the labelled one wins the request."""

    _endpoint(runtime, "a", port=1, profile=r"E:\ProfileA", pid=11)
    _endpoint(runtime, "legacy", port=2, profile=None, pid=22)
    monkeypatch.setenv("WENSU_PROFILE", r"E:\ProfileA")
    _live(monkeypatch, {1, 2})

    assert BridgeAdapter().pin() == (1, "t")
