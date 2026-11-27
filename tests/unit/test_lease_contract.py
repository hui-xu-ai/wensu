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


def test_the_persisted_receipt_drops_page_content() -> None:
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
