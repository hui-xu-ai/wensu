"""A page that matched nothing must not be reported as a refused expression.

Acceptance run 2026-11-25 (Chinese UI of `www.webofscience.com`): two legal zero-hit
expressions — `TS=(zqxionicactuatorprobe) AND PY=(2026)` and
`TS=(ionogel AND actuator*) AND PY=(2001)` — both came back as

    the site refused this query (query.rejected): 布尔运算符 : AND, OR, NOT字段标识 :…

which is the advanced-search **help panel**, not a refusal (P1 in the report). Two things
were wrong at once: the diagnosis read the whole page, so the help panel below the alert
answered instead of the alert itself; and the zero-hit wording list is English-only
(`EMPTY_MARKERS`), so on a localized UI nothing identified the page as an empty result.

The contract here:

* the channel names the alert container and the diagnosis reads **that element** — the
  element the site fills with either wording (`<div role="alert" class="search-error">`);
* an alert that does not refuse the expression **is** the site's "no results" answer, which
  needs no wording list at all and therefore works on every UI language;
* the tail looks at the alert *before* spending the 15 s result-list budget, so the answer
  costs 2 s instead of 14.8 s (P3 in the report).
"""

from __future__ import annotations

import pytest

from scholar_search.channels.webofscience.v2026_11 import parse_records, selectors
from scholar_search.core.contracts import Action, ActionOutcome, Plan
from scholar_search.core.errors import ActionError, ChannelError
from scholar_search.core.service import ScholarService

# Quoted from the 2026-11-25 run: the help panel that sits on the advanced-search form. It
# names the boolean operators, which is why it used to be mistaken for a refusal.
HELP_PANEL = (
    "布尔运算符 : AND, OR, NOT字段标识 :排序方式默认 TS=主题 TI=标题 AB=摘要 AU=[作者] "
    "AI=作者标识符 AK=作者关键词 出版年= PY= 地址= AD= 机构扩展= OG= 语种= LA= "
    "文献类型= DT= 基金资助= FU= 来源出版物= SO= 国家/地"
)
REFUSAL = "检索错误: 布尔运算符的使用无效。请检查您的检索式，确保检索词之间使用正确。"


class _Spec:
    """The registry entry the probe plan is built from; only its name is used."""

    name = "webofscience"


_SPEC = _Spec()


class _Channel:
    """A channel that names its alert container, the way Web of Science does."""

    alert_selector = selectors.ALERT

    def query_error(self, text: str) -> str | None:
        return parse_records.query_error(text)

    def is_empty_page(self, text: str) -> bool:
        return parse_records.is_empty_page(text)


class _PageOnlyChannel:
    """A channel without an alert container (CNKI): wording lists are all it has."""

    def is_empty_page(self, text: str) -> bool:
        return "no results" in text


class _Service(ScholarService):  # type: ignore[misc]
    """Records the probe plan, and answers it with a fixed page instead of a browser."""

    def __init__(self, *, text: str = "", failure: str | None = None) -> None:
        self.probes: list[Plan] = []
        self._text = text
        self._failure = failure

    def _run(self, plan: Plan, spec: object) -> tuple[ActionOutcome, ...]:
        self.probes.append(plan)
        if self._failure is not None:
            raise ActionError(self._failure, verb="read_text", code=self._failure, stage="read")
        action = plan.actions[0]
        return (ActionOutcome(action=action, ok=True, data={"text": self._text}),)


class _TailService(_Service):
    """The result-list wait times out; a probe plan is answered from the page instead."""

    def __init__(self, *, text: str, alert: bool = True) -> None:
        super().__init__(text=text, failure=None if alert else "not_found")

    def _run(self, plan: Plan, spec: object) -> tuple[ActionOutcome, ...]:
        if plan.purpose == "probe":
            return super()._run(plan, spec)
        raise ActionError(
            "wait_for failed: timeout",
            verb="wait_for",
            code="timeout",
            stage="wait.result-list",
        )


# A tail whose first action is the result-list wait: the shape every channel's tail has, and
# the only thing the slicing logic looks at. The budget is small so a test that exhausts it
# finishes in milliseconds.
_TAIL = Plan(
    channel="webofscience",
    purpose="search",
    actions=(
        Action(
            "wait_for",
            {"selector": selectors.RESULT_READY, "state": "visible"},
            timeout_ms=4_000,
        ),
        Action("click", {"selector": "#export-trigger-btn"}),
    ),
)


class _LoopService(ScholarService):  # type: ignore[misc]
    """Sliced waits time out until `slices_before_results`, and the page answers from `probes`.

    `probes` is the sequence of `read_text` answers: `None` means the alert container is not
    there (a real `not_found`), a string is what it says.
    """

    def __init__(self, *, slices_before_results: int, probes: list[str | None]) -> None:
        self.slice_timeouts = 0
        self.probes_taken = 0
        self.slice_budgets: list[int] = []
        self._results_after = slices_before_results
        self._probes = probes

    def _run(self, plan: Plan, spec: object) -> tuple[ActionOutcome, ...]:
        first = plan.actions[0]
        if plan.purpose == "probe":
            index = min(self.probes_taken, len(self._probes) - 1) if self._probes else 0
            self.probes_taken += 1
            text = self._probes[index] if self._probes else None
            if text is None:
                raise ActionError("not_found", verb="read_text", code="not_found", stage="read")
            return (ActionOutcome(action=first, ok=True, data={"text": text}),)
        params = first.params or {}
        if isinstance(params.get("timeout_ms"), int):
            self.slice_budgets.append(int(params["timeout_ms"]))
        if self._results_after > 0:
            self._results_after -= 1
            self.slice_timeouts += 1
            raise ActionError(
                "wait_for failed: timeout",
                verb="wait_for",
                code="timeout",
                stage="wait.result-list",
            )
        return (ActionOutcome(action=first, ok=True, data={}),)


def test_the_help_panel_is_not_a_refusal() -> None:
    assert parse_records.query_error(HELP_PANEL) is None


def test_a_refusal_still_quotes_its_own_sentence() -> None:
    assert parse_records.query_error(REFUSAL + HELP_PANEL) == "检索错误: 布尔运算符的使用无效。"


def test_an_alert_that_does_not_refuse_is_the_no_results_answer() -> None:
    """No wording list: "the alert is up and says nothing about the expression" is enough."""

    service = _Service(text="您的检索没有找到任何记录，请检查拼写或扩大检索范围。")

    assert service._site_diagnosis(_Channel(), _SPEC) == (None, True)


def test_a_refusal_inside_the_alert_is_reported() -> None:
    service = _Service(text=REFUSAL)

    refusal, nothing_matched = service._site_diagnosis(_Channel(), _SPEC)

    assert refusal == "检索错误: 布尔运算符的使用无效。"
    assert nothing_matched is False


def test_the_probe_reads_the_alert_and_not_the_whole_page() -> None:
    service = _Service(text="未找到记录")

    service._site_diagnosis(_Channel(), _SPEC)

    (probe,) = service.probes
    (read,) = probe.actions
    assert read.verb == "read_text"
    assert read.params["selector"] == selectors.ALERT
    # `inner`: rendered text only, so a hidden alert container is not mistaken for a message.
    assert read.params["mode"] == "inner"


def test_a_missing_alert_is_inconclusive() -> None:
    """The page carried no alert: the result list really did not appear."""

    service = _Service(failure="not_found")

    assert service._site_diagnosis(_Channel(), _SPEC) == (None, False)


def test_an_alert_with_nothing_rendered_is_inconclusive() -> None:
    service = _Service(text="   ")

    assert service._site_diagnosis(_Channel(), _SPEC) == (None, False)


def test_a_channel_without_an_alert_still_reads_the_page() -> None:
    service = _Service(text="your search found no results")

    assert service._site_diagnosis(_PageOnlyChannel(), _SPEC) == (None, True)
    (probe,) = service.probes
    assert probe.actions[0].params["selector"] == "body"


def test_the_phase_after_the_click_returns_an_answer_when_nothing_matched() -> None:
    """A zero-hit search is an answer: the caller gets an empty page, not a failure."""

    service = _TailService(text="您的检索没有找到任何记录，请检查拼写或扩大检索范围。")

    assert service._run_tail(_Channel(), _SPEC, _TAIL) is None


def test_the_phase_after_the_click_still_raises_on_a_real_timeout() -> None:
    service = _TailService(text="", alert=False)

    with pytest.raises(ActionError):
        service._run_tail(_Channel(), _SPEC, _TAIL)


def test_the_result_wait_is_taken_in_slices_so_the_page_can_be_asked_between_them() -> None:
    """The banner is not in the DOM when the click returns.

    Measured 2026-11-25 on the live site: a single look right after the click passed in 2 ms
    (nothing there yet) and the refusal still cost 10.8 s. So the wait is sliced and the page
    is asked between slices — whichever of "results" and "the site answered" comes first wins.
    """

    service = _LoopService(slices_before_results=2, probes=[None, None, None])

    outcomes = service._run_tail(_Channel(), _SPEC, _TAIL)

    assert outcomes is not None
    assert service.slice_timeouts == 2, service.slice_timeouts
    assert service.probes_taken == 2, service.probes_taken
    # Each slice is a fraction of the budget the tail asked for, never the whole of it.
    assert all(slice_ms < _TAIL.actions[0].timeout_ms for slice_ms in service.slice_budgets)


def test_a_refusal_is_reported_at_the_next_slice_not_after_the_budget() -> None:
    service = _LoopService(slices_before_results=99, probes=[REFUSAL])

    with pytest.raises(ChannelError) as caught:
        service._run_tail(_Channel(), _SPEC, _TAIL)

    assert "refused this query" in str(caught.value)
    assert service.slice_timeouts == 1, service.slice_timeouts


def test_a_zero_hit_page_ends_the_polling_with_an_empty_answer() -> None:
    service = _LoopService(slices_before_results=99, probes=["未找到记录"])

    assert service._run_tail(_Channel(), _SPEC, _TAIL) is None
    assert service.slice_timeouts == 1, service.slice_timeouts


def test_a_channel_without_an_alert_waits_in_one_piece() -> None:
    """No alert container means nothing to ask between slices: one wait, as before."""

    service = _LoopService(slices_before_results=0, probes=[])

    service._run_tail(_PageOnlyChannel(), _SPEC, _TAIL)

    assert service.slice_budgets == [], service.slice_budgets


@pytest.mark.parametrize("selector", [selectors.ALERT])
def test_the_alert_selector_is_not_read_as_a_capture_wait(selector: str) -> None:
    """`_stage_of` decides whether the failure is diagnosed at all: it must say result-list."""

    stage = ScholarService._stage_of(
        ActionOutcome(action=Action("wait_for", {"selector": selector}), ok=False), 0
    )

    assert stage == "wait.result-list", stage
