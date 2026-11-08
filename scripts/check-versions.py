#!/usr/bin/env python
"""Fail if the five version sources disagree.

The project ships four artefacts under one version number (Python package, browser
extension, native host, DSH bundle). Keeping them aligned by hand is exactly the
kind of thing that slips during a rushed release, so it is checked here and in CI.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _search(pattern: str, text: str, origin: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    if match is None:
        raise SystemExit(f"check-versions: cannot find a version in {origin}")
    return match.group(1)


def read_versions() -> dict[str, str]:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    init = (ROOT / "src" / "scholar_search" / "__init__.py").read_text(encoding="utf-8")
    manifest = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "packages" / "dsh-wensu" / "package.json").read_text(encoding="utf-8")
    )
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")

    return {
        "pyproject.toml": _search(r'^version = "([^"]+)"', pyproject, "pyproject.toml"),
        "src/scholar_search/__init__.py": _search(
            r'__version__ = "([^"]+)"', init, "__init__.py"
        ),
        "extension/manifest.json": manifest["version"],
        "packages/dsh-wensu/package.json": bundle["version"],
        "NOTICE": _search(r"^Version: ([0-9][^\s(]*)", notice, "NOTICE"),
    }


def main() -> int:
    versions = read_versions()
    width = max(len(name) for name in versions)
    for name, value in versions.items():
        print(f"  {name:<{width}}  {value}")

    distinct = sorted(set(versions.values()))
    if len(distinct) != 1:
        print(
            f"\nMISMATCH: {len(distinct)} different versions — {', '.join(distinct)}",
            file=sys.stderr,
        )
        return 1

    print(f"\nall five sources agree on {distinct[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
