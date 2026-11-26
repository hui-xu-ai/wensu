"""Version-pinned real MCP checks against the existing browser and shared quota.

No browser automation outside wensu, no copied quota state, no retries.
Full responses stay in the private runtime directory.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import scholar_search
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["cnki", "wos", "page", "status"])
    args = parser.parse_args()
    if scholar_search.__version__ != "0.14.28":
        raise RuntimeError("The real tests require installed wensu 0.14.28")
    home = Path(os.environ["SCHOLAR_SEARCH_HOME"])
    output = home / "verification" / "2026-11-26-codex-0.14.28"
    output.mkdir(parents=True, exist_ok=True)
    events: list[dict[str, Any]] = []

    params = StdioServerParameters(command=sys.executable,
        args=["-m", "scholar_search.cli", "serve", "--transport", "stdio"],
        env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            if initialized.serverInfo.version != "0.14.28":
                raise RuntimeError("MCP handshake version mismatch")

            async def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
                started = time.perf_counter()
                response = await session.call_tool(name, arguments)
                payload = response.structuredContent
                if not isinstance(payload, dict):
                    texts = [part.text for part in response.content if hasattr(part, "text")]
                    payload = json.loads("\n".join(texts))
                event = {"tool": name, "arguments": arguments,
                         "seconds": round(time.perf_counter() - started, 3),
                         "is_error": bool(response.isError), "response": payload}
                events.append(event)
                (output / f"{args.stage}-events.json").write_text(
                    json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
                if payload.get("status") == "blocked" or payload.get("cooldown_until"):
                    raise RuntimeError("STOP: risk or cooldown; no further tool calls")
                if response.isError or payload.get("error") or payload.get("status") == "error":
                    raise RuntimeError(f"STOP: {name} failed; no automatic retry")
                return payload

            before = await call("status", {"brief": True})
            if before.get("version") != "0.14.28" or before.get("extension_version") != "0.14.28":
                raise RuntimeError("Installed server and extension must both report 0.14.28")
            if not before.get("bridge_ready"):
                raise RuntimeError("STOP: bridge not ready")

            if args.stage == "cnki":
                query = {"channel": "cnki", "query": "柔性 驱动器", "limit": 3,
                         "fields": ["title", "year", "doi", "source"]}
                found = await call("search", query)
                records = found.get("records") or []
                if records:
                    await call("detail", {"url": records[0]["url"], "channel": "cnki",
                        "include_abstract": False,
                        "fields": ["title", "year", "doi", "volume", "issue", "pages"]})
                    await call("detail", {"url": records[0]["url"], "channel": "cnki",
                        "include_abstract": False, "fields": ["title", "doi"]})
                await call("search", {**query, "limit": 1, "local_sort": "year"})
                if records:
                    await call("export", {"records": records, "format": "ris",
                        "out_path": str(output / "cnki-real.ris")})
            elif args.stage == "wos":
                query = {"channel": "webofscience",
                         "query": "TS=(ionic AND actuator) AND PY=(2025-2026)",
                         "limit": 3, "fields": ["title", "year", "doi", "source"]}
                found = await call("search", query)
                records = found.get("records") or []
                if records:
                    await call("detail", {"url": records[0]["url"],
                        "include_abstract": False, "fields": ["title", "doi", "volume", "pages"]})
                await call("search", {**query, "limit": 1, "local_sort": "year"})
            elif args.stage == "page":
                page = await call("page_read", {"doi": "10.3390/s26041303", "refresh": True})
                if page.get("status") == "ok" and page.get("mhtml_path"):
                    await call("page2md", {"mhtml_path": page["mhtml_path"]})
                    await call("page_read", {"doi": "10.3390/s26041303"})

            after = await call("status", {"brief": True})
            summary = {
                "date": datetime.now().isoformat(), "stage": args.stage,
                "interpreter": sys.executable, "module": scholar_search.__file__,
                "handshake_version": initialized.serverInfo.version,
                "quota_before": before.get("quota_remaining"),
                "quota_after": after.get("quota_remaining"),
                "events": [{"tool": e["tool"], "seconds": e["seconds"],
                    "status": e["response"].get("status"),
                    "reason": e["response"].get("reason"),
                    "code": e["response"].get("code"),
                    "quota_charged": e["response"].get("quota_charged"),
                    "quota_remaining": e["response"].get("quota_remaining"),
                    "returned": (len(e["response"]["records"])
                        if isinstance(e["response"].get("records"), list)
                        else e["response"].get("records")),
                    "total": e["response"].get("total"),
                    "cached": e["response"].get("cached"),
                    "full_text": e["response"].get("full_text"),
                    "title": e["response"].get("title"),
                    "doi": e["response"].get("doi"),
                    "warnings": e["response"].get("warnings"),
                    "bytes_md": e["response"].get("bytes_md"),
                } for e in events], "private_evidence": str(output),
            }
            print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        def describe(exc: BaseException) -> str:
            if isinstance(exc, BaseExceptionGroup):
                return "; ".join(describe(item) for item in exc.exceptions)
            return f"{type(exc).__name__}: {exc}"
        print(json.dumps({"stopped": True, "error": describe(error)}, ensure_ascii=False))
        raise SystemExit(1)
