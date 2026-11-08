"""Contract tests for the Web of Science channel.

These run offline against the desensitised fixture and are the first gate before
the channel may be loaded.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import jsonschema
import pytest

from scholar_search.channels.webofscience.v2026_11 import parse_records, plan_search
from scholar_search.core.config import HARD
from scholar_search.core.contracts import VERBS, SearchQuery
from scholar_search.core.errors import ChannelError, ParseError
from scholar_search.core.policy import NETWORK_VERBS
from scholar_search.core.registry import ChannelRegistry

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "webofscience" / "records.ndjson"
SCHEMA = ROOT / "schemas" / "record.json"

CAPTURE = FIXTURE.read_text(encoding="utf-8")


def _channel():  # type: ignore[no-untyped-def]
    return ChannelRegistry().load("webofscience")


def _query(**kwargs):  # type: ignore[no-untyped-def]
    payload = {"text": "actuator", "channel": "webofscience"}
    payload.update(kwargs)
    return SearchQuery(**payload)


def test_channel_is_discoverable() -> None:
    spec = ChannelRegistry().select("webofscience")
    assert spec.manifest.channel == "webofscience"
    assert "search" in spec.manifest.capabilities


def test_manifest_domains_are_bare_hosts() -> None:
    for domain in _channel().manifest.domains:
        assert "/" not in domain and ":" not in domain and "*" not in domain


def test_plan_uses_only_declared_verbs() -> None:
    manifest = _channel().manifest
    plan = plan_search.build(_query())
    assert plan.actions, "plan must not be empty"
    for action in plan.actions:
        assert action.verb in VERBS
        assert action.verb in manifest.verbs


def test_plan_only_navigates_inside_declared_domains() -> None:
    manifest = _channel().manifest
    plan = plan_search.build(_query())
    # A reload carries no URL: it re-navigates to wherever the tab already is, so
    # there is nothing to check against the allowlist.
    urls = [a.params["url"] for a in plan.actions if a.verb == "goto" and "url" in a.params]
    assert urls, "plan must navigate somewhere"
    for url in urls:
        host = urlparse(url).hostname
        assert host is not None
        assert any(host == d or host.endswith("." + d) for d in manifest.domains)


def test_plan_reloads_the_result_page() -> None:
    """A reload is how the whole result set arrives; scrolling must not be needed."""

    plan = plan_search.build(_query())
    reloads = [a for a in plan.actions if a.verb == "goto" and a.params.get("reload") is True]
    assert reloads, "the plan must reload the result page"
    assert not [a for a in plan.actions if a.verb == "scroll"], "reloading replaces scrolling"


def test_plan_stays_within_kernel_budget() -> None:
    for query in (_query(), _query(page=2), _query(sort="date")):
        plan = plan_search.build(query)
        assert len(plan.actions) <= HARD.max_actions_per_plan
        assert sum(a.timeout_ms for a in plan.actions) <= HARD.max_plan_seconds * 1000


def test_worst_case_budget_holds_across_random_pacing() -> None:
    """Pauses are randomised, so the ceiling must hold for every draw, not on average."""

    for _ in range(25):
        plan = plan_search.build(_query(page=2))
        assert len(plan.actions) <= HARD.max_actions_per_plan
        assert sum(a.timeout_ms for a in plan.actions) <= HARD.max_plan_seconds * 1000


def test_a_third_page_is_refused() -> None:
    """Each page needs a scroll round to refill; three of them blow the budget."""

    with pytest.raises(ChannelError):
        plan_search.build(_query(page=3))


def test_pages_and_sort_cannot_share_one_call() -> None:
    with pytest.raises(ChannelError):
        plan_search.build(_query(page=2, sort="date"))


def test_plan_costs_four_network_actions() -> None:
    """goto, type, click and the reload that fetches the whole page."""

    plan = plan_search.build(_query())
    assert sum(1 for a in plan.actions if a.verb in NETWORK_VERBS) == 4


def test_type_clears_the_editor_first() -> None:
    typing = [a for a in plan_search.build(_query()).actions if a.verb == "type"]
    assert len(typing) == 1
    assert typing[0].params["clear"] is True


def test_capture_wait_only_waits_for_the_payload() -> None:
    waits = [a for a in plan_search.build(_query()).actions if a.verb == "wait_for"]
    ready = [a for a in waits if a.params.get("selector") == "#wensu-wos-capture[data-ready='1']"]
    hidden = [a for a in waits if a.params.get("state") == "hidden"]
    assert ready, "the plan must wait for the captured payload"
    assert not hidden, "a ready marker that is often already set cannot be waited out"


def test_default_page_and_sort_add_no_clicks() -> None:
    clicks = [a for a in plan_search.build(_query()).actions if a.verb == "click"]
    assert len(clicks) == 1, "only the submit click should remain on the default path"


def test_page_turns_and_sort_each_add_clicks() -> None:
    turn = [a for a in plan_search.build(_query(page=2)).actions if a.verb == "click"]
    ordered = [a for a in plan_search.build(_query(sort="date")).actions if a.verb == "click"]
    assert len(turn) >= 2, "a page turn is one extra click"
    assert len(ordered) >= 3, "sorting opens the menu and picks an option"


def test_parse_reads_the_fixture() -> None:
    page = parse_records.parse(CAPTURE)
    assert len(page.records) == 4
    assert page.total == 50
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    for record in page.records:
        jsonschema.validate(record.to_dict(), schema)


def test_primary_batch_is_ordered_first() -> None:
    """The fixture puts the runQuerySearch block last on purpose.

    The site sends the primary batch first, but a lazy batch can beat it. With no
    primary block in the fixture the ordering was a no-op that no test could catch;
    putting it last makes a broken ordering show up as a wrong first record.
    """

    page = parse_records.parse(CAPTURE)
    assert page.records[0].title == "Synthetic primary-batch record"


def test_parse_keeps_records_with_missing_fields() -> None:
    first = parse_records.parse(CAPTURE).records[1]
    assert first.keywords == [], "record 1 carried no keywords_plus block"
    assert first.title.startswith("Synthetic")
    assert first.channel == "webofscience"
    assert first.url is not None and "full-record" in first.url


def test_parse_flattens_abstract_markup() -> None:
    record = parse_records.parse(CAPTURE).records[2]
    assert record.abstract is not None
    assert "<p>" not in record.abstract


def test_page_is_none_when_the_stream_reports_none() -> None:
    """The stream carries no page number, and guessing one hides a failed turn.

    The kernel used to overwrite whatever the channel returned with the requested
    page number, so `page=2` came back as 2 even when the site had served page 1.
    """

    page = parse_records.parse(CAPTURE, query=SearchQuery(text="x", channel="webofscience", page=2))
    assert page.page is None


def test_impact_factor_is_returned_with_each_record() -> None:
    page = parse_records.parse(CAPTURE)
    factors = [record.impact_factor for record in page.records]
    # The primary record clones record 1 (5.0); record 4 carries no jcrKey.
    assert factors == [5.0, 5.0, 2.0, None]


def test_impact_factor_filter_uses_the_jcr_block() -> None:
    page = parse_records.parse(
        CAPTURE,
        query=SearchQuery(text="x", channel="webofscience", min_impact_factor=3.0),
    )
    # Record 1 is in the 5.0 journal, record 2 in the 2.0 one, record 3 has no
    # jcrKey at all, and the primary record clones record 1 — so it survives too.
    assert [record.title for record in page.records] == [
        "Synthetic primary-batch record",
        "Synthetic example record 1",
    ]


def test_impact_factor_filter_can_empty_the_page_without_error() -> None:
    page = parse_records.parse(
        CAPTURE,
        query=SearchQuery(text="x", channel="webofscience", min_impact_factor=99.0),
    )
    assert page.records == ()


def test_zero_results_is_an_empty_page_not_an_error() -> None:
    capture = '{"id": 0, "key": "searchInfo", "payload": {"RecordsFound": 0}}'
    page = parse_records.parse(capture)
    assert page.records == ()
    assert page.total == 0


def test_parse_rejects_non_json() -> None:
    with pytest.raises(ParseError):
        parse_records.parse("not json at all")


def test_parse_rejects_empty_capture() -> None:
    with pytest.raises(ParseError):
        parse_records.parse("")
    with pytest.raises(ParseError):
        parse_records.parse('{"key": "searchInfo", "payload": {}}')
