"""`--load-extension` is only for a profile that does not know the extension yet.

Edge keeps extension records in `Secure Preferences`, so a check that looked at `Preferences`
concluded "not installed" and passed the flag on every launch. Edge then opened an
extensions/settings window beside the work window — the second window users saw on every start
(measured 2026-11-25). These tests pin the decision, not the launch.
"""

from __future__ import annotations

import json
from pathlib import Path

from scholar_search.core.browser import BrowserConfig, extension_installed


def _config(tmp_path: Path, *, extension_dir: Path | None = None) -> BrowserConfig:
    profile = tmp_path / "profile"
    (profile / "Default").mkdir(parents=True)
    return BrowserConfig(
        browser="edge",
        executable=str(tmp_path / "msedge.exe"),
        profile_dir=str(profile),
        extension_dir=str(extension_dir or (tmp_path / "extension")),
    )


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_an_extension_recorded_in_secure_preferences_counts_as_installed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _write(
        Path(config.profile_dir) / "Default" / "Secure Preferences",
        {"extensions": {"settings": {"gmaimbocfj": {"path": config.extension_dir}}}},
    )

    assert extension_installed(config) is True


def test_the_plain_preferences_file_is_also_read(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _write(
        Path(config.profile_dir) / "Default" / "Preferences",
        {"extensions": {"settings": {"gmaimbocfj": {"path": config.extension_dir}}}},
    )

    assert extension_installed(config) is True


def test_a_different_path_does_not_count(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _write(
        Path(config.profile_dir) / "Default" / "Secure Preferences",
        {"extensions": {"settings": {"x": {"path": r"C:\somewhere\else"}}}},
    )

    assert extension_installed(config) is False


def test_a_profile_without_records_or_files_is_not_installed(tmp_path: Path) -> None:
    config = _config(tmp_path)

    assert extension_installed(config) is False


def test_a_broken_preferences_file_is_not_installed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    (Path(config.profile_dir) / "Default" / "Secure Preferences").write_text(
        "{not json", encoding="utf-8"
    )

    assert extension_installed(config) is False
