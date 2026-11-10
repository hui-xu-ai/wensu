"""Year ranges, exclusion identifiers and DOI spellings.

All three came from one usability report, all three are offline-verifiable, and all
three shared a shape: **the tool accepted an input it could not honour, and said
nothing**. `year_from=2027` alone produced a backwards range; a record URL copied out
of a browser carried `?locale=en_US` into the identifier; `doi:…` and
`https://doi.org/…` were reported as unknown channels.
"""

from __future__ import annotations

import datetime as dt

import pytest

from scholar_search.channels.webofscience.v2026_11 import query as expression
from scholar_search.core.contracts import SearchQuery
from scholar_search.core.errors import ChannelError
from scholar_search.core.service import normalise_doi

TODAY = dt.date(2026, 11, 10)


def _build(**kwargs: object) -> str:
    kwargs.setdefault("channel", "webofscience")
    return expression.build(SearchQuery(**kwargs), today=TODAY)  # type: ignore[arg-type]


# -- the year clause -------------------------------------------------------


def test_a_single_year_is_written_as_a_single_year() -> None:
    """`PY=(2026-2026)` and `PY=(2026)` are the same query, so generate one spelling.

    A caller who typed the span by hand and a caller who passed
    `year_from=year_to=2026` used to produce different expressions — and therefore
    different cache entries — for identical results.
    """

    assert _build(text="x", year_from=2026, year_to=2026).endswith("AND PY=(2026)")
    assert _build(text="x", year_from=2020, year_to=2026).endswith("AND PY=(2020-2026)")


def test_a_future_year_from_does_not_invert_the_range() -> None:
    """`year_from=2027` with no end used to produce `PY=(2027-2026)`."""

    built = _build(text="x", year_from=2027)
    assert built.endswith("AND PY=(2027)"), built


def test_a_past_year_from_runs_to_the_default_end() -> None:
    assert _build(text="x", year_from=2024).endswith("AND PY=(2024-2026)")


def test_a_year_to_alone_keeps_the_documented_five_year_window() -> None:
    assert _build(text="x", year_to=2020).endswith("AND PY=(2016-2020)")


def test_an_explicitly_reversed_pair_is_refused_with_both_values_named() -> None:
    with pytest.raises(ChannelError, match=r"2020.*2026"):
        _build(text="x", year_from=2026, year_to=2020)


# -- exclusion identifiers -------------------------------------------------


def test_a_url_with_a_query_string_yields_a_clean_identifier() -> None:
    """A URL copied from a browser can carry parameters.

    Taking the tail of the path kept them, producing `"WOS:...?LOCALE=EN_US"` — an
    identifier that does not exist, so the exclusion matched nothing and the caller
    paid for a search that returned the same records again.
    """

    built = _build(
        text="x",
        year_from=2026,
        year_to=2026,
        exclude_ut=(
            "https://webofscience.clarivate.cn/wos/woscc/full-record/WOS:001874427500001?locale=en_US",
        ),
    )
    assert '"WOS:001874427500001"' in built
    assert "?" not in built
    assert "LOCALE" not in built


def test_a_fragment_is_stripped_too() -> None:
    built = _build(
        text="x",
        year_from=2026,
        year_to=2026,
        exclude_ut=("https://webofscience.clarivate.cn/wos/woscc/full-record/WOS:001#tab",),
    )
    assert '"WOS:001"' in built
    assert "#" not in built


# -- DOI spellings ---------------------------------------------------------


@pytest.mark.parametrize(
    "spelling",
    [
        "10.1002/adma.74981",
        "doi:10.1002/adma.74981",
        "DOI: 10.1002/adma.74981",
        "https://doi.org/10.1002/adma.74981",
        "http://dx.doi.org/10.1002/adma.74981",
        "  https://doi.org/10.1002/adma.74981  ",
    ],
)
def test_every_common_doi_spelling_resolves_to_the_bare_doi(spelling: str) -> None:
    """Only the bare form used to be recognised; the rest became UNKNOWN_CHANNEL.

    "no channel claims the host" was accurate and useless — the host is a resolver,
    and the thing the caller has *is* the identifier.
    """

    assert normalise_doi(spelling) == "10.1002/adma.74981"


@pytest.mark.parametrize(
    "not_a_doi",
    [
        "https://webofscience.clarivate.cn/wos/woscc/full-record/WOS:001218812900001",
        "https://kns.cnki.net/kcms2/article/abstract?v=abc",
        "not a doi",
        "",
        "10.no-slash",
    ],
)
def test_a_url_or_a_non_doi_is_left_for_the_channel_router(not_a_doi: str) -> None:
    """Returning None is what keeps a real URL going to the channel that owns it."""

    assert normalise_doi(not_a_doi) is None
