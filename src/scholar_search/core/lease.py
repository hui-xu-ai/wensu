"""The lease/operation contract, inert until P1a wires it (ADR 0030, third slice).

P0 of `work/tasks/2026-11-27-lease-receipt/plan.md`: freeze the vocabulary, the state machine and
the release-evidence table **before** anything writes a lease. Nothing imports this module yet, so
it cannot change a running read; the tests around it are what make the contract executable.

The two edges the plan forbids are absent on purpose, and `test_lease_contract.py` asserts their
absence: there is no "TTL expired → free" and no "next request arrived → free". A lease leaves
`unconfirmed` only through evidence about the *old* operation — calling it expired is what turns a
landed navigation into a silent second one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

# Resource states. `unconfirmed` is *not* a timeout: it is "the browser may still be acting".
LeaseState = Literal["free", "active", "releasing", "unconfirmed", "recovering", "quarantined"]
LEASE_STATES: frozenset[str] = frozenset(
    {"free", "active", "releasing", "unconfirmed", "recovering", "quarantined"}
)

# What is known about one action's side effect.
OperationState = Literal["prepared", "executing", "settled", "unknown"]
OPERATION_STATES: frozenset[str] = frozenset({"prepared", "executing", "settled", "unknown"})

LEASE_REASONS: frozenset[str] = frozenset(
    {
        # admission refusals: this request issued nothing, so they cost nothing
        "lease_held",
        "lease_unconfirmed",
        "lease_protocol_unavailable",
        # navigation outcomes, split because only one of them may ever be retried
        "navigation_not_issued",
        "navigation_unconfirmed",
    }
)

# Evidence that may release a lease. Every entry says something about the *operation*, not about
# the calendar.
RELEASE_EVIDENCE: frozenset[str] = frozenset(
    {
        "refused_before_navigation",  # the worker refused before calling the navigation API
        "settled_with_receipt",  # a receipt for this operation proves its continuations ended
        "quarantined_old_epoch",  # the old worker epoch is fenced off and its output dropped
        "target_closed",  # the tool tab is gone and no fallback is in flight
        "resource_gone",  # the browser instance that held it is verifiably gone
    }
)

# Observations that are *not* evidence, named so nobody re-adopts them by accident.
NOT_EVIDENCE: frozenset[str] = frozenset(
    {
        "url_changed",
        "title_changed",
        "tab_complete",
        "deadline_passed",
        "revoke_ack",
        "process_exit",
    }
)

# Fields a persisted receipt may carry. Anything not listed is dropped before it reaches disk:
# an MHTML body, a base64 chunk or a signed URL must never travel through shared state.
RECEIPT_KEYS: frozenset[str] = frozenset(
    {
        "operation_id",
        "lease_id",
        "fence",
        "worker_epoch",
        "endpoint_epoch",
        "action",
        "state",
        "navigation_issued",
        "navigation_id",
        "tab_id",
        "quiescent",
        "outcome",
        "receipt_seq",
        "started_at",
        "settled_at",
        "error_code",
        "error_class",
    }
)

_FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "html",
        "mhtml",
        "base64",
        "bytes",
        "body",
        "text",
        "content",
        "cookie",
        "cookies",
        "token",
        "records",
        "screenshot",
        "signed_url",
    }
)


@dataclass(slots=True)
class Operation:
    """One action's lifecycle facts, as the host persists them."""

    operation_id: str
    action: str
    worker_epoch: str = ""
    endpoint_epoch: str = ""
    lease_id: str = ""
    fence: int = 0
    state: str = "prepared"
    # Tri-state on purpose: `None` means "we do not know whether the browser was told to navigate",
    # and treating that as `False` is how a landed navigation gets replayed.
    navigation_issued: bool | None = None
    navigation_id: str = ""
    tab_id: int | None = None
    quiescent: bool = False
    outcome: str = ""
    receipt_seq: int = 0
    started_at: float = 0.0
    settled_at: float = 0.0
    error_code: str = ""
    error_class: str = ""

    def receipt(self) -> dict[str, Any]:
        """The persisted projection: whitelist in, everything else out."""

        payload = {key: getattr(self, key) for key in RECEIPT_KEYS if hasattr(self, key)}
        return {key: value for key, value in payload.items() if key not in _FORBIDDEN_KEYS}

    def settled(self, *, outcome: str, at: float) -> Operation:
        self.state = "settled"
        self.quiescent = True
        self.outcome = outcome
        self.settled_at = at
        self.receipt_seq += 1
        return self

    def dumps(self) -> str:
        return json.dumps(self.receipt(), ensure_ascii=False, sort_keys=True)


@dataclass(slots=True)
class Lease:
    """The holder record: who has the browser, and what still has to be accounted for."""

    lease_id: str
    fence: int
    endpoint_epoch: str = ""
    job_id: str = ""
    state: str = "active"
    owner_finished: bool = False
    operations: dict[str, Operation] = field(default_factory=dict)

    def add(self, operation: Operation) -> None:
        self.operations[operation.operation_id] = operation

    def unresolved(self) -> list[Operation]:
        """Operations whose side effect is not accounted for yet.

        `settled` alone is not enough: a settled operation that is not `quiescent` may still have a
        continuation that would navigate, so it keeps the lease.
        """

        return [
            operation
            for operation in self.operations.values()
            if operation.state != "settled" or not operation.quiescent
        ]

    def can_release(self, evidence: str) -> tuple[bool, tuple[str, ...]]:
        """Whether the lease may go back to `free`, and what is missing if not.

        All three conditions from the plan: the caller declared its call finished, the evidence is
        about the operation rather than the clock, and no operation is still in flight.
        """

        missing: list[str] = []
        if not self.owner_finished:
            missing.append("owner_not_finished")
        if evidence in NOT_EVIDENCE or evidence not in RELEASE_EVIDENCE:
            missing.append("evidence_not_conclusive")
        if self.unresolved():
            missing.append("operation_unresolved")
        return (not missing, tuple(missing))


def next_states(state: str) -> frozenset[str]:
    """The allowed transitions. Read this as the answer to "may it become free on its own?"."""

    table: dict[str, frozenset[str]] = {
        "free": frozenset({"active"}),
        "active": frozenset({"releasing", "unconfirmed"}),
        "unconfirmed": frozenset({"recovering", "quarantined"}),
        "recovering": frozenset({"unconfirmed", "releasing", "quarantined"}),
        "quarantined": frozenset({"recovering"}),
        "releasing": frozenset({"free"}),
    }
    return table.get(state, frozenset())


def issued_reason(issued: bool | None) -> str:
    """Which of the two navigation outcomes an `issued` value means.

    `False` is only allowed when something that can see the browser said so (the worker refused
    before calling the navigation API, or the kernel never reached dispatch). Everything else —
    including a socket that timed out mid-write — is `navigation_unconfirmed`, because treating it
    as "not issued" is what lets a landed navigation be replayed.
    """

    return "navigation_not_issued" if issued is False else "navigation_unconfirmed"
