"""The browser profile wensu owns, and its lifecycle.

Why this exists
---------------
The extension lives in exactly one browser profile. Until now wensu only knew how to
*connect* to a native host — it had no idea which profile that host belonged to, so a
user who had the extension in a dedicated window got `bridge_ready: false` whenever
that window was closed, with nothing in the response explaining it.

Two attempts to work around that made things worse: an agent concluded the browser was
"stuck in the background", killed every `msedge` process and restarted the default
profile — which does not have the extension. The user lost their browsing session and
the bridge still did not come back.

The fix is ownership rather than improvisation: wensu creates its **own** profile
directory, records where it is, and starts that exact directory when asked. It never
looks at, starts, or stops any other profile.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import app_home, profiles_dir

CONFIG_NAME = "browser.json"

# Where each browser keeps its executable on Windows. Checked in order; the first hit
# wins, and an explicit `--executable` overrides both.
_KNOWN_EXECUTABLES: dict[str, tuple[str, ...]] = {
    "edge": (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ),
    "chrome": (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ),
}


@dataclass(frozen=True, slots=True)
class BrowserConfig:
    """Which profile wensu owns, and how to start it."""

    browser: str
    executable: str
    profile_dir: str
    extension_dir: str
    extension_id: str | None = None

    @property
    def path(self) -> Path:
        return app_home() / CONFIG_NAME

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def config_path() -> Path:
    return app_home() / CONFIG_NAME


def load() -> BrowserConfig | None:
    """Read the recorded profile, or None when setup has not run."""

    path = config_path()
    if not path.is_file():
        return None
    try:
        # utf-8-sig: a hand-edited file may carry a BOM, and that must not look
        # like "not configured" — the same failure mode that once made the quota
        # state read as corrupt.
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        return BrowserConfig(
            browser=str(raw["browser"]),
            executable=str(raw["executable"]),
            profile_dir=str(raw["profile_dir"]),
            extension_dir=str(raw["extension_dir"]),
            extension_id=raw.get("extension_id"),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save(config: BrowserConfig) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def find_executable(browser: str) -> str | None:
    for candidate in _KNOWN_EXECUTABLES.get(browser.casefold(), ()):
        if Path(candidate).is_file():
            return candidate
    return None


def default_profile_dir(browser: str) -> Path:
    """A profile directory wensu owns outright.

    Deliberately not the user's default profile: touching that one would put a
    research tool's extension into whatever they were already browsing with, and a
    reset would take their sessions with it.
    """

    return profiles_dir() / browser.casefold()


def create(
    browser: str = "edge",
    *,
    executable: str | None = None,
    extension_dir: str | None = None,
    extension_id: str | None = None,
) -> BrowserConfig:
    """Create the profile directory and record it. Idempotent."""

    exe = executable or find_executable(browser)
    if exe is None:
        raise FileNotFoundError(
            f"could not find a {browser} executable; pass --executable explicitly"
        )

    profile = default_profile_dir(browser)
    profile.mkdir(parents=True, exist_ok=True)

    ext = Path(extension_dir) if extension_dir else app_home() / "browser" / "extension"
    config = BrowserConfig(
        browser=browser.casefold(),
        executable=str(exe),
        profile_dir=str(profile),
        extension_dir=str(ext),
        extension_id=extension_id or derive_extension_id(ext),
    )
    save(config)
    return config


def derive_extension_id(extension_dir: str | Path) -> str | None:
    """The id Chromium will assign to this unpacked extension.

    An unpacked extension's id is a hash of the `key` field in its manifest when one
    is present, and of the absolute path otherwise. Ours ships a `key`, so the id is
    the same on every machine — which is what lets the native-messaging manifest
    list it in `allowed_origins` ahead of time.
    """

    manifest = Path(extension_dir) / "manifest.json"
    if not manifest.is_file():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    key = data.get("key")
    if not isinstance(key, str) or not key:
        return None
    try:
        digest = hashlib.sha256(base64.b64decode(key)).hexdigest()[:32]
    except (ValueError, TypeError):
        return None
    alphabet = "abcdefghijklmnop"
    return "".join(alphabet[int(ch, 16)] for ch in digest)


def is_profile_dir(path: Path) -> bool:
    """Whether this looks like a Chromium `--user-data-dir`.

    Chrome and Edge both write `Local State` at the root and a `Default/` profile
    directory beside it. Checking for those two is enough to tell a profile apart
    from an arbitrary folder, and it is much safer than starting a browser with
    whatever path someone typed.
    """

    return (path / "Local State").is_file() and (path / "Default").is_dir()


def adopt(
    profile_dir: str | Path,
    *,
    browser: str = "edge",
    executable: str | None = None,
    extension_dir: str | None = None,
    extension_id: str | None = None,
) -> BrowserConfig:
    """Record an existing profile instead of creating a new one.

    Most users who already have a working setup built it by hand — a dedicated
    profile on another drive, already signed in, extension already installed.
    Rebuilding it as `profiles/edge` would throw that away and force them to
    reinstall the extension. Taking the path they already use is strictly better.
    """

    path = Path(profile_dir).expanduser()
    if not path.is_dir():
        raise FileNotFoundError(f"{path} is not a directory")
    if not is_profile_dir(path):
        raise ValueError(
            f"{path} does not look like a browser user-data-dir "
            "(expected a 'Local State' file and a 'Default' directory beside it)"
        )

    exe = executable or find_executable(browser)
    if exe is None:
        raise FileNotFoundError(
            f"could not find a {browser} executable; pass --executable explicitly"
        )

    ext = Path(extension_dir) if extension_dir else app_home() / "browser" / "extension"
    config = BrowserConfig(
        browser=browser.casefold(),
        executable=str(exe),
        profile_dir=str(path.resolve()),
        extension_dir=str(ext),
        extension_id=extension_id or derive_extension_id(ext),
    )
    save(config)
    return config


def profile_is_running(config: BrowserConfig) -> bool:
    """Whether a browser is currently using this profile.

    Chromium holds `Default/LOCK` for as long as it has the profile open. That file
    is the signal the remediation message needed: the previous version decided from
    `host.log`'s last timestamp, which says when a host last ran — not whether one is
    running now. A stale log line made "the browser is not started" look like "the
    extension dropped", and the instruction sent the user to click an icon in a window
    that did not exist.

    Best effort by nature: a crashed browser can leave the lock behind. The cost of
    being wrong is one wasted instruction, which is what the message already was.
    """

    return (Path(config.profile_dir) / "Default" / "LOCK").exists()


def start(config: BrowserConfig, *, settle_s: float = 1.5) -> subprocess.Popen[bytes]:
    """Start the recorded profile and confirm it stayed up.

    Chromium exits with code 21 when it cannot write to its `--user-data-dir` — a
    read-only or sandboxed mount, most often. Reporting "started, pid N" for a
    process that died a moment later sends the caller looking for a bridge that
    could never appear; the report describes exactly that happening.

    `--load-extension` is passed as a best effort: recent Chromium builds ignore it
    unless the browser is started with developer mode, so a first-time user may still
    have to load the unpacked extension once. The command is idempotent and safe to
    repeat — it always targets this one `--user-data-dir` and never a process by name.
    """

    args = [
        config.executable,
        f"--user-data-dir={config.profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if Path(config.extension_dir).is_dir():
        args.append(f"--load-extension={config.extension_dir}")

    creationflags = 0
    if sys.platform == "win32":
        # Detach: wensu must not die with the browser, and the browser must not
        # inherit our stdio.
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(
        args,
        close_fds=True,
        creationflags=creationflags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ},
    )

    # Give it a moment to fail, then check. A browser that is still running a second
    # and a half later is one that opened its profile successfully; the ones that
    # cannot write exit almost immediately.
    try:
        code = process.wait(timeout=settle_s)
    except subprocess.TimeoutExpired:
        return process

    raise RuntimeError(
        f"{config.browser} exited immediately with code {code}; "
        f"it could not use {config.profile_dir}. "
        "Chromium exit code 21 means the profile directory is not writable — "
        "check permissions or sandbox mounts for that path."
    )
