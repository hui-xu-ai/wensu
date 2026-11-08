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
    SORT,
    SORT_OPEN,
    SUBMIT,
)

# Browser timers are aligned to one-second buckets in a background tab, so a
# pause deadline has to cover the pause itself plus a reply margin — the same
# rule the CNKI channel learned the hard way.
SLEEP_REPLY_MARGIN_MS = 2_000
WAIT_REPLY_MARGIN_MS = 2_000

NAV_TIMEOUT_MS = 10_000
WAIT_TIMEOUT_MS = 8_000
INPUT_TIMEOUT_MS = 3_500
CLICK_TIMEOUT_MS = 2_200
READ_TIMEOUT_MS = 8_000

# The stream answered in 1.6 s on the live site; six seconds is a wide margin
# that still leaves the worst-case plan (page 3 + explicit sort) under the
# kernel's 120 s ceiling.
CAPTURE_WAIT_MS = 6_000
# How long the previous capture may take to be invalidated once the click has
# fired. Short on purpose: the request starts within a few hundred ms.
TURN_MARKER_WAIT_MS = 2_000


def settle(ms: int) -> Action:
    """A pause with a deadline wide enough for a throttled tab to answer."""

    return Action("sleep", {"ms": ms}, timeout_ms=ms + SLEEP_REPLY_MARGIN_MS)


def jitter(low: int, high: int) -> int:
    return random.randint(low, high)


def capture_wait() -> tuple[Action, ...]:
    """Wait for the capture node to be invalidated, then to be written again.

    Two phases on purpose. ``capture.js`` drops ``data-ready`` the moment a
    tracked request starts and restores it when the stream ends, so "ready
    marker disappears, then reappears" is a race-free handshake — a single wait
    would match the *previous* run's marker the instant the click returns.
    """

    return (
        Action(
            "wait_for",
            {
                "selector": CAPTURE_READY,
                "timeout_ms": TURN_MARKER_WAIT_MS,
                "state": "hidden",
            },
            timeout_ms=TURN_MARKER_WAIT_MS + WAIT_REPLY_MARGIN_MS,
        ),
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
        settle(jitter(300, 650)),
        Action("click", {"selector": selector}, timeout_ms=CLICK_TIMEOUT_MS),
        settle(jitter(800, 1_300)),
        *capture_wait(),
    )


def pagination(page: int) -> tuple[Action, ...]:
    """One page turn per extra page, each re-triggering the result stream."""

    actions: list[Action] = []
    for _ in range(max(0, page - 1)):
        actions.append(Action("click", {"selector": NEXT_PAGE}, timeout_ms=CLICK_TIMEOUT_MS))
        actions.append(settle(jitter(1_100, 1_600)))
        actions.extend(capture_wait())
    return tuple(actions)


def build(query: SearchQuery, *, today: dt.date | None = None) -> Plan:
    if query.source_types:
        raise ChannelError(
            "source-type filters are not implemented for the webofscience channel yet; "
            "express them in the search expression instead (e.g. SO=(...) )"
        )

    text = expression.build(query, today=today)

    actions = (
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
        settle(jitter(400, 900)),
        Action("click", {"selector": SUBMIT}, timeout_ms=CLICK_TIMEOUT_MS),
        *capture_wait(),
        *sort_actions(query.sort),
        *pagination(query.page),
        Action(
            "read_text",
            {"selector": CAPTURE, "mode": "text"},
            timeout_ms=READ_TIMEOUT_MS,
        ),
    )
    return Plan(channel="webofscience", purpose="search", actions=actions)
