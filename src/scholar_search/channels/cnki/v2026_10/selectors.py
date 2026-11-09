"""CSS selectors for the CNKI 2026.10 layout.

Verified against live pages on 2026-10-20. Change them only with a fixture.
"""

from __future__ import annotations

# Only the result-grid selectors are used now. The one-box search form
# (`input.search-input` / `input.search-btn` on `kns8s/search`) has been removed:
# every query goes through the expert form, so those two selectors had no caller
# left. Keeping them around implied a second entry point that no longer exists.
SEARCH = {
    "row": ".result-table-list tbody tr",
    "title_link": "td.name a.fz14",
    "authors": "td.author a.KnowledgeNetLink",
    "source": "td.source a",
    "date": "td.date",
    "citations": "td.quote",
    "downloads": "td.download",
    "data": "td.data",
    "checkbox": "input.cbItem",
    "total": ".pagerTitleCell",
    "page_marker": ".countPageMark",
    "next_page": "#PageNext",
    "page_size_open": "#perPageDiv .sort-default",
    "page_size_50": "#perPageDiv li[data-val='50']",
}

# Result-grid sort tabs (#orderList). Relevance is clicked first to reset the
# remembered direction, so a date/citation sort always lands on descending.
SORT = {
    "relevance": "#orderList li[data-sort='FFD']",
    "date": "#orderList li[data-sort='PT']",
    "citation": "#orderList li[data-sort='CF']",
}

EXPERT = {
    # `classid` selects the expert-search form itself. Without it the site can land
    # on a different tab of the advanced-search page, where `textarea.majorSearch`
    # does not exist and the plan dies waiting for it.
    "page": (
        "https://kns.cnki.net/kns8s/AdvSearch"
        "?type=expert&classid=WD0FTY92&rlang=CHINESE&language=CHS"
    ),
    "input": "textarea.majorSearch",
    "submit": "input.btn-search",
}

DETAIL = {
    "title": ".wx-tit h1",
    "authors": "h3.author",
    "institution": "h3.author",
    "abstract": "#ChDivSummary",
    "keywords": "p.keywords a",
    "doi": ".top-space .rowtit",
    "top_tip": ".doc-top",
}

DETAIL_READY = ".wx-tit h1, #ChDivSummary"
# The result grid appearing. Still very much in use: it is the plan's readiness
# signal after the expert form submits.
SEARCH_READY = ".result-table-list tbody tr"
