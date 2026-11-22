"""Sorting the result list must not wait for a capture node the export host never fills.

Real run (2026-11-22, `www.webofscience.com`): two searches with `site_sort="date"` both
died identically at

    wait_for failed: timeout (step 7/19, stage wait.capture)

Step 7 of 19 is `sort_actions()`'s `capture_wait()`: `plan_search.sort_actions` ends with a
wait on `#wensu-wos-capture[data-ready='1']`, which is correct on the Clarivate mirror
(the kernel reads the site's NDJSON stream there) and impossible on the global site, which
`plan_search.uses_export()` sends down the BibTeX export path instead — its payload never
passes through `window.fetch`, so `capture.js` never raises the marker.

Cost of the defect: 5 quota per attempt, and a hard "no results" answer for every
date-sorted WoS search on the global host.

The desired contract: a plan built for an export host must contain no `wait_for` on the
capture node — regardless of the requested sort order — while the mirror keeps its wait
(it is the only readiness signal there).
"""

from __future__ import annotations

import pytest

from scholar_search.channels.webofscience.v2026_11 import plan_export, plan_search, selectors
from scholar_search.core.contracts import Plan, SearchQuery

_FIX = (
    "defect 2 (0.13.2): sort_actions() appends capture_wait() unconditionally, so any "
    "site_sort on www.webofscience.com times out at step 7 before the export runs"
)


def _capture_waits(plan: Plan) -> list[str]:
    return [
        action.verb
        for action in plan.actions
        if action.verb == "wait_for" and "capture" in str((action.params or {}).get("selector", ""))
    ]


def _query(sort: str) -> SearchQuery:
    return SearchQuery(
        text="TS=(ionic AND (soft OR flexible) AND actuator*)",
        channel="webofscience",
        sort=sort,  # type: ignore[arg-type]
        year_from=2026,
    )


@pytest.mark.parametrize("sort", ["date", "citation"])
def test_the_export_path_never_waits_for_the_capture_node(sort: str) -> None:
    plan = plan_export.build_after_click(_query(sort))

    assert _capture_waits(plan) == [], (
        "the export host has no capture node; waiting for it burns 5 quota and returns no records"
    )


def test_the_default_order_already_works() -> None:
    """Why relevance searches succeeded all along: `sort_actions` returns () for it."""

    plan = plan_export.build_after_click(_query("relevance"))

    assert _capture_waits(plan) == []


def test_the_mirror_keeps_its_capture_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fix must not delete the wait everywhere: on the mirror it is the only signal.

    The builder picks its path from the configured host (`uses_export()`), and this
    checkout is configured for the global site, so the mirror path has to be forced here.
    """

    monkeypatch.setattr(plan_search, "uses_export", lambda: False)
    plan = plan_search.build_after_click(_query("date"))

    # Two waits on the mirror: the sort's own, then the one before reading the stream.
    assert _capture_waits(plan) == ["wait_for", "wait_for"]


def test_the_export_chain_is_intact() -> None:
    """Guards the four-click chain the selectors were discovered from."""

    plan = plan_export.build_after_click(_query("relevance"))
    clicked = [
        str((action.params or {}).get("selector"))
        for action in plan.actions
        if action.verb == "click"
    ]

    assert clicked == [
        selectors.EXPORT_TRIGGER,
        selectors.EXPORT_BIBTEX,
        selectors.EXPORT_CONTENT_COMBO,
        selectors.EXPORT_CONTENT_FULL,
        selectors.EXPORT_CONFIRM,
    ]
    confirm = plan.actions[-1]
    assert (confirm.params or {}).get("expect_download") is True
