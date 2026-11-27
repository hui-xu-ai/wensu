"""P1a-a: a reply that arrives after its caller gave up is kept, and never re-delivered.

The host used to drop the pending entry on timeout, so the answer to "did the browser actually
navigate?" was thrown away at the moment it became the only evidence. These tests drive the real
`BridgeHost` over real frames with fake streams.
"""

from __future__ import annotations

import io
from pathlib import Path

from scholar_search.adapters.bridge.host import BridgeHost, write_frame
from scholar_search.core.lease import LeaseStore, archive_late_reply


def _host(tmp_path: Path, seen: list[tuple[str, dict, str]]) -> BridgeHost:
    store = LeaseStore(tmp_path / "coordination")
    host = BridgeHost(
        stdin=io.BytesIO(),
        stdout=io.BytesIO(),
        late_replies=lambda rid, message, action: (
            seen.append((rid, message, action)),
            archive_late_reply(store, rid, message, action),
        )[-1],
    )
    # Skip the handshake: what is under test is the dispatch/timeout path, not negotiation (a
    # failed handshake returns before anything is sent, which has its own test).
    host._handshaked = True
    return host


def test_a_timeout_keeps_the_request_as_an_orphan(tmp_path: Path) -> None:
    seen: list[tuple[str, dict, str]] = []
    host = _host(tmp_path, seen)

    reply = host.request("goto", {"url": "https://pubs.acs.org/doi/10.1021/x"}, timeout_s=0.05)

    assert reply["error"] == "bridge.timeout"
    orphans = host.orphans()
    assert len(orphans) == 1
    assert next(iter(orphans.values()))["action"] == "goto"


def test_a_late_reply_archives_facts_and_is_not_delivered(tmp_path: Path) -> None:
    """The late frame carries navigation_id; it belongs to the old operation, not the next one."""

    seen: list[tuple[str, dict, str]] = []
    host = _host(tmp_path, seen)
    reply = host.request("goto", {"url": "https://pubs.acs.org/doi/10.1021/x"}, timeout_s=0.05)
    request_id = str(reply["id"])

    frames = io.BytesIO()
    write_frame(
        frames,
        {
            "type": "action_result",
            "id": request_id,
            "ok": True,
            "data": {"navigation_id": "nav-late", "tab_id": 12, "url": "https://pubs.acs.org/"},
        },
    )
    frames.seek(0)
    host._in = frames  # the extension's side of the pipe
    host.serve_extension()

    assert [item[0] for item in seen] == [request_id]
    assert host.orphans() == {}, "the archived request is no longer pending"

    archived = LeaseStore(tmp_path / "coordination").operation(request_id)
    assert archived is not None
    assert archived.navigation_issued is True
    assert archived.navigation_id == "nav-late"
    assert archived.tab_id == 12
    assert archived.outcome == "landed"


def test_an_unknown_late_reply_stays_unknown(tmp_path: Path) -> None:
    """A late error that is not a pre-navigation refusal does not become `issued: false`."""

    store = LeaseStore(tmp_path / "coordination")

    operation = archive_late_reply(
        store,
        "req-2",
        {"ok": False, "error": "bridge.timeout", "id": "req-2"},
        "goto",
    )

    assert operation.navigation_issued is None, operation.navigation_issued
    assert operation.outcome == "unknown"
    archived = store.operation("req-2")
    assert archived is not None and archived.navigation_issued is None


def test_a_reply_arriving_at_the_timeout_boundary_is_still_archived(tmp_path: Path) -> None:
    """F46-03: registering the orphan after `_wait` returned left a gap that dropped the reply.

    The transfer out of `_pending` now happens inside `_wait`'s critical section, so the frame is
    archived whether it lands just before or just after the deadline.
    """

    seen: list[tuple[str, dict, str]] = []
    store = LeaseStore(tmp_path / "coordination")
    host = BridgeHost(
        stdin=io.BytesIO(),
        stdout=io.BytesIO(),
        late_replies=lambda rid, message, action: (
            seen.append((rid, message, action)),
            archive_late_reply(store, rid, message, action),
        )[-1],
    )
    host._handshaked = True
    frame = {"type": "action_result", "id": "rid-boundary", "ok": True, "data": {"tab_id": 3}}

    with host._lock:
        host._pending["rid-boundary"] = None
        # The reply arrives while the caller is still inside `_wait`: the wait is over, the caller
        # has not returned yet. Simulating the read order explicitly, no sleeps.
        transfer = host._wait("rid-boundary", deadline=host._clock(), action="goto")
    assert transfer is None
    assert "rid-boundary" in host.orphans()

    frames = io.BytesIO()
    write_frame(frames, frame)
    frames.seek(0)
    host._in = frames
    host.serve_extension()

    assert [item[0] for item in seen] == ["rid-boundary"]
    archived = store.operation("rid-boundary")
    assert archived is not None and archived.tab_id == 3


def test_a_navigation_then_domain_refusal_is_not_written_as_not_issued(tmp_path: Path) -> None:
    """F46-02: `policy.domain` arrives *after* the navigation and carries its id.

    Classifying by the error prefix wrote `issued: false` for a page that had in fact been
    navigated — the one answer that invites a caller to navigate again.
    """

    store = LeaseStore(tmp_path / "coordination")

    operation = archive_late_reply(
        store,
        "req-4",
        {
            "ok": False,
            "error": "policy.domain",
            "id": "req-4",
            "data": {
                "navigation_attempts": 1,
                "navigation_id": "nav-redirect",
                "tab_id": 43,
                "url": "https://elsewhere.example/x",
            },
        },
        "goto",
    )

    assert operation.navigation_issued is True, operation.navigation_issued
    assert operation.outcome == "navigated_then_refused"
    assert operation.navigation_id == "nav-redirect"
    assert operation.tab_id == 43


def test_an_http_refusal_stays_unknown(tmp_path: Path) -> None:
    """403/429 keep their own risk meaning; they are not evidence about navigation."""

    store = LeaseStore(tmp_path / "coordination")

    operation = archive_late_reply(
        store, "req-5", {"ok": False, "error": "RISK_HTTP_403", "id": "req-5"}, "goto"
    )

    assert operation.navigation_issued is None
    assert operation.outcome == "unknown"


def test_a_pre_navigation_refusal_is_the_one_safe_false(tmp_path: Path) -> None:
    store = LeaseStore(tmp_path / "coordination")

    operation = archive_late_reply(
        store,
        "req-3",
        {"ok": False, "error": "policy.url_scheme", "id": "req-3"},
        "goto",
    )

    assert operation.navigation_issued is False
    assert operation.outcome == "refused"
