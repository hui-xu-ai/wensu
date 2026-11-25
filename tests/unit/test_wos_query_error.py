"""A refused expression must be quoted, not reported as "the result list never appeared".

Measured 2026-11-24 with `TS=(ionic OR electroactive) AND actuator`: Web of Science answered
with an alert — 「检索错误: 布尔运算符的使用无效。请检查您的检索式…」 — and the tool waited 15 s
for a result list that was never coming, then said the click had not started a query. The site
had already explained itself; nothing read it.
"""

from __future__ import annotations

import pytest

from scholar_search.channels.webofscience.v2026_11 import parse_records

CHINESE_ALERT = (
    "Science 核心合集引文索引:All 字段检索 检索式生成器 被引参考文献 "
    "检索错误: 布尔运算符的使用无效。请检查您的检索式，确保检索词之间的布尔运算符 "
    "(AND、OR、NOT) 使用正确。将检索词添加到检索式预览"
)
ENGLISH_ALERT = (
    "Search error: Invalid Boolean operator. Check that the Boolean operators (AND, OR, NOT) "
    "between your search terms are used correctly."
)


def test_the_chinese_alert_is_quoted_as_one_sentence() -> None:
    message = parse_records.query_error(CHINESE_ALERT)

    assert message == "检索错误: 布尔运算符的使用无效。", message


def test_the_english_alert_is_recognised() -> None:
    message = parse_records.query_error(ENGLISH_ALERT)

    assert message is not None
    assert "Invalid Boolean operator" in message, message


@pytest.mark.parametrize(
    "text",
    [
        "Your search found no results Check the spelling and/or broaden your search",
        "no records found for this query",
        "检索结果 0 条",
        "",
        "   ",
    ],
)
def test_a_zero_result_page_is_not_a_refusal(text: str) -> None:
    """Both use the same alert container, so the empty wording has to win."""

    assert parse_records.query_error(text) is None


def test_a_plain_results_page_says_nothing() -> None:
    assert parse_records.query_error("1,234 results from Web of Science Core Collection") is None


def test_the_quote_is_bounded() -> None:
    message = parse_records.query_error("检索错误: " + "x" * 5_000)

    assert message is not None
    assert len(message) <= 200, len(message)


def test_a_kernel_refusal_becomes_a_channel_error() -> None:
    """`_run_tail` translates: a failed tail plus a refusal page is the site speaking."""

    from scholar_search.core.contracts import Action, Plan
    from scholar_search.core.errors import ActionError, ChannelError
    from scholar_search.core.service import ScholarService

    class FakeService(ScholarService):  # type: ignore[misc]
        def __init__(self) -> None:
            pass

        def _run(self, plan: object, spec: object) -> tuple[()]:
            raise ActionError(
                "wait_for failed: timeout",
                verb="wait_for",
                code="timeout",
                stage="wait.result-list",
            )

        def _site_diagnosis(self, impl: object, spec: object) -> tuple[str, bool]:
            return ("检索错误: 布尔运算符的使用无效。", False)

    tail = Plan(
        channel="webofscience",
        purpose="search",
        actions=(Action("wait_for", {"selector": "#next", "state": "visible"}, timeout_ms=1_000),),
    )
    with pytest.raises(ChannelError) as caught:
        FakeService()._run_tail(object(), object(), tail)  # type: ignore[arg-type]

    assert "refused this query" in str(caught.value)
    assert "布尔运算符" in str(caught.value)
