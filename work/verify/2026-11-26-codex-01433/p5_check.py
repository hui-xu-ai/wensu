"""Version-pinned P5 checks via official MCP. Every real label runs once; no retries."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import scholar_search
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

VERSION = "0.14.33"


def root() -> Path:
    result = Path(os.environ["SCHOLAR_SEARCH_HOME"]) / "verification/2026-11-26-codex-0.14.33-p5"
    result.mkdir(parents=True, exist_ok=True)
    return result


def save(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def desktop_state() -> dict[str, Any]:
    """Passive Windows observation only; no focus, click or window mutation."""
    try:
        import ctypes
        from ctypes import wintypes
        import win32gui
        import win32process
        window = win32gui.GetForegroundWindow()
        _, pid = win32process.GetWindowThreadProcessId(window)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                    wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        executable = "unknown"
        if handle:
            try:
                buffer = ctypes.create_unicode_buffer(32768)
                size = wintypes.DWORD(len(buffer))
                if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                    executable = Path(buffer.value).name
            finally:
                kernel.CloseHandle(handle)
        from scholar_search.core.pageprobe import challenge_in_title
        return {"foreground_pid": pid, "foreground_executable": executable,
                "foreground_show_cmd": win32gui.GetWindowPlacement(window)[1],
                "foreground_gate_title": challenge_in_title(win32gui.GetWindowText(window)),
                "foreground_title_sha256": hashlib.sha256(win32gui.GetWindowText(window).encode()).hexdigest()}
    except Exception as error:
        return {"observation_error": type(error).__name__}


def serve_observed(label: str) -> None:
    from scholar_search.bootstrap import build_service
    from scholar_search.core.pageprobe import challenge_in_title
    from scholar_search.transports.stdio import serve
    service = build_service()
    factory = service._adapter_factory
    record_lock = threading.Lock()

    def record(value: dict[str, Any]) -> None:
        with record_lock:
            with (root() / f"{label}-actions.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"at_monotonic": time.monotonic(), **value}, ensure_ascii=False) + "\n")

    class Observer:
        def __init__(self) -> None:
            self.inner = factory()

        @property
        def domains(self) -> Any:
            return self.inner.domains

        @domains.setter
        def domains(self, value: Any) -> None:
            self.inner.domains = value

        def __getattr__(self, name: str) -> Any:
            return getattr(self.inner, name)

        def execute(self, action: Any, *, timeout_ms: int) -> Any:
            stop = threading.Event()
            watcher = None
            if action.verb == "await_gate_clear":
                record({"verb": action.verb, "phase": "before", "desktop": desktop_state()})

                def watch() -> None:
                    while not stop.wait(0.25):
                        record({"verb": action.verb, "phase": "during", "desktop": desktop_state()})

                watcher = threading.Thread(target=watch, daemon=True)
                watcher.start()
            started = time.perf_counter()
            try:
                outcome = self.inner.execute(action, timeout_ms=timeout_ms)
            finally:
                stop.set()
                if watcher:
                    watcher.join(1)
            if action.verb in {"goto", "await_gate_clear"}:
                data = dict(outcome.data)
                record({"verb": action.verb, "phase": "returned", "ok": outcome.ok,
                        "seconds": round(time.perf_counter() - started, 3), "error": outcome.error,
                        "host": urlparse(outcome.url or str(data.get("url") or "")).hostname,
                        "title_gate": challenge_in_title(str(data.get("title") or "")),
                        **{k: data.get(k) for k in ["status", "captcha_visible", "halted", "cleared", "reason",
                                                  "tab_id", "kept", "navigation_attempts"]}})
                if data.get("status") in {403, 429} or data.get("captcha_visible") is True:
                    save(root() / "STOP.json", {"label": label, "verb": action.verb,
                                               "status": data.get("status"), "captcha_visible": data.get("captcha_visible")})
            return outcome

    service._adapter_factory = Observer
    serve(service)


async def client(args: argparse.Namespace) -> None:
    from scholar_search.core.policy import PolicyEngine
    from scholar_search.core.risk import RiskGuard
    evidence = root()
    events_file = evidence / f"{args.label}-events.json"
    if args.mode in {"read", "warm", "warm4"}:
        if events_file.exists():
            raise RuntimeError("This real label already has evidence; no automatic rerun")
        if (evidence / "STOP.json").exists() or RiskGuard().cooldown_until():
            raise RuntimeError("Batch stop/cooldown is present; no site call allowed")
    events: list[dict[str, Any]] = []
    before = PolicyEngine().remaining_today
    params = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).resolve()),
        "server", "--label", args.label], env=dict(os.environ))
    result: dict[str, Any] = {"version": VERSION, "label": args.label, "mode": args.mode,
                              "quota_before": before}
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                assert init.serverInfo.version == VERSION, init.serverInfo

                async def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
                    started = time.perf_counter()
                    response = await session.call_tool(name, arguments)
                    value = response.structuredContent
                    assert isinstance(value, dict), response
                    events.append({"tool": name, "arguments": arguments,
                                   "seconds": round(time.perf_counter() - started, 3),
                                   "is_error": response.isError, "response": value})
                    save(events_file, events)
                    return value

                if args.mode != "convert":
                    status = await call("status", {"brief": False})
                    build = (status.get("browser_profile") or {}).get("bridge_build") or {}
                    result["bridge_build"] = build
                    assert status.get("version") == VERSION and status.get("bridge_ready"), status
                    assert build.get("version") == VERSION and build.get("host_version") == VERSION, build
                    assert build.get("handshake") == "ok" and build.get("worker") == f"background-{VERSION}.js", build
                    result["await_gate_clear_advertised"] = "await_gate_clear" in (build.get("capabilities") or [])
                    if status.get("cooldown_until"):
                        raise RuntimeError("Cooldown active; stop")
                    if args.mode in {"warm", "warm4", "read"}:
                        reserve = 16 if args.mode in {"warm", "warm4"} else 2
                        assert isinstance(status.get("quota_remaining"), int) and status["quota_remaining"] >= reserve
                if args.mode == "read":
                    arguments: dict[str, Any] = {"doi": args.target}
                    if args.refresh:
                        arguments["refresh"] = True
                    payload = await call("page_read", arguments)
                    result["response"] = payload
                    if payload.get("mhtml_path"):
                        actual = hashlib.sha256(Path(payload["mhtml_path"]).read_bytes()).hexdigest()
                        result["actual_capture_sha256"] = actual
                        result["capture_hash_matches"] = actual == payload.get("capture_sha256")
                elif args.mode == "warm":
                    result["response"] = await call("warm_up", {"targets": [args.target]})
                elif args.mode == "warm4":
                    targets = args.target.split(",")
                    assert len(targets) == 4 and len(set(targets)) == 4
                    opened: list[Any] = []
                    costs = 0
                    stopped = False
                    for target in targets:
                        # Separate tool calls ensure an exception swallowed by warm_up cannot
                        # advance to another publisher before the caller checks the risk state.
                        item = await call("warm_up", {"targets": [target]})
                        opened.extend(item.get("opened") or [{"target": target, "ok": False, "response": item}])
                        costs += int(item.get("quota_charged") or 0)
                        checkpoint = await call("status", {"brief": True})
                        if ((evidence / "STOP.json").exists() or checkpoint.get("cooldown_until")
                                or item.get("status") == "blocked"):
                            stopped = True
                            break
                    result["response"] = {"status": "stopped" if stopped else "ok",
                                          "opened": opened, "quota_charged": costs,
                                          "stop_checked_after_each_publisher": True}
                elif args.mode == "convert":
                    actual = hashlib.sha256(Path(args.mhtml).read_bytes()).hexdigest()
                    assert actual == args.sha256, "Input does not match handed-off capture"
                    out = evidence / "conversions" / args.label
                    payload = await call("page2md", {"mhtml_path": args.mhtml, "out_dir": str(out)})
                    result["response"] = payload
                    if payload.get("page_md"):
                        meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
                        index = json.loads((out / "index.json").read_text(encoding="utf-8"))
                        result["conversion"] = {"capture_sha256": actual,
                            "input_unchanged": hashlib.sha256(Path(args.mhtml).read_bytes()).hexdigest() == actual,
                            "meta_capture_sha256": meta.get("capture_sha256"),
                            **{k: meta.get(k) for k in ["engine", "coverage", "warnings", "sections_total", "tokens_total", "input_changed"]},
                            "index_sections": len(index.get("sections") or []),
                            "index_total_tokens": index.get("total_tokens")}
    except BaseException as error:
        def describe(exc: BaseException) -> str:
            if isinstance(exc, BaseExceptionGroup):
                return "; ".join(describe(item) for item in exc.exceptions)
            return f"{type(exc).__name__}: {exc}"
        result["test_error"] = describe(error)
    result["quota_after"] = PolicyEngine().remaining_today
    until = RiskGuard().cooldown_until()
    result["cooldown_until"] = until.isoformat() if until else None
    payload = result.get("response") or {}
    # terminal is the new contract. Legacy status=blocked can intentionally accompany
    # terminal=timeout; that case skips a publisher, rather than stopping all publishers.
    if (payload.get("terminal") == "blocked"
            or (not payload.get("terminal") and payload.get("status") == "blocked") or until):
        save(evidence / "STOP.json", {"label": args.label, "reason": payload.get("reason"),
                                     "code": payload.get("code"), "cooldown_until": result["cooldown_until"]})
    if args.mode == "read" and (payload.get("terminal") != "ok" or not result.get("capture_hash_matches")):
        failures_file = evidence / "failures.json"
        failures = json.loads(failures_file.read_text(encoding="utf-8")) if failures_file.exists() else []
        failures.append({"label": args.label, "doi": args.target, "test_error": result.get("test_error"),
                         **{k: payload.get(k) for k in ["publisher", "terminal", "status", "reason", "stage", "evidence", "quota_charged", "job_id"]}})
        save(failures_file, failures)
    save(evidence / f"{args.label}-summary.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    assert scholar_search.__version__ == VERSION
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["server", "status", "read", "warm", "warm4", "convert"])
    parser.add_argument("--label", required=True)
    parser.add_argument("--target", default="")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--mhtml", default="")
    parser.add_argument("--sha256", default="")
    args = parser.parse_args()
    if args.mode == "server":
        serve_observed(args.label)
    else:
        asyncio.run(client(args))
