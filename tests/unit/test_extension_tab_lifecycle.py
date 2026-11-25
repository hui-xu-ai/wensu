"""The extension must keep one tab of its own, and must not touch anyone else's.

Three behaviours were pinned by reading `extension/background-<version>.js` and then reproduced with
`tests/js/tab_lifecycle_probe.js` (real script, fake `chrome`), 2026-11-22:

1. `workTab()` adopted **any** tab whose host was in scope — a tab the user opened himself —
   and remembered it as the work tab, so subsequent `goto`s navigated the user's reading tab.
2. When no such tab existed it created one at a hard-coded `https://www.sciencedirect.com/`,
   so a navigation to another publisher sent an unrequested request to that host.
3. `goto` with `open: "new"` opened a tab and the next `goto` **closed** it, which left the
   extension with no tab of its own at the moment its next navigation needed one.

Desired contract: a tab opened for a single navigation is **blanked** (`about:blank`) and
kept, and that same tab carries the following navigation; a tab the user opened is never
adopted; a fresh tab starts blank.

The probe is skipped when no `node` is available; it is a property of the shipped script,
so it must run in CI wherever node exists (`WENSU_NODE` overrides the lookup).
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
PROBE = ROOT / "tests" / "js" / "tab_lifecycle_probe.js"
# The worker's file name carries the version (it is the browser's cache key), so it is read from
# the manifest instead of being repeated here.
_MANIFEST = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
BACKGROUND = ROOT / "extension" / _MANIFEST["background"]["service_worker"]

_FIX = "defect 3 (0.13.2): the transient tab was closed instead of blanked and reused"


def _node() -> str | None:
    return os.environ.get("WENSU_NODE") or shutil.which("node")


@pytest.fixture(scope="module")
def probe() -> dict[str, Any]:
    node = _node()
    if node is None or not BACKGROUND.is_file():
        pytest.skip("node not available: the extension probe cannot run here")
    env = {**os.environ, "WENSU_BACKGROUND_JS": str(BACKGROUND)}
    completed = subprocess.run(
        [node, str(PROBE)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert "error" not in payload, payload
    return payload


# -- the three defects -------------------------------------------------------


def test_the_transient_tab_is_kept_and_blanked(probe: dict[str, Any]) -> None:
    """The tab is overwritten, not closed: one tab in, one tab out.

    The blanking itself lives between the two navigations, so it cannot be observed from
    the tab list afterwards (the same tab is the article by then) — the extension reports
    the ids it blanked, and that is what this asserts.
    """

    transient = probe["transient"]

    assert transient["first_tab_survived"] is True, (
        "the transient tab is removed; a dedicated tab has to stay so a search can be "
        "driven in it afterwards"
    )
    assert transient["first_tab_url_after"] != "https://advanced.onlinelibrary.wiley.com/", (
        "the tab must not be left on the page it was opened at"
    )
    blanked = transient["replies"][-1]["blanked"]
    assert transient["first_tab_id"] in blanked, (transient["replies"], transient["first_tab_id"])


def test_the_article_lands_in_the_tab_we_already_had(probe: dict[str, Any]) -> None:
    """Reuse, not replace: one tab in, one tab out, same id."""

    transient = probe["transient"]

    assert probe["work_tab"]["id"] == transient["first_tab_id"], probe


def test_no_unrelated_publisher_is_contacted(probe: dict[str, Any]) -> None:
    assert probe["transient"]["unexpected_hosts"] == [], (
        "reading a Wiley DOI must not fetch sciencedirect.com"
    )
    assert probe["created_fallback_url"] in {"about:blank", ""}, probe


def test_a_foreign_tab_is_never_adopted(probe: dict[str, Any]) -> None:
    assert probe["adopted_foreign_tab"] is False, (
        "workTab must only ever drive a tab this extension created"
    )


# -- tabs must not accumulate (2026-11-24) -----------------------------------


def test_the_work_tab_is_remembered_across_an_extension_reload(probe: dict[str, Any]) -> None:
    """The id lives in persistent storage, so a reload reuses the tab instead of opening one.

    `storage.session` is emptied when the extension reloads; the tab it named survives. That
    mismatch opened one more `about:blank` per reload and nothing ever closed the old one.
    """

    reload = probe["reload"]

    assert reload["tab_id"] == 41, reload
    assert reload["tabs_after"] == reload["tabs_before"] == 1, reload
    assert reload["created"] == 0, reload


def test_the_work_tab_is_pinned(probe: dict[str, Any]) -> None:
    """Pinned keeps it compact, apart from the user's pages, and hard to close by accident."""

    assert probe["work_tab"]["pinned"] is True, probe["work_tab"]


def test_the_work_tab_gets_a_window_of_its_own(probe: dict[str, Any]) -> None:
    """The user's tab strip must not gain a slot every time the agent reads a page."""

    assert probe["work_tab"]["window_id"] != 1, probe["work_tab"]


def test_the_work_window_stays_minimized(probe: dict[str, Any]) -> None:
    """Owning a window is not a reason to put it in the user's way.

    Timers keep running at full speed while it is hidden — measured 2026-11-25, `sleep(150)`
    answered in 155 ms after the window had been minimized for 5m40s — so nothing in the pacing
    rules depends on it being visible.
    """

    assert probe["work_tab"]["window_state"] == "minimized", probe["work_tab"]


def test_the_boot_sweep_runs_once_per_browser_session(probe: dict[str, Any]) -> None:
    """A window the user restores by hand stays restored; the sweep does not fight them."""

    quiet = probe["quiet"]

    assert set(quiet["after_first_call"]) == {"minimized"}, quiet
    assert "normal" in quiet["after_second_call"], (
        "the second sweep minimized a window the user had just restored",
        quiet,
    )


def test_stale_tabs_of_ours_are_reused_and_the_spares_removed(probe: dict[str, Any]) -> None:
    """An id this build forgot is no reason to open a second tab."""

    orphans = probe["orphans"]

    assert orphans["tab_id"] == 52, orphans
    assert orphans["remaining"] == [52], orphans


# -- guards ------------------------------------------------------------------


def test_the_article_page_does_get_loaded_once(probe: dict[str, Any]) -> None:
    urls = [tab["url"] for tab in probe["transient"]["tabs_after"]]

    assert any("10.1002/adma.75384" in url for url in urls), probe


def test_both_gotos_report_success(probe: dict[str, Any]) -> None:
    """The defects are silent: no error is returned while the tab is being mishandled."""

    assert probe["transient"]["replies_ok"] is True, probe


def test_the_first_navigation_happens_before_the_second(probe: dict[str, Any]) -> None:
    """Two chained navigations are wanted — a fix must not drop the first one."""

    requests = probe["transient"]["requests"]

    assert requests[0].startswith("https://advanced.onlinelibrary.wiley.com/"), requests
    assert any("10.1002/adma.75384" in url for url in requests), requests
