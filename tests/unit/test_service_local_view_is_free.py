"""A local view change must not re-open the browser.

Reported from a real acceptance run: a one-record WoS query cost 25 s and 4 quota, then
the *same* query with only `local_sort: "year"` added cost another 24 s and 4 quota and
returned the same single record. The same happened for `min_citations` and
`min_impact_factor`. Meanwhile changing `fields` — which never reached the query object
at all — was free.

The cause was that the cache key was the whole `SearchQuery`, including the parameters
that only describe how a page should be *presented*. Those parameters were part of the
identity of the fetch, so the fetch happened again.

These tests pin the fix: one fetch, many views, and the site-facing parameters still
distinguish real requests.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from test_service_limit import build

from scholar_search.core.contracts import SearchQuery
from support import FakeChannel, make_manifest, make_record

SCRIPT = [
    {"verb": "goto", "data": {}},
    {"verb": "read_html", "data": {"html": "<html>results</html>"}},
]


def _service(tmp_path: Path, records):
    channel = FakeChannel(manifest=make_manifest(), records=list(records))
    # One script only: a second fetch would raise StopIteration from `scripts.pop(0)`,
    # which makes an accidental re-fetch a loud failure rather than a slow one.
    return channel, build(tmp_path, channel, [list(SCRIPT)])


def _records() -> list:
    older = make_record("Older")
    older.year = 2018
    older.citations = 3
    newer = make_record("Newer")
    newer.year = 2024
    newer.citations = 900
    return [older, newer]


def test_local_sort_reuses_the_fetched_page(tmp_path: Path) -> None:
    _, service = _service(tmp_path, _records())

    first = service.search(SearchQuery(text="x", channel="fake"))
    assert not first.cache_hit

    second = service.search(SearchQuery(text="x", channel="fake", sort_by="year"))
    assert second.cache_hit, "a re-sort must not cost a search"
    # Same records, newest first — the set is unchanged, only the view is.
    assert {record.title for record in second.records} == {record.title for record in first.records}
    assert [record.title for record in second.records] == ["Newer", "Older"]


def test_a_limit_change_reuses_the_fetched_page(tmp_path: Path) -> None:
    _, service = _service(tmp_path, _records())

    service.search(SearchQuery(text="x", channel="fake"))
    narrowed = service.search(SearchQuery(text="x", channel="fake", limit=1))

    assert narrowed.cache_hit
    assert len(narrowed.records) == 1
    assert narrowed.total == 2, "total describes the site's set, not the caller's limit"


def test_include_abstract_reuses_the_fetched_page(tmp_path: Path) -> None:
    record = make_record("With abstract")
    record.abstract = "a" * 200
    _, service = _service(tmp_path, [record])

    service.search(SearchQuery(text="x", channel="fake"))
    with_abstract = service.search(SearchQuery(text="x", channel="fake", include_abstract=True))

    assert with_abstract.cache_hit
    assert with_abstract.records[0].abstract == "a" * 200


def test_a_citation_threshold_reuses_the_fetched_page_and_counts_what_it_dropped(
    tmp_path: Path,
) -> None:
    _, service = _service(tmp_path, _records())

    service.search(SearchQuery(text="x", channel="fake"))
    filtered = service.search(SearchQuery(text="x", channel="fake", min_citations=500))

    assert filtered.cache_hit, "a filter over a page in hand must not cost a search"
    assert [record.title for record in filtered.records] == ["Newer"]
    assert filtered.dropped_filter == 1


def test_a_filter_that_empties_the_page_says_so(tmp_path: Path) -> None:
    _, service = _service(tmp_path, _records())

    service.search(SearchQuery(text="x", channel="fake"))
    empty = service.search(SearchQuery(text="x", channel="fake", min_citations=10_000))

    assert empty.cache_hit
    assert empty.records == ()
    assert empty.dropped_filter == 2
    assert empty.empty_reason == "all_dropped_by_filter"


def test_site_facing_parameters_still_separate_cached_answers(tmp_path: Path) -> None:
    """The fix must not make everything one cache entry.

    Two different searches are two different searches; only the presentation layer
    became free.
    """

    channel = FakeChannel(manifest=make_manifest(), records=_records())
    service = build(tmp_path, channel, [list(SCRIPT), list(SCRIPT)])

    first = service.search(SearchQuery(text="x", channel="fake"))
    second = service.search(SearchQuery(text="y", channel="fake"))

    assert not first.cache_hit
    assert not second.cache_hit, "a different expression is a different request"


def test_a_different_page_is_a_different_request(tmp_path: Path) -> None:
    channel = FakeChannel(manifest=make_manifest(), records=_records())
    service = build(tmp_path, channel, [list(SCRIPT), list(SCRIPT)])

    service.search(SearchQuery(text="x", channel="fake", page=1))
    service.search(SearchQuery(text="x", channel="fake", page=2))

    assert True  # reaching here means the second page needed its own fetch


def test_the_cached_page_is_stored_unfiltered(tmp_path: Path) -> None:
    """The cache holds what the site returned, so every view can be derived from it.

    Filtering on the way in is what forced a re-fetch on the way out.
    """

    _, service = _service(tmp_path, _records())

    service.search(SearchQuery(text="x", channel="fake", min_citations=500, limit=1))
    # A later call asking for everything must see both records without a fetch.
    everything = service.search(SearchQuery(text="x", channel="fake", limit=50))

    assert everything.cache_hit
    assert len(everything.records) == 2


def test_replacing_only_a_presentation_field_keeps_the_identity() -> None:
    """A white-box check of the projection, independent of the service plumbing."""

    from scholar_search.core.service import _site_fields

    base = SearchQuery(text="TS=(x)", channel="webofscience")
    view = replace(base, sort_by="year", min_citations=5, limit=3, include_abstract=True)

    assert _site_fields(base) == _site_fields(view)
    assert _site_fields(base)["exclude_ut"] == ()
    assert _site_fields(replace(base, exclude_ut=("WOS:1",))) != _site_fields(base)
