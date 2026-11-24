"""一次导出读一段记录（1–1000），而不是二十次五十条的翻页。

站点上限来自 Clarivate 的 "Limit on exporting"：完整记录一次最多 1000 条；我们的实现上限是
**500**（实测 500 条能在单动作 15 s 下载预算内到达，1000 条没有文件）。
选择器是 2026-11-22 真实探测得到的：单选 `#radio3-input` 选「记录:」，
两个数字框 `input[name=markFrom]` / `input[name=markTo]` 在其之前是 `disabled`。
"""

from __future__ import annotations

import pytest

from scholar_search.channels.webofscience.v2026_11 import plan_export
from scholar_search.core.contracts import MAX_RECORDS, SearchQuery


def _query(**kwargs: object) -> SearchQuery:
    base: dict[str, object] = {
        "text": "TS=(ionic AND actuator*)",
        "channel": "webofscience",
    }
    base.update(kwargs)
    return SearchQuery(**base)  # type: ignore[arg-type]


def _verbs(plan: object) -> list[str]:
    return [action.verb for action in plan.actions]  # type: ignore[attr-defined]


def test_a_range_picks_the_radio_and_types_both_bounds() -> None:
    plan = plan_export.build_after_click(_query(records_from=1, records_to=500))

    typed = [
        (action.params["selector"], action.params["text"])
        for action in plan.actions
        if action.verb == "type"
    ]
    assert typed == [
        (plan_export.selectors.EXPORT_RANGE_FROM, "1"),
        (plan_export.selectors.EXPORT_RANGE_TO, "500"),
    ], typed
    assert plan_export.selectors.EXPORT_RANGE_RADIO in [
        action.params.get("selector") for action in plan.actions if action.verb == "click"
    ]


def test_the_radio_comes_before_the_inputs() -> None:
    """两个数字框在选中单选之前是 disabled：顺序错了就等于没填。"""

    plan = plan_export.build_after_click(_query(records_from=101, records_to=500))
    verbs = _verbs(plan)
    radio = verbs.index("click", verbs.index("click", len(verbs) - 12))
    first_type = verbs.index("type")

    assert radio < first_type, verbs


def test_no_range_keeps_the_page_export_untouched() -> None:
    plan = plan_export.build_after_click(_query())

    assert "type" not in _verbs(plan)


def test_only_the_start_means_a_single_record() -> None:
    span = _query(records_from=7).records_span

    assert span == (7, 7)


def test_a_span_over_the_site_cap_is_refused() -> None:
    with pytest.raises(ValueError, match=f"at most {MAX_RECORDS}"):
        _query(records_from=1, records_to=MAX_RECORDS + 1).validate()


def test_the_cap_stays_at_five_hundred() -> None:
    """500, on purpose: two 500-record exports beat one 1000-record file (ADR 0024).

    The site carries 1000 per file, but the failure mode that matters is the download, so the
    smaller file wins even though the download click may now wait 55 s for it.
    """

    assert MAX_RECORDS == 500
    _query(records_from=1, records_to=500).validate()


def test_a_range_and_a_page_turn_are_alternatives() -> None:
    with pytest.raises(ValueError, match="alternatives"):
        _query(records_from=1, records_to=100, page=2).validate()


def test_the_end_must_not_precede_the_start() -> None:
    with pytest.raises(ValueError, match="records_to must be >= records_from"):
        _query(records_from=100, records_to=10).validate()


def test_a_channel_without_an_export_file_refuses_a_range(tmp_path: object) -> None:
    """CNKI 读的是结果页，给不了记录范围——必须明说，不能悄悄只给 50 条。"""

    from scholar_search.core.errors import ScholarSearchError  # noqa: I001 — 与下一行不同分组，函数内导入

    from test_page_read import build_service

    service = build_service(tmp_path, [[]])  # type: ignore[arg-type]
    with pytest.raises(ScholarSearchError, match="cannot read a record range"):
        service.search(_query(channel="cnki", records_from=1, records_to=100))
