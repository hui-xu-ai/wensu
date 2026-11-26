from __future__ import annotations

from pathlib import Path

import pytest

from scholar_search.adapters.fixture import FixtureAdapter
from scholar_search.core.audit import AuditLog
from scholar_search.core.contracts import Action, Plan, RiskSignal
from scholar_search.core.errors import RiskBlocked
from scholar_search.core.planner import Planner
from scholar_search.core.policy import PolicyEngine
from scholar_search.core.risk import RiskGuard
from support import make_manifest


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def build(tmp_path: Path, adapter: FixtureAdapter) -> Planner:
    clock = FakeClock()
    return Planner(
        adapter=adapter,
        policy=PolicyEngine(
            clock=clock.time,
            sleeper=clock.sleep,
            state_path=tmp_path / "quota.json",
        ),
        risk=RiskGuard(state_path=tmp_path / "cooldown.json"),
        audit=AuditLog(path=tmp_path / "audit.jsonl"),
    )


def test_plan_runs_in_order(tmp_path: Path) -> None:
    adapter = FixtureAdapter(
        [
            {"verb": "goto", "data": {"url": "https://example.org/"}},
            {"verb": "read_html", "data": {"html": "<html>ok</html>"}},
        ]
    )
    plan = Plan(
        channel="fake",
        purpose="search",
        actions=(
            Action("goto", {"url": "https://example.org/search"}),
            Action("read_html"),
        ),
    )

    outcomes = build(tmp_path, adapter).run(plan, make_manifest())

    assert [o.action.verb for o in outcomes] == ["goto", "read_html"]
    assert adapter.remaining == 0
    assert (tmp_path / "audit.jsonl").read_text(encoding="utf-8").count("action") == 2


def test_risk_stops_plan_before_next_action(tmp_path: Path) -> None:
    adapter = FixtureAdapter(
        [
            {"verb": "goto", "data": {"url": "https://example.org/"}},
            {"verb": "read_html", "data": {"captcha_visible": True}},
            {"verb": "read_html", "data": {"html": "<html>never</html>"}},
        ]
    )
    plan = Plan(
        channel="fake",
        purpose="search",
        actions=(
            Action("goto", {"url": "https://example.org/search"}),
            Action("read_html"),
            Action("read_html"),
        ),
    )

    with pytest.raises(RiskBlocked):
        build(tmp_path, adapter).run(plan, make_manifest())

    assert adapter.remaining == 1, "third action must never execute"
    assert "risk" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_existing_cooldown_blocks_before_any_action(tmp_path: Path) -> None:
    risk = RiskGuard(state_path=tmp_path / "cooldown.json")
    # A refusal cools down; a captcha stops the plan but leaves no cooldown behind (ADR 0022 r1).
    risk.trip(RiskSignal.HTTP_403)

    adapter = FixtureAdapter([{"verb": "goto"}])
    planner = Planner(
        adapter=adapter,
        policy=PolicyEngine(state_path=tmp_path / "quota.json"),
        risk=risk,
        audit=AuditLog(path=tmp_path / "audit.jsonl"),
    )
    plan = Plan(channel="fake", purpose="search", actions=(Action("read_html"),))

    with pytest.raises(RiskBlocked):
        planner.run(plan, make_manifest())
    assert adapter.remaining == 1
