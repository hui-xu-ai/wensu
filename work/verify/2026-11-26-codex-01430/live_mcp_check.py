"""Version-pinned MCP checks with a passive adapter observer. No retries."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import scholar_search
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

VERSION = "0.14.30"


def evidence() -> Path:
    root = Path(os.environ["SCHOLAR_SEARCH_HOME"]) / "verification/2026-11-26-codex-0.14.30"
    root.mkdir(parents=True, exist_ok=True)
    return root


def serve_observed(case: str) -> None:
    from scholar_search.bootstrap import build_service
    from scholar_search.core.pageprobe import challenge_in_title
    from scholar_search.transports.stdio import serve
    service = build_service()
    original = service._adapter_factory
    log = evidence() / f"{case}-navigation.jsonl"
    class Observer:
        def __init__(self) -> None:
            self.inner = original()
        @property
        def domains(self) -> Any:
            return self.inner.domains
        @domains.setter
        def domains(self, value: Any) -> None:
            self.inner.domains = value
        def __getattr__(self, name: str) -> Any:
            return getattr(self.inner, name)
        def execute(self, action: Any, *, timeout_ms: int) -> Any:
            outcome = self.inner.execute(action, timeout_ms=timeout_ms)
            if action.verb == "goto":
                data = dict(outcome.data)
                row = {"ok": outcome.ok, "error": outcome.error,
                    "host": urlparse(outcome.url or str(data.get("url") or "")).hostname,
                    "title_gate": challenge_in_title(str(data.get("title") or "")),
                    "halted": data.get("halted"), "status": data.get("status"),
                    "captcha_visible": data.get("captcha_visible"),
                    "duration_ms": outcome.duration_ms}
                with log.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            return outcome
    service._adapter_factory = Observer
    serve(service)


async def client(case: str) -> None:
    from scholar_search.core.policy import PolicyEngine
    root = evidence()
    log = root / f"{case}-navigation.jsonl"
    if log.exists() or (root / f"{case}-events.json").exists():
        raise RuntimeError("This real case already has evidence; do not rerun automatically")
    events: list[dict[str, Any]] = []
    params = StdioServerParameters(command=sys.executable,
        args=[str(Path(__file__).resolve()), "--server", "--case", case], env=dict(os.environ))
    before = PolicyEngine().remaining_today
    terminal = "not_started"
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                assert init.serverInfo.version == VERSION
                async def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
                    started = time.perf_counter()
                    response = await session.call_tool(name, arguments)
                    payload = response.structuredContent
                    assert isinstance(payload, dict)
                    events.append({"tool": name, "arguments": arguments,
                        "seconds": round(time.perf_counter() - started, 3), "response": payload})
                    (root / f"{case}-events.json").write_text(
                        json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
                    if payload.get("status") == "blocked" or payload.get("cooldown_until"):
                        raise RuntimeError("STOP: blocked/cooldown; no more MCP calls")
                    if response.isError or payload.get("status") == "error" or payload.get("error"):
                        raise RuntimeError(f"STOP: {name} error; no retry")
                    return payload
                status = await call("status", {"brief": False})
                build = (status.get("browser_profile") or {}).get("bridge_build") or {}
                assert status.get("version") == VERSION and status.get("bridge_ready")
                assert build.get("handshake") == "ok" and build.get("version") == VERSION
                assert build.get("worker") == "background-0.14.30.js" and build.get("host_version") == VERSION
                assert set(build.get("capabilities") or []) == {"goto", "snapshot", "sleep"}
                doi = "10.3390/s26041303" if case == "normal" else "10.1021/acs.inorgchem.1c03019"
                page = await call("page_read", {"doi": doi, "refresh": True})
                terminal = str(page.get("status"))
                if case == "normal" and terminal == "ok" and page.get("mhtml_path"):
                    await call("page2md", {"mhtml_path": page["mhtml_path"]})
    except Exception as error:
        def describe(exc: BaseException) -> str:
            if isinstance(exc, BaseExceptionGroup):
                return "; ".join(describe(item) for item in exc.exceptions)
            return f"{type(exc).__name__}: {exc}"
        terminal = describe(error)
    navigation = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    summary = {"version": VERSION, "case": case, "terminal": terminal,
        "quota_before": before, "quota_after": PolicyEngine().remaining_today,
        "navigation": navigation,
        "events": [{"tool": e["tool"], "seconds": e["seconds"],
            **{k: e["response"].get(k) for k in ["status", "reason", "signal", "code", "full_text",
                "quota_charged", "mhtml_path", "bytes", "bytes_md", "warnings"]}} for e in events]}
    (root / f"{case}-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    assert scholar_search.__version__ == VERSION
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=["normal", "natural"], required=True)
    parser.add_argument("--server", action="store_true")
    args = parser.parse_args()
    if args.server:
        serve_observed(args.case)
    else:
        asyncio.run(client(args.case))
