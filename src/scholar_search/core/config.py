"""Configuration and hard limits.

Every value here is a floor or a ceiling, not a default. Channels and users
may make behaviour stricter, never looser. Loosening requires a new ADR.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import ScholarSearchError
from .locking import interprocess_lock

# Runtime state keeps the pre-0.4.0 directory name on purpose: renaming it would
# orphan quota, cooldown and audit state for everyone upgrading. Only the
# distribution name changed in 0.4.0.
APP_NAME = "scholar-search"
ENV_HOME = "SCHOLAR_SEARCH_HOME"
# State that belongs to the *browser* rather than to one home. First slice (ADR 0029): the browser
# lock, so two homes driving the same browser cannot interleave navigations. Quota and cooldown
# deliberately stay per-home until that change gets its own migration.
ENV_BROWSER_STATE = "SCHOLAR_SEARCH_BROWSER_STATE"
# Diagnostic budgets (ADR 0031). They exist so a *branch* can be exercised on one ordinary read
# instead of waiting for a slow network or a fault: shrink the observation budget to see
# `budget_exhausted`, shrink the capture budget to see `capture_unconfirmed` and then ask
# `navigation_status` about the operation. They are read from this process's environment only —
# never from a request — and they are clamped, so no caller can widen a budget through them.
ENV_READINESS_BUDGET_MS = "SCHOLAR_SEARCH_READINESS_BUDGET_MS"
ENV_SNAPSHOT_TIMEOUT_MS = "SCHOLAR_SEARCH_SNAPSHOT_TIMEOUT_MS"
READINESS_BUDGET_MS = 30_000
SNAPSHOT_TIMEOUT_MS = 55_000
# Floors are what makes a diagnostic meaningful: below them the branch is not being tested, the
# read is just broken.
_MIN_READINESS_MS = 50
_MIN_SNAPSHOT_MS = 200


def _budget(name: str, default: int, floor: int, ceiling: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(floor, min(ceiling, value))


def readiness_budget_ms() -> int:
    """How long to watch tab metadata before capturing anyway (ADR 0031, I3)."""

    return _budget(ENV_READINESS_BUDGET_MS, READINESS_BUDGET_MS, _MIN_READINESS_MS, 300_000)


def snapshot_timeout_ms() -> int:
    """Budget for one capture, never above the native host's single-RPC ceiling (60 s)."""

    return _budget(ENV_SNAPSHOT_TIMEOUT_MS, SNAPSHOT_TIMEOUT_MS, _MIN_SNAPSHOT_MS, 55_000)


@dataclass(frozen=True, slots=True)
class HardLimits:
    """Non-negotiable limits enforced by the kernel."""

    min_interval_ms: int = 900
    # In-page UI work (dialogs, drop-downs, inputs) on a page that is already open: the site
    # answers in milliseconds, so the network floor is pure waiting there. Still one quota
    # unit per action — this is pacing, not billing (ADR 0023).
    ui_interval_ms: int = 150
    default_interval_ms: int = 4_000
    max_interval_ms: int = 6_000
    max_pages_per_call: int = 3
    max_pages_per_session: int = 8
    daily_request_limit: int = 300
    cooldown_hours: int = 24
    concurrency: int = 1
    max_actions_per_plan: int = 40
    # Ordinary actions must answer inside 15 s. A click that waits for a *download* may wait
    # longer: Clarivate will carry 1000 records in one file, and measured 2026-11-24 that file
    # needs well past 15 s to arrive. Nothing else is allowed to run that long (ADR 0024).
    max_action_ms: int = 15_000
    max_download_ms: int = 60_000
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


def browser_state_dir() -> Path:
    """Machine-scoped state, shared by every home that drives this browser.

    The browser is one resource no matter how many `SCHOLAR_SEARCH_HOME` directories point at it,
    so the lock that serialises its use cannot live inside one of them (ADR 0029). Documents,
    caches, quota and cooldown stay per-home for now.
    """

    override = os.environ.get(ENV_BROWSER_STATE)
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME / "browser-state"
    return Path.home() / ".local" / "share" / APP_NAME / "browser-state"


def browser_state_paths() -> tuple[Path, Path, Path]:
    """The three files that belong to the browser: quota, cooldown, lock.

    Returned as a tuple rather than looked up one by one so callers cannot accidentally use the
    per-home `state/` directory for one of them and the machine-wide one for another (ADR 0029).
    """

    shared = browser_state_dir() / "state"
    return shared / "quota.json", shared / "cooldown.json", browser_state_dir() / "browser.lock"


def adopt_legacy_state(legacy: Path, target: Path) -> bool:
    """Copy an old per-home state file into the shared location, once.

    Migration rule: **read the old file, write the new one, never delete anything**. A user who
    rolls back to an older build still finds its own state, and a machine that has both simply
    keeps the numbers it already had instead of restarting the day at zero.

    The check and the publish happen under one cross-process lock, and the bytes land through
    `os.replace`. Checking then writing let two first starts both see "no file yet" and the later
    copy overwrite an allowance that had already been established — 77 became 11 in the replay
    (P5 retest 2026-11-27, F41-02). First source wins; nothing here tries to pick a "larger" one.
    """

    if target.exists() or not legacy.is_file():
        return False
    lock = target.with_name(target.name + ".migrate.lock")
    try:
        with interprocess_lock(lock, timeout_s=10.0):
            if target.exists():  # re-check under the lock: another process may have won
                return False
            staging = target.with_name(f"{target.name}.{os.getpid()}.tmp")
            staging.parent.mkdir(parents=True, exist_ok=True)
            staging.write_bytes(legacy.read_bytes())
            os.replace(staging, target)
    except (OSError, ScholarSearchError):
        return False
    return True


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
