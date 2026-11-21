"""Compose the service graph for a running server."""

from __future__ import annotations

import json
from pathlib import Path

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

# What one action costs, in quota units. One unit = one action whose verb is in
# `NETWORK_VERBS` (see `core/planner.py`), so these numbers are plan properties, not
# opinions — `tests/unit/test_action_cost_matches_plans.py` derives each one from the
# plan and fails when they disagree. They did disagree: this table quoted 4 for a Web
# of Science search while the BibTeX export path billed 8.
ACTION_COST: dict[str, object] = {
    "search": {"cnki": 3, "webofscience": 8},
    "site_sort": {"cnki": 5, "webofscience": 10},
    "page_turn": {"cnki": 4, "webofscience": None},
    "local_sort": 0,
    # Saving the tab the user already has open sends the site nothing (ADR 0018).
    "snapshot": 0,
    # page_read: the publisher front page plus the article page (ADR 0019).
    "page_read": 2,
    "detail_cached": 0,
    "detail_live": {"cnki": 1},
}


def _last_host_activity() -> str | None:
    """The timestamp of the last line in host.log, or None.

    Tells "the browser was never running" apart from "it is running but the
    extension dropped". The two need different instructions, and the fixed
    remediation text gave the same one for both.
    """

    log = host_runtime_dir() / "logs" / "host.log"
    try:
        # Read the tail, not the whole file: this log grows for as long as the tool
        # is installed, and one line is all that is needed.
        with log.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 4096))
            tail = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    for line in reversed(tail.splitlines()):
        line = line.strip()
        if len(line) >= 19 and line[4] == "-" and line[13] == ":":
            return line[:19]
    return None


def _bridge_remediation(last_seen: str | None) -> dict[str, object]:
    """What to do, as data rather than prose.

    The previous version returned a sentence, and the sentence was the same for two
    different situations. That was the bug: a caller that is told "click the
    extension icon" when no browser is running has been sent to do something
    impossible, and it has no way to notice.

    The diagnosis now comes from whether the profile is actually in use, and the
    answer names a command.
    """

    from .core import browser as browser_cfg

    recorded = browser_cfg.load()
    if recorded is None:
        return {
            "diagnosis": "no browser profile recorded",
            "next_action": "setup",
            "command": "wensu setup --browser edge",
            "human_step_required": True,
        }

    running = browser_cfg.profile_is_running(recorded)
    if running is None:
        # Cannot tell whether the profile is in use — the lock exists but could not be
        # probed. Guessing here is what produced the wrong advice twice: "click the
        # icon" when no window existed, and "start the browser" when one did. Say the
        # answer is unknown and give the command that is safe either way.
        return {
            "diagnosis": "cannot tell whether the wensu profile browser is running",
            "next_action": "browser_start",
            "command": "wensu browser start",
            "profile_dir": recorded.profile_dir,
            "human_step_required": False,
            "note": "`browser start` is safe when a window is already open: it hands "
            "the request over and reports that, rather than failing.",
        }
    if running is False:
        return {
            "diagnosis": "the wensu profile browser is not running",
            "next_action": "browser_start",
            "command": "wensu browser start",
            "profile_dir": recorded.profile_dir,
            "human_step_required": False,
        }
    return {
        "diagnosis": "a browser is using the profile, but the extension is not connected",
        "next_action": "reload_extension",
        "command": None,
        "profile_dir": recorded.profile_dir,
        "last_seen": last_seen,
        "human_step_required": True,
    }


def _extension_version(extension_dir: Path | str) -> str | None:
    """The `version` in the manifest the browser actually loads, or None.

    The browser loads a *copy* of the extension, made by `wensu setup`; installing a
    new wheel does not touch it. So "which build is running" has two answers — the
    package's and this copy's — and until now only the package's was reported, which
    is why a copy three versions behind went unnoticed.
    """

    try:
        manifest = json.loads((Path(extension_dir) / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = manifest.get("version")
    return version if isinstance(version, str) else None


def _browser_summary() -> dict[str, object] | None:
    """The recorded browser profile, if setup has run.

    Reported so "the extension is not connected" has an answer better than "find the
    right window yourself" — and so nothing is tempted to guess by inspecting
    processes.
    """

    from .core import browser as browser_cfg

    recorded = browser_cfg.load()
    if recorded is None:
        return None
    extension_version = _extension_version(recorded.extension_dir)
    return {
        "browser": recorded.browser,
        "profile_dir": recorded.profile_dir,
        "profile_exists": Path(recorded.profile_dir).is_dir(),
        "extension_dir": recorded.extension_dir,
        "extension_id": recorded.extension_id,
        # Two answers to "which version am I running": the package's `version` above,
        # and this copy's. `extension_version_mismatch: null` means the manifest could
        # not be read — say "unknown" rather than claiming the copy is current.
        "extension_version": extension_version,
        "extension_version_mismatch": (
            None if extension_version is None else extension_version != __version__
        ),
        "start_with": "wensu browser start",
    }


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

    def status(brief: bool = False) -> dict[str, object]:
        until = risk.cooldown_until()
        # Probed once: the answer is used for both fields, and a probe opens a socket.
        bridge_up = BridgeAdapter.probe()
        last_seen = _last_host_activity()

        # `brief` exists because a health check cost about 500 tokens, more than a
        # search. The three static blocks below are constants; a caller checking
        # whether it can proceed does not need them on every poll.
        if brief:
            return {
                "version": __version__,
                "bridge_ready": bridge_up,
                "bridge_last_seen": last_seen,
                # Enough to act on without pulling the full payload: the report
                # needed `remediation` and `start_with` and had to spend 500 tokens
                # on three static blocks to get them.
                "bridge_next_action": None if bridge_up else _bridge_remediation(last_seen),
                "quota_remaining": policy.remaining_today,
                "cooldown_until": until.isoformat() if until else None,
            }

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
                spec.name: dict(spec.manifest.field_support) for spec in registry.discover()
            },
            "detail_capabilities": {
                spec.name: dict(spec.manifest.detail_field_support) for spec in registry.discover()
            },
            "cooldown_until": until.isoformat() if until else None,
            # None when the quota file cannot be read. Reporting the full limit there
            # made status contradict search, which refuses to run in the same state.
            "quota_remaining": policy.remaining_today,
            "quota_state_error": policy.state_error,
            "quota_state_path": str(policy.state_path),
            # Rough price of one search per channel, so a caller can budget without
            # discovering the cost by spending it.
            "action_cost": ACTION_COST,
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
                "last_seen": last_seen,
                "remediation": None if bridge_up else _bridge_remediation(last_seen),
            },
            # Which browser profile wensu owns, so "the extension is not connected"
            # has an actionable answer other than "figure out which window it is in".
            # None until `wensu setup --browser` has run.
            "browser_profile": _browser_summary(),
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
