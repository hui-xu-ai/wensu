"""The `snapshot` verb (ADR 0018).

It is the one verb that reads a page it did not navigate to, so these tests pin the two
properties that makes acceptable: the closed vocabulary stays closed, and no quota is
spent because no request is issued.
"""

from __future__ import annotations

import json
from pathlib import Path

from scholar_search.adapters.bridge.policy import VERBS as BRIDGE_VERBS
from scholar_search.adapters.bridge.policy import validate_request
from scholar_search.adapters.fixture import FixtureAdapter
from scholar_search.core.cache import Cache
from scholar_search.core.contracts import VERBS
from scholar_search.core.params import ALLOWED_KEYS, validate_params
from scholar_search.core.planner import Planner
from scholar_search.core.policy import NETWORK_VERBS, READ_VERBS, PolicyEngine
from scholar_search.core.risk import RiskGuard
from scholar_search.core.service import ScholarService
from support import FakeChannel, StubRegistry, make_manifest


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def build_service(tmp_path: Path, scripts: list[list[dict[str, object]]]) -> ScholarService:
    clock = FakeClock()
    policy = PolicyEngine(clock=clock.time, sleeper=clock.sleep, state_path=tmp_path / "quota.json")
    risk = RiskGuard(state_path=tmp_path / "cooldown.json")

    def factory() -> FixtureAdapter:
        return FixtureAdapter(scripts.pop(0))

    return ScholarService(
        registry=StubRegistry(FakeChannel(manifest=make_manifest(), records=[])),  # type: ignore[arg-type]
        adapter_factory=factory,
        planner_factory=lambda adapter: Planner(adapter, policy, risk, _audit(tmp_path)),
        policy=policy,
        cache=Cache(path=tmp_path / "cache.sqlite3"),
        bridge_probe=lambda: True,
    )


def _audit(tmp_path: Path) -> object:
    from scholar_search.core.audit import AuditLog

    return AuditLog(path=tmp_path / "audit.jsonl")


def test_snapshot_belongs_to_the_closed_vocabulary() -> None:
    assert "snapshot" in VERBS
    assert "snapshot" in BRIDGE_VERBS
    assert "snapshot" in ALLOWED_KEYS


def test_snapshot_takes_no_parameters() -> None:
    assert validate_params("snapshot", {}) is None
    # It always targets the tab the user has open; a caller cannot aim it elsewhere.
    assert validate_params("snapshot", {"tab": "other"}) == "policy.params"


def test_snapshot_spends_no_quota() -> None:
    assert "snapshot" not in NETWORK_VERBS
    assert "snapshot" in READ_VERBS


def test_bridge_accepts_snapshot_without_any_domain_scope() -> None:
    message = {"type": "action", "id": "abc", "action": "snapshot", "params": {}, "domains": []}

    assert validate_request(message, ()) is None


def test_bridge_still_rejects_verbs_outside_the_vocabulary() -> None:
    message = {"type": "action", "id": "abc", "action": "download_pdf", "params": {}}

    assert validate_request(message, ()) == "policy.verb"


def test_extension_manifest_declares_page_capture() -> None:
    manifest_path = Path(__file__).resolve().parents[2] / "extension" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert "pageCapture" in manifest["permissions"]
    # The verb is useless without the API it depends on.
    assert "downloads" in manifest["permissions"]


def test_service_relays_the_path_and_leaves_the_quota_alone(tmp_path: Path) -> None:
    scripts: list[list[dict[str, object]]] = [
        [
            {
                "verb": "snapshot",
                "data": {
                    "path": "C:\\Users\\x\\Downloads\\wensu-pages\\paper [example.org] 1.mhtml",
                    "bytes": 2_345_678,
                    "url": "https://example.org/article",
                    "title": "A paper",
                },
            }
        ]
    ]
    service = build_service(tmp_path, scripts)

    result = service.snapshot()

    assert result["path"].endswith(".mhtml")
    assert result["bytes"] == 2_345_678
    assert result["url"] == "https://example.org/article"
    assert result["title"] == "A paper"
    # No reservation was taken: the quota file was never touched.
    assert not (tmp_path / "quota.json").exists()


def test_service_raises_a_specific_error_when_the_page_cannot_be_saved(tmp_path: Path) -> None:
    scripts: list[list[dict[str, object]]] = [
        [{"verb": "snapshot", "ok": False, "error": "policy.url_scheme"}],
    ]
    service = build_service(tmp_path, scripts)

    try:
        service.snapshot()
    except Exception as error:  # ActionError
        assert getattr(error, "code", "") == "policy.url_scheme"
        assert getattr(error, "verb", "") == "snapshot"
    else:  # pragma: no cover - the raise above is the expected path
        raise AssertionError("snapshot should have raised")
