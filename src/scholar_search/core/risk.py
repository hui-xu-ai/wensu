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

# Gate pages keep a short, distinctive document title. These used to be matched as
# substrings of any title, which fired on ordinary articles — "Access Denied: 论跨境
# 数据主权" cost a whole day of cooldown for reading a paper. A title now has to be
# one of these exactly, or start with one and continue with the site's own name.
RISK_TITLE_MARKERS: tuple[str, ...] = (
    "安全验证",
    "验证中心",
    "session expired",
    "sign in",
    "access denied",
)

# Login redirects are not a captcha, but they still invalidate the plan.
LOGIN_URL_MARKERS: tuple[str, ...] = (
    "/login",
    "fsso.cnki.net",
    "login.aspx",
    # A bare "sso" used to be here and matched DOIs such as 10.1002/essoar.10501234.
    # An SSO hop appears as a host label or a path segment, so those forms only.
    "//sso.",
    ".sso.",
    "/sso/",
    "shibboleth",
    "carsi",
    "session-expired",
)


def _timestamp(value: object) -> datetime | None:
    """A timestamp from the state file, or None when it is absent or unusable.

    Naive values are read as UTC: the file is written by `isoformat()` on an aware
    datetime, but a hand-edited or older file must not make the comparison in
    `cooldown_until` raise.
    """

    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _title_is_gate(title: str) -> bool:
    """True when the document title names a gate page, not an article.

    An exact match always counts. A prefix match counts only when the remainder
    looks like a site name — short, and free of CJK — because an article whose
    title merely *starts* with "Access Denied" carries on in prose, usually in
    Chinese.
    """

    text = " ".join(title.split()).casefold()
    if not text:
        return False
    for marker in RISK_TITLE_MARKERS:
        lowered = marker.casefold()
        if text == lowered:
            return True
        if not text.startswith(lowered):
            continue
        tail = text[len(lowered) :]
        if any("\u4e00" <= char <= "\u9fff" for char in tail):
            continue
        if len(tail) <= 32:
            return True
    return False


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
        # When that in-memory deadline was recorded. A clear from another process is
        # honoured only if it happened *after* this point — see `cooldown_until`.
        self._memory_since: datetime | None = None

    # -- cooldown ------------------------------------------------------

    def cooldown_until(self) -> datetime | None:
        until = self._memory_until
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return until
        if not isinstance(raw, dict):
            return until

        cleared_at = _timestamp(raw.get("cleared_at"))
        if cleared_at is not None and (
            self._memory_since is None or cleared_at >= self._memory_since
        ):
            # Somebody lifted the cooldown after this process recorded its own deadline.
            # Holding the memory value would keep a long-lived server locked for a cooldown
            # a human already cleared — and the block message tells them to do exactly that,
            # so following the advice would appear to do nothing for 24 hours.
            self._memory_until = None
            self._memory_since = None
            until = None

        stored = _timestamp(raw.get("until"))
        if stored is not None and (until is None or stored > until):
            until = stored
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
        """Lift the cooldown for every process, including ones already running.

        Deleting the file was not enough. A long-lived process (the MCP server) also keeps
        the deadline in memory as a second lock, and `cooldown_until` took the later of the
        two — so `wensu reset --confirm`, the very command the block message recommends, did
        nothing until that process was restarted. The marker records *when* the clear
        happened, which is what lets a running guard tell "cleared after my deadline" from
        "cleared before it".
        """

        self._memory_until = None
        self._memory_since = None
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(
                json.dumps({"cleared_at": self._now().isoformat()}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            # No marker possible; fall back to the old behaviour so a deletable file at
            # least does not keep a fresh process blocked.
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
        if isinstance(title, str) and _title_is_gate(title):
            return RiskSignal.VERIFY_REDIRECT
        return None

    # -- tripping ------------------------------------------------------

    def trip(self, signal: RiskSignal, reason: str = "") -> RiskBlocked:
        until = self._now() + timedelta(hours=self._cooldown_hours)
        self._memory_until = until
        self._memory_since = self._now()
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
