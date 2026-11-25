"""Plan validation and execution.

Sequencing lives here, not in adapters: this is the only place that can stop a
plan between two actions when a risk signal appears. A whole plan holds an
inter-process lock, because the browser is a single shared resource, and the
shared cooldown is re-checked before every action.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlparse

from .audit import AuditLog
from .config import HARD
from .contracts import (
    Action,
    ActionOutcome,
    BrowserAdapter,
    ChannelManifest,
    Plan,
    RiskSignal,
)
from .errors import PolicyError, RiskBlocked
from .locking import interprocess_lock
from .policy import NETWORK_VERBS, PolicyEngine
from .risk import RiskGuard

# Signals a person clears in seconds by acting in the browser: tick the box, slide the
# puzzle, sign back in. CNKI's `/verify/home` and Web of Science's Cloudflare interstitial
# are the same wall as a publisher's, so the channel does not decide this — the signal does.
# Stopping the plan is right; cooling the whole tool down turns one click into a day of
# downtime (ADR 0022).
_SOFT_SIGNALS = frozenset(
    {RiskSignal.CAPTCHA, RiskSignal.VERIFY_REDIRECT, RiskSignal.LOGIN_REDIRECT}
)


def _stops_without_cooldown(signal: RiskSignal) -> bool:
    """A signal a human clears: stop, ask, do not punish the machine."""

    return signal in _SOFT_SIGNALS


def _risk_reason(signal: object, action: Action, outcome: ActionOutcome) -> str:
    """Why the guard stopped, with the one fact needed to tell the cases apart.

    The stored reason used to be `login_redirect after goto`, which says nothing about
    *where* the tab went. A refused navigation to an institutional sign-in, to a
    publisher's login wall and to `www.webofscience.com` all produce that string, and
    they need opposite responses: sign in, stop, or nothing wrong at all.

    Only the **host** is recorded — never the path or query. Which host was reached is
    the whole diagnostic value, and a host is not account data.
    """

    name = getattr(signal, "value", str(signal))
    detail = f"{name} after {action.verb}"
    url = (outcome.url or "").strip()
    if not url and isinstance(outcome.data, dict):
        nested = outcome.data.get("url")
        url = nested.strip() if isinstance(nested, str) else ""
    if url:
        host = (urlparse(url).hostname or "").casefold()
        if host:
            detail = f"{detail} at {host}"
    if outcome.error:
        detail = f"{detail} ({outcome.error})"
    return detail


@dataclass(slots=True)
class Planner:
    adapter: BrowserAdapter
    policy: PolicyEngine
    risk: RiskGuard
    audit: AuditLog

    def run(self, plan: Plan, manifest: ChannelManifest) -> tuple[ActionOutcome, ...]:
        lock_path = self.policy.state_dir / "plan.lock"
        with interprocess_lock(lock_path, timeout_s=90.0):
            return self._run_locked(plan, manifest)

    def _run_locked(self, plan: Plan, manifest: ChannelManifest) -> tuple[ActionOutcome, ...]:
        self.risk.ensure_ready()
        self.policy.validate_plan(plan, manifest)

        if hasattr(self.adapter, "domains"):
            self.adapter.domains = manifest.domains

        outcomes: list[ActionOutcome] = []
        for action in plan.actions:
            # Another process may have tripped the shared cooldown mid-plan.
            self.risk.ensure_ready()

            network = action.verb in NETWORK_VERBS
            if network:
                # In-page UI plans get the small slot: the page is already open and its own
                # code answers in milliseconds (ADR 0023). The quota unit is still debited —
                # `wait_turn` is where accounting lives — so `quota_charged` does not move.
                self.policy.wait_turn(
                    interval_ms=HARD.ui_interval_ms if plan.pacing == "ui" else None,
                    channel=plan.channel,
                    verb=action.verb,
                )
                if self.policy.degraded:
                    raise PolicyError(
                        "quota reservation could not be persisted; refusing the action",
                        rule="quota.persistence",
                    )
                # The interval wait can take seconds; another process may have
                # tripped the shared cooldown while we were sleeping.
                self.risk.ensure_ready()

            started = time.perf_counter()
            outcome = self.adapter.execute(action, timeout_ms=action.timeout_ms)
            elapsed_ms = outcome.duration_ms or int((time.perf_counter() - started) * 1000)

            self.audit.action(
                channel=plan.channel,
                purpose=plan.purpose,
                verb=action.verb,
                ok=outcome.ok,
                duration_ms=elapsed_ms,
                error=outcome.error,
            )
            outcomes.append(outcome)

            signal = self.risk.inspect(outcome)
            if signal is not None:
                if _stops_without_cooldown(signal):
                    # A verification wall: stop the plan, save nothing, and let
                    # the person click through it. Cooling the machine down for a day would
                    # turn one click into an outage (ADR 0022) — and the wall is expected
                    # traffic, not abuse.
                    self.audit.risk(
                        channel=plan.channel,
                        signal=signal.value,
                        cooldown_until=None,
                    )
                    raise RiskBlocked(
                        _risk_reason(signal, action, outcome),
                        signal=signal.value,
                        cooldown_until=None,
                    )
                blocked = self.risk.trip(signal, _risk_reason(signal, action, outcome))
                self.audit.risk(
                    channel=plan.channel,
                    signal=signal.value,
                    cooldown_until=blocked.cooldown_until,
                )
                raise blocked

            if not outcome.ok:
                # Stop here: dependent actions must not run on a failed step.
                break

        return tuple(outcomes)
