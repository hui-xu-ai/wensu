"""Turn a :class:`SearchQuery` into a Web of Science search expression.

Two shapes are accepted, mirroring how people actually use the advanced search
page:

* a bare keyword phrase — wrapped as ``ALL=(...)``;
* a fielded expression such as ``TS=(actuator) AND PY=(2021-2026)`` — passed
  through unchanged.

Everything else the site would otherwise need clicks for (year span, extra
conjunctions, re-running a previous search) is expressed *in the query string*.
That keeps one search at three network actions and no filter widgets.

Why a default span: with no year restriction the engine happily returns
material from the 1970s, and narrowing it afterwards on the page costs a click
plus a re-query. Defaulting to the last five years in the expression is both
cheaper and closer to what a literature review wants.
"""

from __future__ import annotations

import datetime as dt
import re

from ....core.contracts import SearchQuery
from ....core.errors import ChannelError

# Field codes documented by the advanced-search page (user-supplied list,
# 2026-11-08). A code outside this set is almost always a typo, and a typo
# silently yields zero records — so it is rejected instead.
FIELDS: frozenset[str] = frozenset(
    {
        "TS", "TI", "AB", "AU", "AI", "AK", "GP", "ED", "KP", "SO",
        "DO", "PY", "CF", "AD", "OG", "OO", "SG", "SA", "CI", "PS",
        "CU", "ZP", "FO", "FG", "FD", "FT", "SU", "WC", "IS", "UT",
        "PMID", "DOP", "LD", "PUBL", "ALL", "FPY", "EAY", "SDG",
        "TMAC", "TMSO", "TMIC",
    }
)

DEFAULT_SPAN_YEARS = 5

_FIELD = re.compile(r"\b([A-Z]{2,5})\s*=")
_HISTORY_REF = re.compile(r"#\d+")


def field_tokens(expression: str) -> tuple[str, ...]:
    """Return every field code used in ``expression``, upper-cased."""

    return tuple(match.group(1) for match in _FIELD.finditer(expression.upper()))


def unknown_fields(expression: str) -> tuple[str, ...]:
    return tuple(sorted({token for token in field_tokens(expression) if token not in FIELDS}))


def is_expression(text: str) -> bool:
    """True when the caller supplied a fielded expression, not a keyword phrase."""

    return bool(field_tokens(text))


def default_span(today: dt.date | None = None) -> tuple[int, int]:
    """The five-year window used when the caller gives no year at all."""

    year = (today or dt.date.today()).year
    return year - (DEFAULT_SPAN_YEARS - 1), year


def resolve_span(query: SearchQuery, today: dt.date | None = None) -> tuple[int, int]:
    """Fill in whichever end of the year range the caller left out."""

    default_start, default_end = default_span(today)
    start, end = query.year_from, query.year_to
    if start is not None and end is not None:
        return start, end
    if start is not None:
        return start, default_end
    if end is not None:
        return end - (DEFAULT_SPAN_YEARS - 1), end
    return default_start, default_end


def _normalise_py(text: str) -> str:
    """Rewrite `PY=(2026-2026)` as `PY=(2026)`.

    Web of Science accepts `PY=(2021-2026)`, `PY=(2026)` and `PY=(2026, 2024)`, but
    not a range whose ends are equal — it treats the dash form as a range and then
    rejects the single-year range. A caller expressing "only this year" naturally
    writes `2026-2026`, spends a search finding out it is invalid, and loses the
    quota for a purely local mistake. Collapsing it here costs nothing.
    """

    def repl(match: re.Match[str]) -> str:
        start, end = match.group(1), match.group(2)
        if start == end:
            return f"PY=({start})"
        return match.group(0)

    return re.sub(r"PY=\(\s*(\d{4})\s*-\s*(\d{4})\s*\)", repl, text, flags=re.IGNORECASE)


def build(query: SearchQuery, *, today: dt.date | None = None) -> str:
    """Compose the expression that will be typed into the editor."""

    text = _normalise_py(query.text.strip())
    if not text:
        raise ChannelError("search text must not be empty")
    if _HISTORY_REF.search(text):
        raise ChannelError(
            "retrieval-history references (#1, #2 ...) are not supported yet; "
            "pass the full expression instead"
        )

    unknown = unknown_fields(text)
    if unknown:
        raise ChannelError(
            "unknown Web of Science field code(s): " + ", ".join(unknown)
        )

    body = text if is_expression(text) else f"ALL=({text})"

    # An explicit PY= in the caller's expression already bounds the span; adding
    # a second one would intersect two ranges and quietly drop records.
    if "PY" in field_tokens(text):
        return body

    start, end = resolve_span(query, today)
    return f"({body}) AND PY=({start}-{end})"
