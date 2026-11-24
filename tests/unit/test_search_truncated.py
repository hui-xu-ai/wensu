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


def test_a_year_filter_also_leaves_records_out_and_says_so() -> None:
    """A filter that drops records still means this answer is not everything.

    Measured live 2026-11-24: `limit: 3` against `total: 50` answered `truncated: false`,
    because the fetch had pulled all 50 and only the answer was trimmed — the caller's
    question ("is anything missing from what I got?") went unanswered.
    """

    query = SearchQuery(text="ionic actuator", channel="webofscience", limit=50, year_from=2026)
    page = SearchPage(
        records=(*(_record(i) for i in range(49)), _record(2025, year=2025)),
        total=50,
    )

    presented = _present(page, query)

    assert presented.returned == 49
    assert presented.truncated is True
    assert presented.dropped_year == 1, "the reason stays visible next to it"


def test_trimming_the_answer_to_the_limit_is_truncation() -> None:
    """The live case: the fetch had 50, the caller asked for 3."""

    query = SearchQuery(text="ionic actuator", channel="webofscience", limit=3)

    presented = _present(_page(50, 50), query)

    assert presented.returned == 3
    assert presented.truncated is True


def test_a_range_request_is_never_called_truncated() -> None:
    """A range names its own size; getting exactly that many is the contract."""

    query = SearchQuery(
        text="ionic actuator", channel="webofscience", limit=50, records_from=1, records_to=50
    )

    presented = _present(_page(50, None), query)

    assert presented.returned == 50
    assert presented.truncated is False
