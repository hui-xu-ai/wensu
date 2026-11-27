"""P0 of the lease plan: the contract is executable before anything writes a lease.

These tests are the reason `core/lease.py` exists at this stage — the module is inert, and what it
buys is that the vocabulary, the transitions and the release-evidence table are pinned down in a
form that fails loudly if someone later adds the two edges the plan forbids.
"""

from __future__ import annotations

from scholar_search.core.lease import (
    LEASE_REASONS,
    LEASE_STATES,
    NOT_EVIDENCE,
    OPERATION_STATES,
    RECEIPT_KEYS,
    RELEASE_EVIDENCE,
    Lease,
    Operation,
    issued_reason,
    next_states,
)


def test_no_state_reaches_free_on_its_own() -> None:
    """The two forbidden edges: "TTL expired" and "next request arrived".

    Only `releasing` may become `free`, and `releasing` is entered from `active`/`recovering` after
    evidence — never from `unconfirmed` and never from `quarantined`.
    """

    for state in LEASE_STATES:
        if state in {"free", "releasing"}:
            continue
        assert "free" not in next_states(state), state
        assert "active" not in next_states(state), state


def test_an_unknown_lease_cannot_be_admitted() -> None:
    assert next_states("unconfirmed") == frozenset({"recovering", "quarantined"})
    assert next_states("quarantined") == frozenset({"recovering"})
    assert "free" not in next_states("quarantined")


def test_free_is_only_left_by_acquiring() -> None:
    assert next_states("free") == frozenset({"active"})
    assert next_states("releasing") == frozenset({"free"})


def test_every_lease_state_and_operation_state_is_named() -> None:
    assert LEASE_STATES == {
        "free",
        "active",
        "releasing",
        "unconfirmed",
        "recovering",
        "quarantined",
    }
    assert OPERATION_STATES == {"prepared", "executing", "settled", "unknown"}


def test_a_lease_with_an_unconfirmed_navigation_cannot_be_released() -> None:
    lease = Lease(lease_id="L1", fence=1, owner_finished=True)
    lease.add(
        Operation(
            operation_id="op-1",
            action="goto",
            state="executing",
            navigation_issued=True,
        )
    )

    allowed, missing = lease.can_release("settled_with_receipt")

    assert allowed is False
    assert "operation_unresolved" in missing


def test_time_and_observation_are_not_evidence() -> None:
    """URL/title/tab-complete/deadline are observations, and the plan says they do not release."""

    assert NOT_EVIDENCE.isdisjoint(RELEASE_EVIDENCE)
    lease = Lease(lease_id="L1", fence=1, owner_finished=True)
    lease.add(Operation(operation_id="op-1", action="goto").settled(outcome="landed", at=1.0))

    for observation in sorted(NOT_EVIDENCE):
        allowed, missing = lease.can_release(observation)
        assert allowed is False, observation
        assert "evidence_not_conclusive" in missing


def test_the_caller_must_have_finished_its_call() -> None:
    lease = Lease(lease_id="L1", fence=1, owner_finished=False)
    lease.add(Operation(operation_id="op-1", action="goto").settled(outcome="landed", at=1.0))

    allowed, missing = lease.can_release("settled_with_receipt")

    assert allowed is False
    assert "owner_not_finished" in missing


def test_all_conditions_met_allows_release() -> None:
    lease = Lease(lease_id="L1", fence=1, owner_finished=True)
    lease.add(Operation(operation_id="op-1", action="goto").settled(outcome="landed", at=1.0))

    assert lease.can_release("settled_with_receipt") == (True, ())


def test_a_settled_but_not_quiescent_operation_still_holds_the_lease() -> None:
    operation = Operation(operation_id="op-1", action="goto", state="settled", quiescent=False)
    lease = Lease(lease_id="L1", fence=1, owner_finished=True)
    lease.add(operation)

    assert lease.unresolved() == [operation]
    assert lease.can_release("settled_with_receipt")[0] is False


def test_issued_false_only_comes_from_a_statement_about_the_browser() -> None:
    """A timeout or a broken socket is `unconfirmed`; only an explicit `False` is "not issued"."""

    assert issued_reason(False) == "navigation_not_issued"
    assert issued_reason(True) == "navigation_unconfirmed"
    assert issued_reason(None) == "navigation_unconfirmed"
    assert {"navigation_not_issued", "navigation_unconfirmed"} <= LEASE_REASONS


def test_the_store_refuses_a_second_lease_and_has_no_ttl(tmp_path) -> None:
    """Two browsers' worth of callers, one lease: the second gets None, not a wait and not a TTL."""

    from scholar_search.core.lease import LeaseStore

    store = LeaseStore(tmp_path / "coordination", clock=lambda: 1_000.0)
    first = store.acquire(lease_id="L1", job_id="job-1")
    assert first is not None and first.fence == 1

    assert store.acquire(lease_id="L2") is None
    # A clock far in the future changes nothing: there is no expiry edge to trigger.
    later = LeaseStore(tmp_path / "coordination", clock=lambda: 10**9)
    assert later.read().state == "active"
    assert later.acquire(lease_id="L3") is None


def test_only_the_owner_can_finish(tmp_path) -> None:
    from scholar_search.core.lease import LeaseStore

    store = LeaseStore(tmp_path / "coordination")
    lease = store.acquire(lease_id="L1")
    assert lease is not None

    stolen = store.finish(lease_id="other", fence=lease.fence, evidence="settled_with_receipt")

    assert stolen.state == "active", stolen.state


def test_finishing_with_an_unresolved_operation_keeps_the_lease(tmp_path) -> None:
    from scholar_search.core.lease import LeaseStore, Operation

    store = LeaseStore(tmp_path / "coordination")
    lease = store.acquire(lease_id="L1")
    assert lease is not None
    store.record_operation(
        "L1",
        lease.fence,
        Operation(operation_id="op-1", action="goto", state="executing", navigation_issued=True),
    )

    after = store.finish(lease_id="L1", fence=lease.fence, evidence="settled_with_receipt")

    assert after.state == "unconfirmed", after.state


def test_a_settled_operation_with_evidence_releases(tmp_path) -> None:
    from scholar_search.core.lease import LeaseStore, Operation

    store = LeaseStore(tmp_path / "coordination")
    lease = store.acquire(lease_id="L1")
    assert lease is not None
    operation = Operation(operation_id="op-1", action="goto", navigation_issued=True)
    store.record_operation("L1", lease.fence, operation.settled(outcome="landed", at=5.0))

    after = store.finish(lease_id="L1", fence=lease.fence, evidence="settled_with_receipt")

    assert after.state == "free", after.state


def test_a_damaged_lease_file_is_quarantined_not_free(tmp_path) -> None:
    from scholar_search.core.lease import LeaseStore

    root = tmp_path / "coordination"
    root.mkdir(parents=True)
    (root / "lease.json").write_text("{not json", encoding="utf-8")

    store = LeaseStore(root)

    assert store.read().state == "quarantined"
    assert store.acquire(lease_id="L1") is None, "a damaged record must not admit a new task"


def test_two_ids_that_would_alias_one_file_stay_separate(tmp_path) -> None:
    """F46-05: sanitising the id into a filename let `probe/collision` answer for `probe?collision`.

    The file name is a digest now, and the record's own id is checked on read.
    """

    from scholar_search.core.lease import LeaseStore, Operation

    store = LeaseStore(tmp_path / "coordination")
    store.archive(Operation(operation_id="probeA", action="goto", navigation_issued=True))

    assert store.operation("probe?collision") is None
    assert store.operation("probe/collision") is None
    assert store.operation("probeA" + "x" * 200) is None, "over-long ids are refused, not truncated"
    assert store.operation("probeA") is not None


def test_an_unreadable_lease_record_does_not_claim_to_block(tmp_path, monkeypatch) -> None:
    """F46-04: `admission_blocked` describes what admission does, not how healthy the record is."""

    from scholar_search import bootstrap
    from scholar_search.core.lease import LeaseStore

    monkeypatch.setenv("SCHOLAR_SEARCH_BROWSER_STATE", str(tmp_path / "browser-state"))

    def explode() -> object:
        raise PermissionError("no access")

    monkeypatch.setattr(LeaseStore, "read", lambda self: explode())

    summary = bootstrap._lease_summary()

    assert summary["state"] == "unknown", summary
    assert summary["readable"] is False, summary
    assert summary["error"] == "lease_state_unreadable", summary
    assert summary["admission_blocked"] is False, "observe mode must never claim to enforce"


def test_navigation_status_reports_unknown_rather_than_not_issued(tmp_path, monkeypatch) -> None:
    """`known: false` must never be read as `navigation_issued: false` (protocol-lease.md §7)."""

    from test_page_read import build_service

    from scholar_search.core.lease import LeaseStore, Operation

    monkeypatch.setenv("SCHOLAR_SEARCH_BROWSER_STATE", str(tmp_path / "browser-state"))
    service = build_service(tmp_path, [])

    missing = service.navigation_status("never-archived")

    assert missing["known"] is False, missing
    assert missing["operation"]["navigation_issued"] is None, missing
    assert missing["quota_charged"] == 0

    store = LeaseStore()
    store.archive(
        Operation(
            operation_id="op-late",
            action="goto",
            state="settled",
            quiescent=True,
            navigation_issued=True,
            navigation_id="nav-1",
            tab_id=9,
            outcome="landed",
        )
    )
    found = service.navigation_status("op-late")

    assert found["known"] is True, found
    assert found["operation"]["navigation_issued"] is True
    assert found["operation"]["navigation_id"] == "nav-1"
    assert found["operation"]["tab_id"] == 9
    assert found["quota_charged"] == 0


def test_status_reports_the_lease_beside_the_lock(tmp_path, monkeypatch) -> None:
    """`browser_busy` is the lock; `browser_lease` is the record. Different questions."""

    from scholar_search import bootstrap
    from scholar_search.core.lease import LeaseStore, Operation

    monkeypatch.setenv("SCHOLAR_SEARCH_BROWSER_STATE", str(tmp_path / "browser-state"))
    store = LeaseStore()
    lease = store.acquire(lease_id="L1", job_id="job-1")
    assert lease is not None
    store.record_operation(
        "L1",
        lease.fence,
        Operation(operation_id="op-1", action="goto", navigation_issued=True),
    )

    summary = bootstrap._lease_summary()

    assert summary["state"] == "active", summary
    assert summary["job_id"] == "job-1"
    assert summary["unresolved"] == ["op-1"], summary
    assert summary["admission_blocked"] is False, "observe mode must not claim to enforce"
    from scholar_search.core.lease import LeaseStore, Operation

    store = LeaseStore(tmp_path / "coordination")
    lease = store.acquire(lease_id="L1")
    assert lease is not None
    store.record_operation(
        "L1",
        lease.fence,
        Operation(
            operation_id="op-1",
            action="goto",
            navigation_issued=None,
            navigation_id="nav-1",
            tab_id=7,
        ),
    )
    store.finish(lease_id="L1", fence=lease.fence, evidence="refused_before_navigation")

    archived = store.operation("op-1")

    assert archived is not None
    assert archived.navigation_issued is None, "unknown stays unknown across a restart"
    assert archived.tab_id == 7
    assert store.operation("never-existed") is None
    """Shared state carries facts, not the article: no body, no bytes, no signed URL."""

    operation = Operation(
        operation_id="op-1",
        action="snapshot",
        navigation_issued=True,
        navigation_id="nav-1",
        tab_id=7,
        outcome="landed",
    )
    receipt = operation.receipt()

    assert {"operation_id", "navigation_id", "tab_id", "outcome"} <= set(receipt)
    assert set(receipt) <= set(RECEIPT_KEYS)
    # The whitelist is the mechanism; these are the keys it must never grow.
    for forbidden in ("html", "mhtml", "base64", "bytes", "body", "token", "cookies"):
        assert forbidden not in RECEIPT_KEYS, forbidden
