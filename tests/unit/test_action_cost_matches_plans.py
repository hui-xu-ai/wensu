"""The quoted price of an action must equal what its plan bills.

`status.action_cost` is what a caller budgets a run with, and it is a hand-kept
constant. The 0.12.56 acceptance run found it quoting 4 for a Web of Science search
while the plan billed 8: the BibTeX export path added clicks, and nothing failed
because nothing compared the two. These tests derive the price from the plan itself,
so the constant cannot drift in silence again.

One quota unit = one action whose verb is in `NETWORK_VERBS` (`core/planner.py`
reserves a slot per such action, and `policy.wait_turn` increments `used`).
"""

from __future__ import annotations

import pytest

from scholar_search.bootstrap import ACTION_COST
from scholar_search.core.contracts import SearchQuery
from scholar_search.core.errors import ChannelError
from scholar_search.core.policy import NETWORK_VERBS
from scholar_search.core.registry import ChannelRegistry

# One representative query per channel. The price is a property of the plan, not of
# the query, for any query that takes the channel's normal path.
SAMPLE = {
    "cnki": "柔性 驱动器",
    "webofscience": "TS=(ionic AND actuator)",
}


def billed(channel: str, **overrides: object) -> int:
    """How many quota units this plan reserves: one per network verb."""

    impl = ChannelRegistry().load(channel)
    query = SearchQuery(text=SAMPLE[channel], channel=channel, **overrides)  # type: ignore[arg-type]
    return sum(1 for action in impl.plan_search(query).actions if action.verb in NETWORK_VERBS)


def test_a_search_is_quoted_at_what_its_plan_bills() -> None:
    for channel in SAMPLE:
        quoted = ACTION_COST["search"][channel]  # type: ignore[index]
        assert quoted == billed(channel), channel


def test_a_page_turn_is_quoted_only_where_one_is_possible() -> None:
    assert ACTION_COST["page_turn"]["cnki"] == billed("cnki", page=2)  # type: ignore[index]
    # Web of Science has no page turn: its export path reads one page per export and
    # points at `exclude_ut` instead, so quoting a number there would price something
    # it refuses to do.
    with pytest.raises(ChannelError):
        billed("webofscience", page=2)
    assert ACTION_COST["page_turn"]["webofscience"] is None  # type: ignore[index]


def test_a_site_sort_is_quoted_at_what_its_plan_bills() -> None:
    for channel in SAMPLE:
        quoted = ACTION_COST["site_sort"][channel]  # type: ignore[index]
        assert quoted == billed(channel, sort="date"), channel


def test_the_free_views_stay_free() -> None:
    assert ACTION_COST["local_sort"] == 0
    assert ACTION_COST["detail_cached"] == 0
