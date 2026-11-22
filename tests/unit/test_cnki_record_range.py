"""知网的记录范围：靠翻页读，一次最多三页（150 条）。

站点没有"记录 1 至 N"的导出入参（`#batchOpsBox` 里全是格式链接，`#selectCheckAll1` 只勾当前
页），所以范围只能靠翻页实现 —— 与 WoS 的导出区间不同机制、同样效果：
`records_from=1, records_to=150` 一次调用拿三页。真实链路实测 2026-11-22：150 条、44.7 s。
"""

from __future__ import annotations

from scholar_search.channels.cnki.v2026_10 import plan_search
from scholar_search.core.contracts import Record, SearchPage, SearchQuery
from scholar_search.core.service import _merge_pages


def _query(**kwargs: object) -> SearchQuery:
    base: dict[str, object] = {"text": "钙钛矿太阳能电池", "channel": "cnki", "limit": 50}
    base.update(kwargs)
    return SearchQuery(**base)  # type: ignore[arg-type]


def _reads(plan: object) -> int:
    return sum(1 for action in plan.actions if action.verb == "read_html")  # type: ignore[attr-defined]


def _turns(plan: object) -> int:
    return sum(  # type: ignore[attr-defined]
        1
        for action in plan.actions
        if action.verb == "click"
        and action.params.get("selector") == plan_search.SEARCH["next_page"]
    )


def test_a_range_of_three_pages_reads_three_times() -> None:
    plan = plan_search.build(_query(records_from=1, records_to=150))

    assert _reads(plan) == 3, plan.actions
    assert _turns(plan) == 2, plan.actions


def test_a_single_page_range_reads_once() -> None:
    plan = plan_search.build(_query(records_from=1, records_to=50))

    assert _reads(plan) == 1
    assert _turns(plan) == 0


def test_no_range_keeps_the_single_read() -> None:
    plan = plan_search.build(_query())

    assert _reads(plan) == 1
    assert _turns(plan) == 0


def test_a_range_never_exceeds_three_pages() -> None:
    """AGENTS.md：单次 ≤3 页。150 条已是知网这条路的天花板。"""

    plan = plan_search.build(_query(records_from=1, records_to=150, limit=20))

    assert _reads(plan) == 3


def test_the_turn_waits_long_enough_for_the_grid_to_redraw() -> None:
    """2.5 s 会读到上一页（实测），所以每翻一次至少等 4.5 s（两个 sleep 相加）。"""

    plan = plan_search.build(_query(records_from=1, records_to=150))
    sleeps = [
        int(action.params["ms"])
        for action in plan.actions
        if action.verb == "sleep" and action.params.get("ms") in {1_500, 3_000}
    ]
    assert sleeps.count(3_000) >= 2 and sleeps.count(1_500) >= 2, sleeps


def _record(url: str, title: str) -> Record:
    return Record(channel="cnki", title=title, url=url)


def test_merged_pages_keep_each_record_once() -> None:
    first = SearchPage(
        records=(_record("u1", "A"), _record("u2", "B")),
        total=6304,
        page=1,
        page_count=120,
    )
    second = SearchPage(
        records=(_record("u2", "B"), _record("u3", "C")),
        total=6304,
        page=2,
        page_count=120,
    )

    merged = _merge_pages([first, second])

    assert [record.url for record in merged.records] == ["u1", "u2", "u3"]
    assert merged.total == 6304
    assert merged.page_count == 120
