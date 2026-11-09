from __future__ import annotations

from pathlib import Path

from scholar_search.adapters.fixture import FixtureAdapter
from scholar_search.core.audit import AuditLog
from scholar_search.core.cache import Cache
from scholar_search.core.contracts import SearchQuery
from scholar_search.core.planner import Planner
from scholar_search.core.policy import PolicyEngine
from scholar_search.core.risk import RiskGuard
from scholar_search.core.service import ScholarService
from support import FakeChannel, StubRegistry, make_manifest, make_record


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def build(tmp_path: Path, channel: FakeChannel, scripts: list[list[dict[str, object]]]):
    clock = FakeClock()
    policy = PolicyEngine(clock=clock.time, sleeper=clock.sleep, state_path=tmp_path / "quota.json")
    risk = RiskGuard(state_path=tmp_path / "cooldown.json")
    audit = AuditLog(path=tmp_path / "audit.jsonl")

    def factory() -> FixtureAdapter:
        return FixtureAdapter(scripts.pop(0))

    return ScholarService(
        registry=StubRegistry(channel),  # type: ignore[arg-type]
        adapter_factory=factory,
        planner_factory=lambda adapter: Planner(adapter, policy, risk, audit),
        policy=policy,
        cache=Cache(path=tmp_path / "cache.sqlite3"),
        bridge_probe=lambda: True,
    )


def test_search_honours_limit(tmp_path: Path) -> None:
    channel = FakeChannel(
        manifest=make_manifest(),
        records=[make_record(f"Paper {index}") for index in range(5)],
    )
    scripts = [
        [
            {"verb": "goto", "data": {}},
            {"verb": "read_html", "data": {"html": "<html>results</html>"}},
        ]
    ]
    service = build(tmp_path, channel, scripts)

    page = service.search(SearchQuery(text="x", channel="fake", limit=2))

    assert len(page.records) == 2
    assert page.total == 5


def test_year_filter_applies_to_fetched_records(tmp_path: Path) -> None:
    from dataclasses import replace

    years = [2019, 2020, 2021, 2022, 2023]
    channel = FakeChannel(
        manifest=make_manifest(),
        records=[replace(make_record(f"Paper {i}"), year=year) for i, year in enumerate(years)],
    )
    scripts = [
        [
            {"verb": "goto", "data": {}},
            {"verb": "read_html", "data": {"html": "<html>results</html>"}},
        ]
    ]
    service = build(tmp_path, channel, scripts)

    page = service.search(SearchQuery(text="x", channel="fake", year_from=2021, year_to=2022))

    assert [record.year for record in page.records] == [2021, 2022]
    assert page.total == 5
