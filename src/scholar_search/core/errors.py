"""Error hierarchy.

Errors carry enough structure for transports to render actionable messages
without leaking page content or session material.
"""

from __future__ import annotations

from dataclasses import dataclass


class ScholarSearchError(Exception):
    """Base class for all project errors."""


class ChannelError(ScholarSearchError):
    """Channel could not be loaded or is not compatible."""


class ChannelNotFound(ChannelError):
    """No channel registered under that name."""


class PolicyError(ScholarSearchError):
    """An action, domain, or rate violates the policy."""

    def __init__(self, message: str, *, rule: str = "") -> None:
        super().__init__(message)
        self.rule = rule


class ActionError(ScholarSearchError):
    """A browser action failed; dependent actions must not run."""

    def __init__(
        self,
        message: str,
        *,
        verb: str,
        code: str,
        stage: str | None = None,
        diagnostics: dict[str, object] | None = None,
        operation_id: str = "",
        operation_issued: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.verb = verb
        self.code = code
        # Which action this was, so a caller told "timeout" can ask the ledger what became of it
        # (F46-01). Empty when the action never reached the wire.
        self.operation_id = operation_id
        # `False` only with proof the frame never left; `None` means "unknown", which is what every
        # bridge timeout is (F47-01).
        self.operation_issued = operation_issued
        # Where in the plan it stopped. `stage` is a short kind label such as
        # `wait.capture` or `click.submit`, never a selector: three different waits in
        # one WoS search used to be indistinguishable from the outside.
        self.stage = stage
        # What the page held when the wait ran out, when the channel can describe it.
        # `wait.capture` timing out means "no reply in time" and nothing more; whether
        # the stream never started, never finished, or finished without raising the
        # readiness flag are three different bugs, and only the page can say which.
        self.diagnostics = diagnostics


class RiskBlocked(ScholarSearchError):
    """A risk signal was detected; execution stops immediately.

    `cooldown_until` is None when the stop carries no cooldown — a publisher's verification
    wall is solved by the person in front of the browser in seconds, so punishing the machine
    for a day is the wrong reaction (ADR 0022). Signals that mean abuse or a broken session
    still carry the 24 h cooldown from ADR 0004.
    """

    def __init__(
        self,
        message: str,
        *,
        signal: str,
        cooldown_until: str | None = None,
        charged: int = 1,
    ) -> None:
        super().__init__(message)
        self.signal = signal
        self.cooldown_until = cooldown_until
        # How many network actions ran before the stop. The planner knows; a caller that only has
        # the plan would have to guess (and guessed wrong when the first navigation was refused).
        self.charged = charged

    def to_payload(self) -> dict[str, str]:
        payload: dict[str, str] = {
            "status": "blocked",
            "signal": self.signal,
            "action_required": "manual_verification",
        }
        if self.cooldown_until is not None:
            payload["cooldown_until"] = self.cooldown_until
        advice = _RISK_ADVICE.get(self.signal)
        if advice is not None:
            # Only a stop that cools down has an escape hatch worth naming, and only for the
            # signals a person can actually clear: a 403 is not fixed by signing in, so it
            # must not be told to `reset` (ADR 0022 keeps the wall advice cooldown-free).
            if self.cooldown_until is not None and self.signal in _CLEARABLE_SIGNALS:
                advice = f"{advice} After solving it, run `wensu reset --confirm`."
            payload["advice"] = advice
        return payload


# What the person in front of the browser has to do, per signal. Without this the
# payload said only "blocked, try again in 24 hours", which is the wrong instruction for
# three of the four: a captcha is solved in seconds, and an expired session is signed
# back in. Waiting a day fixes neither, and the way out — `reset --confirm` — was never
# mentioned anywhere the caller could see.
# Signals a person clears by acting in the browser (sign in, tick the box). Only these get
# the reset exit named, and only when a cool-down was actually written.
_CLEARABLE_SIGNALS = frozenset({"captcha", "verify_redirect", "login_redirect"})
_RISK_ADVICE: dict[str, str] = {
    "login_redirect": (
        "The browser profile's session ended: the site sent the tab to a sign-in URL. "
        "Sign in to the site in that same browser window, confirm a search works there, "
        "then ask again. No cool-down is recorded for this — waiting never helped, because "
        "nothing was wrong with the network, only with the session (ADR 0022)."
    ),
    "captcha": (
        "Solve the captcha in that browser window yourself. Never automate it, and do not "
        "retry before solving it — the tool stops at the wall instead of pushing through."
    ),
    "verify_redirect": (
        "The site asked for a human check (a verification wall). Complete it in that browser "
        "window, then make the same request again — a solved wall is read from the open tab, "
        "free. No cooldown applies: this is expected traffic, not abuse (ADR 0022)."
    ),
    "http_403": (
        "The site refused the request with 403. Stop for the day; retrying, changing "
        "network or switching profile turns a temporary refusal into a durable one."
    ),
    "rate_limited": (
        "The site answered 429. Stop for the day; the quota is not the problem, the "
        "request rate is."
    ),
    "cooldown": (
        "A cooldown is already running. Do not retry; wait it out or, after fixing the "
        "underlying cause in the browser, run `wensu reset --confirm`."
    ),
    "text_marker": (
        "The page itself showed wording that means access was refused — a block notice, "
        "an account wall, or a 'too many requests' page. Read that page in the browser "
        "before doing anything else: the wording says which of those it is, and only one "
        "of them is fixed by signing in."
    ),
}


class ParseError(ScholarSearchError):
    """Page structure did not match the channel's expectations."""

    @dataclass(frozen=True, slots=True)
    class Context:
        channel: str
        site_version: str
        purpose: str

    def __init__(self, message: str, *, context: Context | None = None) -> None:
        super().__init__(message)
        self.context = context


class BridgeError(ScholarSearchError):
    """Native messaging transport failed."""


class BridgeTimeout(BridgeError):
    """The browser did not answer within the deadline."""


class BridgeAmbiguous(BridgeError):
    """More than one host is running and they cannot be told apart.

    Each host reports the profile from the same `browser.json`, so with two browsers
    open every endpoint claims the same profile and the label identifies nothing.
    Picking one would succeed, return a real page, and possibly answer with another
    search's results — so the call is refused instead. Starting one browser, or one
    host per profile with `WENSU_PROFILE`, removes the ambiguity.
    """
