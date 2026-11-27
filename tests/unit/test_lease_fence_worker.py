"""The worker's lease fence, driven for real (plan P2's third enforcement point).

Two earlier attempts at this probe failed: a two-pipe handshake drove the host instead of the
worker, and a VM with port listeners received nothing. The pattern that works is the one
`gate_watch_probe.js` uses — fake `chrome`, `onHostMessage(message, channel)` directly, and an
explicit `process.exit(0)` at the end so the worker's own listeners do not keep node alive.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "tests" / "js" / "lease_fence_probe.js"
MANIFEST = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
BACKGROUND = ROOT / "extension" / MANIFEST["background"]["service_worker"]


@pytest.fixture(scope="module")
def probe() -> dict[str, object]:
    node = os.environ.get("WENSU_NODE") or shutil.which("node")
    if node is None or not BACKGROUND.is_file():
        pytest.skip("node not available: the fence probe cannot run here")
    completed = subprocess.run(
        [node, str(PROBE)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        env={**os.environ, "WENSU_BACKGROUND_JS": str(BACKGROUND)},
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert "error" not in payload, payload
    return payload


def test_the_worker_acknowledges_the_lease_it_now_holds(probe: dict[str, object]) -> None:
    ack = probe["sync_ack"] or {}
    hello = probe["hello"] or {}

    assert ack.get("type") == "lease_ack", ack
    assert ack.get("ok") is True, ack
    assert ack.get("fence") == 5, ack
    assert ack.get("lease_id") == "L1", ack
    assert ack.get("worker_epoch") == hello.get("worker_epoch"), ack  # type: ignore[union-attr]


def test_a_superseded_lease_cannot_touch_the_tab(probe: dict[str, object]) -> None:
    """The point of the fence: a call that was already superseded must not act."""

    stale = probe["stale"] or {}

    assert stale.get("ok") is False, stale
    assert stale.get("error") == "policy.fence", stale
    assert (stale.get("data") or {}).get("fence") == 5, stale  # the worker says what it holds


def test_the_fence_is_not_a_wall_for_current_or_legacy_callers(probe: dict[str, object]) -> None:
    legacy = probe["legacy"] or {}
    fresh = probe["fresh"] or {}

    assert legacy.get("ok") is True, "an older kernel sends no envelope and must keep working"
    assert fresh.get("ok") is True, fresh
    # The envelope comes back with the reply, so a caller can prove which call it answers.
    assert (fresh.get("context") or {}).get("lease_id") == "L1", fresh
