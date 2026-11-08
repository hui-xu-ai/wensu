"""Validation for messages crossing the native bridge.

The host is the second line of defence: even if the extension is compromised,
it can only ask for the nine verbs with the closed parameter schema. Domain
authority comes from the selected channel manifest, but the host always keeps a
trusted default and a request may only narrow that scope, never replace it.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

from ...core.params import validate_params

VERBS: frozenset[str] = frozenset(
    {
        "goto",
        "wait_for",
        "type",
        "click",
        "select",
        "read_html",
        "read_text",
        "scroll",
        "sleep",
    }
)

MAX_FRAME_BYTES = 2 * 1024 * 1024

# Trusted default scope used when no channel manifest is supplied. The host
# keeps its own copy on purpose: a compromised extension cannot widen it, so a
# new channel has to be added here as well as in its manifest.
TRUSTED_DOMAINS: tuple[str, ...] = (
    "kns.cnki.net",
    "www.cnki.net",
    "webofscience.clarivate.cn",
    "www.webofscience.com",
)


def _host_allowed(host: str, domains: Iterable[str]) -> bool:
    host = host.casefold()
    for domain in domains:
        domain = domain.casefold()
        if host == domain or host.endswith("." + domain):
            return True
    return False


def narrow_domains(requested: Iterable[str] | None, trusted: Iterable[str]) -> tuple[str, ...]:
    """Keep only requested domains that fall inside the trusted scope."""

    trusted_list = tuple(trusted)
    if not requested:
        return trusted_list
    narrowed = tuple(
        item
        for item in requested
        if any(
            item.casefold() == trusted.casefold()
            or item.casefold().endswith("." + trusted.casefold())
            for trusted in trusted_list
        )
    )
    return narrowed or trusted_list


def validate_request(message: dict[str, Any], domains: Iterable[str] | None = None) -> str | None:
    """Return an error code, or None when the request is acceptable."""

    action = message.get("action")
    if not isinstance(action, str) or action not in VERBS:
        return "policy.verb"

    params = message.get("params", {})
    error = validate_params(action, params)
    if error is not None:
        return error

    if action == "goto":
        if params.get("reload") is True:
            # No URL travels with a reload; the extension checks the live one
            # against the same allowlist immediately before reloading.
            return None
        allowed = tuple(domains) if domains is not None else TRUSTED_DOMAINS
        parsed = urlparse(str(params["url"]))
        if parsed.scheme != "https":
            return "policy.url_scheme"
        if not parsed.hostname or not _host_allowed(parsed.hostname, allowed):
            return "policy.domain"
    return None
