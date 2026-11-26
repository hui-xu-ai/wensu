"""Local installation migration. No product implementation changes."""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tomllib
from datetime import datetime
from pathlib import Path

import scholar_search
from scholar_search.assets import copy_assets

VERSION = "0.14.29"


def main() -> None:
    assert scholar_search.__version__ == VERSION
    home = Path(os.environ["LOCALAPPDATA"]) / "scholar-search"
    root = home / "installations" / VERSION
    assert Path(sys.executable) == root / "venv/Scripts/python.exe"
    backup = root / "upgrade-backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
    backup.mkdir(parents=True)
    assets = root / "browser"
    copy_assets(assets)
    settings = json.loads((home / "browser.json").read_text(encoding="utf-8"))
    extension = Path(settings["extension_dir"])
    assert extension.resolve() == (home / "browser/extension").resolve()
    shutil.copytree(extension, backup / "extension-before")
    for source in (assets / "extension").rglob("*"):
        if source.is_file():
            target = extension / source.relative_to(assets / "extension")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    config = Path.home() / ".codex/config.toml"
    original = config.read_text(encoding="utf-8")
    shutil.copy2(config, backup / "codex-config.toml.before")
    matches = list(re.finditer(r"(?ms)^\[mcp_servers\.wensu\]\s*\n(.*?)(?=^\[|\Z)", original))
    assert len(matches) == 1
    match = matches[0]
    body, count = re.subn(r"(?m)^command\s*=.*$", lambda _: f"command = '{sys.executable}'", match[1])
    assert count == 1
    changed = original[:match.start(1)] + body + original[match.end(1):]
    assert tomllib.loads(changed)["mcp_servers"]["wensu"]["command"] == sys.executable
    config.write_text(changed, encoding="utf-8", newline="")
    workspace = Path("D:/DSH/.dsh/profiles/desktop/pnpm-workspace.yaml")
    policy = workspace.read_text(encoding="utf-8")
    marker = f" || {VERSION}'"
    if marker in policy:
        shutil.copy2(workspace, backup / "pnpm-workspace-after-install.yaml")
        workspace.write_text(policy.replace(marker, "'", 1), encoding="utf-8", newline="")
    # The patch installer's first-only backup must match the official version being installed.
    global_core = Path("D:/Python/Python314/Lib/site-packages/scholar_search/core")
    old = global_core / "page_nav.official.py"
    if old.exists():
        shutil.copy2(old, backup / "global-page_nav.official.before.py")
    shutil.copy2(global_core / "page_nav.py", old)
    print(json.dumps({"version": VERSION, "backup": str(backup),
        "command": sys.executable, "extension": str(extension),
        "native_host": str(assets / "native-host"),
        "profile_preserved": settings["profile_dir"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
