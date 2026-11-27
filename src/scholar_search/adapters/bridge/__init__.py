"""TCP client for the native host.

The host listens on loopback only and requires a per-run token. Several hosts
may exist at once — one per browser profile — so the adapter pings the registry
and talks to one of them.

**Which one matters.** Taking whichever host answers first is fine when only one
browser is open, and wrong when two are: a search submitted in one profile would
read whatever page the other profile happens to be showing. Each host records the
`profile_dir` it belongs to, and this adapter prefers the host matching
`WENSU_PROFILE` (or, failing that, the profile in `browser.json`) before falling
back to any live host. That fallback exists so a setup that never recorded a
profile still works; it is the case the docs tell users not to rely on.

There is no transparent retry: a request that may already have reached the
browser is never replayed, because the kernel has metered it once and the
action may have had side effects.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import uuid
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ...core.config import host_runtime_dir
from ...core.contracts import Action, ActionOutcome
from ...core.errors import BridgeAmbiguous, BridgeError
from ...core.process import process_alive

PING_TIMEOUT_S = 0.6

# How much longer the socket read waits than the action deadline the host was given. Zero
# margin means the two deadlines race, and the loser is always the reply.
BRIDGE_REPLY_MARGIN_S = 2.0


class BridgeAdapter:
    name = "bridge"

    def __init__(
        self,
        endpoint: Path | None = None,
        *,
        timeout_s: float = 15.0,
    ) -> None:
        self._endpoint = endpoint
        self._timeout = timeout_s
        self._socket: socket.socket | None = None
        self._reader: Any = None
        self._token: str | None = None
        self._port: int | None = None
        # The id of the most recent action, kept so a failed send can still tell the caller which
        # operation to ask about (F46-01).
        self._last_request_id: str = ""
        # The id whose frame was actually written: only then may a failure not claim "not issued".
        self._dispatched: str = ""
        # Optional identity provider: returns the lease/job part of the action envelope, and
        # `execute` adds this attempt's `operation_id`. Unset means "send no context".
        self._context_provider: Callable[[], dict[str, Any]] | None = None
        self._context: dict[str, Any] = {}
        self.domains: tuple[str, ...] | None = None

    # -- discovery -----------------------------------------------------

    @staticmethod
    def _wanted_profile() -> str | None:
        """Which browser profile this process should talk to, if it can tell.

        `WENSU_PROFILE` wins, so two agents can share one machine deliberately. It
        falls back to the recorded config, which is what a single-agent setup has.
        """

        explicit = os.environ.get("WENSU_PROFILE")
        if explicit:
            return explicit
        try:
            from ...core import browser as browser_cfg

            recorded = browser_cfg.load()
        except Exception:
            # An unreadable config must not break probing: the fallback is to try
            # every endpoint, which is what a setup without a record already does.
            return None
        return recorded.profile_dir if recorded is not None else None

    def _candidates(self) -> list[Path]:
        """Endpoint files to try, the recorded profile first.

        A host's `profile_dir` is a hint, not an identity: every host on the machine
        reads the same `browser.json`, so with two browsers open **both endpoints
        claim the same profile**. Ordering by that label would look like isolation
        while providing none — a review caught exactly this, two hosts labelled
        `E:\\ProfileA` with only one of them actually being A.

        So a label is only used to *order* when it cannot mislead, and ambiguity is
        refused instead of guessed:
        """

        if self._endpoint is not None:
            return [self._endpoint]

        root = host_runtime_dir()
        files = sorted(
            (root / "hosts").glob("*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        legacy = root / "bridge.json"
        ordered = [*files, *([legacy] if legacy.exists() else [])]

        # One host writes two endpoint files — `bridge.json` and
        # `hosts/bridge-<pid>.json` — so counting files counts hosts twice. The first
        # version of this check did exactly that and refused a completely normal
        # single-browser setup: "2 native hosts are running and all of them report
        # the same profile", with one host alive. Identity is the pid, not the path.
        ordered = self._unique_by_pid(ordered)

        # Ordering only. Ambiguity is decided in `pin`, after liveness is known: a
        # registry entry left behind by a crashed host is a file, not a browser, and
        # judging from files refused setups that had exactly one reachable host.
        wanted = self._wanted_profile()
        if wanted is None:
            return ordered
        labelled = self._read_profiles(ordered)
        matching = [path for path in ordered if labelled.get(path) == wanted.casefold()]
        others = [path for path in ordered if labelled.get(path) != wanted.casefold()]
        return [*matching, *others]

    @staticmethod
    def _unique_by_pid(paths: list[Path]) -> list[Path]:
        """Collapse endpoint files that describe the same host process.

        Keeps the first file for each pid, preserving the order already computed. A
        file whose pid cannot be read is kept as-is: dropping it would hide a live
        host behind a malformed record.
        """

        seen: set[int] = set()
        unique: list[Path] = []
        for path in paths:
            try:
                info = json.loads(path.read_text(encoding="utf-8"))
                pid = int(info["pid"])
            except (OSError, ValueError, KeyError, TypeError):
                unique.append(path)
                continue
            if pid in seen:
                continue
            seen.add(pid)
            unique.append(path)
        return unique

    @staticmethod
    def _drop_dead(paths: list[Path]) -> list[Path]:
        """Endpoint files whose host process has exited, and cannot come back.

        A host writes `bridge-<pid>.json` and the file stays after it exits. Every one of them
        was pinged on every transaction: fourteen dead files at 605 ms each put **8.5 s** in
        front of every search before anything reached the browser (measured 2026-11-25). The pid
        is the answer, and the file is deleted — a dead pid never writes it again.

        A file with no readable pid is kept: deleting a malformed record could hide a live host.
        Files written in the last minute are also kept, so a host that is still starting cannot
        lose its endpoint to a race.
        """

        import time

        now = time.time()
        kept: list[Path] = []
        for path in paths:
            try:
                info = json.loads(path.read_text(encoding="utf-8"))
                pid = int(info["pid"])
                fresh = now - path.stat().st_mtime < 60
            except (OSError, ValueError, KeyError, TypeError):
                kept.append(path)
                continue
            if fresh or process_alive(pid):
                kept.append(path)
                continue
            with contextlib.suppress(OSError):
                path.unlink()
        return kept

    @staticmethod
    def _read_profiles(paths: list[Path]) -> dict[Path, str | None]:
        found: dict[Path, str | None] = {}
        for path in paths:
            try:
                info = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            value = info.get("profile_dir")
            found[path] = str(value).casefold() if value else None
        return found

    @staticmethod
    def _ping(path: Path) -> tuple[int, str] | None:
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
            port = int(info["port"])
            token = str(info["token"])
        except (OSError, ValueError, KeyError, TypeError):
            return None
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=PING_TIMEOUT_S) as sock:
                sock.settimeout(PING_TIMEOUT_S)
                payload = json.dumps({"cmd": "ping", "token": token}) + "\n"
                sock.sendall(payload.encode("utf-8"))
                line = sock.makefile("r", encoding="utf-8", newline="\n").readline()
                if line and json.loads(line).get("ok"):
                    return port, token
        except (OSError, ValueError):
            return None
        return None

    def pin(self) -> tuple[int, str]:
        """Choose and keep the endpoint this adapter will use.

        Called at the start of a browser transaction so the choice is made once.

        Two rules, and the second one was wrong twice:

        1. **Liveness before ambiguity.** Judging from endpoint files counted a host
           that had already crashed: one live browser plus one stale registry entry
           reported "2 native hosts are running" and told the caller to close a
           browser that was not open.
        2. **Ambiguity is about the candidates this request may select, not about the
           machine.** The first fix compared the set of distinct labels across *all*
           live hosts, so two hosts labelled A were refused only while nothing else
           was running — opening an unrelated browser B made the set `{A, B}`, the
           check pass, and one of the two A's get picked. A third browser must never
           make two indistinguishable candidates distinguishable.

        So the eligible set is built first, and it is that set's size that decides.
        """

        wanted = self._wanted_profile()
        live: list[tuple[Path, tuple[int, str], str | None]] = []
        for path in self._drop_dead(self._candidates()):
            found = self._ping(path)
            if found is None:
                continue
            live.append((path, found, self._read_profiles([path]).get(path)))

        if not live:
            raise self._no_host_error(wanted)

        # The hosts this request is allowed to end up on. An unlabelled endpoint stays
        # eligible for any request: it predates the field and may well be the right
        # browser.
        if wanted is None:
            eligible = live
        else:
            eligible = [item for item in live if item[2] is None or item[2] == wanted.casefold()]
            if not eligible:
                raise self._no_host_error(wanted)

        # Ambiguity is **two candidates sharing a label**, not "the labels differ".
        #
        # Comparing distinct labels failed three times in a row, each time with a
        # different third party: an unrelated B, then a third A, then an unlabelled
        # endpoint. Every time the set of distinct values grew and the check went
        # quiet while two indistinguishable candidates remained. Counting per label is
        # the property that actually matters — if any label has more than one
        # claimant, the request cannot be routed. An unlabelled host forms its own
        # group, so two of them are ambiguous too.
        claimants = Counter(item[2] for item in eligible)
        contested = [label for label, count in claimants.items() if count > 1]
        if contested:
            shown = ", ".join(
                "an unreported profile" if label is None else label for label in contested
            )
            raise BridgeAmbiguous(
                f"{len(eligible)} native hosts are live and {shown} is claimed more "
                "than once. A host cannot say which browser launched it, so this "
                "request could read a different profile's page. Close all but one "
                "browser, or run one host per profile and set WENSU_PROFILE."
            )

        path, found, _label = eligible[0]
        self._endpoint = path
        self._port, self._token = found
        return found

    @staticmethod
    def _no_host_error(wanted: str | None) -> BridgeError:
        if wanted is not None:
            return BridgeError(
                f"no native host is serving the profile {wanted!r}. Start it with "
                "`wensu browser start`, or unset WENSU_PROFILE to use any live host."
            )
        return BridgeError("no live native host found")

    @classmethod
    def probe(cls) -> bool:
        """True when at least one registered host answers a ping."""

        probe = cls()
        return any(probe._ping(path) is not None for path in probe._candidates())

    def info(self) -> dict[str, Any]:
        """What the running host and extension say they are, for `status` and the capability gate.

        The handshake used to carry a protocol number and nothing else, so `status` could only
        report the manifest *on disk*: a build that was loaded but not running, or a running
        worker older than its manifest, both looked healthy (audit 2026-11-26, D batch). Answers
        `{}` when the host cannot say — an older host is not an error here.
        """

        try:
            self._connect()
            assert self._socket is not None and self._reader is not None
            request_id = uuid.uuid4().hex
            request = {"id": request_id, "token": self._token, "cmd": "info"}
            self._socket.settimeout(self._timeout)
            self._socket.sendall((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
            line = self._reader.readline()
            if not line:
                return {}
            reply = json.loads(line)
        except (OSError, ValueError):
            return {}
        if not isinstance(reply, dict) or not reply.get("ok"):
            return {}
        build = reply.get("build")
        if not isinstance(build, dict):
            return {}
        info = {**build, "host_version": reply.get("host_version")}
        # The host's own answer about whether *it* can write the lease records. It runs at the
        # browser's integrity level; a kernel-side check could not answer this (unverified.md §2).
        writable = reply.get("coordination_writable")
        if isinstance(writable, bool):
            info["coordination_writable"] = writable
        return info

    def _connect(self) -> None:
        if self._socket is not None:
            return
        for path in self._candidates():
            found = self._ping(path)
            if found is None:
                continue
            self._port, self._token = found
            sock = socket.create_connection(("127.0.0.1", self._port), timeout=self._timeout)
            self._socket = sock
            self._reader = sock.makefile("r", encoding="utf-8", newline="\n")
            return
        raise ConnectionError("no live native host found")

    # -- actions -------------------------------------------------------

    def _send(
        self, action: Action, timeout_ms: int, request_id: str | None = None
    ) -> ActionOutcome:
        assert self._socket is not None and self._reader is not None
        # The client must outwait the server, not match it. The host allows itself the
        # action's whole `timeout_ms` and then writes the reply; a socket read deadline of
        # exactly that long aborts the read in the same millisecond, so an action that used
        # its full budget could never report what happened — it surfaced as
        # `bridge.error: timed out` on a run that had in fact succeeded.
        self._socket.settimeout(max(self._timeout, timeout_ms / 1000 + BRIDGE_REPLY_MARGIN_S))
        request_id = request_id or uuid.uuid4().hex
        self._last_request_id = request_id
        request = {
            "id": request_id,
            "token": self._token,
            "action": action.verb,
            "params": dict(action.params),
            "timeout_ms": timeout_ms,
            "domains": list(self.domains or ()),
        }
        if self._context:
            # The identity block (plan §三). Sent only when a caller set one up: an empty context
            # is omitted so nothing changes for a plain read or an older peer.
            request["context"] = dict(self._context)
        self._socket.sendall((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
        # From here on the frame is out: a failure can no longer claim "it was never issued".
        self._dispatched = request_id

        # A navigation can delay the previous action's reply past its own return,
        # leaving it in the stream. Those replies belong to an action that already
        # finished and was already inspected, so they are dropped rather than
        # mistaken for a correlation error.
        reply: dict[str, Any] = {}
        for _ in range(8):
            line = self._reader.readline()
            if not line:
                raise ConnectionError("bridge closed the connection")
            candidate = json.loads(line)
            if str(candidate.get("id", "")) == request_id:
                reply = candidate
                break
        else:
            raise ConnectionError("bridge reply id does not match the request")

        data = dict(reply.get("data") or {})
        # The id the host is archiving a late reply under (plan §三: an operation identity the
        # caller can quote). It travels with every outcome — including the ones the caller reads
        # after a timeout — and it is *this* action's id, never the previous one's.
        data["operation_id"] = request_id

        url = reply.get("url") or data.get("url")
        return ActionOutcome(
            action=action,
            ok=bool(reply.get("ok")),
            data=data,
            error=reply.get("error"),
            duration_ms=int(reply.get("duration_ms") or 0),
            url=url if isinstance(url, str) else None,
        )

    def context_provider(self, provider: Callable[[], dict[str, Any]] | None) -> None:
        """Install (or clear) the identity source for the action envelope."""

        self._context_provider = provider

    def _context_for(self, request_id: str) -> dict[str, Any]:
        """The envelope for one attempt: the provider's fields plus this attempt's id."""

        if self._context_provider is None:
            return {}
        from ...core.lease import build_context

        try:
            base = self._context_provider() or {}
        except Exception:  # a broken provider must not break the action
            base = {}
        return build_context(
            job_id=str(base.get("job_id") or ""),
            lease_id=str(base.get("lease_id") or ""),
            fence=int(base.get("fence") or 0),
            operation_id=request_id,
            endpoint_epoch=str(base.get("endpoint_epoch") or ""),
            worker_epoch=str(base.get("worker_epoch") or ""),
            tab_id=base.get("tab_id") if isinstance(base.get("tab_id"), int) else None,
        )

    def execute(self, action: Action, *, timeout_ms: int) -> ActionOutcome:
        # One identity per attempt, allocated *before* anything can fail, so a failure can never
        # report the previous action's id (retest 2026-11-27, F47-02).
        request_id = uuid.uuid4().hex
        self._context = self._context_for(request_id)
        try:
            self._connect()
            return self._send(action, timeout_ms, request_id)
        except (OSError, ValueError, KeyError) as exc:
            # A timed-out socket stays unusable, so drop it: the next call dials
            # again instead of reading from a poisoned stream. Without this, one
            # slow navigation made every later action fail.
            self.close()
            # `operation_issued: false` only when the request provably never left the wire. A read
            # that timed out after the frame was written may have navigated: that one must stay
            # "unconfirmed", because "it was not issued, ask again" invites a second navigation
            # (F47-01).
            issued = self._dispatched == request_id
            return ActionOutcome(
                action=action,
                ok=False,
                error=f"bridge.error: {exc}",
                data={"operation_id": request_id, "operation_issued": issued},
            )

    def close(self) -> None:
        for closable in (self._reader, self._socket):
            try:
                if closable is not None:
                    closable.close()
            except OSError:
                pass
        self._reader = None
        self._socket = None
