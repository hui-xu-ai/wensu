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
import os
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .config import browser_state_dir
from .locking import interprocess_lock

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


# -- persistence (P1a-a) ---------------------------------------------------------------
#
# The store is the authority; the kernel and the extension only mirror it (plan §二.1). Everything
# here happens under a short cross-process lock: re-read, mutate, publish through a temporary file
# with `os.replace`. The F41-02 defect was exactly this pattern missing, so it is not optional.


def coordination_dir() -> Path:
    """Where lease/operation records live: beside the browser, never inside a home."""

    return browser_state_dir() / "coordination"


class LeaseStore:
    """Reads and writes the lease record. Writes are atomic and lock-protected."""

    def __init__(self, root: Path | None = None, *, clock: Callable[[], float] = time.time) -> None:
        self._root = Path(root) if root is not None else coordination_dir()
        self._clock = clock

    @property
    def root(self) -> Path:
        return self._root

    def lease_path(self) -> Path:
        return self._root / "lease.json"

    def operations_dir(self) -> Path:
        return self._root / "operations"

    def read(self) -> Lease:
        """The current lease, or a `free` one. A corrupt record is `quarantined`, not `free`."""

        path = self.lease_path()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return Lease(lease_id="", fence=0, state="free")
        except (OSError, ValueError):
            # Refusing to guess is the whole contract: a damaged file must not become an
            # empty lease that lets the next navigation through.
            return Lease(lease_id="", fence=0, state="quarantined")
        if not isinstance(payload, dict) or payload.get("state") not in LEASE_STATES:
            return Lease(lease_id="", fence=0, state="quarantined")
        lease = Lease(
            lease_id=str(payload.get("lease_id") or ""),
            fence=int(payload.get("fence") or 0),
            endpoint_epoch=str(payload.get("endpoint_epoch") or ""),
            job_id=str(payload.get("job_id") or ""),
            state=str(payload.get("state") or "quarantined"),
            owner_finished=payload.get("owner_finished") is True,
        )
        for item in payload.get("operations") or []:
            if isinstance(item, dict) and item.get("operation_id"):
                lease.add(_operation_from(item))
        return lease

    def acquire(self, *, lease_id: str, job_id: str = "", endpoint_epoch: str = "") -> Lease | None:
        """Take the browser, or return None when somebody else holds it (no waiting, no TTL)."""

        with self._exclusive():
            current = self.read()
            if current.state != "free":
                return None
            lease = Lease(
                lease_id=lease_id,
                fence=current.fence + 1,
                endpoint_epoch=endpoint_epoch,
                job_id=job_id,
                state="active",
            )
            self._write(lease)
            return lease

    def finish(self, *, lease_id: str, fence: int, evidence: str) -> Lease:
        """Declare the call finished and release *if* the evidence allows it."""

        with self._exclusive():
            lease = self.read()
            if lease.lease_id != lease_id or lease.fence != fence:
                return lease  # an old owner cannot finish somebody else's lease
            lease.owner_finished = True
            allowed, _missing = lease.can_release(evidence)
            lease.state = "releasing" if allowed else "unconfirmed"
            if allowed:
                lease.state = "free"
            self._write(lease)
            return lease

    def record_operation(self, lease_id: str, fence: int, operation: Operation) -> bool:
        """Persist one operation's facts. The receipt is whitelisted before it reaches disk."""

        with self._exclusive():
            lease = self.read()
            if lease.lease_id != lease_id or lease.fence != fence:
                return False
            self.operations_dir().mkdir(parents=True, exist_ok=True)
            path = self.operations_dir() / f"{_safe_name(operation.operation_id)}.json"
            _atomic_write(path, operation.dumps())
            lease.add(operation)
            self._write(lease)
            return True

    def operation(self, operation_id: str) -> Operation | None:
        """Archived facts for one operation. `None` means "not known", never "not issued"."""

        path = self.operations_dir() / f"{_safe_name(operation_id)}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return _operation_from(payload) if isinstance(payload, dict) else None

    def archive(self, operation: Operation) -> None:
        """Persist one operation's facts even when no lease is held any more.

        A late reply can arrive after the lease was released (or after the host restarted). The
        facts still belong to that operation, and the next caller must be able to ask about them.
        """

        with self._exclusive():
            self.operations_dir().mkdir(parents=True, exist_ok=True)
            path = self.operations_dir() / f"{_safe_name(operation.operation_id)}.json"
            _atomic_write(path, operation.dumps())
            lease = self.read()
            if lease.lease_id and lease.lease_id == operation.lease_id:
                lease.add(operation)
                self._write(lease)

    def _write(self, lease: Lease) -> None:
        payload = {
            "lease_id": lease.lease_id,
            "fence": lease.fence,
            "endpoint_epoch": lease.endpoint_epoch,
            "job_id": lease.job_id,
            "state": lease.state,
            "owner_finished": lease.owner_finished,
            "operations": [operation.receipt() for operation in lease.operations.values()],
            "updated_at": self._clock(),
        }
        _atomic_write(self.lease_path(), json.dumps(payload, ensure_ascii=False, indent=1))

    def _exclusive(self) -> AbstractContextManager[None]:
        return interprocess_lock(self._root / "lease.lock", timeout_s=10.0)


def _operation_from(payload: dict[str, Any]) -> Operation:
    issued = payload.get("navigation_issued")
    return Operation(
        operation_id=str(payload.get("operation_id") or ""),
        action=str(payload.get("action") or ""),
        worker_epoch=str(payload.get("worker_epoch") or ""),
        endpoint_epoch=str(payload.get("endpoint_epoch") or ""),
        lease_id=str(payload.get("lease_id") or ""),
        fence=int(payload.get("fence") or 0),
        state=str(payload.get("state") or "unknown"),
        navigation_issued=issued if isinstance(issued, bool) or issued is None else None,
        navigation_id=str(payload.get("navigation_id") or ""),
        tab_id=payload.get("tab_id") if isinstance(payload.get("tab_id"), int) else None,
        quiescent=payload.get("quiescent") is True,
        outcome=str(payload.get("outcome") or ""),
        receipt_seq=int(payload.get("receipt_seq") or 0),
        started_at=float(payload.get("started_at") or 0.0),
        settled_at=float(payload.get("settled_at") or 0.0),
        error_code=str(payload.get("error_code") or ""),
        error_class=str(payload.get("error_class") or ""),
    )


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    staging.write_text(text, encoding="utf-8")
    os.replace(staging, path)


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_." else "_" for char in value)[:80] or "op"


def archive_late_reply(
    store: LeaseStore, request_id: str, reply: dict[str, Any], action: str, *, at: float = 0.0
) -> Operation:
    """Turn one late `action_result` into an archived operation, without inventing facts.

    This is the *only* place a timed-out action's fate gets recorded. It never returns the reply to
    a caller, and it refuses to guess: `ok` proves the action ran; an explicit pre-navigation
    refusal proves it did not; anything else stays `navigation_issued = None`.
    """

    raw = reply.get("data")
    data: dict[str, Any] = raw if isinstance(raw, dict) else {}
    error = str(reply.get("error") or "")
    ok = reply.get("ok") is True
    refused = error.startswith("policy.") or error in {"no_active_tab", "policy.params"}
    operation = Operation(
        operation_id=request_id,
        action=action,
        state="settled",
        quiescent=True,
        navigation_issued=True if ok else (False if refused else None),
        navigation_id=str(data.get("navigation_id") or ""),
        tab_id=data.get("tab_id") if isinstance(data.get("tab_id"), int) else None,
        outcome="landed" if ok else "refused" if refused else "unknown",
        error_code=error,
        started_at=at,
        settled_at=at,
        receipt_seq=1,
    )
    store.archive(operation)
    return operation
