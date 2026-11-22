"""The extension must keep one controlled tab, and must not touch anyone else's.

Three behaviours were pinned by reading `extension/background.js` and then reproduced with
`tests/js/tab_lifecycle_probe.js` (real script, fake `chrome`), 2026-11-22:

1. `workTab()` adopts **any** tab whose host is in scope — a tab the user opened himself —
   and remembers it as the work tab (`background.js:264-277`). Subsequent `goto`s then
   navigate the user's reading tab.
2. When no such tab exists it creates one at a hard-coded
   `https://www.sciencedirect.com/` (`background.js:278`), so reading a Wiley/Springer DOI
   sends an unrequested request to an unrelated publisher.
3. `read_page`'s referrer hop opens the publisher front page in a throwaway tab
   (`open:"new"`) and the next `goto` **closes** it (`close:"disposable"`,
   `background.js:436`). Closing it means the only tab of ours is gone at exactly the
   moment a search needs a dedicated, composable tab; the observed run ended with the
   article in a *new* tab id and a request to sciencedirect.com in between.

Desired contract (the third point is the user's requirement, 2026-11-22): the front-page
tab is **overwritten** with a blank/test page and kept, and that same tab carries the
article and any later search.

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
BACKGROUND = ROOT / "extension" / "background.js"

_FIX = "defect 3 (0.13.2): the referrer tab is closed instead of being blanked and reused"


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


def test_the_referrer_tab_is_kept_and_blanked(probe: dict[str, Any]) -> None:
    """The front page is overwritten, not closed: one tab in, one tab out.

    The blanking itself lives between the two navigations, so it cannot be observed from
    the tab list afterwards (the same tab is the article by then) — the extension reports
    the ids it blanked, and that is what this asserts.
    """

    referrer = probe["referrer"]

    assert referrer["home_tab_survived"] is True, (
        "the front-page tab is removed; a dedicated tab has to stay so a search can be "
        "driven in it afterwards"
    )
    assert referrer["home_tab_url_after"] != "https://advanced.onlinelibrary.wiley.com/", (
        "the front page itself must not be what the tab is left showing"
    )
    blanked = referrer["replies"][-1]["blanked"]
    assert referrer["home_tab_id"] in blanked, (referrer["replies"], referrer["home_tab_id"])


def test_the_article_lands_in_the_tab_we_already_had(probe: dict[str, Any]) -> None:
    """Reuse, not replace: one tab in, one tab out, same id."""

    referrer = probe["referrer"]

    assert probe["work_tab"]["id"] == referrer["home_tab_id"], probe


def test_no_unrelated_publisher_is_contacted(probe: dict[str, Any]) -> None:
    assert probe["referrer"]["unexpected_hosts"] == [], (
        "reading a Wiley DOI must not fetch sciencedirect.com"
    )
    assert probe["created_fallback_url"] in {"about:blank", ""}, probe


def test_a_foreign_tab_is_never_adopted(probe: dict[str, Any]) -> None:
    assert probe["adopted_foreign_tab"] is False, (
        "workTab must only ever drive a tab this extension created"
    )


# -- guards ------------------------------------------------------------------


def test_the_article_page_does_get_loaded_once(probe: dict[str, Any]) -> None:
    urls = [tab["url"] for tab in probe["referrer"]["tabs_after"]]

    assert any("10.1002/adma.75384" in url for url in urls), probe


def test_both_gotos_report_success(probe: dict[str, Any]) -> None:
    """The defects are silent: no error is returned while the tab is being mishandled."""

    assert probe["referrer"]["replies_ok"] is True, probe


def test_the_front_page_is_visited_before_the_article(probe: dict[str, Any]) -> None:
    """The referrer chain itself is wanted — a fix must not drop the hop."""

    requests = probe["referrer"]["requests"]

    assert requests[0].startswith("https://advanced.onlinelibrary.wiley.com/"), requests
    assert any("10.1002/adma.75384" in url for url in requests), requests
