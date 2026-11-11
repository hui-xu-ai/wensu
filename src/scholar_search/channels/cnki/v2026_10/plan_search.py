"""Build the CNKI search plan.

Two entry points exist on the site:

* one-box search (keyword) — the default;
* expert search (field expressions such as ``SU='IPMC' and KY='驱动器'``) —
  reached through ``AdvSearch?type=expert`` and a textarea.

Year filters are applied by the service to the returned page, without sending
additional browser actions.

Pagination is a client-side page turn (``#PageNext``), so page N costs N-1
extra clicks. The kernel's page-per-call limit keeps that bounded.
"""

from __future__ import annotations

import re
import time

from ....core.contracts import Action, Plan, SearchQuery
from ....core.errors import ChannelError
from .selectors import EXPERT, SEARCH, SEARCH_READY, SORT

_EXPRESSION = re.compile(
    # Any field code the site documents (SU, TKA, KY, TI, FT, AU, FI, RP, AF,
    # FU, AB, CO, RF, CLC, LY, DOI, CF) plus an escape hatch for unknown ones.
    r"(?:^|[\s(])[A-Z]{2,4}\s*(?:=|%)",
    re.IGNORECASE,
)

PAGE_TURN_MS = 1800
# Browser timers are aligned to one-second buckets whenever the CNKI window is
# not the active window, so a 2.5 s pause can answer at 3 s. A pause deadline
# therefore has to cover the pause itself plus a reply margin; the budget these
# margins cost is taken back from navigation and read timeouts, which run far
# above their observed latency.
SLEEP_REPLY_MARGIN_MS = 2_000
NAV_TIMEOUT_MS = 10_000
WAIT_TIMEOUT_MS = 10_000
INPUT_TIMEOUT_MS = 3_000
CLICK_TIMEOUT_MS = 2_200
# The submit button starts a navigation, which tears down the content script before
# it can reply. The extension answers after its own 2 s race plus the time the click
# itself takes (hover, press, release), which measured at over 2.2 s — the old budget
# sat right on that boundary and any jitter surfaced as
# `click failed: bridge.timeout` on a click that had in fact worked.
#
# 5 s is comfortably above the measured cost and still leaves the worst-case plan
# (50 rows, explicit sort, 3 pages) inside the kernel's 120 s ceiling: at 12 s it
# summed to 126.4 s and the budget test caught it. The other clicks keep the short
# budget because they do not navigate.
SUBMIT_CLICK_TIMEOUT_MS = 5_000
READ_TIMEOUT_MS = 4_000
FILTER_WAIT_MS = 6_000
WAIT_REPLY_MARGIN_MS = 2_000


def settle(ms: int) -> Action:
    """A fixed pause with a deadline wide enough for a throttled tab to answer."""

    return Action("sleep", {"ms": ms}, timeout_ms=ms + SLEEP_REPLY_MARGIN_MS)


def is_expression(text: str) -> bool:
    return bool(_EXPRESSION.search(text))


def _quote(text: str) -> str:
    """Escape a bare keyword for use inside `SU='...'`.

    The expert form treats a single quote as a delimiter, so a keyword containing one
    would otherwise end the string early and change the meaning of the expression.
    """

    return text.replace("'", "''").strip()


def effective_expression(text: str) -> str:
    """What will be typed, given what the caller asked for.

    Shared by the plan builder and by the channel's `effective_query` hook so the
    reported expression cannot drift from the one actually submitted.
    """

    return text if is_expression(text) else f"SU='{_quote(text)}'"


def _pagination(query: SearchQuery) -> tuple[Action, ...]:
    actions: list[Action] = []
    for index in range(max(0, query.page - 1)):
        if index == 0:
            # Let the freshly rendered grid finish binding before the first turn.
            actions.append(settle(800))
        actions.append(
            Action("click", {"selector": SEARCH["next_page"]}, timeout_ms=CLICK_TIMEOUT_MS)
        )
        actions.append(settle(PAGE_TURN_MS))
        actions.append(
            Action(
                "wait_for",
                {"selector": SEARCH_READY, "timeout_ms": FILTER_WAIT_MS},
                timeout_ms=FILTER_WAIT_MS + WAIT_REPLY_MARGIN_MS,
            )
        )
    return tuple(actions)


def _sort(query: SearchQuery) -> tuple[Action, ...]:
    selector = SORT.get(query.sort)
    # The result grid already opens on 发表时间 DESC, so explicit date sorting
    # needs no clicks (and clicking would toggle it to ascending).
    if selector is None or query.sort == "relevance":
        return ()
    return (
        # Reset to relevance first: the grid remembers the direction of the
        # previous sort, and a direct click would toggle it unpredictably.
        Action("click", {"selector": SORT["relevance"]}, timeout_ms=CLICK_TIMEOUT_MS),
        settle(900),
        Action("click", {"selector": selector}, timeout_ms=CLICK_TIMEOUT_MS),
        settle(1_500),
        Action(
            "wait_for",
            {"selector": SEARCH_READY, "timeout_ms": FILTER_WAIT_MS},
            timeout_ms=FILTER_WAIT_MS + WAIT_REPLY_MARGIN_MS,
        ),
    )


def _page_size(query: SearchQuery) -> tuple[Action, ...]:
    """Ask the result grid for 50 rows when the caller wants more than 20."""

    if query.limit <= 20:
        return ()
    return (
        Action("click", {"selector": SEARCH["page_size_open"]}, timeout_ms=CLICK_TIMEOUT_MS),
        settle(400),
        Action("click", {"selector": SEARCH["page_size_50"]}, timeout_ms=CLICK_TIMEOUT_MS),
        settle(2_500),
        Action(
            "wait_for",
            {"selector": SEARCH_READY, "timeout_ms": FILTER_WAIT_MS},
            timeout_ms=FILTER_WAIT_MS + WAIT_REPLY_MARGIN_MS,
        ),
    )


# URL query parameters this channel appends purely to defeat navigation caching.
#
# The kernel hashes a channel's plan to decide whether a cached page answers the
# current request, so anything that changes on every build but does not change the
# question must be declared. The declaration lives here, next to the code that
# generates the value, because the channel is the only thing that knows `t` is a
# timestamp and not a search term.
VOLATILE_URL_PARAMS = frozenset({"t"})


def build(query: SearchQuery) -> Plan:
    if query.source_types:
        raise ChannelError("source-type filters are not implemented for the cnki channel yet")

    # A unique parameter forces a real navigation, so the result grid always
    # starts from its default state (20 rows, page 1).
    #
    # It is a cache-buster, not part of the query — and the channel declares it as
    # such, because the channel is what generates it. The kernel hashes this plan to
    # decide whether a cached page answers the current request; a millisecond
    # timestamp in there made two identical searches hash differently, so CNKI never
    # hit its cache at all. See `VOLATILE_URL_PARAMS` below.
    nonce = int(time.time() * 1000)

    # One path only. The one-box search and the expert form both end up doing a topic
    # search, so keeping both made the caller pick between two ways to say the same
    # thing. A bare keyword is wrapped as `SU='...'`; anything already carrying a
    # field code is passed through untouched.
    expression = effective_expression(query.text)

    actions = (
        Action("goto", {"url": f"{EXPERT['page']}&t={nonce}"}, timeout_ms=NAV_TIMEOUT_MS),
        settle(2_500),
        Action(
            "wait_for",
            {"selector": EXPERT["input"], "timeout_ms": WAIT_TIMEOUT_MS},
            timeout_ms=WAIT_TIMEOUT_MS + WAIT_REPLY_MARGIN_MS,
        ),
        Action(
            "type",
            {"selector": EXPERT["input"], "text": expression},
            timeout_ms=INPUT_TIMEOUT_MS,
        ),
        Action(
            "click",
            {"selector": EXPERT["submit"]},
            timeout_ms=SUBMIT_CLICK_TIMEOUT_MS,
        ),
        Action(
            "wait_for",
            {"selector": SEARCH_READY, "timeout_ms": WAIT_TIMEOUT_MS},
            timeout_ms=WAIT_TIMEOUT_MS + WAIT_REPLY_MARGIN_MS,
        ),
        *_sort(query),
        *_page_size(query),
        *_pagination(query),
        Action("read_html", timeout_ms=READ_TIMEOUT_MS),
    )
    return Plan(channel="cnki", purpose="search", actions=actions)
