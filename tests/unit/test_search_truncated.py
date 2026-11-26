"""`total == limit` must not be a question the caller has to answer with a second search.

Web of Science's page path reports the number it returned as `total`, so the two cases —
"the site has exactly this many" and "cut at the limit" — looked identical. One call spent
8 quota points and a whole search cycle resolving that doubt (2026-11-24 report, D4).
`returned` + `truncated` answer it without another visit.
"""

from __future__ import annotations

from scholar_search.core.contracts import Record, SearchPage, SearchQuery
from scholar_search.core.service import _present


def _record(index: int, *, year: int = 2026) -> Record:
    return Record(
        title=f"Paper {index}",
        authors=("A. Author",),
        source="Advanced Materials",
        year=year,
        channel="webofscience",
        url=f"https://www.webofscience.com/wos/woscc/full-record/WOS:000{index}",
    )


def _page(count: int, total: int | None) -> SearchPage:
    return SearchPage(records=tuple(_record(i) for i in range(count)), total=total)


def test_a_page_that_holds_less_than_the_site_matched_says_there_is_more() -> None:
    query = SearchQuery(text="ionic actuator", channel="webofscience", limit=50)

    presented = _present(_page(50, 6304), query)

    assert presented.returned == 50
    assert presented.truncated is True


def test_a_page_that_holds_everything_the_site_matched_is_whole() -> None:
    """`total: 50` with 50 records is a complete answer, not a truncated one.

    The report read that shape as ambiguous and paid for a second search (2026-11-24, D4);
    measured live, `total` is the site's own count, so the two cases are distinguishable.
    """

    query = SearchQuery(text="ionic actuator", channel="webofscience", limit=50)

    presented = _present(_page(50, 50), query)

    assert presented.returned == 50
    assert presented.truncated is False


def test_a_small_limit_against_a_big_result_set_is_truncated() -> None:
    query = SearchQuery(text="ionic actuator", channel="webofscience", limit=3)

    presented = _present(_page(3, 50), query)

    assert presented.returned == 3
    assert presented.truncated is True


def test_fetched_says_what_the_fetch_brought_back() -> None:
    """`total: 5000, fetched: 50` is one screen, not a site that has fifty (2026-11-26 P2-7)."""

    query = SearchQuery(text="ionic actuator", channel="webofscience", limit=3)

    presented = _present(_page(50, 6304), query)

    assert presented.fetched == 50
    assert presented.returned == 3
    assert presented.truncated is True


def test_the_year_filter_trims_the_answer_without_making_the_fetch_partial() -> None:
    """A complete fetch that a local filter trims is not "there is more at the site"."""

    page = SearchPage(
        records=tuple(
            _record(i, year=2026 if index % 2 else 2010) for index, i in enumerate(range(20))
        ),
        total=20,
    )
    query = SearchQuery(text="ionic actuator", channel="webofscience", limit=50, year_from=2020)

    presented = _present(page, query)

    assert presented.fetched == 20
    assert presented.returned == 10
    assert presented.truncated is False


def test_the_payload_reports_fetched_beside_total_and_returned() -> None:
    from scholar_search.server import _page_payload

    query = SearchQuery(text="ionic actuator", channel="webofscience", limit=3)
    payload = _page_payload(_present(_page(50, 6304), query), query)

    assert payload["total"] == 6304
    assert payload["fetched"] == 50
    assert payload["returned"] == 3


def test_the_payload_echoes_the_sort_that_was_actually_applied() -> None:
    """`relevance` is not an order any channel can impose: it leaves the site's own order.

    The site's default is often date-descending, which is why a "relevance" search came back
    as one year only (2026-11-26 report P2-8). Saying which of the two happened is the fix.
    """

    from scholar_search.server import _page_payload

    asked = SearchQuery(text="x", channel="webofscience")
    default = _page_payload(_page(3, 50), asked)
    assert default["sort_applied"] is False
    assert default["effective_sort"] == "site-default"

    dated = _page_payload(_page(3, 50), SearchQuery(text="x", channel="webofscience", sort="date"))
    assert dated["sort_applied"] is True
    assert dated["effective_sort"] == "date"


def test_a_year_filter_keeps_the_reason_visible_without_calling_the_fetch_partial() -> None:
    """The site matched 50, the fetch brought 50, the year filter left 49.

    Nothing the site matched is missing, so this is not truncation — the reason is
    `dropped_year`, and `returned` says the answer is smaller than `fetched`
    (2026-11-26 report P2-7: the old rule compared the answer to `total`, so any local
    filter sent the caller to re-fetch what they already had).
    """

    query = SearchQuery(text="ionic actuator", channel="webofscience", limit=50, year_from=2026)
    page = SearchPage(
        records=(*(_record(i) for i in range(49)), _record(2025, year=2025)),
        total=50,
    )

    presented = _present(page, query)

    assert presented.returned == 49
    assert presented.fetched == 50
    assert presented.truncated is False
    assert presented.dropped_year == 1, "the reason stays visible next to it"


def test_trimming_the_answer_to_the_limit_is_not_a_partial_fetch() -> None:
    """The fetch had all 50; the caller asked for 3. Nothing is left at the site."""

    query = SearchQuery(text="ionic actuator", channel="webofscience", limit=3)

    presented = _present(_page(50, 50), query)

    assert presented.returned == 3
    assert presented.fetched == 50
    assert presented.truncated is False


def test_a_range_request_is_never_called_truncated() -> None:
    """A range names its own size; getting exactly that many is the contract."""

    query = SearchQuery(
        text="ionic actuator", channel="webofscience", limit=50, records_from=1, records_to=50
    )

    presented = _present(_page(50, None), query)

    assert presented.returned == 50
    assert presented.truncated is False
