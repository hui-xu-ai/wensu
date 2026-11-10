from __future__ import annotations

from pathlib import Path

import pytest

from scholar_search.channels.cnki.v2026_10 import parse_detail, plan_search
from scholar_search.core.config import HARD
from scholar_search.core.contracts import SearchQuery, SortOrder

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "cnki_detail_online_metadata_2026_10.html"
)
URL = "https://kns.cnki.net/kcms2/article/abstract?v=fixture"


def test_online_first_keeps_explicit_journal_type() -> None:
    record = parse_detail.parse(FIXTURE.read_text(encoding="utf-8"), URL)
    assert record.doc_type == "journal"
    assert record.volume is None
    assert record.issue is None
    assert record.pages is None


def test_unrelated_metadata_does_not_invent_a_type() -> None:
    html = FIXTURE.read_text(encoding="utf-8").replace(
        '<div class="doc-top">文献类型：期刊</div>', ""
    )
    assert parse_detail.parse(html, URL).doc_type is None


def test_explicit_thesis_type_wins_over_source_words() -> None:
    html = FIXTURE.read_text(encoding="utf-8").replace("文献类型：期刊", "硕士学位论文")
    assert parse_detail.parse(html, URL).doc_type == "thesis"


def test_labelled_type_field_wins_over_compact_header() -> None:
    html = FIXTURE.read_text(encoding="utf-8").replace("文献类型：期刊", "会议")
    html = html.replace(
        "<ul>",
        '<ul><li class="top-space"><span class="rowtit">文献类型：</span><p>硕士学位论文</p></li>',
    )
    assert parse_detail.parse(html, URL).doc_type == "thesis"


def test_unknown_explicit_type_stays_unknown() -> None:
    html = FIXTURE.read_text(encoding="utf-8").replace("文献类型：期刊", "文献类型：未来类型")
    assert parse_detail.parse(html, URL).doc_type is None


@pytest.mark.parametrize("text", ["IPMC驱动器", "SU='IPMC' and KY='驱动器'"])
@pytest.mark.parametrize("page", [1, 2, 3])
@pytest.mark.parametrize("sort", ["relevance", "date", "citation"])
@pytest.mark.parametrize("limit", [1, 50])
def test_search_waits_reserve_reply_time(text: str, page: int, sort: SortOrder, limit: int) -> None:
    # Validate every public search combination without opening a browser.
    query = SearchQuery(text, page=page, sort=sort, limit=limit)
    plan = plan_search.build(query)
    assert sum(action.timeout_ms for action in plan.actions) <= HARD.max_plan_seconds * 1000
    waits = [action for action in plan.actions if action.verb == "wait_for"]
    assert waits
    for action in waits:
        assert action.params["timeout_ms"] + 2_000 <= action.timeout_ms <= 15_000


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("《期刊》", "journal"),
        ("《期刊》网络首发", "journal"),
        ("期刊（网络首发）", "journal"),
        ("文献类型：期刊（网络首发）", "journal"),
        ("文献类型：期刊论文", "journal"),
        ("《硕士学位论文》", "thesis"),
    ],
)
def test_decorated_type_values_keep_their_type(value: str, expected: str) -> None:
    base = FIXTURE.read_text(encoding="utf-8")
    html = base.replace(
        '<div class="doc-top">文献类型：期刊</div>',
        f'<div class="doc-top">{value}</div>',
    )
    assert parse_detail.parse(html, URL).doc_type == expected


def test_dissertation_doi_marks_thesis() -> None:
    html = (
        '<html><body><div class="wx-tit"><h1>某学位论文</h1></div>'
        '<div class="top-first">某大学 . 2024</div>'
        '<ul><li class="top-space"><span class="rowtit">DOI：</span>'
        "<p>10.27300/d.cnki.gx.2024.000001</p></li></ul>"
        '<div id="ChDivSummary">摘要</div></body></html>'
    )
    record = parse_detail.parse(html, "https://kns.cnki.net/kcms2/article/abstract?v=x")
    assert record.doc_type == "thesis"
