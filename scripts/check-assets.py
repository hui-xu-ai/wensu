"""Check that the wheel contains every file the extension manifest references.

A clean install is the only place this class of defect shows up. A machine that has
ever run from the source tree already has every file on disk, so a missing entry in
`pyproject.toml`'s force-include list is invisible there — it produced a released
wheel whose extension manifest pointed at a `content/capture.js` the wheel did not
contain, and nothing noticed until someone installed it fresh.

So this does not compare against a hand-kept list. It reads the manifest, collects
every path the extension will ask the browser to load, and checks the built wheel.
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSET_PREFIX = "scholar_search/assets/extension/"


def referenced_files(manifest: dict[str, object]) -> list[str]:
    """Every file path the manifest tells the browser to load."""

    wanted: list[str] = []

    background = manifest.get("background")
    if isinstance(background, dict):
        worker = background.get("service_worker")
        if isinstance(worker, str) and worker:
            wanted.append(worker)
        for script in background.get("scripts", []) or []:
            if isinstance(script, str):
                wanted.append(script)

    for entry in manifest.get("content_scripts", []) or []:
        if not isinstance(entry, dict):
            continue
        for key in ("js", "css"):
            for path in entry.get(key, []) or []:
                if isinstance(path, str):
                    wanted.append(path)

    web = manifest.get("web_accessible_resources", []) or []
    for entry in web:
        if isinstance(entry, dict):
            for path in entry.get("resources", []) or []:
                if isinstance(path, str) and not path.startswith("*"):
                    wanted.append(path)

    # Preserve order, drop duplicates.
    seen: set[str] = set()
    ordered: list[str] = []
    for path in wanted:
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered


def main() -> int:
    manifest_path = ROOT / "extension" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    wanted = referenced_files(manifest)

    wheels: list[Path] = []
    for candidate in sys.argv[1:]:
        wheels.extend(Path(candidate).glob("wensu-*.whl"))
    if not wheels:
        wheels = list((ROOT / "dist").glob("wensu-*.whl"))
    if not wheels:
        print(
            "no wheel found; pass the directory holding it, or build with "
            "`uv build --out-dir <dir>`"
        )
        return 1
    # Newest by mtime, not by name: `0.9.9` sorts after `0.12.30` as a string, and a
    # stale wheel in the output directory would then be the one checked.
    wheel = max(wheels, key=lambda path: path.stat().st_mtime)

    with zipfile.ZipFile(wheel) as archive:
        present = set(archive.namelist())

    missing = [
        path for path in wanted if f"{ASSET_PREFIX}{path}" not in present
    ]

    print(f"wheel: {wheel.name}")
    print(f"manifest references {len(wanted)} file(s):")
    for path in wanted:
        mark = "MISSING" if path in missing else "ok"
        print(f"  {mark:8} {path}")

    if missing:
        print()
        print("the wheel is missing files the extension manifest loads:", file=sys.stderr)
        for path in missing:
            print(f"  {path}", file=sys.stderr)
        print(
            "add them to [tool.hatch.build.targets.wheel.force-include] in pyproject.toml",
            file=sys.stderr,
        )
        return 1

    print("all referenced extension files are present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
