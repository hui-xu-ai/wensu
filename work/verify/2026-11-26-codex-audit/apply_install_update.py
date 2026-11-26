"""Install-path migration only. Does not change the wensu implementation."""
from __future__ import annotations

import json
import os
import re
import shutil
import tomllib
from datetime import datetime
from pathlib import Path

import scholar_search
from scholar_search.assets import copy_assets


def main() -> None:
    if scholar_search.__version__ != "0.14.28":
        raise RuntimeError("Run with the newly installed 0.14.28 interpreter")
    home = Path(os.environ["LOCALAPPDATA"]) / "scholar-search"
    root = home / "installations/0.14.28"
    backup = root / "upgrade-backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
    backup.mkdir(parents=True)
    browser_assets = root / "browser"
    copy_assets(browser_assets)

    settings_path = home / "browser.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    extension = Path(settings["extension_dir"])
    expected = home / "browser/extension"
    if extension.resolve() != expected.resolve():
        raise RuntimeError("Unexpected extension directory; inspect before updating")
    shutil.copytree(extension, backup / "extension-before")
    for source in (browser_assets / "extension").rglob("*"):
        if source.is_file():
            target = extension / source.relative_to(browser_assets / "extension")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    shutil.copy2(settings_path, backup / "browser.json.before")

    config = Path.home() / ".codex/config.toml"
    original = config.read_text(encoding="utf-8")
    shutil.copy2(config, backup / "codex-config.toml.before")
    interpreter = root / "venv/Scripts/python.exe"
    section = re.compile(r"(?ms)(^\[mcp_servers\.wensu\]\s*\n)(.*?)(?=^\[|\Z)")
    matches = list(section.finditer(original))
    if len(matches) != 1:
        raise RuntimeError("Expected exactly one wensu MCP configuration")
    match = matches[0]
    body, count = re.subn(r"(?m)^command\s*=.*$", lambda _: f"command = '{interpreter}'", match[2])
    if count != 1:
        raise RuntimeError("Expected exactly one wensu command")
    changed = original[:match.start(2)] + body + original[match.end(2):]
    parsed = tomllib.loads(changed)
    assert parsed["mcp_servers"]["wensu"]["command"] == str(interpreter)
    config.write_text(changed, encoding="utf-8", newline="")

    # pnpm automatically appended a release-age exception during the explicit update.
    # Keep the installed dependency while removing only that newly appended exception.
    workspace = Path("D:/DSH/.dsh/profiles/desktop/pnpm-workspace.yaml")
    policy = workspace.read_text(encoding="utf-8")
    marker = " || 0.14.28'"
    if marker in policy:
        shutil.copy2(workspace, backup / "pnpm-workspace-after-install.yaml")
        workspace.write_text(policy.replace(marker, "'", 1), encoding="utf-8", newline="")

    print(json.dumps({"version": scholar_search.__version__, "backup": str(backup),
        "mcp_interpreter": str(interpreter), "extension_directory": str(extension),
        "new_host_directory": str(browser_assets / "native-host"),
        "browser_profile_preserved": settings["profile_dir"],
        "requires_extension_reload": True, "requires_mcp_reconnect": True},
        ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
