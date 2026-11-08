"""TCP client for the native host.

The host listens on loopback only and requires a per-run token. Several hosts
may exist at once (one per browser reconnect), so the adapter pings the
registry and talks to whichever host answers.

There is no transparent retry: a request that may already have reached the
browser is never replayed, because the kernel has metered it once and the
action may have had side effects.
"""

from __future__ import annotations

import json
import socket
import uuid
from pathlib import Path
from typing import Any

from ...core.config import host_runtime_dir
from ...core.contracts import Action, ActionOutcome

PING_TIMEOUT_S = 0.6


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
        self.domains: tuple[str, ...] | None = None

    # -- discovery -----------------------------------------------------

    def _candidates(self) -> list[Path]:
        if self._endpoint is not None:
            return [self._endpoint]

        root = host_runtime_dir()
        files = sorted(
            (root / "hosts").glob("*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        legacy = root / "bridge.json"
        return [*files, *([legacy] if legacy.exists() else [])]

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

    @classmethod
    def probe(cls) -> bool:
        """True when at least one registered host answers a ping."""

        probe = cls()
        return any(probe._ping(path) is not None for path in probe._candidates())

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

    def _send(self, action: Action, timeout_ms: int) -> ActionOutcome:
        assert self._socket is not None and self._reader is not None
        request_id = uuid.uuid4().hex
        request = {
            "id": request_id,
            "token": self._token,
            "action": action.verb,
            "params": dict(action.params),
            "timeout_ms": timeout_ms,
            "domains": list(self.domains or ()),
        }
        self._socket.sendall((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))

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

        url = reply.get("url") or data.get("url")
        return ActionOutcome(
            action=action,
            ok=bool(reply.get("ok")),
            data=data,
            error=reply.get("error"),
            duration_ms=int(reply.get("duration_ms") or 0),
            url=url if isinstance(url, str) else None,
        )

    def execute(self, action: Action, *, timeout_ms: int) -> ActionOutcome:
        try:
            self._connect()
            return self._send(action, timeout_ms)
        except (OSError, ValueError, KeyError) as exc:
            # A timed-out socket stays unusable, so drop it: the next call dials
            # again instead of reading from a poisoned stream. Without this, one
            # slow navigation made every later action fail.
            self.close()
            return ActionOutcome(action=action, ok=False, error=f"bridge.error: {exc}")

    def close(self) -> None:
        for closable in (self._reader, self._socket):
            try:
                if closable is not None:
                    closable.close()
            except OSError:
                pass
        self._reader = None
        self._socket = None
