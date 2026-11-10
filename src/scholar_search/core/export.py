"""RIS and EndNote text rendering.

Only bibliographic text is produced. Nothing is written to disk and no
download endpoint is ever contacted. Every field is validated and cleaned, so a
crafted record cannot inject extra tags or records.

The document type comes from the source page. A missing or unknown type is
rendered as generic and never silently relabelled as a journal article.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from .contracts import Record, unify_doc_type

_STRING_FIELDS = (
    "channel",
    "title",
    "institution",
    "source",
    "volume",
    "issue",
    "pages",
    "doi",
    "abstract",
    "url",
)
_LIST_FIELDS = ("authors", "keywords")
_INT_FIELDS = ("citations", "downloads", "impact_factor_year")
_FLOAT_FIELDS = ("impact_factor",)
# Derived at serialisation time from `doc_type`, never stored. Accepted here so a
# payload that came out of `Record.to_dict()` can go back in.
_DERIVED_FIELDS = frozenset({"doc_type_unified"})
_KNOWN = frozenset(
    {
        *_STRING_FIELDS,
        *_LIST_FIELDS,
        *_INT_FIELDS,
        *_FLOAT_FIELDS,
        *_DERIVED_FIELDS,
        "year",
        "fetched_at",
        "doc_type",
    }
)

# Keyed by the **unified** vocabulary, not by any one channel's words. These maps
# used to hold only CNKI's values (`journal`, `conference`, …), so every Web of
# Science record — whose parser emits `article`, `review`, `proceedings` — exported as
# `TY  - GEN`. A journal article, a review and a conference paper all arrived in
# Zotero as "Generic".
_RIS_TYPES = {
    "article": "JOUR",
    "review": "JOUR",
    "thesis": "THES",
    "conference": "CPAPER",
    "newspaper": "NEWS",
    "book": "BOOK",
    "book_chapter": "CHAP",
    "patent": "PAT",
    "standard": "STAND",
    "yearbook": "BOOK",
    "achievement": "GEN",
    "other": "GEN",
}

_ENDNOTE_TYPES = {
    "article": "Journal Article",
    "review": "Journal Article",
    "thesis": "Thesis",
    "conference": "Conference Paper",
    "newspaper": "Newspaper Article",
    "book": "Book",
    "book_chapter": "Book Section",
    "patent": "Patent",
    "standard": "Generic",
    "yearbook": "Book",
    "achievement": "Generic",
    "other": "Generic",
}


def _text(value: Any, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return " ".join(value.split())


def _year(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        raise ValueError("year must be an integer or a four-digit string")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.isdigit() and len(value) == 4:
        return value
    raise ValueError("year must be an integer or a four-digit string")


# Keys the tool wraps *around* a record rather than storing *in* it. `detail` flattens
# them onto the record, so a caller passing a detail response straight to `export` is
# doing the obvious thing — these are skipped rather than reported as unknown fields.
ENVELOPE_FIELDS = frozenset({"quota_charged", "quota_remaining"})


def record_from_payload(payload: Mapping[str, Any]) -> Record:
    """Build a Record from a client payload, rejecting malformed fields."""

    if not isinstance(payload, Mapping):
        raise ValueError("record must be an object")
    # `detail` returns the record with the response envelope flattened into it, so the
    # natural flow — take what `detail` gave you and hand it to `export` — used to fail
    # on wensu's own bookkeeping fields:
    #
    #   unknown record fields: ['quota_charged', 'quota_remaining']
    #
    # The caller had to know which keys were "real" and drop the rest, which is exactly
    # the kind of knowledge an interface should not require. Envelope keys are dropped
    # here; genuinely unknown keys are still rejected, so a typo is still caught.
    body = {key: value for key, value in payload.items() if key not in ENVELOPE_FIELDS}
    unknown = set(body) - _KNOWN
    if unknown:
        raise ValueError(f"unknown record fields: {sorted(unknown)}")
    payload = body

    title = _text(payload.get("title"), "title")
    if not title:
        raise ValueError("title must not be empty")
    channel = _text(payload.get("channel") or "cnki", "channel")

    authors = payload.get("authors") or []
    if not isinstance(authors, list) or any(not isinstance(x, str) for x in authors):
        raise ValueError("authors must be a list of strings")
    keywords = payload.get("keywords") or []
    if not isinstance(keywords, list) or any(not isinstance(x, str) for x in keywords):
        raise ValueError("keywords must be a list of strings")

    numbers: dict[str, int | None] = {}
    for field in _INT_FIELDS:
        value = payload.get(field)
        if value is None:
            numbers[field] = None
        elif isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{field} must be an integer")
        else:
            numbers[field] = value

    doc_type = payload.get("doc_type")
    if doc_type is not None and not isinstance(doc_type, str):
        raise ValueError("doc_type must be a string")

    impact = payload.get("impact_factor")
    if impact is not None:
        if isinstance(impact, bool) or not isinstance(impact, (int, float)):
            raise ValueError("impact_factor must be a number")
        impact = float(impact)

    impact_year = payload.get("impact_factor_year")
    if impact_year is not None and (
        isinstance(impact_year, bool) or not isinstance(impact_year, int)
    ):
        raise ValueError("impact_factor_year must be an integer")

    year_text = _year(payload.get("year"))
    fetched = payload.get("fetched_at")
    if isinstance(fetched, str):
        fetched = datetime.fromisoformat(fetched)
    elif fetched is not None and not isinstance(fetched, datetime):
        raise ValueError("fetched_at must be an ISO string")

    return Record(
        channel=channel,
        title=title,
        authors=[_text(author, "author") for author in authors],
        institution=_text(payload.get("institution"), "institution") or None,
        source=_text(payload.get("source"), "source") or None,
        year=int(year_text) if year_text else None,
        volume=_text(payload.get("volume"), "volume") or None,
        issue=_text(payload.get("issue"), "issue") or None,
        pages=_text(payload.get("pages"), "pages") or None,
        doi=_text(payload.get("doi"), "doi") or None,
        abstract=_text(payload.get("abstract"), "abstract") or None,
        keywords=[_text(keyword, "keyword") for keyword in keywords],
        citations=numbers["citations"],
        downloads=numbers["downloads"],
        url=_text(payload.get("url"), "url") or None,
        fetched_at=fetched,
        doc_type=_text(doc_type, "doc_type").casefold() or None,
        impact_factor=impact,
        impact_factor_year=impact_year,
    )


def _clean(value: str | None) -> str:
    return _text(value, "field") if value else ""


def _type_token(record: Record) -> tuple[str, str]:
    """Map a record's type to RIS and EndNote vocabularies.

    The **raw** type is tried first, then the unified one. That order matters: the
    unified vocabulary exists so cross-channel filtering can compare types, and it is
    deliberately coarse — `standard` and `yearbook` collapse to `other` there. Using
    it as the only lookup made those two export as generic, which is a regression from
    the version before unification.

    So: a channel's own word wins when the export knows it, and unification is the
    fallback for the words the RSI/EndNote maps do not carry directly.
    """

    raw = (record.doc_type or "").casefold()
    if raw in _RIS_TYPES:
        return _RIS_TYPES[raw], _ENDNOTE_TYPES[raw]
    unified = unify_doc_type(record.doc_type) or ""
    return _RIS_TYPES.get(unified, "GEN"), _ENDNOTE_TYPES.get(unified, "Generic")


def to_ris(records: Iterable[Record]) -> str:
    lines: list[str] = []
    for record in records:
        year = _year(record.year)
        ris_type, _ = _type_token(record)
        lines.append(f"TY  - {ris_type}")
        if ris_type == "GEN":
            # Two different situations, and the old text conflated them: the source
            # reported nothing, or it reported something this mapping does not cover.
            # The second is our gap, not the record's, and saying otherwise sends the
            # user looking for a problem in the data.
            if record.doc_type:
                lines.append(f"N1  - {record.doc_type}; no RIS equivalent mapped")
            else:
                lines.append("N1  - document type not reported by source")
        lines.append(f"TI  - {_text(record.title, 'title')}")
        for author in record.authors:
            lines.append(f"AU  - {_text(author, 'author')}")
        if record.source:
            lines.append(f"T2  - {_clean(record.source)}")
        if year:
            lines.append(f"PY  - {year}")
        if record.volume:
            lines.append(f"VL  - {_clean(record.volume)}")
        if record.issue:
            lines.append(f"IS  - {_clean(record.issue)}")
        if record.pages:
            first, _, last = _clean(record.pages).partition("-")
            lines.append(f"SP  - {first}")
            if last:
                lines.append(f"EP  - {last}")
        if record.doi:
            lines.append(f"DO  - {_clean(record.doi)}")
        if record.abstract:
            lines.append(f"AB  - {_clean(record.abstract)}")
        for keyword in record.keywords:
            lines.append(f"KW  - {_clean(keyword)}")
        if record.url:
            lines.append(f"UR  - {_clean(record.url)}")
        lines.append("ER  - ")
        lines.append("")
    return "\n".join(lines)


def to_endnote(records: Iterable[Record]) -> str:
    lines: list[str] = []
    for record in records:
        year = _year(record.year)
        _, endnote_type = _type_token(record)
        lines.append(f"%0 {endnote_type}")
        lines.append(f"%T {_text(record.title, 'title')}")
        for author in record.authors:
            lines.append(f"%A {_text(author, 'author')}")
        if record.source:
            lines.append(f"%J {_clean(record.source)}")
        if year:
            lines.append(f"%D {year}")
        if record.volume:
            lines.append(f"%V {_clean(record.volume)}")
        if record.issue:
            lines.append(f"%N {_clean(record.issue)}")
        if record.pages:
            lines.append(f"%P {_clean(record.pages)}")
        if record.doi:
            lines.append(f"%R {_clean(record.doi)}")
        if record.abstract:
            lines.append(f"%X {_clean(record.abstract)}")
        for keyword in record.keywords:
            lines.append(f"%K {_clean(keyword)}")
        if record.url:
            lines.append(f"%U {_clean(record.url)}")
        lines.append("")
    return "\n".join(lines)


def to_markdown(records: Iterable[Record]) -> str:
    """A readable document, one section per record.

    The citation formats exist to be imported. When the goal is a document a person
    reads — a literature review draft, a summary table — `markdown` is what a caller
    would otherwise assemble by hand, which means pulling every abstract back
    through the context first. Writing it directly costs nothing.
    """

    blocks: list[str] = []
    for index, record in enumerate(records, start=1):
        heading = _clean(record.title) or f"Record {index}"
        blocks.append(f"## {index}. {heading}")
        meta: list[str] = []
        if record.authors:
            meta.append("、".join(record.authors))
        if record.source:
            meta.append(_clean(record.source))
        if record.year is not None:
            meta.append(str(record.year))
        if record.volume or record.issue or record.pages:
            bits = "".join(
                part
                for part in (
                    f"{record.volume}" if record.volume else "",
                    f"({record.issue})" if record.issue else "",
                    f": {record.pages}" if record.pages else "",
                )
            )
            meta.append(bits)
        if meta:
            blocks.append(" · ".join(meta))
        if record.doi:
            blocks.append(f"DOI: {_clean(record.doi)}")
        if record.impact_factor is not None:
            blocks.append(f"影响因子: {record.impact_factor}")
        if record.citations is not None:
            blocks.append(f"被引: {record.citations}")
        if record.keywords:
            blocks.append(f"关键词: {'; '.join(_clean(k) for k in record.keywords)}")
        if record.abstract:
            blocks.append("")
            blocks.append(_clean(record.abstract))
        if record.url:
            blocks.append("")
            blocks.append(f"<{_clean(record.url)}>")
        blocks.append("")
    return "\n".join(blocks)


def to_csv(records: Iterable[Record]) -> str:
    """One row per record, for a spreadsheet.

    Written with the `csv` module rather than by joining with commas: titles contain
    commas, quotes and newlines, and a hand-rolled writer would corrupt exactly the
    records a user most wants to keep.
    """

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "title",
            "authors",
            "source",
            "year",
            "volume",
            "issue",
            "pages",
            "doi",
            "citations",
            "impact_factor",
            "doc_type",
            "keywords",
            "abstract",
            "url",
        ]
    )
    for record in records:
        writer.writerow(
            [
                _clean(record.title),
                "; ".join(record.authors),
                _clean(record.source),
                record.year if record.year is not None else "",
                record.volume or "",
                record.issue or "",
                record.pages or "",
                record.doi or "",
                record.citations if record.citations is not None else "",
                record.impact_factor if record.impact_factor is not None else "",
                record.doc_type or "",
                "; ".join(record.keywords),
                _clean(record.abstract),
                record.url or "",
            ]
        )
    return buffer.getvalue()
