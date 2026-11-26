"""The TCP handler's domain narrowing, end to end (audit 2026-11-26, F04).

`narrow_domains` already failed closed; the *caller* undid it with `effective or None`, so a
request whose domains survived nothing was served with the default trusted list. Testing the
helper alone could never have caught that — this drives the handler itself.
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
NATIVE_HOST = ROOT / "native-host" / "main.py"
TOKEN = "test-token"


def _handler() -> Any:
    spec = importlib.util.spec_from_file_location("wensu_native_host_main", NATIVE_HOST)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Connection:
    """The socket surface `serve_client` uses, with no operating-system socket involved."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._lines = (json.dumps({"token": TOKEN, **payload}) + "\n").encode("utf-8")
        self.sent: list[bytes] = []

    def makefile(self, *args: Any, **kwargs: Any) -> io.StringIO:
        return io.StringIO(self._lines.decode("utf-8"))

    def sendall(self, payload: bytes) -> None:
        self.sent.append(payload)

    def close(self) -> None:
        return None

    def reply(self) -> dict[str, Any]:
        assert self.sent, "the handler answered nothing"
        return json.loads(self.sent[-1].decode("utf-8"))


class _Host:
    """Records what the handler asked for; returns a fixed reply."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def request(self, action: str, params: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"action": action, "params": params, **kwargs})
        return {"ok": True}


def _serve(payload: dict[str, Any], trusted: tuple[str, ...]) -> tuple[dict[str, Any], _Host]:
    module = _handler()
    host = _Host()
    connection = _Connection(payload)
    module.serve_client(connection, host, TOKEN, trusted)  # type: ignore[arg-type]
    return connection.reply(), host


def test_a_domain_scope_that_survives_nothing_is_refused() -> None:
    reply, host = _serve(
        {"action": "goto", "params": {"url": "https://example.org/"}, "domains": ["evil.example"]},
        ("pubs.acs.org",),
    )

    assert reply.get("ok") is False, reply
    assert reply.get("error") == "policy.domains", reply
    assert host.calls == [], "nothing may reach the browser"


def test_no_domain_scope_keeps_the_default_behaviour() -> None:
    reply, host = _serve(
        {"action": "goto", "params": {"url": "https://pubs.acs.org/"}}, ("pubs.acs.org",)
    )

    assert reply.get("ok") is True, reply
    assert host.calls and host.calls[0]["domains"] == ("pubs.acs.org",), host.calls


def test_a_domain_inside_the_trusted_scope_is_passed_through() -> None:
    reply, host = _serve(
        {"action": "goto", "params": {"url": "https://pubs.acs.org/"}, "domains": ["pubs.acs.org"]},
        ("pubs.acs.org", "onlinelibrary.wiley.com"),
    )

    assert reply.get("ok") is True, reply
    assert host.calls[0]["domains"] == ("pubs.acs.org",), host.calls
