"""Read the NDJSON result stream captured from the Web of Science result page.

The payload is not HTML: the page streams one JSON object per line and the
records arrive in blocks (observed 20 + 20 + 10, with ``link`` blocks in
between). Every accessor below is defensive — a missing branch yields ``None``
or an empty list, because the site omits fields per document type — but a
capture that yields *no* usable record is an error, never an empty page.
"""

from __future__ import annotations

import html as html_module
import json
import re
from datetime import datetime, timezone
from typing import Any

from ....core.contracts import Record, SearchPage, SearchQuery
from ....core.errors import ParseError

CHANNEL = "webofscience"
PRIMARY_API = "runQuerySearch"


# What the results page says when a query matches nothing. The site does not send
# its data stream in that case, so capture never fires and the plan times out
# instead of returning an empty page — which reads to a caller as "the tool broke",
# or worse, as "this topic has no papers". Recognising the wording is site
# knowledge, so it lives here rather than in the extension.
EMPTY_MARKERS = (
    "no records found",
    "found no records",
    "no results found",
    "0 results",
)

DETAIL_PREFIX = "https://webofscience.clarivate.cn/wos/woscc/full-record/"

# WoS document types are a small English vocabulary; anything outside it is
# kept as lower-cased text rather than dropped, so nothing is lost silently.
DOC_TYPES: dict[str, str] = {
    "article": "article",
    "review": "review",
    "proceedings paper": "proceedings",
    "book": "book",
    "book chapter": "book_chapter",
    "book in series": "book",
    "editorial material": "editorial",
    "letter": "letter",
    "meeting abstract": "meeting_abstract",
    "correction": "correction",
    "retraction": "retraction",
    "data paper": "data_paper",
    "early access": "early_access",
}

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def _as_text(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, int):
        return str(value)
    return None


def _title_of(node: Any) -> str | None:
    """Read ``{"en": [{"title": "..."}]}`` (or any locale) defensively."""

    if not isinstance(node, dict):
        return None
    for items in node.values():
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                value = _as_text(item.get("title"))
                if value:
                    return value
    return None


def _titles(record: dict[str, Any]) -> dict[str, Any]:
    node = record.get("titles")
    return node if isinstance(node, dict) else {}


def _pub(record: dict[str, Any]) -> dict[str, Any]:
    node = record.get("pub_info")
    return node if isinstance(node, dict) else {}


def _authors(record: dict[str, Any]) -> list[str]:
    names = record.get("names")
    author = ((names or {}).get("author") or {}).get("en") if isinstance(names, dict) else None
    if not isinstance(author, list):
        return []
    out: list[str] = []
    for entry in author:
        if not isinstance(entry, dict):
            continue  # the payload really does contain null holes
        value = _as_text(entry.get("wos_standard")) or _as_text(entry.get("display_name"))
        if value:
            out.append(value)
    return out


def _year(record: dict[str, Any]) -> int | None:
    raw = _as_text(_pub(record).get("pubyear"))
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _pages(record: dict[str, Any]) -> str | None:
    pub = _pub(record)
    begin = _as_text(pub.get("begin"))
    end = _as_text(pub.get("end"))
    if begin and end:
        return begin if begin == end else f"{begin}-{end}"
    if begin:
        return begin
    return _as_text(pub.get("page_count"))


def _abstract(record: dict[str, Any]) -> str | None:
    node = record.get("abstract")
    if not isinstance(node, dict):
        return None
    basic = node.get("basic")
    if not isinstance(basic, dict):
        return None
    for payload in basic.values():
        if not isinstance(payload, dict):
            continue
        raw = payload.get("abstract")
        if not isinstance(raw, str) or not raw.strip():
            continue
        text = _SPACE.sub(" ", html_module.unescape(_TAG.sub(" ", raw))).strip()
        return text or None
    return None


def _keywords(record: dict[str, Any]) -> list[str]:
    item = record.get("item")
    if not isinstance(item, dict):
        return []
    raw = item.get("keywords_plus")
    if not isinstance(raw, list):
        return []
    return [value.strip() for value in raw if isinstance(value, str) and value.strip()]


def _citations(record: dict[str, Any]) -> int | None:
    related = record.get("citation_related")
    if not isinstance(related, dict):
        return None
    counts = related.get("counts")
    if not isinstance(counts, dict):
        return None
    for key in ("ALLDB", "WOSCC"):
        value = counts.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _institution(record: dict[str, Any]) -> str | None:
    data = record.get("address_data")
    if not isinstance(data, dict):
        return None
    entries = data.get("address")
    if not isinstance(entries, list):
        return None
    preferred: str | None = None
    fallback: str | None = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        spec = entry.get("address_spec")
        if not isinstance(spec, dict):
            continue
        orgs = spec.get("organizations")
        if not isinstance(orgs, list):
            continue
        for org in orgs:
            if not isinstance(org, dict):
                continue
            name = _as_text(org.get("organization"))
            if name is None:
                continue
            if org.get("pref") == "Y" and preferred is None:
                preferred = name
            if fallback is None:
                fallback = name
    return preferred or fallback


def _doc_type(record: dict[str, Any]) -> str | None:
    types = record.get("doctypes")
    if not isinstance(types, list):
        return None
    raw = next((value for value in types if isinstance(value, str) and value.strip()), None)
    if raw is None:
        return None
    folded = raw.strip().casefold()
    return DOC_TYPES.get(folded, folded)


def _order(key: str) -> int:
    return int(key) if key.isdigit() else 0


def _impact_factors(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Map a record's ``jcrKey`` to its journal's impact factor.

    The metrics ride in their own ``jcr`` block, and it arrives *after* the
    records it describes — hence a separate pass rather than inline lookup.
    """

    factors: dict[str, float] = {}
    for row in rows:
        if row.get("key") != "jcr":
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        for key, entry in payload.items():
            if not isinstance(entry, dict):
                continue
            value = entry.get("ImpactFactor")
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                factors[str(key)] = float(value)
            elif isinstance(value, str):
                try:
                    factors[str(key)] = float(value)
                except ValueError:
                    continue
    return factors


def _record(payload: dict[str, Any], factors: dict[str, float] | None = None) -> Record | None:
    titles = _titles(payload)
    title = _title_of(titles.get("item"))
    if title is None:
        return None
    ut = _as_text(payload.get("ut")) or _as_text(payload.get("colluid"))
    jcr_key = _as_text(payload.get("jcrKey"))
    impact = factors.get(jcr_key) if (factors and jcr_key) else None
    return Record(
        channel=CHANNEL,
        title=title,
        authors=_authors(payload),
        institution=_institution(payload),
        source=_title_of(titles.get("source")),
        year=_year(payload),
        volume=_as_text(_pub(payload).get("vol")),
        issue=_as_text(_pub(payload).get("issue")),
        pages=_pages(payload),
        doi=_as_text(payload.get("doi")),
        abstract=_abstract(payload),
        keywords=_keywords(payload),
        citations=_citations(payload),
        downloads=None,
        url=f"{DETAIL_PREFIX}{ut}" if ut else None,
        fetched_at=datetime.now(timezone.utc),
        doc_type=_doc_type(payload),
        impact_factor=impact,
    )


def is_empty_page(text: str) -> bool:
    """True when the page itself says the query matched nothing.

    Called only after the data stream failed to appear, so this turns a timeout into
    an answer instead of an error.
    """

    lowered = " ".join(text.split()).lower()
    return any(marker in lowered for marker in EMPTY_MARKERS)


def parse(text: str, *, query: SearchQuery | None = None) -> SearchPage:
    """Turn the captured stream into a page of records."""

    if not isinstance(text, str) or not text.strip():
        raise ParseError("empty capture: the result stream was never written")

    rows: list[dict[str, Any]] = []
    malformed = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except ValueError:
            # A stream cut mid-line leaves one unparseable tail. Skipping it keeps
            # the records that did arrive; a capture with nothing usable still
            # fails the checks below.
            malformed += 1
            continue
        if not isinstance(row, dict):
            malformed += 1
            continue
        rows.append(row)

    factors = _impact_factors(rows)
    wanted = query.min_impact_factor if query is not None else None

    records: list[Record] = []
    total: int | None = None
    seen = 0

    for row in rows:
        key = row.get("key")
        payload = row.get("payload")
        if key == "searchInfo" and isinstance(payload, dict):
            value = payload.get("RecordsFound")
            if isinstance(value, int):
                total = value

    # The primary query's batch is the first screen. A lazy batch can arrive
    # before it, and ordering by arrival alone would then scramble the page, so
    # the primary batch is always put first. Within a batch, the payload keys
    # carry the true order.
    batches = sorted(
        (row for row in rows if row.get("key") == "records"),
        key=lambda row: 0 if row.get("api") == PRIMARY_API else 1,
    )

    for row in batches:
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        for index in sorted(payload, key=_order):
            raw = payload[index]
            if not isinstance(raw, dict):
                continue
            seen += 1
            record = _record(raw, factors)
            if record is None:
                continue
            if wanted is not None:
                factor = factors.get(str(raw.get("jcrKey") or ""))
                if factor is None or factor < wanted:
                    continue
            records.append(record)

    if seen == 0:
        # A query that matches nothing is a valid answer, not a broken capture:
        # the site still sends the searchInfo block, with a zero count.
        if total == 0:
            return SearchPage(
                records=(),
                total=0,
                page=None,
            )
        raise ParseError(
            "capture holds no records; the stream was not intercepted "
            f"({malformed} unparseable line(s) dropped)"
        )
    if not records and wanted is None:
        raise ParseError("capture holds records but none carried a usable title")

    # An impact-factor filter that matches nothing is a legitimate empty page, not
    # a parse failure: the capture was fine, the journals just did not qualify.
    return SearchPage(
        records=tuple(records),
        total=total,
        page=None,
    )
