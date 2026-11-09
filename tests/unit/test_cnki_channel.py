from __future__ import annotations

from pathlib import Path

from scholar_search.channels.cnki.v2026_10 import get_channel, plan_search
from scholar_search.core.contracts import SearchQuery

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "cnki_search_2026_10.html"
DETAIL_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "cnki_detail_2026_10.html"
PRINT_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "cnki_detail_print_2026_10.html"
MIXED_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "cnki_search_mixed_types.html"

SEARCH_HTML = """
<html><body>
  <div class="pagerTitleCell">共找到 1,234 条结果</div>
  <div class="countPageMark">1/62</div>
  <table class="result-table-list"><tbody>
    <tr>
      <td class="name">
        <a class="fz14" href="/kcms2/article/abstract?v=abc">测试论文标题</a>
      </td>
      <td class="author">
        <a class="KnowledgeNetLink">张三</a><a class="KnowledgeNetLink">李四</a>
      </td>
      <td class="source"><a>测试期刊</a></td>
      <td class="date">2026-10-14 11:22</td>
      <td class="quote">12</td>
      <td class="download">34</td>
      <td><input class="cbItem" value="EXP1"></td>
    </tr>
    <tr>
      <td class="name"><a class="fz14" href="/kcms2/article/abstract?v=def">第二篇</a></td>
      <td class="author"><a class="KnowledgeNetLink">王五</a></td>
      <td class="source"><a>另一期刊</a></td>
      <td class="date">2024-03-01</td>
      <td class="quote">0</td>
      <td class="download"></td>
      <td><input class="cbItem" value="EXP2"></td>
    </tr>
  </tbody></table>
</body></html>
"""

DETAIL_HTML = """
<html><body>
  <h1>测试论文标题</h1>
  <div class="author"><a>张三</a><a>李四</a></div>
  <div class="orgn">某大学某学院</div>
  <div id="ChDivSummary">这是摘要正文。</div>
  <p class="keywords"><a>关键词一</a><a>关键词二</a></p>
  <p class="doi">DOI：10.16290/j.cnki.1674-5205.2026.06.008</p>
  <div class="top-tip">《测试期刊》2026年06期</div>
</body></html>
"""


def test_manifest_declares_search_and_detail() -> None:
    channel = get_channel()
    assert channel.manifest.channel == "cnki"
    assert "search" in channel.manifest.capabilities
    assert "detail" in channel.manifest.capabilities
    assert "journal" not in channel.manifest.capabilities


def test_search_plan_uses_the_expert_form_for_a_bare_keyword() -> None:
    """A plain keyword is wrapped as SU=..., not sent to the one-box search.

    Two entry points that do the same thing forced the caller to choose between them
    for no benefit, so the one-box path was removed. `SU=` is the topic search, which
    is what that box did anyway.
    """

    plan = plan_search.build(SearchQuery(text="人工智能", channel="cnki"))
    assert plan.purpose == "search"
    assert [action.verb for action in plan.actions] == [
        "goto",
        "sleep",
        "wait_for",
        "type",
        "click",
        "wait_for",
        "read_html",
    ]
    assert str(plan.actions[0].params["url"]).startswith(
        "https://kns.cnki.net/kns8s/AdvSearch?type=expert"
    )
    assert plan.actions[3].params["text"] == "SU='人工智能'"


def test_expression_plan_uses_expert_page() -> None:
    expression = "SU='IPMC' and KY='驱动器'"
    plan = plan_search.build(SearchQuery(text=expression, channel="cnki"))

    assert str(plan.actions[0].params["url"]).startswith(
        "https://kns.cnki.net/kns8s/AdvSearch?type=expert"
    )
    assert plan.actions[3].params["text"] == expression
    assert plan.actions[3].params["selector"] == "textarea.majorSearch"
    assert plan.actions[4].params["selector"] == "input.btn-search"


def test_all_documented_fields_route_to_expert_page() -> None:
    for field in (
        "SU",
        "TKA",
        "KY",
        "TI",
        "FT",
        "AU",
        "FI",
        "RP",
        "AF",
        "FU",
        "AB",
        "CO",
        "RF",
        "CLC",
        "LY",
        "DOI",
        "CF",
    ):
        plan = plan_search.build(SearchQuery(text=f"{field}='x'", channel="cnki"))
        assert str(plan.actions[0].params["url"]).startswith(
            "https://kns.cnki.net/kns8s/AdvSearch"
        ), field


def test_author_wildcard_routes_to_expert_page() -> None:
    plan = plan_search.build(SearchQuery(text="AU % '陈'", channel="cnki"))
    assert str(plan.actions[0].params["url"]).startswith("https://kns.cnki.net/kns8s/AdvSearch")


def test_page_two_adds_a_page_turn() -> None:
    plan = plan_search.build(SearchQuery(text="IPMC", channel="cnki", page=2))

    clicks = [action for action in plan.actions if action.verb == "click"]
    assert len(clicks) == 2
    assert clicks[1].params["selector"] == "#PageNext"
    assert plan.actions[-1].verb == "read_html"


def test_large_limit_switches_page_size() -> None:
    plan = plan_search.build(SearchQuery(text="IPMC", channel="cnki", limit=50))
    selectors = [action.params.get("selector") for action in plan.actions]
    assert "#perPageDiv li[data-val='50']" in selectors


def test_year_filters_do_not_touch_the_site_control() -> None:
    plan = plan_search.build(SearchQuery(text="IPMC", year_from=2020, year_to=2021))
    selectors = [action.params.get("selector") for action in plan.actions if action.verb == "click"]
    assert "#txtStartYear" not in selectors
    assert "#btnFilterYear" not in selectors


def test_sort_uses_result_grid_tabs() -> None:
    # The grid already opens on publication-time DESC; clicking would toggle it.
    plan = plan_search.build(SearchQuery(text="IPMC", channel="cnki", sort="date"))
    selectors = [action.params.get("selector") for action in plan.actions if action.verb == "click"]
    assert selectors.count("#orderList li[data-sort='PT']") == 1

    plan = plan_search.build(SearchQuery(text="IPMC", channel="cnki", sort="citation"))
    selectors = [action.params.get("selector") for action in plan.actions if action.verb == "click"]
    assert selectors.count("#orderList li[data-sort='CF']") == 1


def test_unsupported_filters_fail_loudly() -> None:
    import pytest

    from scholar_search.core.errors import ChannelError

    with pytest.raises(ChannelError, match="source-type"):
        plan_search.build(SearchQuery(text="IPMC", source_types=("journal",)))


def test_plan_stays_within_budget() -> None:
    plan = plan_search.build(SearchQuery(text="IPMC", channel="cnki", page=3))
    assert sum(action.timeout_ms for action in plan.actions) <= 120_000


def test_worst_case_plan_stays_within_budget() -> None:
    plan = plan_search.build(
        SearchQuery(text="IPMC", channel="cnki", page=3, limit=50, sort="date")
    )
    assert sum(action.timeout_ms for action in plan.actions) <= 120_000


def test_sleep_actions_leave_room_for_a_throttled_tab() -> None:
    # A background window aligns timers to one-second buckets, so a deadline
    # equal to the pause itself fires before the pause can answer.
    plan = plan_search.build(
        SearchQuery(text="IPMC", channel="cnki", page=3, limit=50, sort="date")
    )
    sleeps = [action for action in plan.actions if action.verb == "sleep"]
    assert sleeps
    for action in sleeps:
        assert action.timeout_ms - int(action.params["ms"]) >= 1_500


def test_parses_recorded_live_page() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    page = get_channel().parse_search(html, query=SearchQuery(text="IPMC"))

    assert page.total == 595
    assert page.page == 1
    assert page.page_count == 30
    assert len(page.records) == 2
    assert page.records[0].title
    assert page.records[0].url is not None
    assert page.records[0].url.startswith("https://kns.cnki.net/kcms2/article/abstract")
    assert page.records[0].source


def test_parse_search_extracts_rows() -> None:
    channel = get_channel()
    page = channel.parse_search(SEARCH_HTML, query=SearchQuery(text="x"))

    assert page.total == 1234
    assert page.page == 1
    assert page.page_count == 62
    assert len(page.records) == 2

    first = page.records[0]
    assert first.title == "测试论文标题"
    assert first.authors == ["张三", "李四"]
    assert first.source == "测试期刊"
    assert first.year == 2026
    assert first.citations == 12
    assert first.downloads == 34
    assert first.url == "https://kns.cnki.net/kcms2/article/abstract?v=abc"

    assert page.records[1].url == "https://kns.cnki.net/kcms2/article/abstract?v=def"


def test_parse_detail_from_recorded_page() -> None:
    html = DETAIL_FIXTURE.read_text(encoding="utf-8")
    record = get_channel().parse_detail(
        html, url="https://kns.cnki.net/kcms2/article/abstract?v=abc"
    )

    assert record.title.startswith("受马铃薯")
    assert not record.title.endswith("附视频")
    assert record.authors == ["张三", "李四", "王五"]
    assert record.institution is not None and "示例大学" in record.institution
    assert record.source == "复合材料学报"
    assert record.doi == "10.13801/j.cnki.fhclxb.20261013.003"
    assert record.year == 2026
    assert len(record.keywords) == 6
    assert record.abstract and "IPMC" in record.abstract


def test_parse_detail_extracts_print_issue() -> None:
    html = PRINT_FIXTURE.read_text(encoding="utf-8")
    record = get_channel().parse_detail(html, url="https://kns.cnki.net/x")

    assert record.title.startswith("软体连续机械臂")
    assert record.source == "力学学报"
    assert record.year == 2022
    assert record.volume == "54"
    assert record.issue == "01"
    assert record.pages == "184-195"


def test_parse_search_keeps_document_type() -> None:
    html = MIXED_FIXTURE.read_text(encoding="utf-8")
    page = get_channel().parse_search(html, query=SearchQuery(text="x"))

    assert [record.doc_type for record in page.records] == [
        "journal",
        "thesis",
        "conference",
    ]


def test_parse_search_normalises_prefixed_document_types() -> None:
    html = """
    <html><body>
      <div class="pagerTitleCell">共找到 3 条结果</div>
      <div class="countPageMark">1/1</div>
      <table class="result-table-list"><tbody>
        <tr><td class="name"><a class="fz14" href="/kcms2/article/abstract?v=b1">图书</a></td>
            <td class="data">中文图书</td></tr>
        <tr><td class="name"><a class="fz14" href="/kcms2/article/abstract?v=j2">期刊</a></td>
            <td class="data">外文期刊</td></tr>
        <tr><td class="name"><a class="fz14" href="/kcms2/article/abstract?v=u3">未知</a></td>
            <td class="data">法律法规</td></tr>
      </tbody></table>
    </body></html>
    """
    page = get_channel().parse_search(html, query=SearchQuery(text="x"))

    assert [record.doc_type for record in page.records] == ["book", "journal", None]


def test_detail_plan_wait_stays_below_action_budget() -> None:
    from scholar_search.channels.cnki.v2026_10 import plan_detail

    plan = plan_detail.build("https://kns.cnki.net/kcms2/article/abstract?v=x")
    wait = next(action for action in plan.actions if action.verb == "wait_for")
    assert wait.params["timeout_ms"] < wait.timeout_ms
    assert wait.params["selector"] == ".wx-tit h1, #ChDivSummary"


def _parse_detail_html(html: str):
    from scholar_search.channels.cnki.v2026_10 import parse_detail

    return parse_detail.parse(html, "https://kns.cnki.net/kcms2/article/abstract?v=x")


def test_journal_not_retyped_by_related_recommendation() -> None:
    html = PRINT_FIXTURE.read_text(encoding="utf-8")
    html += "<aside>相关推荐：某博士学位论文</aside>"
    record = _parse_detail_html(html)
    assert record.doc_type == "journal"
    assert record.volume == "54"


def test_journal_not_retyped_by_body_conference_word() -> None:
    html = PRINT_FIXTURE.read_text(encoding="utf-8")
    html += "<p>本期会议通知：请参会代表按时提交论文。</p>"
    record = _parse_detail_html(html)
    assert record.doc_type == "journal"


def test_thesis_type_from_metadata_header() -> None:
    html = """
    <html><body>
      <div class="doc-top">硕士学位论文</div>
      <div class="wx-tit"><h1>某硕士论文题目</h1></div>
      <div class="top-first">某大学 . 2024</div>
      <h3 class="author"><a>张三</a></h3>
      <div id="ChDivSummary">摘要正文</div>
    </body></html>
    """
    record = _parse_detail_html(html)
    assert record.doc_type == "thesis"
    assert record.source == "某大学"


def test_online_first_detail_is_journal_from_header_link() -> None:
    html = DETAIL_FIXTURE.read_text(encoding="utf-8")
    record = _parse_detail_html(html)
    assert record.doc_type == "journal"
    assert record.volume is None


def test_sort_fix_only_when_ascending() -> None:
    channel = get_channel()
    query = SearchQuery(text="x", channel="cnki", sort="date")
    asc = '<ul id="orderList"><li data-sort="PT" class="ASC cur">x</li></ul>'
    desc = '<ul id="orderList"><li data-sort="PT" class="DESC cur">x</li></ul>'

    plan = channel.sort_fix(query, asc)
    assert plan is not None
    assert any(action.verb == "click" for action in plan.actions)
    assert channel.sort_fix(query, desc) is None


def test_sort_fix_pause_also_carries_the_reply_margin() -> None:
    channel = get_channel()
    query = SearchQuery(text="x", channel="cnki", sort="date")
    asc = '<ul id="orderList"><li data-sort="PT" class="ASC cur">x</li></ul>'

    plan = channel.sort_fix(query, asc)
    assert plan is not None
    sleeps = [action for action in plan.actions if action.verb == "sleep"]
    assert sleeps
    for action in sleeps:
        assert action.timeout_ms - int(action.params["ms"]) >= 1_500
