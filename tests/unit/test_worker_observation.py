"""The worker's observation mode (ADR 0031, P2) — the part only the extension can do.

Publisher pages have no content script and the extension has no `scripting` permission, so the only
zero-request readiness signal is the browser's own tab metadata. The probe runs the real worker
under a fake `chrome`, so a refusal or a wrong state here is the same code path a live tab takes.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "tests" / "js" / "readiness_probe.js"
MANIFEST = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
BACKGROUND = ROOT / "extension" / MANIFEST["background"]["service_worker"]


@pytest.fixture(scope="module")
def probe() -> dict[str, object]:
    node = os.environ.get("WENSU_NODE") or shutil.which("node")
    if node is None or not BACKGROUND.is_file():
        pytest.skip("node not available: the observation probe cannot run here")
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


def test_the_worker_advertises_the_observation_features(probe: dict[str, object]) -> None:
    hello = (probe["candidate"] or {}).get("hello") or {}  # type: ignore[union-attr]
    features = hello.get("features") or {}

    assert features.get("readiness_observe") == 1, hello
    assert features.get("capture_receipts") == 1, hello


def test_a_settled_tab_is_a_candidate(probe: dict[str, object]) -> None:
    reply = (probe["candidate"] or {}).get("reply") or {}  # type: ignore[union-attr]
    data = reply.get("data") or {}

    assert reply.get("ok") is True, reply
    assert data.get("mode") == "observe", data
    assert data.get("state") == "candidate", data
    assert data.get("page_state", {}).get("status") == "complete", data


def test_a_tab_that_never_settles_says_nothing_about_the_page(probe: dict[str, object]) -> None:
    """`observing` is an observation, not a verdict: the kernel captures anyway when time is up."""

    reply = (probe["late"] or {}).get("reply") or {}  # type: ignore[union-attr]
    data = reply.get("data") or {}

    assert data.get("state") == "observing", data
    assert data.get("budget_exhausted") is True, data
    assert "ok" not in data and "full_text" not in data, "an observation is not an answer"


def test_observing_never_produces_bytes(probe: dict[str, object]) -> None:
    """The whole point of a separate mode: `pageCapture` is not called once."""

    assert (probe["candidate"] or {}).get("captures") == 0, probe  # type: ignore[union-attr]
    assert (probe["late"] or {}).get("captures") == 0, probe  # type: ignore[union-attr]
