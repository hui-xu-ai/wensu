"""Closed parameter schemas for the ten browser verbs.

Both the kernel and the native host validate with this module, so the accepted
shape cannot drift between layers.
"""

from __future__ import annotations

from typing import Any

MAX_TIMEOUT_MS = 15_000
# How much text one `type` action may carry.
#
# This is not a human-typing budget — `humanType` assigns `element.value` in a single
# statement and dispatches events, so the site sees a paste, not 12 000 keystrokes.
# The cap exists so a tab cannot be handed an unbounded string.
#
# 16 000, raised from 500 by ADR 0015. A Web of Science expression that excludes the
# records already collected grows by ~25 characters per record: 50 exclusions make
# 1 372 characters and 500 make 12 622. At 500 the ceiling silently limited
# `exclude_ut` to about seventeen identifiers — the parameter accepted 500 and the
# type verb refused the expression built from them, so the feature worked in testing
# (three identifiers) and failed at the size it was documented for.
MAX_TEXT_CHARS = 16_000
MAX_SLEEP_MS = 3_000

ALLOWED_KEYS: dict[str, frozenset[str]] = {
    "goto": frozenset({"url", "reload", "open", "close", "wait", "dwell_ms"}),
    "wait_for": frozenset({"selector", "timeout_ms", "state"}),
    "type": frozenset({"selector", "text", "clear"}),
    # `wait_until` lets a click report when the site finished the work it started.
    # A search button goes disabled while the query runs; waiting for it to come
    # back is the site's own "done" signal, which beats guessing a fixed pause.
    # `expect_download` asks the extension to report the file a click produced. It is a
    # parameter of an existing verb rather than a tenth verb: the click had to happen
    # anyway to make the site export anything, so the file is the click's own outcome.
    "click": frozenset({"selector", "wait_until", "timeout_ms", "expect_download"}),
    "select": frozenset({"selector", "value"}),
    "read_html": frozenset(),
    "read_text": frozenset({"selector", "mode"}),
    "scroll": frozenset({"to", "by"}),
    "sleep": frozenset({"ms"}),
    # No parameters for a capture; `token`/`offset` read the bytes back in chunks, because
    # the browser's download manager blocks every `.mhtml` it writes (ADR 0018).
    "snapshot": frozenset({"token", "offset", "tab"}),
}

WAIT_STATES = frozenset({"visible", "hidden"})
# `goto` normally drives the one work tab. `open: "new"` opens a separate tab for a single
# navigation, `close: "disposable"` blanks those tabs on the next navigation (a blank tab can
# be reused; a closed one cannot), and `wait: "none"` returns as soon as the navigation is
# issued. Parameters of an existing verb, not new verbs.
GOTO_OPEN = frozenset({"work", "new"})
# `wait: "none"` returns as soon as the navigation is issued, for callers that immediately
# replace the tab's contents and do not need the load event.
GOTO_WAIT = frozenset({"load", "none"})
GOTO_CLOSE = frozenset({"disposable"})
READ_TEXT_MODES = frozenset({"inner", "text"})
# Which tab a capture reads: the dedicated work tab, or whatever the user is looking at.
SNAPSHOT_TABS = frozenset({"work", "active"})
# What a click can wait for before answering: `enabled` = the control went busy and came
# back; `url` = the tab's address moved. Web of Science never leaves `enabled` on submit but
# moves the route in 1–3 s, so `url` is both faster and truer there (2026-11-24, ADR 0023).
CLICK_WAIT_UNTIL = frozenset({"enabled", "url"})


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
        if "open" in params and params["open"] not in GOTO_OPEN:
            return "policy.params"
        if "close" in params and params["close"] not in GOTO_CLOSE:
            return "policy.params"
        if "wait" in params and params["wait"] not in GOTO_WAIT:
            return "policy.params"
        if "dwell_ms" in params:
            dwell = params["dwell_ms"]
            if not isinstance(dwell, int) or isinstance(dwell, bool) or not 0 <= dwell <= 3_000:
                return "policy.params"
        if params.get("reload") is True:
            # A reload is the F5 the user would press. Measured on the live site:
            # the reloaded result page streams all 50 records through
            # runQueryGetRecordsStream and never issues runQuerySearch at all.
            return None
        url = params.get("url")
        if not isinstance(url, str) or not url.strip():
            return "policy.params"
        return None

    if verb == "snapshot":
        if "tab" in params and params["tab"] not in SNAPSHOT_TABS:
            return "policy.params"
        if "offset" in params and not isinstance(params["offset"], int):
            return "policy.params"
        if "token" in params and not isinstance(params["token"], str):
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
        if (
            verb == "click"
            and "expect_download" in params
            and not isinstance(params["expect_download"], bool)
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
