"""Build the Web of Science search plan.

One search costs exactly three network actions: ``goto``, ``type``, ``click``.
Everything the site would otherwise want clicks for — the year span, extra
conjunctions, re-running a previous search — is folded into the expression
itself (see :mod:`query`).

The payload is read from the capture node, not from the result DOM: the list
carries no abstracts, and fetching fifty detail pages to recover them would be
fifty requests instead of none.

Interaction discipline:

* every pause is a random range, never a fixed value — a constant cadence is
  the most obvious automation fingerprint there is;
* sorting is the only multi-click path left, and it is skipped entirely for the
  default ``relevance`` order;
* nothing here clicks a filter widget.
"""

from __future__ import annotations

import datetime as dt
import random

from ....core.contracts import Action, Plan, SearchQuery
from ....core.errors import ChannelError
from . import query as expression
from .selectors import (
    ADVANCED_SEARCH,
    CAPTURE,
    CAPTURE_READY,
    NEXT_PAGE,
    QUERY_INPUT,
    RESULT_READY,
    SORT,
    SORT_OPEN,
    SUBMIT,
)

# Browser timers are aligned to one-second buckets in a background tab, so a
# pause deadline has to cover the pause itself plus a reply margin — the same
# rule the CNKI channel learned the hard way.
SLEEP_REPLY_MARGIN_MS = 2_000
WAIT_REPLY_MARGIN_MS = 1_000

NAV_TIMEOUT_MS = 10_000
WAIT_TIMEOUT_MS = 8_000
INPUT_TIMEOUT_MS = 4_000
CLICK_TIMEOUT_MS = 2_200
READ_TIMEOUT_MS = 8_000

# How long to wait for the result list to render after the submit click.
#
# This is a **fallback deadline, not a decision**. The click itself gives up after
# 2.2 s because the extension races it against 2 s — that deadline exists so a
# click on a control that never replies cannot hang the plan. It must never be read
# as "the navigation finished, or did not happen": the site is a slow SPA and the
# navigation routinely outlives it. What actually decides is whether the result
# list exists, which is what this wait observes.
#
# 10 s: the audit trail shows about 9.5 s from the submit click to a rendered result
# list on a slow run, and two-page plans have to stay inside the kernel's 120 s budget.
RESULT_TIMEOUT_MS = 15_000

# Must exceed capture.js's standby budget (6 windows x 1.5 s = 9 s), otherwise a
# payload whose tail takes a while to parse is declared complete *after* this wait
# has already given up. Observed: 50 records captured, ready marker late, timeout.
#
# **13 s is the ceiling, not a preference.** `params.MAX_TIMEOUT_MS` caps one action at
# 15 s and the native host enforces the same bound, so adding the 1 s reply margin
# leaves 14 s — and a plan that declares 46 s is refused before it runs
# (`policy: timeout 46000ms is outside 0..15000`).
#
# That is the real reason a deliberately slow link cannot be served: the result page
# took minutes to render, and no single wait can span that. Waiting longer needs a
# kernel-level retry of the capture phase, not a bigger number here.
CAPTURE_WAIT_MS = 13_000

# A page turn reloads an application that is already warm, so it does not need the cold
# boot window. Giving it one anyway put a three-page plan at 260 s, past the kernel's
# 200 s budget; 12 s keeps three pages inside it.
CAPTURE_TURN_WAIT_MS = 12_000


def settle(ms: int) -> Action:
    """A pause with a deadline wide enough for a throttled tab to answer."""

    return Action("sleep", {"ms": ms}, timeout_ms=ms + SLEEP_REPLY_MARGIN_MS)


def jitter(low: int, high: int) -> int:
    return random.randint(low, high)


def capture_wait(*, timeout_ms: int | None = None) -> tuple[Action, ...]:
    """Wait for the captured payload to be complete.

    There is deliberately no "wait until ready disappears" phase: the first
    batch often lands during the pause after the click, so the marker is already
    set and that phase would do nothing but time out. The pause before this call
    is what gives a fresh request time to start.

    The window is per call because the two situations are not comparable. The first
    capture waits for a cold single-page application to boot, which on a slow link is
    the expensive part; a page turn reloads an application that is already warm. Giving
    both the same 45 s pushed a three-page plan to 260 s, past the kernel's budget, so
    the first capture gets the long window and page turns get a short one.
    """

    budget = CAPTURE_WAIT_MS if timeout_ms is None else timeout_ms
    return (
        Action(
            "wait_for",
            {"selector": CAPTURE_READY, "timeout_ms": budget},
            timeout_ms=budget + WAIT_REPLY_MARGIN_MS,
        ),
    )


def scroll_round() -> tuple[Action, ...]:
    """Walk down the list the way a reader would, then wait for the lazy batch.

    Two steps, not one teleport: the first scroll moves a random distance and the
    second finishes the page. A single `scrollTo(bottom)` produces identical
    positions on every run, which is exactly the kind of fingerprint automation
    detection looks for.

    No "wait until ready disappears" phase, unlike the older version: on the last
    round the list is already complete and no new request starts, so that phase
    would simply time out and kill the plan.
    """

    return (
        Action("scroll", {"by": jitter(700, 1_300)}, timeout_ms=CLICK_TIMEOUT_MS),
        settle(jitter(400, 900)),
        Action("scroll", {"to": "bottom"}, timeout_ms=CLICK_TIMEOUT_MS),
        settle(jitter(1_400, 2_000)),
        Action(
            "wait_for",
            {"selector": CAPTURE_READY, "timeout_ms": CAPTURE_WAIT_MS},
            timeout_ms=CAPTURE_WAIT_MS + WAIT_REPLY_MARGIN_MS,
        ),
    )


def sort_actions(order: str) -> tuple[Action, ...]:
    """Open the sort menu and pick a descending order, or nothing at all."""

    selector = SORT.get(order)
    if selector is None:
        return ()
    return (
        Action("click", {"selector": SORT_OPEN}, timeout_ms=CLICK_TIMEOUT_MS),
        settle(jitter(700, 1_300)),
        Action("click", {"selector": selector}, timeout_ms=CLICK_TIMEOUT_MS),
        settle(jitter(1_000, 1_600)),
        *capture_wait(),
    )


def reload_and_wait(
    *, expect_navigation: bool = True, capture_timeout_ms: int | None = None
) -> tuple[Action, ...]:
    """Wait for the result list, then reload it and wait for the payload.

    Measured on the live site: a reload answers with all 50 records through three
    ``runQueryGetRecordsStream`` batches and never issues ``runQuerySearch`` at all.
    Scrolling for the same records costs four more actions and two more requests, so
    the plan reloads instead of walking down the list.

    **The wait is not decoration.** `goto` with `reload` navigates to the tab's
    *current* URL. The previous version reloaded immediately after the click, using
    whatever URL was current at that instant — and because the click had given up
    after 2.2 s while the site was still navigating, that URL was still
    `advanced-search`. The reload then refreshed the search form: a page load that
    accomplishes nothing, followed by waiting for a capture stream the query had
    already sent elsewhere. The audit trail showed exactly this.

    `expect_navigation` is False after a page turn: the result list is already on
    screen and only its contents change, so waiting for it to "appear" would burn the
    deadline for nothing — and two of those would push a two-page plan past the
    kernel's 120 s budget.
    """

    wait: tuple[Action, ...] = (
        (
            Action(
                "wait_for",
                {"selector": RESULT_READY, "state": "visible"},
                timeout_ms=RESULT_TIMEOUT_MS,
            ),
        )
        if expect_navigation
        else ()
    )
    return (
        *wait,
        Action("goto", {"reload": True}, timeout_ms=NAV_TIMEOUT_MS),
        settle(jitter(1_500, 2_500)),
        *capture_wait(timeout_ms=capture_timeout_ms),
    )


def pagination(page: int) -> tuple[Action, ...]:
    """One page turn per extra page, each followed by the reload that fills it."""

    actions: list[Action] = []
    for _ in range(max(0, page - 1)):
        actions.append(Action("click", {"selector": NEXT_PAGE}, timeout_ms=CLICK_TIMEOUT_MS))
        actions.append(settle(jitter(1_500, 2_500)))
        actions.extend(
            reload_and_wait(expect_navigation=False, capture_timeout_ms=CAPTURE_TURN_WAIT_MS)
        )
    return tuple(actions)


def build_until_click(query: SearchQuery, *, today: dt.date | None = None) -> Plan:
    """Everything up to and including the click that submits the search.

    Split from the rest so the caller can look at where the tab ended up before
    deciding whether a reload makes sense. A query that matches nothing does not
    navigate: the tab stays on `/wos/woscc/advanced-search`, and reloading there
    throws away the only evidence the site gives. See `build_after_click`.
    """

    if query.source_types:
        raise ChannelError(
            "source-type filters are not implemented for the webofscience channel yet; "
            "express them in the search expression instead (e.g. SO=(...) )"
        )

    text = expression.build(query, today=today)

    return Plan(
        channel="webofscience",
        purpose="search",
        actions=(
            Action("goto", {"url": ADVANCED_SEARCH}, timeout_ms=NAV_TIMEOUT_MS),
            settle(jitter(1_000, 1_600)),
            Action(
                "wait_for",
                {"selector": QUERY_INPUT, "timeout_ms": WAIT_TIMEOUT_MS},
                timeout_ms=WAIT_TIMEOUT_MS + WAIT_REPLY_MARGIN_MS,
            ),
            # `clear` is the default in actions.js, but stating it keeps the intent
            # explicit: the editor remembers the previous expression across visits.
            Action(
                "type",
                {"selector": QUERY_INPUT, "text": text, "clear": True},
                timeout_ms=INPUT_TIMEOUT_MS,
            ),
            settle(jitter(1_200, 2_200)),
            # The button goes disabled while the site runs the query and recovers
            # when it is done. Waiting for that transition is the site's own "done"
            # signal: a fixed pause is either too short for a long expression or
            # wasted time for a short one.
            Action(
                "click",
                {"selector": SUBMIT, "wait_until": "enabled", "timeout_ms": 10_000},
                timeout_ms=CLICK_TIMEOUT_MS + 10_000,
            ),
            # Give the in-page route change a moment to land before the URL is read.
            settle(jitter(400, 900)),
        ),
    )


def _reject_too_many_pages(query: SearchQuery) -> None:
    """Refuse a page count the plan cannot fit inside the kernel's budget.

    One place, called by both builders. Having this check in two functions meant
    raising the limit in one of them left the other still refusing — which is exactly
    what happened when the ceiling moved from 120 s to 200 s.

    Three pages fit: measured marginal cost per turn is ~32 s, so 93 + 32 + 32 ≈ 157 s
    against a 200 s ceiling (ADR 0014). It stops at three because the kernel's
    `max_pages_per_call` is 3, and because a fourth turn would be a fourth
    re-submission of the same query — the traffic pattern the cadence rules exist to
    avoid.
    """

    if query.page > 3:
        raise ChannelError(
            "the webofscience channel supports at most 3 pages per call: each page "
            "re-submits the search and waits for the capture stream to refill (~32 s "
            "per turn). Narrow the query or change the year range instead of asking "
            "for a later page — there is no continuation interface, so repeating the "
            "same page number returns the same records."
        )


def build_after_click(query: SearchQuery) -> Plan:
    """Reload for the full result set, then read it.

    Safe only when the click actually navigated to `/summary/...`; on a search form
    a reload would discard the "no results" state the page is showing.
    """

    if query.page > 1 and query.sort != "relevance":
        raise ChannelError(
            "page turns and an explicit sort cannot share one call: sorting costs two "
            "clicks, each page costs two more actions, and together they exceed the "
            "kernel's 120 s plan budget"
        )
    _reject_too_many_pages(query)

    actions: list[Action] = [
        # The click navigates in-page. A reload navigates to the *current* URL, so
        # the new route has to be in place first. The kernel caps a single sleep at
        # 3 s, hence two pauses rather than one long one.
        *reload_and_wait(),
        *sort_actions(query.sort),
        *pagination(query.page),
        Action(
            "read_text",
            {"selector": CAPTURE, "mode": "text"},
            timeout_ms=READ_TIMEOUT_MS,
        ),
    ]
    return Plan(channel="webofscience", purpose="search", actions=tuple(actions))


def build(query: SearchQuery, *, today: dt.date | None = None) -> Plan:
    """The whole search in one plan. Kept for callers that cannot split it."""

    if query.page > 1 and query.sort != "relevance":
        raise ChannelError(
            "page turns and an explicit sort cannot share one call: sorting costs two "
            "clicks, each page costs two more actions, and together they exceed the "
            "kernel's 120 s plan budget"
        )
    # Kept in one place: `build_after_click` enforces the same cap, and two copies of
    # this check meant raising the limit in one spot left the other refusing.
    _reject_too_many_pages(query)

    head = build_until_click(query, today=today)
    tail = build_after_click(query)
    return Plan(channel="webofscience", purpose="search", actions=head.actions + tail.actions)
