"""F47-01 / F47-02: a timeout must not be dressed up as "never sent, just retry".

`TimeoutError("timed out")` contains no "timeout" in a form the old classifier looked for, so a read
that hit it answered "the navigation failed before it was issued: ask again" — while the frame had
already been written. These tests pin the evidence rule: only a pre-dispatch proof may say that.
"""

from __future__ import annotations

import socket
import threading

from scholar_search.adapters.bridge import BridgeAdapter
from scholar_search.core.contracts import Action
from scholar_search.core.service import _navigation_unconfirmed

URL = "https://pubs.acs.org/doi/10.1021/jacs.6c13448"


def test_a_read_timeout_is_unconfirmed_not_a_retry_invitation() -> None:
    answer = _navigation_unconfirmed(
        code="bridge.error: timed out",
        operation_id="op-1",
        doi="10.1016/j.cej.2023.145123",
        publisher="elsevier",
        target="https://www.sciencedirect.com/science/article/pii/X",
        error="bridge.error: timed out",
        issued=None,
    )

    assert answer["status"] == "timeout", answer
    assert answer["reason"] == "navigation_unconfirmed", answer
    assert answer["unconfirmed"] is True, answer
    assert answer["stage"] == "navigate", answer
    assert "ask again is safe" not in answer["next"], answer["next"]


def test_only_a_pre_dispatch_failure_may_invite_a_retry() -> None:
    answer = _navigation_unconfirmed(
        code="bridge.error: no live native host found",
        operation_id="op-2",
        doi="10.1016/j.cej.2023.145123",
        publisher="elsevier",
        target="https://www.sciencedirect.com/science/article/pii/X",
        error="bridge.error: no live native host found",
        issued=False,
    )

    assert answer["status"] == "error", answer
    assert answer["unconfirmed"] is False, answer
    assert "asking again is safe" in answer["next"], answer["next"]


def _listening() -> tuple[socket.socket, int]:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    return server, int(server.getsockname()[1])


def test_a_frame_that_was_written_never_reports_not_issued() -> None:
    """The fake socket accepts the request, then the reply read times out."""

    server, port = _listening()
    received: list[str] = []

    def serve() -> None:
        connection, _ = server.accept()
        with connection:
            line = connection.makefile("rb").readline()
            received.append(line.decode("utf-8"))
            # Never answer: the client's read deadline is what fails.

    threading.Thread(target=serve, daemon=True).start()
    adapter = BridgeAdapter()
    adapter._socket = socket.create_connection(("127.0.0.1", port), timeout=1.0)
    adapter._reader = adapter._socket.makefile("r", encoding="utf-8")
    adapter._timeout = 0.05

    outcome = adapter.execute(Action("goto", {"url": URL}), timeout_ms=50)
    adapter.close()

    assert received, "the frame really was written"
    assert outcome.ok is False
    data = dict(outcome.data or {})
    assert data.get("operation_id"), data
    assert data.get("operation_issued") is True, "a written frame must not claim 'not issued'"


def test_a_connect_failure_does_not_reuse_the_previous_operation_id(monkeypatch) -> None:
    """F47-02: `_last_request_id` was shared, so the second failure answered with the first id."""

    adapter = BridgeAdapter()
    adapter._last_request_id = "previous-success"
    adapter._dispatched = "previous-success"

    # Hermetic: a live host on this machine would make the "connect fails" scenario unreachable
    # (the frame would really be sent, and `operation_issued: true` would be the correct answer).
    def no_host() -> None:
        raise ConnectionError("no live native host found")

    monkeypatch.setattr(adapter, "_connect", no_host)

    outcome = adapter.execute(Action("goto", {"url": URL}), timeout_ms=50)

    assert outcome.ok is False
    data = dict(outcome.data or {})
    assert data.get("operation_id") != "previous-success", data
    assert data.get("operation_issued") is False, data
