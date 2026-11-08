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
    value = node.get_text(" ", strip=True)
    return value or None


def _int(text: str | None) -> int | None:
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def _normalize_url(href: object) -> str | None:
    if not isinstance(href, str):
        return None
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return "https://kns.cnki.net" + href
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
    year = int(date_text[:4]) if date_text and date_text[:4].isdigit() else None

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

    return SearchPage(
        records=tuple(records),
        total=int(total_match.group(1).replace(",", "")) if total_match else None,
        # The page marker this page shows, or None when it carries none. Filling in
        # `query.page` here would claim a turn that may never have happened.
        page=int(page_match.group(1)) if page_match else None,
        page_count=int(page_match.group(2)) if page_match else None,
    )
