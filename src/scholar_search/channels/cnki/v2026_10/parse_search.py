"""Parse a CNKI result table into records."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from ....core.contracts import Record, SearchPage, SearchQuery
from ....core.errors import ParseError
from . import doc_types
from .selectors import SEARCH

_TOTAL = re.compile(r"([\d,]+)")
_PAGE = re.compile(r"(\d+)\s*/\s*(\d+)")


def _text(node: Tag | None) -> str | None:
    if node is None:
        return None
    # Join with no separator: the highlight markup CNKI injects around matched
    # words splits the title mid-token, and joining with a space turned "TiO2"
    # into "TiO 2" — the detail page, which has no highlight, disagreed.
    value = node.get_text("", strip=True)
    return value or None


def _year(text: str | None) -> int | None:
    """A four-digit prefix only counts when it is a plausible publication year."""

    if not text or not text[:4].isdigit():
        return None
    year = int(text[:4])
    return year if 1800 <= year <= 2200 else None


def _int(text: str | None) -> int | None:
    """Parse a count that may carry a decimal and a 万/千 multiplier.

    Collapsing every non-digit used to turn "1.2万" into 12 (should be 12000) and
    "12.5" into 125, so `--min-citations` and `--sort-by citations` worked on
    numbers that were off by orders of magnitude.
    """

    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*([万千]?)", text.replace(",", ""))
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2)
    if unit == "万":
        value *= 10_000
    elif unit == "千":
        value *= 1_000
    return round(value)


def _normalize_url(href: object) -> str | None:
    if not isinstance(href, str):
        return None
    value = href.strip()
    if value.startswith("//"):
        # Protocol-relative: the host is part of the value, so completing the
        # scheme gives https://kns.cnki.net/... — prepending the host instead
        # produced a double-host URL.
        return "https:" + value
    if value.startswith("https://"):
        return value
    if value.startswith("/"):
        return "https://kns.cnki.net" + value
    # http: and everything else is rejected: the policy layer would refuse an
    # http URL later anyway, so it must not enter a record as a usable link.
    return None


def _record(row: Tag) -> Record | None:
    link = row.select_one(SEARCH["title_link"])
    if link is None:
        return None
    title = _text(link)
    if not title:
        return None

    authors = [text for node in row.select(SEARCH["authors"]) if (text := _text(node))]
    date_text = _text(row.select_one(SEARCH["date"]))
    year = _year(date_text)

    return Record(
        channel="cnki",
        title=title,
        authors=authors,
        source=_text(row.select_one(SEARCH["source"])),
        year=year,
        citations=_int(_text(row.select_one(SEARCH["citations"]))),
        downloads=_int(_text(row.select_one(SEARCH["downloads"]))),
        doc_type=_doc_type(_text(row.select_one(SEARCH["data"]))),
        url=_normalize_url(link.get("href")),
    )


def _doc_type(raw: str | None) -> str | None:
    return doc_types.normalize(raw)


def _node_text(soup: BeautifulSoup, selector: str) -> str:
    node = soup.select_one(selector)
    return node.get_text() if node is not None else ""


def parse(html: str, query: SearchQuery) -> SearchPage:
    soup = BeautifulSoup(html, "lxml")

    table = soup.select_one(".result-table-list")
    total_text = _node_text(soup, SEARCH["total"])
    marker_text = _node_text(soup, SEARCH["page_marker"])
    if table is None and not total_text and not marker_text:
        raise ParseError("page has no result-grid structure")

    rows = soup.select(SEARCH["row"])
    records = [record for row in rows if (record := _record(row)) is not None]

    total_match = _TOTAL.search(total_text)
    page_match = _PAGE.search(marker_text)
    total_value = int(total_match.group(1).replace(",", "")) if total_match else None

    if not records and total_value != 0:
        # A grid with no parsable rows and no "0 results" marker means the page
        # structure changed. Returning an empty page here would present a broken
        # parse as "your query matched nothing".
        raise ParseError("result grid is present but no records could be parsed")

    return SearchPage(
        records=tuple(records),
        total=total_value,
        # The page marker this page shows, or None when it carries none. Filling in
        # `query.page` here would claim a turn that may never have happened.
        page=int(page_match.group(1)) if page_match else None,
        page_count=int(page_match.group(2)) if page_match else None,
    )
