"""Read the result list by asking the site for a BibTeX export.

Used on `www.webofscience.com`, where the result payload never passes through the page's
`fetch`/`XMLHttpRequest` and so cannot be captured. The mirror still uses the capture path;
nothing here runs there.

The head of the plan — open the advanced search form, type the expression, submit — is
identical either way, so this module only supplies the tail. That keeps one place that
knows how a search is started.

Every selector below was observed on the live site; none was guessed. The chain is four
clicks because each step reveals the next: the export menu does not exist until the toolbar
button is clicked, and the dialog does not exist until a format is chosen.
"""

from __future__ import annotations

import datetime as dt

from ....core.contracts import Action, Plan, SearchQuery
from . import selectors
from .plan_search import (
    CLICK_TIMEOUT_MS,
    RESULT_TIMEOUT_MS,
    WAIT_TIMEOUT_MS,
    jitter,
    settle,
    sort_actions,
)

# The confirm click both submits and waits for the file, so its budget is the download
# budget. `MAX_TIMEOUT_MS` caps one action at 15 s; the extension reserves what is left
# after the click itself returns.
EXPORT_TIMEOUT_MS = 15_000


def _range_actions(query: SearchQuery) -> tuple[Action, ...]:
    """Ask for a record range instead of "everything on this page" (up to 1000 records).

    The dialog defaults to `fromWholePage` (页面上的所有记录), i.e. the fifty records the
    list happens to be showing. Picking 记录: reveals two number inputs that stay
    `disabled` until the radio is chosen, so the order below is not cosmetic.

    This is what makes `exclude_ut` unnecessary for reading past the first page: the site
    will hand over records 1–1000 in one export, and 1001–2000 in the next.
    """

    span = query.records_span
    if span is None:
        return ()
    start, end = span
    return (
        Action("click", {"selector": selectors.EXPORT_RANGE_RADIO}, timeout_ms=CLICK_TIMEOUT_MS),
        Action(
            "wait_for",
            {"selector": selectors.EXPORT_RANGE_FROM, "state": "visible"},
            timeout_ms=WAIT_TIMEOUT_MS,
        ),
        settle(jitter(60, 120)),
        Action("type", {"selector": selectors.EXPORT_RANGE_FROM, "text": str(start)}),
        Action("type", {"selector": selectors.EXPORT_RANGE_TO, "text": str(end)}),
        settle(jitter(60, 120)),
    )


def build_after_click(query: SearchQuery, *, today: dt.date | None = None) -> Plan:
    """Everything from "the result list is on screen" to "a .bib file exists"."""

    _ = today
    actions: list[Action] = [
        Action(
            "wait_for",
            {"selector": selectors.RESULT_READY, "state": "visible"},
            timeout_ms=RESULT_TIMEOUT_MS,
        ),
        *sort_actions(query.sort, capture=False),
        Action("click", {"selector": selectors.EXPORT_TRIGGER}, timeout_ms=CLICK_TIMEOUT_MS),
        Action(
            "wait_for",
            {"selector": selectors.EXPORT_BIBTEX, "state": "visible"},
            timeout_ms=WAIT_TIMEOUT_MS,
        ),
        Action("click", {"selector": selectors.EXPORT_BIBTEX}, timeout_ms=CLICK_TIMEOUT_MS),
        Action(
            "wait_for",
            {"selector": selectors.EXPORT_CONTENT_COMBO, "state": "visible"},
            timeout_ms=WAIT_TIMEOUT_MS,
        ),
        settle(jitter(60, 120)),
        # The dialog opens on its least complete option, which carries neither DOI nor
        # abstract. Selecting 完整记录 is what makes the file usable at all.
        Action(
            "click",
            {"selector": selectors.EXPORT_CONTENT_COMBO},
            timeout_ms=CLICK_TIMEOUT_MS,
        ),
        Action(
            "wait_for",
            {"selector": selectors.EXPORT_CONTENT_FULL, "state": "visible"},
            timeout_ms=WAIT_TIMEOUT_MS,
        ),
        Action(
            "click",
            {"selector": selectors.EXPORT_CONTENT_FULL},
            timeout_ms=CLICK_TIMEOUT_MS,
        ),
        *_range_actions(query),
        Action(
            "wait_for",
            {"selector": selectors.EXPORT_CONFIRM, "state": "visible"},
            timeout_ms=WAIT_TIMEOUT_MS,
        ),
        settle(jitter(60, 120)),
        # `expect_download` is what turns the reply into a file path; without it the
        # extension reports only that the click happened. `timeout_ms` travels in the
        # params as well as on the action because the download wait is budgeted from the
        # params the extension can see — the action-level field never reaches it.
        Action(
            "click",
            {
                "selector": selectors.EXPORT_CONFIRM,
                "expect_download": True,
                "timeout_ms": EXPORT_TIMEOUT_MS,
            },
            timeout_ms=EXPORT_TIMEOUT_MS,
        ),
    ]
    # Every action here drives controls on a page that is already open: the dialog answers
    # in milliseconds, so this plan takes the UI slot instead of the network floor
    # (ADR 0023). Measured 2026-11-24: the whole dialog flow is ~1-3 s by hand, while 900 ms
    # per action made it ~14 s.
    return Plan(channel="webofscience", purpose="search", actions=tuple(actions), pacing="ui")
