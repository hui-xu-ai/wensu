#!/usr/bin/env python
"""Which wensu bundle does the DSH on this machine need?

`@deepseek-ai/dsh-mcp-client` declares its ten DSH core peers at **exact** versions, so one
bundle is usable on exactly one DSH build. When the tools disappear after a DSH upgrade the
question is never "is the plugin broken" but "which bundle matches this build" — answer it here
instead of reading an asar by hand.

Sources:
  * the DSH version, from the desktop app's ``app.asar`` (or ``--asar`` / ``--dsh-version``);
  * the pin and ``engines.dsh`` from this repository's bundle;
  * published versions and their engines from ``docs/market/index.json``.

Exit code is 0 when this repository's bundle is built for the DSH found, 1 when it is not.

Run:  python scripts/check-bundle-compat.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "packages" / "dsh-wensu" / "package.json"
MARKET = ROOT / "docs" / "market" / "index.json"
CLIENT = "@deepseek-ai/dsh-mcp-client"

ASAR_HEADER_BYTES = 16


def _version_from_asar(asar: Path) -> str:
    """The version in the root ``package.json`` stored inside an Electron asar."""

    with asar.open("rb") as handle:
        head = handle.read(ASAR_HEADER_BYTES)
        if len(head) < ASAR_HEADER_BYTES:
            raise ValueError(f"{asar} is too short to be an asar archive")
        # Layout: uint32 always=4, uint32 pickle size, uint32 always=?, uint32 json size.
        pickle_size = int.from_bytes(head[4:8], "little")
        json_size = int.from_bytes(head[12:16], "little")
        header = json.loads(handle.read(json_size))
        directory = header.get("files", {})
        entry = directory["package.json"]
        handle.seek(8 + pickle_size + int(entry["offset"]))
        package = json.loads(handle.read(int(entry["size"])))
    version = package.get("version")
    if not isinstance(version, str):
        raise ValueError(f"{asar}: root package.json has no version")
    return version


def _candidate_asars() -> list[Path]:
    """Where a desktop install keeps its asar, best guess first."""

    candidates: list[Path] = []
    install_dir = os.environ.get("DSH_INSTALL_DIR")
    if install_dir:
        # ...\resources\app.asar\dsh\node_modules\@deepseek-ai\dsh
        marker = os.sep + "app.asar" + os.sep
        if marker in install_dir:
            candidates.append(Path(install_dir.split(marker)[0] + os.sep + "app.asar"))
    node = os.environ.get("DSH_NODE_EXECUTABLE")
    if node:
        candidates.append(Path(node).parent / "resources" / "app.asar")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Programs" / "DeepSeek Harness" / "resources" / "app.asar")
    candidates.append(Path("C:/Program Files/DeepSeek Harness/resources/app.asar"))
    return candidates


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        # The verdict line uses em dashes; a cp1252 console turns them into noise.
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    pinned = bundle["dependencies"][CLIENT]
    engine = bundle["engines"]["dsh"]

    arguments = sys.argv[1:]
    dsh_version: str | None = None
    source = "(--dsh-version)"
    if "--dsh-version" in arguments:
        dsh_version = arguments[arguments.index("--dsh-version") + 1]
    else:
        asars = (
            [Path(arguments[arguments.index("--asar") + 1])]
            if "--asar" in arguments
            else _candidate_asars()
        )
        for asar in asars:
            if not asar.is_file():
                continue
            try:
                dsh_version = _version_from_asar(asar)
            except (OSError, KeyError, ValueError) as error:
                print(f"check-bundle-compat: cannot read {asar}: {error}", file=sys.stderr)
                continue
            source = str(asar)
            break

    print(f"bundle in this repo : {bundle['version']}")
    print(f"  {CLIENT} = {pinned}")
    print(f"  engines.dsh{' ' * 12}= {engine}")
    if dsh_version is None:
        print("\nDSH on this machine : unknown")
        print("  pass --asar <path> or --dsh-version <version>", file=sys.stderr)
        return 2

    print(f"\nDSH on this machine : {dsh_version}")
    print(f"  read from {source}")

    if dsh_version == engine:
        print("\nverdict: OK — this bundle is built for this DSH")
        code = 0
    else:
        print(f"\nverdict: MISMATCH — the bundle needs DSH {engine}, found {dsh_version}")
        print("  installing it anyway is refused with error.code 'incompatible-version',")
        print("  the MCP row never mounts, and no mcp__wensu__* tools appear.")
        code = 1

    try:
        market = json.loads(MARKET.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        market = {}
    matches = [
        entry["version"]
        for plugin in market.get("plugins", [])
        for entry in plugin.get("versions", [])
        if entry.get("engines", {}).get("dsh") == dsh_version
    ]
    print(
        f"\npublished for DSH {dsh_version}: "
        + (", ".join(matches) if matches else "none yet — a matching release is needed")
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
