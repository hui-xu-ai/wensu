from __future__ import annotations

from pathlib import Path

import pytest

from scholar_search.adapters.fixture import FixtureAdapter
from scholar_search.core.audit import AuditLog
from scholar_search.core.cache import Cache
from scholar_search.core.contracts import SearchQuery
from scholar_search.core.errors import PolicyError
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


def build_service(
    tmp_path: Path, channel: FakeChannel, scripts: list[list[dict[str, object]]]
) -> ScholarService:
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
    )


def test_search_returns_records_and_caches(tmp_path: Path) -> None:
    channel = FakeChannel(manifest=make_manifest(), records=[make_record("Paper A")])
    scripts: list[list[dict[str, object]]] = [
        [
            {"verb": "goto", "data": {}},
            {"verb": "read_html", "data": {"html": "<html>results</html>"}},
        ],
        [
            {"verb": "goto", "data": {}},
            {"verb": "read_html", "data": {"html": "<html>detail</html>"}},
        ],
    ]
    service = build_service(tmp_path, channel, scripts)

    page = service.search(SearchQuery(text="x", channel="fake"))
    assert [record.title for record in page.records] == ["Paper A"]

    # Second call must hit the cache: the detail script is still untouched.
    again = service.search(SearchQuery(text="x", channel="fake"))
    assert again.records[0].title == "Paper A"
    assert len(scripts) == 1


def test_detail_rejects_foreign_host(tmp_path: Path) -> None:
    channel = FakeChannel(manifest=make_manifest())
    service = build_service(tmp_path, channel, [])

    with pytest.raises(PolicyError):
        service.detail("https://evil.test/article/1", channel="fake")


def test_detail_rejects_wrong_path(tmp_path: Path) -> None:
    channel = FakeChannel(manifest=make_manifest())
    service = build_service(tmp_path, channel, [])

    with pytest.raises(PolicyError, match="path"):
        service.detail("https://example.org/other/1", channel="fake")


def test_detail_returns_record(tmp_path: Path) -> None:
    channel = FakeChannel(manifest=make_manifest())
    scripts: list[list[dict[str, object]]] = [
        [
            {"verb": "goto", "data": {}},
            {"verb": "read_html", "data": {"html": "<html>detail</html>"}},
        ]
    ]
    service = build_service(tmp_path, channel, scripts)

    record = service.detail("https://example.org/article/1", channel="fake")
    assert record.title == "A paper"


def test_search_seeds_the_detail_cache(tmp_path: Path) -> None:
    """A record already parsed during search must not cost a second visit."""

    record = make_record("Paper A")
    record.url = "https://example.org/article/1"
    channel = FakeChannel(manifest=make_manifest(), records=[record])
    scripts: list[list[dict[str, object]]] = [
        [
            {"verb": "goto", "data": {}},
            {"verb": "read_html", "data": {"html": "<html>results</html>"}},
        ],
    ]
    service = build_service(tmp_path, channel, scripts)

    service.search(SearchQuery(text="x", channel="fake"))

    # No script is left: anything that reached the browser would fail here.
    detail = service.detail("https://example.org/article/1", channel="fake")
    assert detail.title == "Paper A"


SEARCH_SCRIPT: list[dict[str, object]] = [
    {"verb": "goto", "data": {}},
    {"verb": "read_html", "data": {"html": "<html>results</html>"}},
]


def test_search_omits_abstracts_by_default(tmp_path: Path) -> None:
    channel = FakeChannel(manifest=make_manifest(), records=[make_record("Paper A")])
    service = build_service(tmp_path, channel, [list(SEARCH_SCRIPT)])

    page = service.search(SearchQuery(text="x", channel="fake"))

    assert page.records[0].abstract is None


def test_include_abstract_keeps_it(tmp_path: Path) -> None:
    channel = FakeChannel(manifest=make_manifest(), records=[make_record("Paper A")])
    service = build_service(tmp_path, channel, [list(SEARCH_SCRIPT)])

    page = service.search(SearchQuery(text="x", channel="fake", include_abstract=True))

    assert page.records[0].abstract == "Abstract text"


def test_local_sort_orders_by_citations(tmp_path: Path) -> None:
    low = make_record("Low")
    low.citations = 2
    high = make_record("High")
    high.citations = 40
    channel = FakeChannel(manifest=make_manifest(), records=[low, high])
    service = build_service(tmp_path, channel, [list(SEARCH_SCRIPT)])

    page = service.search(SearchQuery(text="x", channel="fake", sort_by="citations"))

    assert [record.title for record in page.records] == ["High", "Low"]


def test_min_citations_keeps_records_without_a_count(tmp_path: Path) -> None:
    measured = make_record("Measured")
    measured.citations = 1
    unmeasured = make_record("Unmeasured")  # citations stays None
    channel = FakeChannel(manifest=make_manifest(), records=[measured, unmeasured])
    service = build_service(tmp_path, channel, [list(SEARCH_SCRIPT)])

    page = service.search(SearchQuery(text="x", channel="fake", min_citations=5))

    assert [record.title for record in page.records] == ["Unmeasured"]


def test_sources_only_filters_by_journal(tmp_path: Path) -> None:
    inside = make_record("Inside")
    outside = make_record("Outside")
    outside.source = "Something Else"
    channel = FakeChannel(manifest=make_manifest(), records=[inside, outside])
    service = build_service(tmp_path, channel, [list(SEARCH_SCRIPT)])

    page = service.search(SearchQuery(text="x", channel="fake", sources_only=("journ",)))

    assert [record.title for record in page.records] == ["Inside"]


def test_list_only_records_do_not_seed_the_detail_cache(tmp_path: Path) -> None:
    """A CNKI row has a URL but no abstract; caching it would starve detail()."""

    row = make_record("Paper A")
    row.abstract = None  # exactly what a CNKI result row looks like
    row.url = "https://example.org/article/1"
    channel = FakeChannel(manifest=make_manifest(), records=[row])
    service = build_service(
        tmp_path,
        channel,
        [
            list(SEARCH_SCRIPT),
            [
                {"verb": "goto", "data": {}},
                {"verb": "read_html", "data": {"html": "<html>detail</html>"}},
            ],
        ],
    )

    service.search(SearchQuery(text="x", channel="fake"))
    detail = service.detail("https://example.org/article/1", channel="fake")

    # parse_detail returns "A paper", the list row is "Paper A": seeing the
    # latter would mean the row was served from the cache and the abstract lost.
    assert detail.title == "A paper"
