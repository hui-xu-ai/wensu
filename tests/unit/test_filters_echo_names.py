"""`filters` must use the parameter names a caller can pass today.

`local_sort` is the documented name; `sort_by` survives only as an accepted alias.
The response echoed the alias, so a caller who set `local_sort` and then read the
`filters` block for it found nothing there.
"""

from __future__ import annotations

from scholar_search.core.contracts import SearchPage, SearchQuery
from scholar_search.server import _filters_payload


def test_a_local_sort_is_echoed_under_its_own_name() -> None:
    page = SearchPage(records=(), total=0)
    query = SearchQuery(text="x", channel="cnki", sort_by="citations")

    assert _filters_payload(page, query) == {"local_sort": "citations"}


def test_the_legacy_alias_lands_in_the_same_place() -> None:
    """`sort_by` is only an input alias; the response speaks one vocabulary."""

    page = SearchPage(records=(), total=0)
    query = SearchQuery(text="x", channel="cnki", sort_by="year")

    assert _filters_payload(page, query) == {"local_sort": "year"}
