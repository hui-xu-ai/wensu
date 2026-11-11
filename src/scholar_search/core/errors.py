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
    ) -> None:
        super().__init__(message)
        self.verb = verb
        self.code = code
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
    """A risk signal was detected; execution stops immediately."""

    def __init__(self, message: str, *, signal: str, cooldown_until: str) -> None:
        super().__init__(message)
        self.signal = signal
        self.cooldown_until = cooldown_until

    def to_payload(self) -> dict[str, str]:
        payload = {
            "status": "blocked",
            "signal": self.signal,
            "cooldown_until": self.cooldown_until,
            "action_required": "manual_verification",
        }
        advice = _RISK_ADVICE.get(self.signal)
        if advice is not None:
            payload["advice"] = advice
        return payload


# What the person in front of the browser has to do, per signal. Without this the
# payload said only "blocked, try again in 24 hours", which is the wrong instruction for
# three of the four: a captcha is solved in seconds, and an expired session is signed
# back in. Waiting a day fixes neither, and the way out — `reset --confirm` — was never
# mentioned anywhere the caller could see.
_RISK_ADVICE: dict[str, str] = {
    "login_redirect": (
        "The browser profile's session ended: the site sent the tab to a sign-in URL. "
        "Sign in to the site in that same browser window, confirm a search works there, "
        "then run `wensu reset --confirm`. Waiting will not help — nothing is wrong with "
        "the network, only with the session."
    ),
    "captcha": (
        "Solve the captcha in that browser window, then run `wensu reset --confirm`. "
        "Never automate it, and do not retry before solving it."
    ),
    "verify_redirect": (
        "The site asked for account verification. Complete it in the browser window, "
        "then run `wensu reset --confirm`."
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
