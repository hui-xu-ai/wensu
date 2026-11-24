"""`wensu doctor`: is the build that answers the build that was installed?

Four artefacts share one version number (ADR 0013), and two of them live outside the wheel:
the DSH bundle sits in a profile's `node_modules`, the browser extension in the asset
directory. "I updated it" and "it is running" therefore drift apart silently — on
2026-11-24 this machine answered `0.13.2` while the bundle and the extension were `0.14.2`,
and the only field that said so was in the ~500-token full `status` payload.

The report answers one question — do the three versions agree — and names the artefact that
disagrees when they do not.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

BUNDLE_NAME = "@hui-xu-ai/dsh-wensu"

OK = "ok"
PARTIAL = "partial"
MISMATCH = "mismatch"
UNKNOWN = "unknown"

PANDOC_HINT = (
    "pandoc 未安装：公式仍会转换，但复杂的（积分上下限、矩阵）可能失真。"
    "安装：winget install JohnMacFarlane.Pandoc  或  https://pandoc.org/installing.html"
)


def dsh_homes() -> list[Path]:
    """Places a DSH install may keep `profiles/`, most specific first."""

    homes: list[Path] = []
    for key in ("DSH_HOME", "DSH_DATA_HOME"):
        value = os.environ.get(key)
        if value:
            homes.append(Path(value))
    homes.append(Path.home() / ".dsh")
    ordered: list[Path] = []
    for home in homes:
        if home not in ordered:
            ordered.append(home)
    return ordered


def bundle_in(profile: Path) -> dict[str, Any]:
    """`{version, path}` for one profile directory; version is None when it is not there."""

    manifest = profile / "node_modules" / BUNDLE_NAME / "package.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": None, "path": str(manifest), "profile": profile.name}
    version = payload.get("version") if isinstance(payload, dict) else None
    return {
        "version": version if isinstance(version, str) else None,
        "path": str(manifest),
        "profile": profile.name,
    }


def find_bundle(homes: list[Path] | None = None) -> dict[str, Any]:
    """Where the DSH bundle is installed, if any profile has it."""

    for home in dsh_homes() if homes is None else homes:
        profiles = home / "profiles"
        if not profiles.is_dir():
            continue
        for profile in sorted(entry for entry in profiles.iterdir() if entry.is_dir()):
            found = bundle_in(profile)
            if found["version"]:
                return found
    return {"version": None, "path": None, "profile": None}


def verdict(*, cli: str | None, extension: str | None, bundle: str | None) -> str:
    """`ok` only when all three are known and equal; `partial` when one is unknown."""

    known = [value for value in (cli, extension, bundle) if value]
    if not known:
        return UNKNOWN
    if len(set(known)) > 1:
        return MISMATCH
    if len(known) < 3:
        return PARTIAL
    return OK


def pandoc_version() -> str | None:
    """The installed pandoc's version, or None. Never installs anything.

    `page2md` converts formulae without pandoc — the builtin MathML subset converter is the
    fallback — so a missing pandoc degrades quality rather than blocking the chain. Asking
    the user to install it is a one-line hint, not a hidden download: pulling a third-party
    binary from an MCP tool is a supply-chain decision, not a convenience.
    """

    executable = shutil.which("pandoc")
    if executable is None:
        return None
    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    first = (completed.stdout or "").splitlines()
    if not first:
        return None
    match = re.search(r"\d+\.\d+(?:\.\d+)?", first[0])
    return match.group(0) if match else first[0].strip()[:40]
