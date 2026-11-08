"""Unit tests for the Web of Science expression builder.

The builder is where the channel decides what *not* to click: the year span and
any extra conjunction live in the expression string, so one search stays at
three network actions.
"""

from __future__ import annotations

import datetime as dt

import pytest

from scholar_search.channels.webofscience.v2026_11 import query
from scholar_search.core.contracts import SearchQuery
from scholar_search.core.errors import ChannelError

TODAY = dt.date(2026, 11, 8)


def _query(text: str, **kwargs: object) -> SearchQuery:
    return SearchQuery(text=text, channel="webofscience", **kwargs)  # type: ignore[arg-type]


def test_bare_keyword_becomes_an_all_field_search() -> None:
    assert query.build(_query("actuator"), today=TODAY) == "(ALL=(actuator)) AND PY=(2022-2026)"


def test_fielded_expression_is_passed_through() -> None:
    text = "TS=(actuator) AND AU=(Kim)"
    assert query.build(_query(text), today=TODAY) == f"({text}) AND PY=(2022-2026)"


def test_explicit_year_range_wins() -> None:
    built = query.build(_query("actuator", year_from=2015, year_to=2020), today=TODAY)
    assert built == "(ALL=(actuator)) AND PY=(2015-2020)"


def test_missing_end_falls_back_to_this_year() -> None:
    assert query.build(_query("actuator", year_from=2015), today=TODAY) == (
        "(ALL=(actuator)) AND PY=(2015-2026)"
    )


def test_missing_start_falls_back_to_a_five_year_window() -> None:
    assert query.build(_query("actuator", year_to=2020), today=TODAY) == (
        "(ALL=(actuator)) AND PY=(2016-2020)"
    )


def test_py_inside_the_expression_short_circuits_the_default() -> None:
    text = "TS=(actuator) AND PY=(1999-2003)"
    assert query.build(_query(text), today=TODAY) == text


def test_unknown_field_code_is_rejected() -> None:
    with pytest.raises(ChannelError):
        query.build(_query("XX=(actuator)"), today=TODAY)


def test_history_reference_is_rejected() -> None:
    with pytest.raises(ChannelError):
        query.build(_query("#5 AND #2"), today=TODAY)


def test_empty_text_is_rejected() -> None:
    with pytest.raises(ChannelError):
        query.build(_query("   "), today=TODAY)


def test_lower_case_field_code_is_recognised() -> None:
    assert query.build(_query("ts=(actuator)"), today=TODAY) == "(ts=(actuator)) AND PY=(2022-2026)"
