from __future__ import annotations

import io
import json
import socket
import threading
from pathlib import Path

from scholar_search.adapters.bridge import BridgeAdapter
from scholar_search.adapters.bridge.host import BridgeHost, read_frame, write_frame
from scholar_search.adapters.bridge.policy import narrow_domains, validate_request
from scholar_search.core.contracts import Action


def test_narrow_domains_fails_closed_when_nothing_survives() -> None:
    """An out-of-scope request must yield an empty set, never the full list.

    Returning the trusted list here would hand back a wider scope than the caller
    asked for — the exact fail-open the module's own docstring forbids.
    """

    assert narrow_domains(["evil.test"], ("good.test",)) == ()
    assert narrow_domains(["good.test"], ("good.test",)) == ("good.test",)
    assert narrow_domains(None, ("good.test",)) == ("good.test",)


def test_policy_accepts_allowed_goto() -> None:
    assert validate_request({"action": "goto", "params": {"url": "https://kns.cnki.net/x"}}) is None


def test_policy_rejects_http_and_foreign_host() -> None:
    insecure = {"action": "goto", "params": {"url": "http://kns.cnki.net/"}}
    foreign = {"action": "goto", "params": {"url": "https://evil.test/"}}
    assert validate_request(insecure, ("kns.cnki.net",)) == "policy.url_scheme"
    assert validate_request(foreign, ("kns.cnki.net",)) == "policy.domain"


def test_policy_rejects_unknown_verb() -> None:
    assert validate_request({"action": "eval", "params": {}}) == "policy.verb"


def test_policy_bounds_sleep() -> None:
    assert validate_request({"action": "sleep", "params": {"ms": 3000}}) is None
    assert validate_request({"action": "sleep", "params": {"ms": 3001}}) == "policy.params"


def test_frame_roundtrip() -> None:
    buffer = io.BytesIO()
    write_frame(buffer, {"type": "action", "id": "1"})
    buffer.seek(0)
    assert read_frame(buffer) == {"type": "action", "id": "1"}
    assert read_frame(buffer) is None


def test_bridge_request_times_out() -> None:
    host = BridgeHost(stdin=io.BytesIO(), stdout=io.BytesIO())
    reply = host.request("read_html", {}, timeout_s=0.05)
    assert reply["ok"] is False
    assert reply["error"] == "bridge.timeout"


def test_adapter_roundtrip(tmp_path: Path) -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = int(server.getsockname()[1])
    token = "test-token"

    def serve() -> None:
        for _ in range(2):
            connection, _ = server.accept()
            with connection, connection.makefile("r", encoding="utf-8") as reader:
                request = json.loads(reader.readline())
                assert request["token"] == token
                if request.get("cmd") == "ping":
                    connection.sendall(b'{"ok":true}\n')
                    continue
                reply = {
                    "id": request["id"],
                    "ok": True,
                    "data": {"html": "<html/>"},
                    "url": "https://kns.cnki.net/x",
                    "duration_ms": 5,
                }
                connection.sendall((json.dumps(reply) + "\n").encode("utf-8"))
        server.close()

    threading.Thread(target=serve, daemon=True).start()
    endpoint = tmp_path / "bridge.json"
    endpoint.write_text(json.dumps({"port": port, "token": token}), encoding="utf-8")

    adapter = BridgeAdapter(endpoint=endpoint, timeout_s=5)
    outcome = adapter.execute(Action("read_html"), timeout_ms=1000)
    adapter.close()

    assert outcome.ok
    assert outcome.data["html"] == "<html/>"
    assert outcome.url == "https://kns.cnki.net/x"
