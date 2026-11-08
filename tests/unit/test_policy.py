from __future__ import annotations

import json
from datetime import date
from typing import cast

import pytest

from scholar_search.core.config import HARD
from scholar_search.core.contracts import Action, Plan, Verb
from scholar_search.core.errors import PolicyError
from scholar_search.core.policy import PolicyEngine
from support import make_manifest


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def engine(clock: FakeClock | None = None, **kwargs: object) -> PolicyEngine:
    clock = clock or FakeClock()
    return PolicyEngine(clock=clock.time, sleeper=clock.sleep, **kwargs)  # type: ignore[arg-type]


def test_rejects_unknown_verb() -> None:
    policy = engine()
    action = Action(cast(Verb, "eval"), {"code": "1+1"})
    plan = Plan(channel="fake", purpose="search", actions=(action,))
    with pytest.raises(PolicyError, match="unknown verb"):
        policy.validate_plan(plan, make_manifest())


def test_rejects_verb_not_in_manifest() -> None:
    policy = engine()
    plan = Plan(channel="fake", purpose="search", actions=(Action("click", {"selector": "a"}),))
    with pytest.raises(PolicyError, match="does not allow"):
        policy.validate_plan(plan, make_manifest(verbs=("goto", "read_html")))


def test_rejects_non_https() -> None:
    policy = engine()
    with pytest.raises(PolicyError, match="https"):
        policy.check_url("http://example.org/", ("example.org",))


def test_rejects_foreign_domain() -> None:
    policy = engine()
    with pytest.raises(PolicyError, match="not allowed"):
        policy.check_url("https://evil.test/", ("example.org",))


def test_allows_subdomain() -> None:
    policy = engine()
    policy.check_url("https://kns.example.org/x", ("example.org",))


def test_rejects_oversized_plan() -> None:
    policy = engine()
    actions = tuple(Action("read_html") for _ in range(HARD.max_actions_per_plan + 1))
    plan = Plan(channel="fake", purpose="search", actions=actions)
    with pytest.raises(PolicyError, match="actions"):
        policy.validate_plan(plan, make_manifest())


def test_sleep_is_bounded() -> None:
    policy = engine()
    plan = Plan(channel="fake", purpose="search", actions=(Action("sleep", {"ms": 5000}),))
    with pytest.raises(PolicyError, match="sleep"):
        policy.validate_plan(plan, make_manifest())


def test_wait_turn_enforces_interval(tmp_path) -> None:
    clock = FakeClock()
    policy = engine(clock, state_path=tmp_path / "quota.json")
    first = policy.wait_turn()
    assert first == 0.0
    second = policy.wait_turn()
    assert second >= HARD.min_interval_ms / 1000
    assert clock.sleeps


def test_scroll_accepts_a_relative_offset() -> None:
    policy = engine()
    plan = Plan(channel="fake", purpose="search", actions=(Action("scroll", {"by": 800}),))
    policy.validate_plan(plan, make_manifest(verbs=("scroll",)))


def test_scroll_rejects_an_unknown_parameter() -> None:
    policy = engine()
    plan = Plan(channel="fake", purpose="search", actions=(Action("scroll", {"sideways": 1}),))
    with pytest.raises(PolicyError, match="params"):
        policy.validate_plan(plan, make_manifest(verbs=("scroll",)))


def test_quota_exhaustion(tmp_path) -> None:
    clock = FakeClock()
    policy = engine(clock, state_path=tmp_path / "quota.json")
    for _ in range(HARD.daily_request_limit):
        policy.wait_turn()
        policy.note_request()
    assert policy.remaining_today == 0
    with pytest.raises(PolicyError, match="quota"):
        policy.wait_turn()


def test_rebooted_clock_does_not_sleep_for_the_previous_uptime(tmp_path) -> None:
    """`last` is a monotonic stamp, and a reboot restarts it from zero."""

    state = tmp_path / "quota.json"
    state.write_text(
        json.dumps({"day": date.today().isoformat(), "used": 1, "last": 1_000_000.0}),
        encoding="utf-8",
    )
    clock = FakeClock()
    clock.now = 12.0  # just booted; the stamp belongs to the previous uptime
    policy = engine(clock, state_path=state)

    slept = policy.wait_turn()

    assert slept <= HARD.max_interval_ms / 1000 + 1
    assert sum(clock.sleeps) < 20, "a backwards clock must not become a multi-hour sleep"
