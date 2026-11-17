#!/usr/bin/env python
"""Write ``schemas/tools.json`` from the server's own tool list.

The file used to be hand-maintained, and it drifted: `exclude_ut`, the two sort
aliases and `status.brief` were missing, while its own description called it "the
stable tool surface". Nothing read the file, so nothing failed — the contract test
deliberately asks the server instead of parsing this file, which was the right call
for the test and left the file decorative.

Generating it makes the file a statement of fact. Run with `--check` to fail when it
is out of date; that runs in the test suite, `release-check.py` and CI.
"""

from __future__ import annotations

import asyncio
import difflib
import inspect
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "schemas" / "tools.json"

HEADER: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://github.com/scholar-search/scholar-search/schemas/tools.json",
    "title": "scholar-search MCP tools",
    "description": (
        "Generated from the running server by scripts/dump-tools.py; do not edit by "
        "hand. scripts/dump-tools.py --check runs in the tests, in release-check and "
        "in CI, and fails when this file is stale."
    ),
}


def _clean(entry: dict[str, object]) -> dict[str, object]:
    """Normalise the whitespace of every docstring in this entry."""

    description = entry.get("description")
    if isinstance(description, str):
        entry["description"] = inspect.cleandoc(description)
    schema = entry.get("inputSchema")
    if isinstance(schema, dict):
        for prop in (schema.get("properties") or {}).values():
            if isinstance(prop, dict) and isinstance(prop.get("description"), str):
                prop["description"] = inspect.cleandoc(prop["description"])
    return entry


def render() -> str:
    """What the file should contain, right now, according to the server."""

    # Building the service touches the runtime home (quota state, cache, audit). A
    # schema dump must not do that to the user's directory, so build against a
    # scratch home; it is removed when this process exits.
    scratch = tempfile.TemporaryDirectory(prefix="wensu-tools-")
    globals()["_scratch_home"] = scratch
    os.environ["SCHOLAR_SEARCH_HOME"] = scratch.name

    from scholar_search.bootstrap import build_service
    from scholar_search.server import build_server

    tools = asyncio.run(build_server(build_service()).list_tools())
    payload = {
        **HEADER,
        "tools": [
            # `model_dump` hands back the docstring exactly as written, indentation
            # included. A documentation file is read, not executed, so normalise the
            # whitespace — this is the same text a client shows.
            _clean(tool.model_dump(mode="json", by_alias=True, exclude_none=True))
            for tool in tools
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    wanted = render()
    if "--check" not in sys.argv[1:]:
        OUT.write_text(wanted, encoding="utf-8")
        print(f"wrote {OUT.relative_to(ROOT)}")
        return 0
    try:
        found = OUT.read_text(encoding="utf-8")
    except OSError as error:
        print(f"dump-tools: cannot read {OUT}: {error}", file=sys.stderr)
        return 1
    if found == wanted:
        print(f"{OUT.relative_to(ROOT)} matches the server")
        return 0
    print(f"{OUT.relative_to(ROOT)} is stale — run scripts/dump-tools.py", file=sys.stderr)
    diff = difflib.unified_diff(
        found.splitlines(), wanted.splitlines(), "file", "server", lineterm=""
    )
    for line in list(diff)[:40]:
        print(line, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
