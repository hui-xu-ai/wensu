"""Contract tests that must pass before a channel can be loaded.

These run offline and are the first gate in CI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scholar_search.adapters.bridge.policy import validate_request
from scholar_search.core.config import HARD
from scholar_search.core.contracts import (
    FORBIDDEN_VERB_MARKERS,
    VERBS,
    ChannelManifest,
    SearchQuery,
)
from scholar_search.core.errors import ScholarSearchError
from scholar_search.core.policy import PolicyEngine
from scholar_search.core.registry import ChannelRegistry

CHANNELS = Path(__file__).resolve().parents[2] / "src" / "scholar_search" / "channels"


def _manifests() -> list[Path]:
    return sorted(CHANNELS.glob("*/manifest.json"))


def test_at_least_one_channel_exists() -> None:
    assert _manifests(), "no channel manifest found"


@pytest.mark.parametrize("path", _manifests(), ids=lambda p: p.parent.name)
def test_manifest_is_valid(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    manifest = ChannelManifest(
        channel=data["channel"],
        site_version=data["site_version"],
        schema_version=data["schema_version"],
        min_core=data["min_core"],
        domains=tuple(data["domains"]),
        verbs=tuple(data["verbs"]),
        capabilities=tuple(data["capabilities"]),
        detail_url_prefixes=tuple(data.get("detail_url_prefixes", ())),
    )
    manifest.validate()


@pytest.mark.parametrize("path", _manifests(), ids=lambda p: p.parent.name)
def test_no_forbidden_verbs(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    for verb in data["verbs"]:
        assert verb in VERBS, f"{path.parent.name}: unknown verb {verb!r}"
        lowered = verb.lower()
        for marker in FORBIDDEN_VERB_MARKERS:
            assert marker not in lowered, f"{path.parent.name}: forbidden verb {verb!r}"


@pytest.mark.parametrize("path", _manifests(), ids=lambda p: p.parent.name)
def test_declared_domains_are_bare_hosts(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    for domain in data["domains"]:
        assert "/" not in domain and ":" not in domain and "*" not in domain


def test_hard_limits_match_adr() -> None:
    assert HARD.min_interval_ms == 3_000
    assert HARD.max_pages_per_call == 3
    assert HARD.max_pages_per_session == 8
    assert HARD.daily_request_limit == 300
    assert HARD.cooldown_hours == 24
    assert HARD.concurrency == 1


def test_every_channel_plan_passes_both_validation_layers() -> None:
    """The kernel and the native host keep separate copies of the same rules.

    Change one and not the other and you get a plan the kernel accepts and the
    host rejects — a failure that only surfaces after the extension has been
    reloaded and quota spent. This is the comparison, run offline; the same check
    ships as ``scripts/check-plan.py`` for pre-deploy use.
    """

    registry = ChannelRegistry()
    engine = PolicyEngine()
    checked = 0
    for spec in registry.discover():
        for extra in ({}, {"page": 2}, {"sort": "date"}):
            query = SearchQuery(text="plan check", channel=spec.name, **extra)
            try:
                plan = registry.load(spec.name).plan_search(query)
            except ScholarSearchError:
                # A channel may refuse a combination by design (budget, unsupported
                # paging). That is an answer, not a defect.
                continue
            engine.validate_plan(plan, spec.manifest)
            for action in plan.actions:
                code = validate_request(
                    {"action": action.verb, "params": dict(action.params)},
                    spec.manifest.domains,
                )
                assert code is None, f"{spec.name} {extra}: host rejected {action.verb}: {code}"
            checked += 1
    assert checked >= 2, "expected at least one plan per channel"
