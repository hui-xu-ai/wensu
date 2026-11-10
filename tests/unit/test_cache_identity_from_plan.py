"""What identifies a fetch must come from the plan, not from a hand-kept list.

Two rounds of the same class of bug, in opposite directions:

* **0.12.47** put the whole query in the cache key, so re-sorting a page in hand re-ran
  the search. Fixed by keeping a hand-picked list of "site-facing" fields.
* That list was then wrong for CNKI both ways at once: it dropped `limit`, which **does**
  change the plan above 20 (the site's page size switches), so a cached 20-record page
  answered a later `limit: 50` with 20 records and `cache_hit: true`; and it kept
  `year_from`/`year_to`, which CNKI applies locally only, so adding a year bought a 14 s
  re-search for a byte-identical site request.

Both are guesses about what a channel will do. `_site_signature` stops guessing and
hashes the plan. These tests use the **real** channel builders — a fake channel with a
fixed script cannot express the difference that caused the bug.
"""

from __future__ import annotations

import pytest

from scholar_search.channels.cnki.v2026_10 import get_channel as cnki_channel
from scholar_search.channels.webofscience.v2026_11 import get_channel as wos_channel
from scholar_search.core.contracts import SearchPage, SearchQuery
from scholar_search.core.service import _cache_can_answer, _site_signature


def _signature(channel, **kwargs):  # type: ignore[no-untyped-def]
    kwargs.setdefault("channel", str(channel.manifest.channel))
    return _site_signature(channel, SearchQuery(**kwargs))  # type: ignore[arg-type]


# -- CNKI: limit changes the plan ------------------------------------------


def test_cnki_limit_above_twenty_is_a_different_fetch() -> None:
    """The reported bug: `limit: 1` then `limit: 50` served 20 records from cache.

    CNKI's plan switches the site's page size when `limit > 20`, so these are two
    different requests. The old field list excluded `limit` for every channel.
    """

    channel = cnki_channel()
    small = _signature(channel, text="离子 柔性 驱动器", limit=1)
    large = _signature(channel, text="离子 柔性 驱动器", limit=50)
    assert small != large


def test_cnki_limits_on_the_same_side_of_twenty_are_one_fetch() -> None:
    """Below the threshold the plan never changes, so the page is reusable."""

    channel = cnki_channel()
    assert _signature(channel, text="x", limit=1) == _signature(channel, text="x", limit=20)


# -- CNKI: the year filter is local only -----------------------------------


def test_cnki_year_filter_does_not_identify_a_new_fetch() -> None:
    """The reported bug: adding a year cost a 14 s re-search for the same page.

    CNKI has no year field in its expression, so the site is asked exactly the same
    thing. Filtering afterwards is a view.
    """

    channel = cnki_channel()
    plain = _signature(channel, text="离子 柔性 驱动器", limit=1)
    with_year = _signature(channel, text="离子 柔性 驱动器", limit=1, year_from=2026, year_to=2026)
    assert plain == with_year


# -- WoS: the mirror image -------------------------------------------------


def test_wos_year_bound_is_part_of_the_expression() -> None:
    """On WoS the year becomes `PY=(…)`, so it genuinely is a different question."""

    channel = wos_channel()
    plain = _signature(channel, text="TS=(x)", year_from=2020, year_to=2020)
    other = _signature(channel, text="TS=(x)", year_from=2021, year_to=2021)
    assert plain != other


def test_wos_limit_does_not_change_the_plan() -> None:
    """The site always returns its page of 50; `limit` truncates afterwards."""

    channel = wos_channel()
    small = _signature(channel, text="TS=(x)", limit=1)
    large = _signature(channel, text="TS=(x)", limit=50)
    assert small == large


def test_wos_exclusions_change_the_expression() -> None:
    channel = wos_channel()
    plain = _signature(channel, text="TS=(x)", year_from=2026, year_to=2026)
    excluded = _signature(
        channel, text="TS=(x)", year_from=2026, year_to=2026, exclude_ut=("WOS:1",)
    )
    assert plain != excluded


# -- whitespace ------------------------------------------------------------


@pytest.mark.parametrize("channel_factory", [cnki_channel, wos_channel])
def test_surrounding_whitespace_does_not_buy_a_second_fetch(channel_factory) -> None:  # type: ignore[no-untyped-def]
    """An acceptance run paid for a control query that differed only by outer spaces."""

    channel = channel_factory()
    bare = _signature(channel, text="ionogel actuator")
    padded = _signature(channel, text="  ionogel actuator  ")
    assert bare == padded


# -- the capacity guard ----------------------------------------------------


def _page(records: int, total: int | None) -> SearchPage:
    from support import make_record

    return SearchPage(
        records=tuple(make_record(f"P{i}") for i in range(records)),
        total=total,
    )


def test_a_short_cached_page_does_not_answer_a_larger_request() -> None:
    """Belt to the signature's braces.

    A cache entry that holds 20 records while the site reports 128 cannot answer a
    request for 50 — reporting it as the answer is how a truncated list becomes a
    conclusion.
    """

    cached = _page(20, 128)
    assert not _cache_can_answer(cached, SearchQuery(text="x", channel="cnki", limit=50))


def test_a_short_cached_page_answers_a_request_it_can_cover() -> None:
    cached = _page(20, 128)
    assert _cache_can_answer(cached, SearchQuery(text="x", channel="cnki", limit=5))


def test_a_page_holding_the_whole_result_set_is_enough_at_any_limit() -> None:
    """19 records and `total: 19` means there is nothing more to fetch."""

    cached = _page(19, 19)
    assert _cache_can_answer(cached, SearchQuery(text="x", channel="cnki", limit=50))


def test_an_unknown_total_does_not_block_a_cache_hit() -> None:
    """A channel that cannot report a total must not lose its cache."""

    cached = _page(20, None)
    assert _cache_can_answer(cached, SearchQuery(text="x", channel="cnki", limit=50))
