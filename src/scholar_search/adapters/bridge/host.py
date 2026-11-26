"""Native messaging transport: framing and request correlation.

Framing matches the Chrome/Edge native messaging protocol: a 4-byte
little-endian length followed by a UTF-8 JSON object. stdout carries frames
only; every diagnostic goes to stderr.

One handshake precedes the first action, and every reply must carry the id of
its request; both checks keep the two hops of the bridge in sync.
"""

from __future__ import annotations

import json
import struct
import sys
import threading
import time
import uuid
from collections.abc import Callable
from typing import IO, Any

from .policy import MAX_FRAME_BYTES, validate_request

PROTOCOL_VERSION = 1


class BridgeClosed(RuntimeError):
    """The extension went away (stdin EOF) or the port was closed."""


def read_frame(stream: IO[bytes]) -> dict[str, Any] | None:
    header = stream.read(4)
    if not header:
        return None
    if len(header) < 4:
        raise BridgeClosed("truncated frame header")
    (length,) = struct.unpack("=I", header)
    if length == 0 or length > MAX_FRAME_BYTES:
        raise BridgeClosed(f"illegal frame length: {length}")
    payload = stream.read(length)
    if len(payload) < length:
        raise BridgeClosed("truncated frame body")
    message = json.loads(payload.decode("utf-8"))
    if not isinstance(message, dict):
        raise BridgeClosed("frame is not a JSON object")
    return message


def write_frame(stream: IO[bytes], message: dict[str, Any]) -> None:
    payload = json.dumps(message, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(payload) > MAX_FRAME_BYTES:
        raise ValueError(f"frame is {len(payload)} bytes, limit is {MAX_FRAME_BYTES}")
    stream.write(struct.pack("=I", len(payload)))
    stream.write(payload)
    stream.flush()


class BridgeHost:
    """Owns the extension connection and correlates requests with replies."""

    def __init__(
        self,
        stdin: IO[bytes] | None = None,
        stdout: IO[bytes] | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._in = stdin or sys.stdin.buffer
        self._out = stdout or sys.stdout.buffer
        self._clock = clock
        self._lock = threading.Condition()
        self._pending: dict[str, dict[str, Any] | None] = {}
        self._closed = False
        self._handshaked = False
        # Filled by `_handshake` from the extension's own reply; empty until then.
        self.build: dict[str, Any] = {}

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def serve_extension(self) -> None:
        """Read frames until EOF, dispatching replies to waiting callers."""

        try:
            while True:
                message = read_frame(self._in)
                if message is None:
                    break
                if message.get("type") in {"action_result", "hello_ack"}:
                    request_id = str(message.get("id", ""))
                    with self._lock:
                        if request_id in self._pending:
                            self._pending[request_id] = message
                            self._lock.notify_all()
        except (BridgeClosed, OSError, ValueError):
            pass
        finally:
            with self._lock:
                self._closed = True
                self._lock.notify_all()

    def _wait(self, request_id: str, deadline: float) -> dict[str, Any] | None:
        with self._lock:
            while self._pending.get(request_id) is None and not self._closed:
                remaining = deadline - self._clock()
                if remaining <= 0:
                    break
                self._lock.wait(remaining)
            return self._pending.pop(request_id, None)

    def _handshake(self, deadline: float) -> bool:
        if self._handshaked:
            return True
        request_id = uuid.uuid4().hex
        with self._lock:
            if self._closed:
                return False
            self._pending[request_id] = None
        try:
            write_frame(
                self._out,
                {
                    "type": "hello",
                    "id": request_id,
                    "protocol": PROTOCOL_VERSION,
                },
            )
        except (OSError, ValueError):
            with self._lock:
                self._pending.pop(request_id, None)
            return False
        reply = self._wait(request_id, deadline)
        if reply is None or reply.get("protocol") != PROTOCOL_VERSION:
            return False
        # What the running extension says it is. Absent fields are an older worker, not an error:
        # `build_info()` then simply has nothing to report beyond the protocol (audit D batch).
        self.build = {
            "protocol": reply.get("protocol"),
            "version": str(reply.get("version") or ""),
            "worker": str(reply.get("worker") or ""),
            "capabilities": [
                str(item) for item in (reply.get("capabilities") or []) if isinstance(item, str)
            ],
            # Verbs that need the content script, so they only exist on the channels' domains.
            "channel_capabilities": [
                str(item)
                for item in (reply.get("channel_capabilities") or [])
                if isinstance(item, str)
            ],
        }
        self._handshaked = True
        return True

    def ensure_handshake(self, timeout_s: float = 5.0) -> bool:
        """Run the handshake if it has not happened yet, and say whether it succeeded.

        `cmd=info` used to answer from `self.build`, which is empty until *some other* call
        happens to handshake. A freshly started host therefore reported nothing but its own
        version, and the capability gate — reading "no capabilities" as "no opinion" — let a
        plan through (retest 2026-11-26, §1/§2). Asking now performs the handshake first.
        """

        return self._handshake(self._clock() + timeout_s)

    def build_info(self) -> dict[str, Any]:
        """The running extension's own account of itself, for `status`.

        `handshake` says which of three situations this is: `ok` (the worker answered and
        described itself), `timeout` (a host is up but the extension did not answer), or
        `old` (the worker answered without a capability list, i.e. a build from before it
        advertised anything). Collapsing those three into "empty" is what made the gate silent.
        """

        info = dict(self.build)
        if self._handshaked:
            info["handshake"] = "ok" if info.get("capabilities") else "old"
        else:
            info["handshake"] = "timeout"
        return info

    def request(
        self,
        action: str,
        params: dict[str, Any],
        *,
        timeout_s: float = 15.0,
        domains: tuple[str, ...] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Send one action to the extension and wait for its reply."""

        request_id = request_id or uuid.uuid4().hex
        if timeout_s <= 0:
            return {"ok": False, "error": "bridge.timeout", "id": request_id}

        message: dict[str, Any] = {
            "type": "action",
            "id": request_id,
            "action": action,
            "params": params,
            "domains": list(domains or ()),
        }
        error = validate_request(message, domains)
        if error is not None:
            return {"ok": False, "error": error, "id": request_id}

        deadline = self._clock() + timeout_s
        if not self._handshake(deadline):
            return {"ok": False, "error": "bridge.timeout", "id": request_id}

        with self._lock:
            if self._closed:
                return {"ok": False, "error": "bridge.closed", "id": request_id}
            self._pending[request_id] = None

        try:
            write_frame(self._out, message)
        except (OSError, ValueError):
            with self._lock:
                self._pending.pop(request_id, None)
            return {"ok": False, "error": "bridge.write", "id": request_id}

        reply = self._wait(request_id, deadline)
        if reply is None:
            return {
                "ok": False,
                "error": "bridge.timeout" if not self.closed else "bridge.closed",
                "id": request_id,
            }
        return reply
