"""A gate page has to be recognized while it is still loading, not 12 seconds later.

Acceptance run 2026-11-25 (case D2): `page_read(doi: "10.1002/adma.75384")` hit a Wiley
verification interstitial. The `goto` action ran its whole budget — `waitNavigated` returned in
about a second, then `waitComplete` polled for **12.12 s** for a load event an interstitial never
fires (the extension's own comment says so) — and only then did the kernel read the title and
answer `blocked`. Nothing was captured, nothing was written: those 12 seconds bought the sentence
"please verify by hand" and nothing else.

The fix is a **timing** change, not a classification one. The `goto` action now carries the
kernel's own gate markers (`halt_url_markers`, `halt_titles`) and the extension stops waiting as
soon as one of them has persisted for a grace period; the kernel keeps deciding blocked /
not-blocked with the stricter rule (`RiskGuard`, `challenge_in_title`). What this file pins down:

* the markers travel from the kernel's single source (`core/risk.py`) — the extension never grows
  a second copy of the list (ADR 0025);
* the lists as they are today fit the parameter schema, so adding a marker cannot silently make
  every `page_read` navigation invalid;
* a navigation without markers is untouched.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scholar_search.core.params import validate_params
from scholar_search.core.risk import RISK_TITLE_MARKERS, VERIFY_URL_MARKERS
from scholar_search.core.service import ScholarService

DOI_URL = "https://onlinelibrary.wiley.com/doi/10.1002/adma.75384"
ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "tests" / "js" / "gate_watch_probe.js"
# The worker's file name carries the version (it is the browser's cache key), so it is read from
# the manifest instead of being repeated here.
_MANIFEST = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
BACKGROUND = ROOT / "extension" / _MANIFEST["background"]["service_worker"]


def test_the_goto_action_carries_the_kernels_own_gate_markers() -> None:
    params = ScholarService._page_goto_params(DOI_URL)

    assert params["url"] == DOI_URL
    # The same values the risk rules use, passed through rather than copied.
    assert tuple(params["halt_url_markers"]) == tuple(VERIFY_URL_MARKERS)
    assert tuple(params["halt_titles"]) == tuple(RISK_TITLE_MARKERS)


def test_the_real_marker_lists_fit_the_parameter_schema() -> None:
    """A marker added to `risk.py` must not turn every navigation into `policy.params`."""

    assert validate_params("goto", ScholarService._page_goto_params(DOI_URL)) is None


def test_a_navigation_without_markers_is_unchanged() -> None:
    assert validate_params("goto", {"url": DOI_URL}) is None


def test_the_new_parameters_are_accepted() -> None:
    assert validate_params("goto", {"url": DOI_URL, "halt_titles": ["请稍候"]}) is None
    assert validate_params("goto", {"url": DOI_URL, "halt_url_markers": ["/verify/"]}) is None
    # An empty list means "watch nothing", which is the behaviour before this parameter existed.
    assert validate_params("goto", {"url": DOI_URL, "halt_titles": []}) is None


@pytest.mark.parametrize(
    "markers",
    [
        "请稍候",  # a bare string, not a list
        [1],  # not a string
        [""],  # an empty marker would match every title
        ["   "],
        ["x" * 81],  # longer than any gate title we would ever write
        [None],
        [f"m{index}" for index in range(33)],  # more markers than the schema allows
    ],
)
def test_a_malformed_marker_list_is_refused(markers: object) -> None:
    assert validate_params("goto", {"url": DOI_URL, "halt_titles": markers}) == "policy.params"
    assert validate_params("goto", {"url": DOI_URL, "halt_url_markers": markers}) == "policy.params"


# -- the extension side, with a fake browser ---------------------------------


@pytest.fixture(scope="module")
def probe() -> dict[str, Any]:
    """The real `background.js` under a fake `chrome` (tests/js/gate_watch_probe.js)."""

    node = os.environ.get("WENSU_NODE") or shutil.which("node")
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


def test_navigating_to_the_page_already_open_is_not_a_stall(probe: dict[str, Any]) -> None:
    """Search re-opens the advanced-search page, `page_read` re-reads the same article.

    The URL is unchanged in both, which the first version of the stall check reported as
    `navigation.stalled`.
    """

    there = probe["already_there"]

    assert there["ok"] is True, there


def test_a_tab_that_never_moved_is_navigated_again(probe: dict[str, Any]) -> None:
    """An accepted-but-ignored update must not be reported as a domain violation.

    Live, right after a browser start: `policy.domain` in 330 ms with `url: "about:blank"`. The
    target was in scope, so this was never a policy question — the tab had simply not navigated.
    """

    blank = probe["stays_blank"]

    assert blank["ok"] is True, blank
    assert "wiley.com" in (blank["url"] or ""), blank


def test_a_rejected_update_is_retried_once(probe: dict[str, Any]) -> None:
    """Edge rejects an update on a work tab the previous run left behind.

    Measured 2026-11-25, right after a browser start: the first `goto` of a search answered
    `policy.domain` (the tab never moved off `about:blank`) and the immediate retry answered
    `Navigation rejected.` — the tab is ours and the target is in scope, so one retry is right.
    """

    rejected = probe["rejected"]

    assert rejected["ok"] is True, rejected
    assert "wiley.com" in (rejected["url"] or ""), rejected


def test_a_navigation_that_commits_late_is_not_reported_as_a_domain_violation(
    probe: dict[str, Any],
) -> None:
    """The wait must not be abandoned just because there is no gate to watch for.

    The first version of the gate watch raced the real navigation wait against an
    already-resolved "no gate" promise. The race won instantly, both waits were dropped, and
    the read-back found the previous page — `policy.domain` for a navigation that was simply
    still in flight (measured 2026-11-25: the first search after `wensu browser start` failed
    once, then worked).
    """

    late = probe["late_commit"]

    assert late["ok"] is True, late
    assert "wiley.com" in (late["url"] or ""), late
    assert late["halted"] is False, late


def test_a_wall_stops_the_wait_instead_of_using_the_whole_budget(probe: dict[str, Any]) -> None:
    """12.12 s was the old cost (2026-11-25). The grace period is 1.5 s; nothing else may run."""

    wall = probe["wall"]

    assert wall["halted"] is True, wall
    assert wall["elapsed_ms"] < 4_000, wall
    assert "请稍候" in (wall["title"] or ""), wall


def test_a_challenge_that_solves_itself_is_not_reported_as_a_wall(
    probe: dict[str, Any],
) -> None:
    """The grace period exists for exactly this: the marker is up, then the article is."""

    solved = probe["solved"]

    assert solved["halted"] is False, solved
    assert "Ionograsper" in (solved["title"] or ""), solved


def test_a_navigation_without_markers_is_untouched(probe: dict[str, Any]) -> None:
    plain = probe["plain"]

    assert plain["ok"] is True, plain
    assert plain["halted"] is False, plain
    assert "Ionograsper" in (plain["title"] or ""), plain
