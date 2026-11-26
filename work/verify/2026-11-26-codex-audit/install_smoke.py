"""Exercise the wheel-installed MCP over stdio without touching a browser."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import zipfile
from importlib.metadata import version
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    import scholar_search

    root = Path(os.environ["SCHOLAR_SEARCH_HOME"]).parent
    wheel = next((root / "dist").glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        entries = archive.namelist()
        unexpected = [name for name in entries if any(fragment in name.casefold()
            for fragment in ("warmup", "official.py", "work/scratch", "private"))]
    output = {
        "imported_version": scholar_search.__version__,
        "metadata_version": version("wensu"),
        "module_path": str(scholar_search.__file__),
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "wheel_entries": len(entries),
        "unexpected_private_entries": unexpected,
    }
    params = StdioServerParameters(command=sys.executable,
        args=["-m", "scholar_search.cli", "serve", "--transport", "stdio"],
        env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            listed = await session.list_tools()
            by_name = {tool.name: tool for tool in listed.tools}
            output["server"] = initialized.serverInfo.model_dump()
            output["tools"] = sorted(by_name)
            output["page_read_parameters"] = sorted(by_name["page_read"].inputSchema["properties"])
            status = await session.call_tool("status", {"brief": True})
            output["status"] = status.structuredContent
            exported = await session.call_tool("export", {
                "format": "ris", "out_path": str(root / "smoke.ris"),
                "records": [{"title": "Synthetic installation audit", "year": 2026,
                             "channel": "cnki", "url": "https://example.invalid/audit"}],
            })
            output["export"] = exported.structuredContent
            output["ris_written"] = (root / "smoke.ris").is_file()
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
