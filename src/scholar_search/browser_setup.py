"""One-command browser-side setup.

``wensu setup`` copies the bundled browser assets next to the runtime home and
registers the native messaging host, leaving only the one-time "load unpacked"
step in the browser.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from .assets import copy_assets, install_skills
from .core import config

# Pinned by the ``key`` field in extension/manifest.json, so an unpacked load
# keeps the same id across machines.
EXTENSION_ID = "gmaimbocfjkolcpljeekjcomakipoaph"


def setup_browser(
    target: Path | None = None,
    *,
    force: bool = False,
    python: str | None = None,
    register_host: bool = True,
    skills_dir: Path | None = None,
) -> int:
    """Copy the assets, register the host, and print the remaining steps."""

    # Skills first, and independently of the assets. They go where the agent reads
    # them, not into the tool's runtime directory, and an already-installed asset
    # tree used to abort this function before the skills were ever touched — the
    # first live test of this feature installed nothing.
    installed = install_skills(skills_dir, force=force) if skills_dir else []
    if installed:
        print(f"skills: {skills_dir}")
        for path in installed:
            print(f"  {path.name}")
    elif skills_dir:
        print(f"skills: nothing to install (none bundled, or all present in {skills_dir})")

    destination = target if target is not None else config.app_home() / "browser"
    try:
        copied = copy_assets(destination, force=force)
    except FileExistsError as error:
        # Not fatal: re-running setup is usually about the profile or the skills.
        print(f"assets: {error}", file=sys.stderr)
        copied = []
    else:
        print(f"assets: {destination}")
        for path in copied:
            print(f"  {path.name}")

    extension = destination / "extension"
    print()
    print("next, once per browser:")
    print("  1. open edge://extensions (or chrome://extensions)")
    print("  2. turn on Developer mode")
    print("  3. Load unpacked, and choose this directory:")
    print(f"     {extension}")
    print(f"  the extension id stays {EXTENSION_ID}")

    if not register_host:
        print()
        print("native host: skipped (--no-host)")
        return 0

    script = destination / "native-host" / "install.ps1"
    if not script.is_file():
        print(f"native host: missing {script}", file=sys.stderr)
        return 1

    shell = shutil.which("pwsh") or shutil.which("powershell")
    if shell is None:
        print("native host: PowerShell was not found on PATH", file=sys.stderr)
        return 1

    interpreter = python or sys.executable
    print()
    print(f"native host: registering with {interpreter}")
    command = [
        shell,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-Python",
        interpreter,
    ]
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        print(f"native host: registration failed (exit {completed.returncode})", file=sys.stderr)
        return completed.returncode

    print()
    print("done. open a CNKI page once, then check:")
    print("  wensu status")
    return 0
