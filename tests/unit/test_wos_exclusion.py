"""Reaching deeper results by excluding what was already seen.

Turning pages keeps one result set open across several minutes and several SPA state
transitions — brittle, and the traffic pattern the cadence rules exist to avoid. Asking
the same question again with "not these ones" is a fresh, independent request.

The mechanism was verified against the live site before this was written: excluding
three UTs from a 38-record query returned a total of 35 and a different page of
records.

These tests cover the expression, which is the part that can be checked offline. The
`NOT UT=(...)` clause working at all is a site behaviour, recorded above.
"""

from __future__ import annotations

import datetime as dt

import pytest

from scholar_search.channels.webofscience.v2026_11 import query as expression
from scholar_search.core.contracts import MAX_EXCLUDE_UT, SearchQuery

TODAY = dt.date(2026, 11, 10)


def _build(**kwargs: object) -> str:
    kwargs.setdefault("channel", "webofscience")
    return expression.build(SearchQuery(**kwargs), today=TODAY)  # type: ignore[arg-type]


def test_no_exclusion_leaves_the_expression_unchanged() -> None:
    """The common path must not gain a stray clause."""

    plain = _build(text="TS=(ionogel AND actuator)")
    assert "NOT UT" not in plain
    assert plain == "(TS=(ionogel AND actuator)) AND PY=(2022-2026)"


def test_identifiers_are_excluded_with_not_ut() -> None:
    built = _build(
        text="TS=(ionogel AND actuator)",
        exclude_ut=("WOS:001218812900001", "WOS:001174201100160"),
    )
    assert 'NOT UT=("WOS:001218812900001" OR "WOS:001174201100160")' in built
    # The exclusion sits outside the year-scoped body, not inside it.
    assert built.index("PY=") < built.index("NOT UT")


def test_a_detail_url_is_accepted_as_an_identifier() -> None:
    """That is where the identifier is visible in a response, so callers pass it."""

    built = _build(
        text="TS=(x)",
        exclude_ut=("https://webofscience.clarivate.cn/wos/woscc/full-record/WOS:001218812900001",),
    )
    assert '"WOS:001218812900001"' in built
    assert "webofscience.clarivate.cn" not in built


def test_a_bare_or_lowercase_identifier_is_normalised() -> None:
    built = _build(text="TS=(x)", exclude_ut=("wos:001218812900001", "001174201100160"))
    assert '"WOS:001218812900001"' in built
    assert '"WOS:001174201100160"' in built


def test_blank_entries_are_skipped_not_rendered_as_empty_quotes() -> None:
    built = _build(text="TS=(x)", exclude_ut=("", "   "))
    assert "NOT UT" not in built, "an all-blank list must not emit an empty clause"


def test_the_cap_is_enforced() -> None:
    ids = tuple(f"WOS:{i:015d}" for i in range(MAX_EXCLUDE_UT + 1))
    with pytest.raises(ValueError, match="at most"):
        SearchQuery(text="TS=(x)", channel="webofscience", exclude_ut=ids).validate()


def test_the_cap_itself_is_allowed() -> None:
    ids = tuple(f"WOS:{i:015d}" for i in range(MAX_EXCLUDE_UT))
    SearchQuery(text="TS=(x)", channel="webofscience", exclude_ut=ids).validate()


def test_an_explicit_py_is_still_not_doubled() -> None:
    """The exclusion must not change how the year span is handled."""

    built = _build(text="TS=(x) AND PY=(2024)", exclude_ut=("WOS:001218812900001",))
    assert built.count("PY=") == 1
    assert "NOT UT" in built
