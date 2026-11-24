"""`total == limit` must not be a question the caller has to answer with a second search.

Web of Science's page path reports the number it returned as `total`, so the two cases —
"the site has exactly this many" and "cut at the limit" — looked identical. One call spent
8 quota points and a whole search cycle resolving that doubt (2026-11-24 report, D4).
`returned` + `truncated` answer it without another visit.
"""

from __future__ import annotations

from scholar_search.core.contracts import Record, SearchPage, SearchQuery
from scholar_search.core.service import _present


def _record(index: int) -> Record:
    return Record(
        title=f"Paper {index}",
        authors=("A. Author",),
        source="Advanced Materials",
        year=2026,
        channel="webofscience",
        url=f"https://www.webofscience.com/wos/woscc/full-record/WOS:000{index}",
    )


def _page(count: int, total: int | None) -> SearchPage:
    return SearchPage(records=tuple(_record(i) for i in range(count)), total=total)


def test_a_page_that_filled_its_limit_says_there_may_be_more() -> None:
    query = SearchQuery(text="ionic actuator", channel="webofscience", limit=50)

    presented = _present(_page(50, 50), query)

    assert presented.returned == 50
    assert presented.truncated is True


def test_a_shorter_page_is_not_truncated() -> None:
    query = SearchQuery(text="ionic actuator", channel="webofscience", limit=50)

    presented = _present(_page(49, 49), query)

    assert presented.returned == 49
    assert presented.truncated is False


def test_a_range_request_is_never_called_truncated() -> None:
    """A range names its own size; getting exactly that many is the contract."""

    query = SearchQuery(
        text="ionic actuator", channel="webofscience", limit=50, records_from=1, records_to=50
    )

    presented = _present(_page(50, None), query)

    assert presented.returned == 50
    assert presented.truncated is False
