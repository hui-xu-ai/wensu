"""Endpoint files outlive the host that wrote them, and every one costs a connect timeout.

Measured 2026-11-25: `host/hosts/` held fourteen `bridge-<pid>.json` files whose processes were
long gone, `pin()` pinged all of them, and each dead one took ~605 ms — **8.5 s in front of every
search**, before anything reached the browser. The pid in the file is the answer, so a dead pid's
file is dropped (and deleted) instead of being pinged.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from scholar_search.adapters.bridge import BridgeAdapter


def _endpoint(directory: Path, pid: int, *, age_s: float = 600.0) -> Path:
    path = directory / f"bridge-{pid}.json"
    path.write_text(json.dumps({"pid": pid, "port": 1, "token": "t"}), encoding="utf-8")
    old = time.time() - age_s
    os.utime(path, (old, old))
    return path


def _dead_pid() -> int:
    """A pid that is certainly not running: one past the platform's maximum."""

    return 999_999


def test_a_dead_hosts_endpoint_file_is_dropped_and_deleted(tmp_path: Path) -> None:
    dead = _endpoint(tmp_path, _dead_pid())
    live = _endpoint(tmp_path, os.getpid())

    kept = BridgeAdapter._drop_dead([dead, live])

    assert kept == [live], kept
    assert not dead.exists(), "the dead file must not be pinged again on the next call"


def test_a_live_pid_is_kept(tmp_path: Path) -> None:
    live = _endpoint(tmp_path, os.getpid())

    assert BridgeAdapter._drop_dead([live]) == [live]
    assert live.exists()


def test_a_fresh_file_is_kept_even_with_a_dead_pid(tmp_path: Path) -> None:
    """A host that is still starting writes the file before it can answer a ping."""

    fresh = _endpoint(tmp_path, _dead_pid(), age_s=0.0)

    assert BridgeAdapter._drop_dead([fresh]) == [fresh]
    assert fresh.exists()


def test_an_unreadable_file_is_kept(tmp_path: Path) -> None:
    """Dropping a malformed record could hide a live host behind it."""

    broken = tmp_path / "bridge-broken.json"
    broken.write_text("{not json", encoding="utf-8")

    assert BridgeAdapter._drop_dead([broken]) == [broken]
    assert broken.exists()
