"""Policy enforcement: verb/domain allowlists, rate limiting, daily quota.

Every limit here is a floor or ceiling from :mod:`scholar_search.core.config`.
Channels may tighten behaviour, never loosen it.

The quota file is the single source of truth. A network slot is *reserved*
inside one atomic critical section (interval check + increment + persist), so
two processes cannot both spend the last remaining request.
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from .config import HARD, HardLimits, app_home
from .contracts import VERBS, Action, ChannelManifest, Plan
from .errors import PolicyError
from .locking import interprocess_lock
from .params import validate_params

NETWORK_VERBS: frozenset[str] = frozenset({"goto", "click", "select", "type"})
READ_VERBS: frozenset[str] = frozenset({"wait_for", "read_html", "read_text", "scroll", "sleep"})


@dataclass(slots=True)
class QuotaState:
    day: str
    used: int = 0
    last: float | None = None


def _default_jitter() -> float:
    """Human-like spacing above the hard floor; never below it."""

    delay = random.uniform(0, 1_200)
    if random.random() < 0.1:
        delay += random.uniform(2_000, 4_000)
    return delay


class PolicyEngine:
    """Validates plans and meters their execution."""

    def __init__(
        self,
        limits: HardLimits = HARD,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] | None = None,
        state_path: Path | None = None,
    ) -> None:
        self._limits = limits
        self._clock = clock
        self._sleep = sleeper
        self._jitter = jitter or _default_jitter
        self._state_path = state_path or (app_home() / "state" / "quota.json")
        self._lock_path = self._state_path.with_suffix(".lock")
        self._fallback = QuotaState(day=self._today())
        self._degraded = False
        self._state_error: str | None = None

    # -- quota ---------------------------------------------------------

    def _today(self) -> str:
        return date.today().isoformat()

    @property
    def state_path(self) -> Path:
        return self._state_path

    @property
    def state_dir(self) -> Path:
        return self._state_path.parent

    def _read(self) -> QuotaState:
        try:
            # `utf-8-sig` strips a leading BOM. The file is written without one, but
            # an editor, a PowerShell `Set-Content -Encoding utf8` on 5.1, or a hand
            # edit will add it, and plain utf-8 then leaves \ufeff in the text so
            # json.loads fails on a file that looks perfectly fine. Reading leniently
            # is better than telling the user their quota state is corrupt.
            text = self._state_path.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            self._state_error = None
            return QuotaState(day=self._today())
        except OSError:
            self._state_error = "unreadable"
            return self._fallback

        try:
            raw = json.loads(text)
            state = QuotaState(
                day=str(raw["day"]),
                used=int(raw["used"]),
                last=float(raw["last"]) if raw.get("last") is not None else None,
            )
        except (ValueError, KeyError, TypeError):
            # An existing but broken file must not be read as "zero used".
            self._state_error = "corrupt"
            return self._fallback
        self._state_error = None
        if state.day != self._today():
            return QuotaState(day=self._today())
        return state

    def _write(self, state: QuotaState) -> bool:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(
                json.dumps({"day": state.day, "used": state.used, "last": state.last}),
                encoding="utf-8",
            )
        except OSError:
            # Unknown counters are unsafe: stop after the reservation that
            # could not be persisted, instead of trusting the stale file.
            self._degraded = True
            self._fallback = state
            return False
        self._fallback = state
        return True

    @property
    def used_today(self) -> int:
        if self._degraded:
            return self._fallback.used
        return self._read().used

    @property
    def degraded(self) -> bool:
        return self._degraded

    @property
    def state_error(self) -> str | None:
        """Why the quota file could not be used, or None when it is fine."""

        self._read()
        return self._state_error

    @property
    def remaining_today(self) -> int | None:
        """How many requests are left, or None when that cannot be known.

        Returning None rather than the full limit is the point: `search` refuses to
        run while the state is unreadable, so reporting 300 here made `status` and
        `search` contradict each other — one said "full quota", the other said
        "corrupt".
        """

        if self._degraded:
            return max(0, self._limits.daily_request_limit - self._fallback.used)
        state = self._read()
        if self._state_error is not None:
            return None
        return max(0, self._limits.daily_request_limit - state.used)

    # -- validation ----------------------------------------------------

    def validate_plan(self, plan: Plan, manifest: ChannelManifest) -> None:
        actions = plan.actions
        if not actions:
            raise PolicyError("plan is empty", rule="plan.empty")
        if len(actions) > self._limits.max_actions_per_plan:
            raise PolicyError(
                f"plan has {len(actions)} actions, limit is {self._limits.max_actions_per_plan}",
                rule="plan.size",
            )

        total_ms = sum(action.timeout_ms for action in actions)
        if total_ms > self._limits.max_plan_seconds * 1000:
            raise PolicyError(
                f"plan budget {total_ms}ms exceeds {self._limits.max_plan_seconds}s",
                rule="plan.duration",
            )

        for action in actions:
            self._validate_action(action, manifest)

    def _validate_action(self, action: Action, manifest: ChannelManifest) -> None:
        if action.verb not in VERBS:
            raise PolicyError(f"unknown verb {action.verb!r}", rule="verb.unknown")
        if action.verb not in manifest.verbs:
            raise PolicyError(
                f"channel {manifest.channel!r} does not allow {action.verb!r}",
                rule="verb.not_allowed",
            )
        if action.timeout_ms < 0 or action.timeout_ms > 15_000:
            raise PolicyError(
                f"timeout {action.timeout_ms}ms is outside 0..15000",
                rule="action.timeout",
            )

        error = validate_params(action.verb, action.params)
        if error is not None:
            raise PolicyError(f"invalid parameters for {action.verb}: {error}", rule=error)

        if action.verb == "goto":
            if action.params.get("reload") is True:
                # A reload re-navigates to wherever the tab already sits, so the
                # kernel has no URL to check. The host validates the live URL
                # against the same allowlist before it reloads.
                return
            self.check_url(str(action.params["url"]), manifest.domains)

    def check_url(self, url: str, domains: Iterable[str]) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise PolicyError("only https URLs are allowed", rule="url.scheme")
        host = (parsed.hostname or "").casefold()
        allowed = {d.casefold() for d in domains}
        if not any(host == d or host.endswith("." + d) for d in allowed):
            raise PolicyError(f"host {host!r} is not allowed", rule="url.domain")

    # -- metering ------------------------------------------------------

    def wait_turn(self) -> float:
        """Reserve one network slot, sleeping for the interval if needed."""

        required = self._limits.min_interval_ms + self._jitter()
        slept = 0.0
        with interprocess_lock(self._lock_path, timeout_s=30.0):
            if self._degraded:
                raise PolicyError(
                    "quota state is not writable; refusing new network actions",
                    rule="quota.persistence",
                )
            state = self._read()
            if self._state_error is not None:
                raise PolicyError(
                    f"quota state is {self._state_error} at {self._state_path}; "
                    "delete the file to start a fresh day count, or repair it to "
                    '{"day": "YYYY-MM-DD", "used": N, "last": null}',
                    rule="quota.state",
                )
            if state.used >= self._limits.daily_request_limit:
                raise PolicyError("daily quota exhausted", rule="quota.daily")

            now = self._clock()
            if state.last is not None:
                elapsed_ms = (now - state.last) * 1000
                # ``last`` is a monotonic timestamp, and a monotonic clock
                # restarts from zero when the machine reboots. A negative
                # elapsed time therefore means "the clock restarted", not "we
                # are early"; treating it as early makes the first request after
                # a reboot sleep for the length of the previous uptime (observed:
                # ~5 hours, while holding the plan lock).
                if elapsed_ms < 0:
                    elapsed_ms = required
                remaining_ms = required - elapsed_ms
                if remaining_ms > 0:
                    slept = remaining_ms / 1000
                    self._sleep(slept)
                    now = self._clock()
            state.used += 1
            state.last = now
            # A failed write marks the engine degraded; the planner refuses to
            # send the reserved action (see Planner below).
            self._write(state)
        return slept

    def note_request(self) -> None:
        """Compatibility shim: the slot is already reserved by ``wait_turn``."""

    def reserve(self) -> float:
        """Alias for ``wait_turn`` used by the planner."""

        return self.wait_turn()
