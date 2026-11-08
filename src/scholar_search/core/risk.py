"""Risk detection and cooldown.

A risk signal is terminal for the session: the plan stops, the cooldown file is
written, and every later request is refused until a human clears it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import HARD, app_home
from .contracts import ActionOutcome, RiskSignal
from .errors import RiskBlocked

# URL fragments that mean "you are behind an interstitial", not a result page.
VERIFY_URL_MARKERS: tuple[str, ...] = (
    "/verify/home",
    "/verify/",
    "captcha",
    "recaptcha",
    "hcaptcha",
)

# Document titles that mean "you are on a gate page". Compared after casefold,
# so the English entries also match "Sign In" / "SIGN IN".
RISK_TITLE_MARKERS: tuple[str, ...] = (
    "安全验证",
    "验证中心",
    "session expired",
    "sign in",
    "access denied",
)

# Text that only appears when a human check is being demanded. Kept for
# reference; detection now relies on the content script's visibility flag.
CAPTCHA_TEXT_MARKERS: tuple[str, ...] = (
    "安全验证",
    "滑动验证",
    "请完成验证",
)

# Login redirects are not a captcha, but they still invalidate the plan.
LOGIN_URL_MARKERS: tuple[str, ...] = (
    "/login",
    "fsso.cnki.net",
    "login.aspx",
    # Web of Science (Clarivate) routes an expired session through an SSO hop.
    "sso",
    "shibboleth",
    "carsi",
    "session-expired",
)


class RiskGuard:
    """Inspects outcomes and owns the cooldown state."""

    def __init__(
        self,
        *,
        state_path: Path | None = None,
        now: Callable[[], datetime] | None = None,
        cooldown_hours: int = HARD.cooldown_hours,
    ) -> None:
        self._state_path = state_path or (app_home() / "state" / "cooldown.json")
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._cooldown_hours = cooldown_hours
        # Persistence can fail (read-only disk, sandbox); the signal still has
        # to block this process, so the deadline is also held in memory.
        self._memory_until: datetime | None = None

    # -- cooldown ------------------------------------------------------

    def cooldown_until(self) -> datetime | None:
        until = self._memory_until
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
            stored = datetime.fromisoformat(raw["until"])
            if until is None or stored > until:
                until = stored
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return until

    def ensure_ready(self) -> None:
        until = self.cooldown_until()
        if until is None:
            return
        if self._now() < until:
            raise RiskBlocked(
                f"risk cooldown active until {until.isoformat()}",
                signal="cooldown",
                cooldown_until=until.isoformat(),
            )

    def clear(self) -> None:
        self._memory_until = None
        self._state_path.unlink(missing_ok=True)

    # -- inspection ----------------------------------------------------

    def inspect(self, outcome: ActionOutcome) -> RiskSignal | None:
        if outcome.error:
            lowered = outcome.error.casefold()
            if "http 403" in lowered or "403" == lowered.strip():
                return RiskSignal.HTTP_403
            if "captcha" in lowered:
                return RiskSignal.CAPTCHA

        url = (outcome.url or "").casefold()
        if not url:
            nested = outcome.data.get("url")
            url = nested.casefold() if isinstance(nested, str) else ""
        if any(marker in url for marker in VERIFY_URL_MARKERS):
            return RiskSignal.VERIFY_REDIRECT
        if any(marker in url for marker in LOGIN_URL_MARKERS):
            return RiskSignal.LOGIN_REDIRECT

        status = outcome.data.get("status")
        if status == 403 or status == "403":
            return RiskSignal.HTTP_403
        if status == 429 or status == "429":
            return RiskSignal.RATE_LIMITED
        if outcome.error and "429" in outcome.error:
            return RiskSignal.RATE_LIMITED

        # The content script reports whether the captcha widget is actually on
        # screen; scanning raw HTML would match the SDK's hidden preloaded DOM.
        if outcome.data.get("captcha_visible") is True:
            return RiskSignal.CAPTCHA

        # Account verification gates ("手机号认证") are a login wall in disguise.
        if outcome.data.get("auth_required") is True:
            return RiskSignal.LOGIN_REDIRECT

        # Verification interstitials keep a short, distinctive document title.
        title = outcome.data.get("title")
        if isinstance(title, str) and any(
            marker in title.casefold() for marker in RISK_TITLE_MARKERS
        ):
            return RiskSignal.VERIFY_REDIRECT
        return None

    # -- tripping ------------------------------------------------------

    def trip(self, signal: RiskSignal, reason: str = "") -> RiskBlocked:
        until = self._now() + timedelta(hours=self._cooldown_hours)
        self._memory_until = until
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(
                json.dumps(
                    {
                        "signal": signal.value,
                        "reason": reason,
                        "until": until.isoformat(),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError:
            # The in-memory deadline above keeps blocking this process.
            pass
        return RiskBlocked(
            reason or f"risk signal detected: {signal.value}",
            signal=signal.value,
            cooldown_until=until.isoformat(),
        )
