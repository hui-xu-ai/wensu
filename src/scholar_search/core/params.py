"""Closed parameter schemas for the nine browser verbs.

Both the kernel and the native host validate with this module, so the accepted
shape cannot drift between layers.
"""

from __future__ import annotations

from typing import Any

MAX_TIMEOUT_MS = 15_000
MAX_TEXT_CHARS = 500
MAX_SLEEP_MS = 3_000

ALLOWED_KEYS: dict[str, frozenset[str]] = {
    "goto": frozenset({"url", "reload"}),
    "wait_for": frozenset({"selector", "timeout_ms", "state"}),
    "type": frozenset({"selector", "text", "clear"}),
    # `wait_until` lets a click report when the site finished the work it started.
    # A search button goes disabled while the query runs; waiting for it to come
    # back is the site's own "done" signal, which beats guessing a fixed pause.
    "click": frozenset({"selector", "wait_until", "timeout_ms"}),
    "select": frozenset({"selector", "value"}),
    "read_html": frozenset(),
    "read_text": frozenset({"selector", "mode"}),
    "scroll": frozenset({"to", "by"}),
    "sleep": frozenset({"ms"}),
}

WAIT_STATES = frozenset({"visible", "hidden"})
READ_TEXT_MODES = frozenset({"inner", "text"})
CLICK_WAIT_UNTIL = frozenset({"enabled"})


def _selector(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 2_000


def validate_params(verb: str, params: Any) -> str | None:
    """Return an error code, or None when the params match the verb schema."""

    allowed = ALLOWED_KEYS.get(verb)
    if allowed is None:
        return "policy.verb"
    if not isinstance(params, dict):
        return "policy.params"
    if set(params) - allowed:
        return "policy.params"

    if verb == "goto":
        if params.get("reload") is True:
            # A reload is the F5 the user would press. Measured on the live site:
            # the reloaded result page streams all 50 records through
            # runQueryGetRecordsStream and never issues runQuerySearch at all.
            return None
        url = params.get("url")
        if not isinstance(url, str) or not url.strip():
            return "policy.params"
        return None

    if verb in {"click", "read_text", "type", "select", "wait_for"}:
        if not _selector(params.get("selector")):
            return "policy.params"
        if verb == "type":
            text = params.get("text")
            if not isinstance(text, str) or len(text) > MAX_TEXT_CHARS:
                return "policy.params"
            if "clear" in params and not isinstance(params["clear"], bool):
                return "policy.params"
        if verb == "select" and not isinstance(params.get("value"), str):
            return "policy.params"
        if verb == "read_text" and params.get("mode", "inner") not in READ_TEXT_MODES:
            return "policy.params"
        if verb == "click" and "wait_until" in params:
            if params["wait_until"] not in CLICK_WAIT_UNTIL:
                return "policy.params"
            budget = params.get("timeout_ms", 10_000)
            if (
                not isinstance(budget, int)
                or isinstance(budget, bool)
                or not 0 <= budget <= MAX_TIMEOUT_MS
            ):
                return "policy.params"
        if verb == "wait_for":
            timeout = params.get("timeout_ms", 10_000)
            if (
                not isinstance(timeout, int)
                or isinstance(timeout, bool)
                or not 0 <= timeout <= MAX_TIMEOUT_MS
            ):
                return "policy.params"
            state = params.get("state", "visible")
            if state not in WAIT_STATES:
                return "policy.params"
        return None

    if verb == "scroll":
        if params.get("to") in {"top", "bottom"}:
            return None
        by = params.get("by")
        if isinstance(by, int) and not isinstance(by, bool) and 0 < by <= 10_000:
            return None
        return "policy.params"

    if verb == "sleep":
        ms = params.get("ms")
        if not isinstance(ms, int) or isinstance(ms, bool) or not 0 <= ms <= MAX_SLEEP_MS:
            return "policy.params"
        return None

    return None
