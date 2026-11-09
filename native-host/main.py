"""Native messaging host entry point.

Started by Edge/Chrome through a registry-registered manifest. It speaks the
native messaging protocol on stdin/stdout and a line-delimited JSON protocol
on a loopback TCP port for the MCP server.

stdout must carry protocol frames only; every diagnostic goes to stderr.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

from scholar_search.adapters.bridge.host import BridgeHost
from scholar_search.adapters.bridge.policy import TRUSTED_DOMAINS, narrow_domains
from scholar_search.core.config import ensure_host_runtime, host_runtime_dir

HOST_NAME = "com.scholar.search"
ENDPOINT_NAME = "bridge.json"


def _profile_dir() -> str | None:
    """The profile recorded in `browser.json`, as a hint and nothing more.

    This is deliberately **not** proof of which browser launched this host. The
    extension cannot report the path of the profile it runs in, and the launcher
    manifest is registered once per user, so every host on the machine reads the same
    file and would claim the same profile. An independent review showed exactly that:
    two simulated hosts both labelled `E:\\ProfileA` while only one of them was.

    A hint that can be wrong is worse than no hint if a client trusts it, so the
    client does not treat a match as identification — see `_candidates`. What this
    field is good for is telling a single-profile setup apart from a two-browser one.
    """

    try:
        from scholar_search.core import browser as browser_cfg

        recorded = browser_cfg.load()
    except Exception:
        # A host must start even if the config is unreadable; the field is advisory.
        return None
    return recorded.profile_dir if recorded is not None else None


def write_endpoint(port: int, token: str) -> Path:
    root = host_runtime_dir()
    payload = {
        "port": port,
        "token": token,
        "pid": os.getpid(),
        "started": time.time(),
        # Which browser profile this host was launched for. Without it a client that
        # opens two profiles sees two endpoints, takes whichever answers first, and a
        # search issued for one profile can read the other's page.
        "profile_dir": _profile_dir(),
    }
    encoded = json.dumps(payload)

    path = root / ENDPOINT_NAME
    path.write_text(encoded, encoding="utf-8")

    registry = root / "hosts"
    registry.mkdir(parents=True, exist_ok=True)
    (registry / f"bridge-{os.getpid()}.json").write_text(encoded, encoding="utf-8")
    return path


def clear_endpoint(path: Path) -> None:
    registry = host_runtime_dir() / "hosts" / f"bridge-{os.getpid()}.json"
    with contextlib.suppress(OSError):
        registry.unlink()
    with contextlib.suppress(OSError):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if int(payload.get("pid", -1)) == os.getpid():
            path.unlink()


# A request is one JSON line. Accepting an unbounded line means one client can make
# the host buffer without limit before it ever validates a token.
MAX_LINE_BYTES = 1_000_000


def serve_client(
    connection: socket.socket, host: BridgeHost, token: str, domains: tuple[str, ...]
) -> None:
    reader = connection.makefile("r", encoding="utf-8", newline="\n")
    try:
        while True:
            line = reader.readline(MAX_LINE_BYTES)
            if not line:
                break
            if not line.endswith("\n"):
                # The line reached the cap before a newline: refuse it rather than
                # grow the buffer. The connection is dropped because the stream is
                # no longer aligned on line boundaries.
                connection.sendall(b'{"ok":false,"error":"protocol.line_too_long"}\n')
                break
            if not line.strip():
                continue
            try:
                request = json.loads(line)
            except ValueError:
                connection.sendall(b'{"ok":false,"error":"protocol.json"}\n')
                continue

            if not secrets.compare_digest(str(request.get("token", "")), token):
                connection.sendall(b'{"ok":false,"error":"policy.token"}\n')
                continue

            if request.get("cmd") == "ping":
                connection.sendall(b'{"ok":true}\n')
                continue

            if request.get("cmd") == "shutdown":
                connection.sendall(b'{"ok":true}\n')
                connection.close()
                # os._exit skips every finally block, so the endpoint file has to be
                # cleared by hand: a stale one makes the next client dial a dead port.
                with contextlib.suppress(OSError):
                    clear_endpoint(host_runtime_dir() / ENDPOINT_NAME)
                os._exit(0)

            action = request.get("action")
            params = request.get("params") or {}
            timeout_raw = request.get("timeout_ms", 15_000)
            try:
                timeout_ms = int(timeout_raw)
            except (TypeError, ValueError):
                connection.sendall(b'{"ok":false,"error":"policy.params"}\n')
                continue
            if not 0 < timeout_ms <= 15_000:
                connection.sendall(b'{"ok":false,"error":"policy.deadline"}\n')
                continue
            if not isinstance(action, str) or not isinstance(params, dict):
                connection.sendall(b'{"ok":false,"error":"policy.params"}\n')
                continue

            requested_domains = request.get("domains")
            if isinstance(requested_domains, list):
                effective = narrow_domains(
                    (str(item) for item in requested_domains if item), domains
                )
            else:
                effective = domains

            reply = host.request(
                action,
                params,
                timeout_s=timeout_ms / 1000,
                domains=effective or None,
                request_id=str(request.get("id") or "") or None,
            )
            connection.sendall((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
    except OSError:
        pass
    finally:
        try:
            reader.close()
            connection.close()
        except OSError:
            pass


def start_tcp_server(
    host: BridgeHost, token: str, domains: tuple[str, ...]
) -> tuple[socket.socket, int]:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(4)
    port = int(server.getsockname()[1])

    def accept_loop() -> None:
        while True:
            try:
                connection, _ = server.accept()
            except OSError:
                return
            threading.Thread(
                target=serve_client,
                args=(connection, host, token, domains),
                daemon=True,
            ).start()

    threading.Thread(target=accept_loop, daemon=True, name="tcp-accept").start()
    return server, port


def _log(message: str) -> None:
    """Diagnostics go to a file because Chrome discards host stderr."""
    try:
        path = host_runtime_dir() / "logs" / "host.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass


def read_endpoint() -> tuple[int, str] | None:
    path = host_runtime_dir() / ENDPOINT_NAME
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
        return int(info["port"]), str(info["token"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def retire_endpoint(endpoint: tuple[int, str] | None) -> None:
    """Ask the previous host to exit, so only the newest one survives."""

    if endpoint is None:
        return
    port, token = endpoint
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0) as sock:
            payload = json.dumps({"cmd": "shutdown", "token": token}) + "\n"
            sock.sendall(payload.encode("utf-8"))
    except OSError:
        pass


def prune_registry() -> None:
    """Drop registry files whose host no longer listens."""

    registry = host_runtime_dir() / "hosts"
    for path in registry.glob("*.json"):
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
            with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=0.3):
                continue
        except (OSError, ValueError, KeyError, TypeError):
            with contextlib.suppress(OSError):
                path.unlink()


def _apply_runtime_home() -> None:
    """Honour the HOME recorded at install time (browser env cannot set it)."""

    if os.environ.get("SCHOLAR_SEARCH_HOME"):
        return
    marker = Path(__file__).with_name("runtime-home.txt")
    try:
        home = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return
    if home:
        os.environ["SCHOLAR_SEARCH_HOME"] = home


def main() -> int:
    try:
        _apply_runtime_home()
        ensure_host_runtime()
        prune_registry()
        _log(f"start pid={os.getpid()} cwd={os.getcwd()}")
        host = BridgeHost()
        token = secrets.token_urlsafe(24)
        domains = (
            tuple(item for item in os.environ.get("SCHOLAR_SEARCH_DOMAINS", "").split(",") if item)
            or TRUSTED_DOMAINS
        )

        previous = read_endpoint()
        server, port = start_tcp_server(host, token, domains)
        endpoint = write_endpoint(port, token)
        _ = previous  # kept for diagnostics; hosts no longer retire each other

        _log(f"ready port={port} endpoint={endpoint}")
        print(
            f"scholar-search host ready: 127.0.0.1:{port} ({endpoint})",
            file=sys.stderr,
            flush=True,
        )

        try:
            host.serve_extension()
        finally:
            _log("extension channel closed; shutting down")
            clear_endpoint(endpoint)
            server.close()
        return 0
    except BaseException as error:
        import traceback

        _log("fatal: " + "".join(traceback.format_exception(error)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
