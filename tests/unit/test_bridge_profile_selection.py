"""Which host the adapter talks to when more than one browser is open.

The acceptance review (A02) found that a lock released between the submit and read
segments of a split search lets two requests read each other's results. That is one
half of the concurrency problem. The other half is at the other end: with two
browsers open there are two hosts, and the adapter used to take whichever answered
first, so a search typed for one profile could read the other profile's page.

These tests cover the selection rule. The segment-lock problem is documented as
unsupported rather than fixed: one browser is meant to serve one agent at a time.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scholar_search.adapters.bridge import BridgeAdapter


def _write(path: Path, *, port: int, profile: str | None) -> None:
    payload: dict[str, object] = {"port": port, "token": "t", "pid": port}
    if profile is not None:
        payload["profile_dir"] = profile
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture()
def registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "host"
    (root / "hosts").mkdir(parents=True)
    monkeypatch.setattr(
        "scholar_search.adapters.bridge.host_runtime_dir", lambda: root
    )
    return root


def test_the_matching_profile_is_tried_first(
    registry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two browsers open: the one this process is configured for must win.

    Getting this wrong is silent. The request succeeds, the page is real, and it
    belongs to a different search.
    """

    _write(registry / "hosts" / "bridge-1.json", port=1, profile=r"E:\ProfileA")
    _write(registry / "hosts" / "bridge-2.json", port=2, profile=r"E:\ProfileB")
    monkeypatch.setenv("WENSU_PROFILE", r"E:\ProfileB")

    paths = BridgeAdapter()._candidates()
    ports = [json.loads(path.read_text(encoding="utf-8"))["port"] for path in paths]
    assert ports[0] == 2, "the configured profile should be tried first"


def test_an_endpoint_without_a_profile_stays_a_fallback(
    registry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An endpoint written before `profile_dir` existed must not vanish.

    Dropping it would make an upgrade look like a dead bridge, and the user would be
    told to start a browser that is already running.
    """

    _write(registry / "hosts" / "bridge-1.json", port=1, profile=None)
    _write(registry / "hosts" / "bridge-2.json", port=2, profile=r"E:\ProfileB")
    monkeypatch.setenv("WENSU_PROFILE", r"E:\ProfileA")

    paths = BridgeAdapter()._candidates()
    ports = [json.loads(path.read_text(encoding="utf-8"))["port"] for path in paths]
    assert ports == [1], "no match, but the unlabelled endpoint is still a candidate"


def test_no_configured_profile_keeps_every_candidate(
    registry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A setup that never recorded a profile still has to work."""

    _write(registry / "hosts" / "bridge-1.json", port=1, profile=r"E:\ProfileA")
    _write(registry / "hosts" / "bridge-2.json", port=2, profile=r"E:\ProfileB")
    monkeypatch.delenv("WENSU_PROFILE", raising=False)
    monkeypatch.setattr(
        "scholar_search.core.browser.load", lambda: None
    )

    paths = BridgeAdapter()._candidates()
    assert len(paths) == 2
