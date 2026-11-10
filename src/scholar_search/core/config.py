"""Configuration and hard limits.

Every value here is a floor or a ceiling, not a default. Channels and users
may make behaviour stricter, never looser. Loosening requires a new ADR.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Runtime state keeps the pre-0.4.0 directory name on purpose: renaming it would
# orphan quota, cooldown and audit state for everyone upgrading. Only the
# distribution name changed in 0.4.0.
APP_NAME = "scholar-search"
ENV_HOME = "SCHOLAR_SEARCH_HOME"


@dataclass(frozen=True, slots=True)
class HardLimits:
    """Non-negotiable limits enforced by the kernel."""

    min_interval_ms: int = 3_000
    default_interval_ms: int = 4_000
    max_interval_ms: int = 6_000
    max_pages_per_call: int = 3
    max_pages_per_session: int = 8
    daily_request_limit: int = 300
    cooldown_hours: int = 24
    concurrency: int = 1
    max_actions_per_plan: int = 40
    # Wall-clock ceiling for one plan, checked as the sum of every action's declared
    # timeout *before* the plan runs.
    #
    # 200 s, raised from 120 s by ADR 0014. The check is a static worst case, not a
    # measurement: a Web of Science page declares ~118 s of timeouts and typically
    # finishes in ~49 s, so the old ceiling was refusing work that fits comfortably
    # in reality, and the response was to shrink per-action deadlines (a 15 s wait
    # became 9 s) to satisfy arithmetic. Raising the ceiling restores those deadlines
    # instead of pretending the network is faster than it is.
    #
    # It stays a ceiling: a plan still cannot declare more than this, which is what
    # stops a channel from asking a tab to sit for an unbounded time.
    max_plan_seconds: int = 200


HARD = HardLimits()


def app_home() -> Path:
    """Return the private runtime directory.

    Defaults to ``%LOCALAPPDATA%\\scholar-search`` on Windows and
    ``~/.local/share/scholar-search`` elsewhere. Never inside the repository.
    """

    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override).expanduser().resolve()

    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME

    return Path.home() / ".local" / "share" / APP_NAME


def profiles_dir() -> Path:
    return app_home() / "profiles"


def cache_dir() -> Path:
    return app_home() / "cache"


def audit_dir() -> Path:
    return app_home() / "audit"


def logs_dir() -> Path:
    return app_home() / "logs"


def tmp_dir() -> Path:
    return app_home() / "tmp"


def ensure_home() -> Path:
    """Create the runtime tree and return its root."""

    root = app_home()
    for sub in (profiles_dir(), cache_dir(), audit_dir(), logs_dir(), tmp_dir()):
        sub.mkdir(parents=True, exist_ok=True)
    return root


def host_runtime_dir() -> Path:
    """Directory the browser-launched host may write to.

    It stays inside :func:`app_home` so the documented HOME boundary holds.
    The installer marks this subtree as low-integrity writable, because Chrome
    and Edge start native messaging hosts at low integrity.
    """

    return app_home() / "host"


def ensure_host_runtime() -> Path:
    root = host_runtime_dir()
    (root / "logs").mkdir(parents=True, exist_ok=True)
    return root
