"""Which host the adapter talks to when more than one browser is open.

A review of the first attempt at this (R02) found the mechanism could not do what the
name suggested: every host reads the same `browser.json`, so with two browsers open
**both endpoints report the same profile**. Ordering candidates by that label looks
like isolation while providing none.

These tests encode the rule that replaced it: a label is used to order only when the
labels actually differ, and identical labels with more than one host are refused
rather than guessed at.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scholar_search.adapters.bridge import BridgeAdapter
from scholar_search.core.errors import BridgeAmbiguous


def _write(path: Path, *, port: int, profile: str | None) -> None:
    payload: dict[str, object] = {"port": port, "token": "t", "pid": port}
    if profile is not None:
        payload["profile_dir"] = profile
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _ports(paths: list[Path]) -> list[int]:
    return [json.loads(path.read_text(encoding="utf-8"))["port"] for path in paths]


@pytest.fixture()
def registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "host"
    (root / "hosts").mkdir(parents=True)
    monkeypatch.setattr("scholar_search.adapters.bridge.host_runtime_dir", lambda: root)
    return root


def test_distinct_labels_put_the_configured_profile_first(
    registry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the hosts really do differ, honour the choice."""

    _write(registry / "hosts" / "bridge-1.json", port=1, profile=r"E:\ProfileA")
    _write(registry / "hosts" / "bridge-2.json", port=2, profile=r"E:\ProfileB")
    monkeypatch.setenv("WENSU_PROFILE", r"E:\ProfileB")

    assert _ports(BridgeAdapter()._candidates())[0] == 2


def test_identical_labels_are_refused_not_guessed(
    registry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The case the review demonstrated: two hosts, one label.

    This is what a two-browser setup looks like today, because the label comes from a
    shared file. Picking either endpoint would return a real page that may belong to
    another search, so the call must fail loudly instead.
    """

    _write(registry / "hosts" / "bridge-1.json", port=1, profile=r"E:\ProfileA")
    _write(registry / "hosts" / "bridge-2.json", port=2, profile=r"E:\ProfileA")
    monkeypatch.setenv("WENSU_PROFILE", r"E:\ProfileA")

    with pytest.raises(BridgeAmbiguous) as caught:
        BridgeAdapter()._candidates()
    message = str(caught.value)
    assert "WENSU_PROFILE" in message, "the message must name the way out"
    assert "same profile" in message


def test_one_host_is_never_ambiguous(registry: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A single host needs no disambiguation, whatever it labels itself."""

    _write(registry / "hosts" / "bridge-1.json", port=1, profile=r"E:\ProfileA")
    monkeypatch.setenv("WENSU_PROFILE", r"E:\ProfileB")

    assert _ports(BridgeAdapter()._candidates()) == [1]


def test_an_endpoint_without_a_label_stays_a_candidate(
    registry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An endpoint written before `profile_dir` existed must not vanish.

    Dropping it would make an upgrade look like a dead bridge, and the user would be
    told to start a browser that is already running.
    """

    _write(registry / "hosts" / "bridge-1.json", port=1, profile=None)
    _write(registry / "hosts" / "bridge-2.json", port=2, profile=r"E:\ProfileB")
    monkeypatch.setenv("WENSU_PROFILE", r"E:\ProfileB")

    assert _ports(BridgeAdapter()._candidates()) == [2, 1]


def test_no_configured_profile_keeps_every_candidate(
    registry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A setup that never recorded a profile still has to work."""

    _write(registry / "hosts" / "bridge-1.json", port=1, profile=r"E:\ProfileA")
    _write(registry / "hosts" / "bridge-2.json", port=2, profile=r"E:\ProfileB")
    monkeypatch.delenv("WENSU_PROFILE", raising=False)
    monkeypatch.setattr("scholar_search.core.browser.load", lambda: None)

    assert len(BridgeAdapter()._candidates()) == 2
