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
        # Probed once: the answer is used for both fields, and a probe opens a socket.
        bridge_up = BridgeAdapter.probe()
        return {
            # Which build is answering, and which bridge protocol it speaks. Without
            # these, a caller cannot tell "the tool is missing" from "an old build is
            # answering" — and the two need very different fixes.
            "version": __version__,
            "bridge_protocol": PROTOCOL_VERSION,
            "channels": [spec.name for spec in registry.discover()],
            # What each channel can actually fill, per endpoint. Without this a
            # caller asks for `include_abstract` on CNKI, gets nulls from the list
            # row, and concludes CNKI has no abstracts — while its detail page holds
            # the complete one. The two endpoints are declared separately.
            "channel_capabilities": {
                spec.name: dict(spec.manifest.field_support)
                for spec in registry.discover()
            },
            "detail_capabilities": {
                spec.name: dict(spec.manifest.detail_field_support)
                for spec in registry.discover()
            },
            "cooldown_until": until.isoformat() if until else None,
            # None when the quota file cannot be read. Reporting the full limit there
            # made status contradict search, which refuses to run in the same state.
            "quota_remaining": policy.remaining_today,
            "quota_state_error": policy.state_error,
            "quota_state_path": str(policy.state_path),
            # Rough price of one search per channel, so a caller can budget without
            # discovering the cost by spending it.
            "action_cost": {
                "search": {"cnki": 3, "webofscience": 4},
                "page_turn": 4,
                "site_sort": 5,
                "local_sort": 0,
                "detail_cached": 0,
                "detail_live": {"cnki": 1},
            },
            "bridge_endpoint": str(endpoint),
            "bridge_ready": bridge_up,
            # `bridge_ready: false` on its own told a caller nothing about *why*,
            # so an agent had to go read host.log and guess — and one guessed by
            # killing the user's browser. State the diagnosis and the only allowed
            # reaction here, where the caller is already looking.
            "bridge": {
                "ready": bridge_up,
                "endpoint": str(endpoint),
                "log_path": str(host_runtime_dir() / "logs" / "host.log"),
                "remediation": None if bridge_up else ScholarService.BRIDGE_REMEDIATION,
            },
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
