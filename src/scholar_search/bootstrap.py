"""Compose the service graph for a running server."""

from __future__ import annotations

from . import __version__
from .adapters.bridge import BridgeAdapter
from .adapters.bridge.host import PROTOCOL_VERSION
from .core.audit import AuditLog
from .core.cache import Cache
from .core.config import host_runtime_dir
from .core.contracts import BrowserAdapter
from .core.planner import Planner
from .core.policy import PolicyEngine
from .core.registry import ChannelRegistry
from .core.risk import RiskGuard
from .core.service import ScholarService


def build_service() -> ScholarService:
    registry = ChannelRegistry()
    policy = PolicyEngine()
    risk = RiskGuard()
    audit = AuditLog()
    cache = Cache()
    endpoint = host_runtime_dir() / "bridge.json"

    def adapter_factory() -> BridgeAdapter:
        # Let the adapter discover a live host; the legacy file can be stale
        # while several browser reconnects are in flight.
        return BridgeAdapter()

    def planner_factory(adapter: BrowserAdapter) -> Planner:
        return Planner(adapter=adapter, policy=policy, risk=risk, audit=audit)

    def status() -> dict[str, object]:
        until = risk.cooldown_until()
        return {
            # Which build is answering, and which bridge protocol it speaks. Without
            # these, a caller cannot tell "the tool is missing" from "an old build is
            # answering" — and the two need very different fixes.
            "version": __version__,
            "bridge_protocol": PROTOCOL_VERSION,
            "channels": [spec.name for spec in registry.discover()],
            "cooldown_until": until.isoformat() if until else None,
            "quota_remaining": policy.remaining_today,
            "bridge_endpoint": str(endpoint),
            "bridge_ready": BridgeAdapter.probe(),
        }

    return ScholarService(
        registry=registry,
        adapter_factory=adapter_factory,
        planner_factory=planner_factory,
        policy=policy,
        cache=cache,
        status_provider=status,
        risk=risk,
    )
