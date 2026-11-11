"""A refused navigation must say which host it reached.

The stored reason was `login_redirect after goto`, and the error was
`goto failed: policy.domain`. Neither says *where* the tab went, and three very different
situations produce exactly that pair:

* an institutional sign-in (the campus SSO hop that actually happened),
* a publisher's own login wall,
* a redirect to another legitimate WoS host.

The first is fixed by signing in, the third by adding a domain to the manifest, and
telling them apart took an inference chain across three files. The host is the missing
fact, and it costs nothing to record: a host is not account data.
"""

from __future__ import annotations

from scholar_search.core.contracts import Action, ActionOutcome, Plan
from scholar_search.core.planner import _risk_reason
from scholar_search.core.risk import RiskSignal
from scholar_search.core.service import ScholarService


def _plan(*actions: Action) -> Plan:
    return Plan(channel="webofscience", purpose="search", actions=actions)


REFUSED = ActionOutcome(
    action=Action("goto", {"url": "https://webofscience.clarivate.cn/wos/woscc/advanced-search"}),
    ok=False,
    error="policy.domain",
    data={"url": "https://carsi.example.edu.cn/idp/login?entityId=wos&ticket=SECRET123"},
)


def test_the_stored_reason_names_the_host() -> None:
    reason = _risk_reason(RiskSignal.LOGIN_REDIRECT, REFUSED.action, REFUSED)
    assert "carsi.example.edu.cn" in reason
    assert reason.startswith("login_redirect after goto")


def test_the_stored_reason_does_not_copy_the_query() -> None:
    """Host only. The path can carry a session ticket, and the audit is not a place
    for one."""

    reason = _risk_reason(RiskSignal.LOGIN_REDIRECT, REFUSED.action, REFUSED)
    assert "SECRET123" not in reason
    assert "idp/login" not in reason
    assert "entityId" not in reason


def test_the_error_message_names_the_host_too() -> None:
    """The person reading the failure sees the same fact as the audit."""

    message = ScholarService._failure_message(REFUSED, 0, _plan(REFUSED.action))
    assert message.startswith("goto failed: policy.domain")
    assert "[reached carsi.example.edu.cn]" in message


def test_a_failure_without_a_url_still_reads_correctly() -> None:
    bare = ActionOutcome(action=Action("click", {"selector": "x"}), ok=False, error="timeout")
    reason = _risk_reason(RiskSignal.CAPTCHA, bare.action, bare)
    assert "at " not in reason
    assert "captcha after click" in reason
    assert "[reached" not in ScholarService._failure_message(bare, 0, _plan(bare.action))


def test_the_top_level_url_field_is_used_when_data_has_none() -> None:
    outcome = ActionOutcome(
        action=Action("goto", {}),
        ok=False,
        error="policy.domain",
        url="https://fsso.example.edu/login",
    )
    assert "fsso.example.edu" in _risk_reason(RiskSignal.LOGIN_REDIRECT, outcome.action, outcome)
