"""Read a Web of Science BibTeX export into records.

Why this exists at all: on `www.webofscience.com` the result payload is not reachable
from a content script. `capture.js` patches `window.fetch` and `XMLHttpRequest` in the top
frame, and on that host neither ever carries `runQueryGetRecordsStream` — the request the
user sees in DevTools is issued from a context that patch does not cover. Rather than keep
guessing at the site's internals, the channel asks the site for what it already publishes:
an export file in a format that has a specification.

BibTeX is also *better* input than the stream. Everything the stream carries that we use is
present, plus `Times-Cited`, `ISSN`, `EISSN` and the author's own spelling — and the format
is stable in a way an internal endpoint is not.

Two details that are easy to get wrong:

* **The entry key is the UT.** `@article{ WOS:001218812900001,` — so `url` is built exactly
  the way the stream path builds it, and `exclude_ut`, `detail` and the export formats keep
  working without knowing which path produced the record.
* **Values are wrapped and folded.** A value is `{...}` and a long one continues on the next
  line indented by three spaces. WoS escapes literal braces as `{[}` / `{]}` and ampersands
  as `\\&`, so both are undone here; leaving them in produces titles with stray LaTeX.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator

from ....core.contracts import Record, SearchPage, SearchQuery
from . import selectors

# `(name, issn, eissn) -> (impact factor, JCR edition year)` or None. Passed in rather than
# imported so this module has no database dependency and can be tested on its own.
MetricLookup = Callable[[str | None, str | None, str | None], "tuple[float, int] | None"]

_ENTRY_START = re.compile(r"@(\w+)\s*\{")
# A field name is everything before the first `=` that is not inside braces.
_FIELD = re.compile(r"([A-Za-z][A-Za-z0-9_\-]*)\s*=\s*")


def _balanced(text: str, start: int, opener: str, closer: str) -> tuple[str, int]:
    """Read from `start` (just past `opener`) to the matching `closer`."""

    depth = 1
    index = start
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start:index], index + 1
        index += 1
    return text[start:], len(text)


def _clean(value: str) -> str:
    """Undo WoS's LaTeX-ish escaping and fold continuation lines."""

    folded = re.sub(r"\s*\n\s*", " ", value)
    folded = folded.replace("{[}", "{").replace("{]}", "}")
    folded = folded.replace("\\&", "&").replace("~", " ")
    folded = re.sub(r"\s{2,}", " ", folded)
    return folded.strip()


def _entries(text: str) -> Iterator[tuple[str, str, dict[str, str]]]:
    """Yield `(entry_type, key, fields)` for every entry in the document."""

    position = 0
    while True:
        start = _ENTRY_START.search(text, position)
        if start is None:
            return
        entry_type = start.group(1).lower()
        body_start = start.end()
        body, position = _balanced(text, body_start, "{", "}")

        # The key is the first top-level token, up to the first comma.
        comma = body.find(",")
        if comma == -1:
            key, rest = body.strip(), ""
        else:
            key, rest = body[:comma].strip(), body[comma + 1 :]

        fields: dict[str, str] = {}
        index = 0
        while index < len(rest):
            match = _FIELD.search(rest, index)
            if match is None:
                break
            name = match.group(1)
            cursor = match.end()
            while cursor < len(rest) and rest[cursor] in " \t\r\n":
                cursor += 1
            if cursor >= len(rest):
                break
            opener = rest[cursor]
            if opener == "{":
                value, cursor = _balanced(rest, cursor + 1, "{", "}")
            elif opener == '"':
                close = rest.find('"', cursor + 1)
                close = len(rest) if close == -1 else close
                value, cursor = rest[cursor + 1 : close], close + 1
            else:
                # A bare value (a number, usually) ends at the next comma or line break.
                stop = min(
                    (p for p in (rest.find(",", cursor), rest.find("\n", cursor)) if p != -1),
                    default=len(rest),
                )
                value, cursor = rest[cursor:stop], stop
            fields[name.lower()] = _clean(value)
            # Skip the separator comma.
            comma_at = rest.find(",", cursor)
            index = len(rest) if comma_at == -1 else comma_at + 1

        yield entry_type, key, fields


def _authors(fields: dict[str, str]) -> list[str]:
    raw = fields.get("author") or ""
    names = [part.strip() for part in re.split(r"\s+and\s+", raw) if part.strip()]
    # `Last, First` is what the site writes and what `_authors` produces from the stream,
    # so the two paths agree without a conversion step.
    return names


def _year(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"(\d{4})", value)
    return int(match.group(1)) if match else None


def _keywords(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(";") if part.strip()]


def _doi(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    text = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)\s*", "", text, flags=re.I)
    return text.strip() or None


def parse(
    text: str,
    *,
    query: SearchQuery,
    metrics: MetricLookup | None = None,
) -> SearchPage:
    """Turn an export file into the same `SearchPage` the capture path produces."""

    records: list[Record] = []
    for entry_type, key, fields in _entries(text):
        ut = fields.get("unique-id") or key
        title = fields.get("title")
        if not title:
            # A record with no title is not usable, and inventing one hides a format
            # change. Skipping keeps the rest of the page.
            continue

        doi = _doi(fields.get("doi"))
        source = fields.get("journal") or fields.get("booktitle")
        doc_type = (fields.get("type") or entry_type or "").strip().lower() or None

        impact_factor: float | None = None
        impact_factor_year: int | None = None
        if metrics is not None:
            resolved = metrics(source, fields.get("issn"), fields.get("eissn"))
            if resolved is not None:
                impact_factor, impact_factor_year = resolved

        records.append(
            Record(
                channel="webofscience",
                title=title,
                authors=_authors(fields),
                institution=fields.get("affiliations") or None,
                source=source,
                year=_year(fields.get("year")),
                volume=fields.get("volume") or None,
                issue=fields.get("number") or None,
                pages=fields.get("pages") or None,
                doi=doi,
                abstract=fields.get("abstract") or None,
                keywords=_keywords(fields.get("keywords")),
                citations=_int(fields.get("times-cited")),
                url=f"{selectors.DETAIL_PREFIX}{ut}" if ut else None,
                doc_type=doc_type,
                impact_factor=impact_factor,
                impact_factor_year=impact_factor_year,
            )
        )

    return SearchPage(
        records=tuple(records),
        total=len(records),
        page=query.page,
        query_effective=query.text,
    )


def _int(value: str | None) -> int | None:
    if not value:
        return None
    text = value.strip()
    return int(text) if text.lstrip("-").isdigit() else None
