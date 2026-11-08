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
    hosts = [urlparse(a.params["url"]).hostname for a in plan.actions if a.verb == "goto"]
    assert hosts, "plan must navigate somewhere"
    for host in hosts:
        assert host is not None
        assert any(host == d or host.endswith("." + d) for d in manifest.domains)


def test_plan_stays_within_kernel_budget() -> None:
    for query in (_query(), _query(page=3), _query(sort="date")):
        plan = plan_search.build(query)
        assert len(plan.actions) <= HARD.max_actions_per_plan
        assert sum(a.timeout_ms for a in plan.actions) <= HARD.max_plan_seconds * 1000


def test_pages_and_sort_cannot_share_one_call() -> None:
    with pytest.raises(ChannelError):
        plan_search.build(_query(page=2, sort="date"))


def test_plan_costs_three_network_actions() -> None:
    plan = plan_search.build(_query())
    assert sum(1 for a in plan.actions if a.verb in NETWORK_VERBS) == 3


def test_type_clears_the_editor_first() -> None:
    typing = [a for a in plan_search.build(_query()).actions if a.verb == "type"]
    assert len(typing) == 1
    assert typing[0].params["clear"] is True


def test_capture_wait_is_a_two_phase_handshake() -> None:
    waits = [a for a in plan_search.build(_query()).actions if a.verb == "wait_for"]
    hidden = [a for a in waits if a.params.get("state") == "hidden"]
    ready = [a for a in waits if a.params.get("state") != "hidden"]
    assert hidden, "must wait for the stale marker to clear"
    assert ready, "must then wait for the new payload"


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
    assert len(page.records) == 3
    assert page.total == 50
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    for record in page.records:
        jsonschema.validate(record.to_dict(), schema)


def test_parse_keeps_records_with_missing_fields() -> None:
    first = parse_records.parse(CAPTURE).records[0]
    assert first.keywords == [], "record 1 carried no keywords_plus block"
    assert first.title.startswith("Synthetic")
    assert first.channel == "webofscience"
    assert first.url is not None and "full-record" in first.url


def test_parse_flattens_abstract_markup() -> None:
    record = parse_records.parse(CAPTURE).records[1]
    assert record.abstract is not None
    assert "<p>" not in record.abstract


def test_parse_rejects_non_json() -> None:
    with pytest.raises(ParseError):
        parse_records.parse("not json at all")


def test_parse_rejects_empty_capture() -> None:
    with pytest.raises(ParseError):
        parse_records.parse("")
    with pytest.raises(ParseError):
        parse_records.parse('{"key": "searchInfo", "payload": {}}')
