from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scholar_search.core.contracts import Action, ActionOutcome, RiskSignal
from scholar_search.core.errors import RiskBlocked
from scholar_search.core.risk import RiskGuard


def outcome(
    *,
    data: dict[str, str] | None = None,
    error: str | None = None,
    url: str | None = None,
) -> ActionOutcome:
    return ActionOutcome(
        action=Action("read_html"),
        ok=error is None,
        data=data or {},
        error=error,
        url=url,
    )


def guard(tmp_path: Path) -> RiskGuard:
    return RiskGuard(state_path=tmp_path / "cooldown.json")


def test_detects_visible_captcha_widget(tmp_path: Path) -> None:
    signal = guard(tmp_path).inspect(outcome(data={"captcha_visible": True}))
    assert signal is RiskSignal.CAPTCHA


def test_hidden_sdk_dom_is_not_a_captcha(tmp_path: Path) -> None:
    # The captcha SDK preloads DOM; text alone must not trigger a cooldown.
    assert guard(tmp_path).inspect(outcome(data={"html": "验证码登录"})) is None
    assert guard(tmp_path).inspect(outcome(data={"captcha_visible": False})) is None


def test_verification_page_title_is_a_risk(tmp_path: Path) -> None:
    signal = guard(tmp_path).inspect(outcome(data={"title": "安全验证"}))
    assert signal is RiskSignal.VERIFY_REDIRECT


def test_account_verification_gate_is_a_login_wall(tmp_path: Path) -> None:
    signal = guard(tmp_path).inspect(outcome(data={"auth_required": True}))
    assert signal is RiskSignal.LOGIN_REDIRECT


def test_detects_verify_redirect(tmp_path: Path) -> None:
    signal = guard(tmp_path).inspect(outcome(url="https://kns.cnki.net/verify/home?x=1"))
    assert signal is RiskSignal.VERIFY_REDIRECT


def test_detects_http_403(tmp_path: Path) -> None:
    signal = guard(tmp_path).inspect(outcome(error="http 403 forbidden"))
    assert signal is RiskSignal.HTTP_403


def test_detects_login_redirect(tmp_path: Path) -> None:
    signal = guard(tmp_path).inspect(outcome(url="https://fsso.cnki.net/login"))
    assert signal is RiskSignal.LOGIN_REDIRECT


def test_clean_outcome_has_no_signal(tmp_path: Path) -> None:
    assert guard(tmp_path).inspect(outcome(data={"html": "<html>ok</html>"})) is None


def test_trip_sets_cooldown_and_blocks(tmp_path: Path) -> None:
    risk = guard(tmp_path)
    blocked = risk.trip(RiskSignal.CAPTCHA, "captcha appeared")

    assert blocked.signal == "captcha"
    assert blocked.to_payload()["action_required"] == "manual_verification"
    with pytest.raises(RiskBlocked):
        risk.ensure_ready()


def test_expired_cooldown_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "cooldown.json"
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    path.write_text(f'{{"until": "{past.isoformat()}", "signal": "captcha"}}', encoding="utf-8")

    risk = RiskGuard(state_path=path)
    risk.ensure_ready()  # must not raise


def test_clear_removes_cooldown(tmp_path: Path) -> None:
    risk = guard(tmp_path)
    risk.trip(RiskSignal.VERIFY_REDIRECT)
    risk.clear()
    risk.ensure_ready()


def test_article_titles_do_not_trigger_a_gate(tmp_path: Path) -> None:
    """A paper may legitimately carry "Access Denied" or "sign in" in its title.

    Matching those as substrings cost a full day of cooldown for reading an
    ordinary article, so only a title that *is* the gate counts now.
    """

    risk = guard(tmp_path)
    for title in (
        "Access Denied: 论跨境数据主权 - 中国知网",
        "How to sign in to a legacy system - 中国知网",
        "When access denied errors reveal design flaws",
    ):
        assert risk.inspect(outcome(data={"title": title})) is None


def test_real_gate_titles_still_trigger(tmp_path: Path) -> None:
    risk = guard(tmp_path)
    for title in ("Sign In", "Sign In - Web of Science", "安全验证", "Session Expired"):
        assert risk.inspect(outcome(data={"title": title})) is RiskSignal.VERIFY_REDIRECT


def test_doi_containing_sso_is_not_a_login_redirect(tmp_path: Path) -> None:
    """The bare substring "sso" matched 10.1002/essoar.10501234."""

    risk = guard(tmp_path)
    doi_url = "https://onlinelibrary.wiley.com/doi/10.1002/essoar.10501234"
    assert risk.inspect(outcome(url=doi_url)) is None


def test_a_real_sso_hop_still_redirects(tmp_path: Path) -> None:
    risk = guard(tmp_path)
    for url in (
        "https://sso.clarivate.com/authorize",
        "https://login.webofscience.com/sso/authorize",
        "https://fsso.cnki.net/wayf",
    ):
        assert risk.inspect(outcome(url=url)) is RiskSignal.LOGIN_REDIRECT
