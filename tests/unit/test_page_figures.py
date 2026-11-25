"""Figures via the debugger protocol (ADR 0026), pinned where a fake browser can pin it.

The whole point of the feature is that it reads what the browser **already downloaded**: attaching
after the page loaded would find nothing (`getResponseBody` only knows requests that happened while
attached), so the ordering, the filtering and the "no bytes in the reply" rule are the contract.
The chunked readback is verified against the real browser — see `figures_probe.js`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "tests" / "js" / "figures_probe.js"
_MANIFEST = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
BACKGROUND = ROOT / "extension" / _MANIFEST["background"]["service_worker"]


@pytest.fixture(scope="module")
def probe() -> dict[str, Any]:
    node = os.environ.get("WENSU_NODE") or shutil.which("node")
    if node is None or not BACKGROUND.is_file():
        pytest.skip("node not available: the extension probe cannot run here")
    completed = subprocess.run(
        [node, str(PROBE)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "WENSU_BACKGROUND_JS": str(BACKGROUND)},
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert "error" not in payload, payload
    return payload


def test_the_debugger_is_attached_before_the_navigation(probe: dict[str, Any]) -> None:
    """Attaching afterwards would find no response bodies at all — that is the whole constraint."""

    assert probe["attach_before_navigation"] is True, probe
    assert probe["network_enabled"] is True, probe
    assert probe["goto_ok"] is True, probe


def test_only_images_are_kept_and_oversized_ones_are_named(probe: dict[str, Any]) -> None:
    manifest = probe["manifest"]
    skipped = {item["url"]: item["reason"] for item in probe["skipped"]}

    assert [item["url"] for item in manifest] == ["https://mdpi-res.com/a.png"], manifest
    assert skipped.get("https://mdpi-res.com/huge.png") == "too_large", skipped
    assert "https://mdpi-res.com/a.css" not in skipped, "a stylesheet is not a figure"


def test_the_reply_carries_the_figure_bytes_inline(probe: dict[str, Any]) -> None:
    """The bytes ride along: reading them back by index failed three live runs in a row.

    A frame holds 2 MB and the page's own first chunk takes ~256 KB, so figures up to a budget come
    with the capture and `figures_inline` marks them. What does not fit stays readable by index.
    """

    assert probe["manifest"][0]["inline"] is True, probe["manifest"]
    # `reply_has_no_bytes` is the inverse: false here means the bytes really are in the reply.
    assert probe["reply_has_no_bytes"] is False, probe


def test_the_debugger_is_detached_when_the_capture_ends(probe: dict[str, Any]) -> None:
    """The browser's "being debugged" banner must not outlive the capture."""

    assert probe["detached_after_capture"] is True, probe
