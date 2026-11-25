"""The service worker's file name has to change with every release, and this test is why.

Edge keeps serving the *cached* copy of a service worker whose file name did not change: the
repository had a newer `background.js` on disk, the browser was restarted, and the extension went
on running the old code — five fixes in a row were "tested" against a script nobody was executing
(measured 2026-11-25). Renaming the file (with the manifest pointing at the new name) made the new
code run immediately.

So the name carries the version — `background-<version>.js` — and this test fails when the two
disagree, which is exactly what a version bump without a rename looks like. The rename is
mechanical, and it is the only mechanism that survives the browser's cache.
"""

from __future__ import annotations

import json
from pathlib import Path

import scholar_search

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "extension" / "manifest.json"


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_the_service_worker_is_named_after_the_version() -> None:
    manifest = _manifest()

    expected = f"background-{manifest['version']}.js"
    assert manifest["background"]["service_worker"] == expected, manifest["background"]


def test_the_extension_and_the_package_agree_on_the_version() -> None:
    assert _manifest()["version"] == scholar_search.__version__


def test_the_named_worker_exists() -> None:
    worker = ROOT / "extension" / _manifest()["background"]["service_worker"]

    assert worker.is_file(), worker


def test_the_wheel_ships_the_worker_under_that_name() -> None:
    """The build maps the worker into the wheel by exact path, so the rename must reach it too.

    It is a hand-kept list — the same kind of list that once dropped `content/capture.js` — and
    the `assets` gate catches a stale entry at release time. This catches it at `pytest` time.
    """

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    worker = _manifest()["background"]["service_worker"]

    assert f'"extension/{worker}"' in pyproject, worker


def test_no_stale_worker_is_left_behind() -> None:
    """A leftover `background.js` would be loaded again the moment the manifest points at it."""

    stale = ROOT / "extension" / "background.js"

    assert not stale.is_file(), f"{stale} is still here; rename it with the manifest"
