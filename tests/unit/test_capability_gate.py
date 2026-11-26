"""A verb is refused before it navigates when the running build cannot serve it (audit D batch).

`wait_for` was requested on publisher pages for a whole release while the content script was only
injected into the two channels' domains. The plan was accepted, the navigation was paid for, and
the action failed with "no receiver". The handshake now advertises what the running worker can do,
and the service refuses the plan first.
"""

from __future__ import annotations

from typing import Any

import pytest

from scholar_search.core.contracts import Action
from scholar_search.core.errors import ActionError

ADVERTISED = {
    "capabilities": ["goto", "snapshot", "sleep"],
    "channel_capabilities": ["read_text", "wait_for", "click"],
}


class _Adapter:
    def __init__(self, info: dict[str, Any] | None) -> None:
        self._info = info
        self.executed: list[str] = []

    def info(self) -> dict[str, Any]:
        return self._info or {}

    def execute(self, action: Action, *, timeout_ms: int) -> None:
        self.executed.append(action.verb)


def _service(adapter: _Adapter) -> Any:
    from scholar_search.core.service import ScholarService

    service = ScholarService.__new__(ScholarService)
    service._ensure_capabilities(adapter, _Plan("page:acs", (Action("wait_for"),)))
    return service


class _Plan:
    def __init__(self, channel: str, actions: tuple[Action, ...]) -> None:
        self.channel = channel
        self.actions = actions


def _gate(adapter: _Adapter, channel: str, *verbs: str) -> None:
    from scholar_search.core.service import ScholarService

    service = ScholarService.__new__(ScholarService)
    service._ensure_capabilities(adapter, _Plan(channel, tuple(Action(verb) for verb in verbs)))


def test_a_content_script_verb_is_refused_on_a_publisher_page() -> None:
    with pytest.raises(ActionError) as error:
        _gate(_Adapter(dict(ADVERTISED)), "page:acs", "goto", "wait_for")

    assert error.value.code == "action.unsupported"
    assert "wait_for" in str(error.value)


def test_the_same_verb_is_allowed_on_a_channel_page() -> None:
    _gate(_Adapter(dict(ADVERTISED)), "cnki", "goto", "wait_for")


def test_a_universal_verb_is_allowed_anywhere() -> None:
    _gate(_Adapter(dict(ADVERTISED)), "page:wiley", "goto", "sleep", "snapshot")


def test_an_unknown_capability_set_is_not_permission() -> None:
    """The gate used to return here, so the plan navigated and only then timed out (§2)."""

    with pytest.raises(ActionError) as error:
        _gate(_Adapter({}), "page:mdpi", "goto", "wait_for")

    assert error.value.code == "action.unsupported"


def test_a_host_that_never_answered_the_handshake_is_named_as_such() -> None:
    with pytest.raises(ActionError) as error:
        _gate(_Adapter({"handshake": "timeout"}), "page:mdpi", "goto")

    assert error.value.code == "bridge.handshake"


def test_an_older_worker_that_cannot_describe_itself_is_refused() -> None:
    with pytest.raises(ActionError) as error:
        _gate(_Adapter({"handshake": "old"}), "cnki", "goto")

    assert error.value.code == "action.unsupported"


def test_the_capability_list_reaches_the_native_host() -> None:
    """`cmd=info` reports the running host version and what the extension said about itself."""

    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "wensu_host_info", root / "native-host" / "main.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class _Host:
        def build_info(self) -> dict[str, Any]:
            return {"protocol": 1, "version": "0.14.29", "capabilities": ["goto"]}

    class _Connection:
        def __init__(self) -> None:
            self.sent: list[bytes] = []

        def makefile(self, *args: Any, **kwargs: Any) -> Any:
            import io
            import json

            return io.StringIO(json.dumps({"token": "t", "cmd": "info"}) + "\n")

        def sendall(self, payload: bytes) -> None:
            self.sent.append(payload)

        def close(self) -> None:
            return None

    connection = _Connection()
    module.serve_client(connection, _Host(), "t", ("pubs.acs.org",))

    import json

    reply = json.loads(connection.sent[-1].decode("utf-8"))
    assert reply["ok"] is True
    assert reply["build"]["capabilities"] == ["goto"]
    assert reply["host_version"]
