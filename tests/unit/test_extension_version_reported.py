"""`status` must report which extension copy the browser is loading.

A stale copy is otherwise invisible: the package answers `version: 0.12.56` while the
browser runs whatever sits in `<home>/browser/extension`. The acceptance run found
0.12.53 there, saw the mismatch only by opening the file, and had no field to quote.
Copying the assets is a separate step from installing the wheel, so this state is a
normal outcome of an upgrade that skipped `wensu setup --force`.
"""

from __future__ import annotations

import json
from pathlib import Path

from scholar_search import __version__
from scholar_search.bootstrap import _browser_summary, _extension_version
from scholar_search.core.browser import BrowserConfig


def _extension(tmp_path: Path, version: str | None) -> Path:
    directory = tmp_path / "extension"
    directory.mkdir()
    manifest = {} if version is None else {"version": version}
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return directory


def test_the_version_is_read_from_the_copy_the_browser_loads(tmp_path: Path) -> None:
    directory = _extension(tmp_path, "0.12.53")

    assert _extension_version(directory) == "0.12.53"


def test_a_missing_manifest_is_not_an_error(tmp_path: Path) -> None:
    """Before `setup` has ever run there is no manifest; status must still answer."""

    assert _extension_version(tmp_path / "extension") is None


def test_a_manifest_without_a_version_is_not_a_version(tmp_path: Path) -> None:
    assert _extension_version(_extension(tmp_path, None)) is None


def test_the_summary_names_the_mismatch(tmp_path: Path, monkeypatch) -> None:
    directory = _extension(tmp_path, "0.12.53")
    recorded = BrowserConfig(
        browser="edge",
        executable="msedge.exe",
        profile_dir=str(tmp_path / "profile"),
        extension_dir=str(directory),
    )
    monkeypatch.setattr("scholar_search.core.browser.load", lambda: recorded)

    summary = _browser_summary()

    assert summary is not None
    assert summary["extension_version"] == "0.12.53"
    # The package is this build; 0.12.53 is not.
    assert summary["extension_version_mismatch"] is True


def test_a_matching_copy_is_stated_as_matching(tmp_path: Path, monkeypatch) -> None:
    directory = _extension(tmp_path, __version__)
    recorded = BrowserConfig(
        browser="edge",
        executable="msedge.exe",
        profile_dir=str(tmp_path / "profile"),
        extension_dir=str(directory),
    )
    monkeypatch.setattr("scholar_search.core.browser.load", lambda: recorded)

    summary = _browser_summary()

    assert summary is not None
    assert summary["extension_version_mismatch"] is False


def test_an_unreadable_copy_reports_unknown_rather_than_a_verdict(
    tmp_path: Path, monkeypatch
) -> None:
    """`None` means "cannot tell". False would claim the copy is current."""

    recorded = BrowserConfig(
        browser="edge",
        executable="msedge.exe",
        profile_dir=str(tmp_path / "profile"),
        extension_dir=str(tmp_path / "not-installed"),
    )
    monkeypatch.setattr("scholar_search.core.browser.load", lambda: recorded)

    summary = _browser_summary()

    assert summary is not None
    assert summary["extension_version"] is None
    assert summary["extension_version_mismatch"] is None


def test_brief_carries_the_mismatch_too(tmp_path: Path, monkeypatch) -> None:
    """The cheapest health check has to answer "is the copy I updated the one running".

    2026-11-24: a machine answered `version: 0.13.2` while the market bundle and the
    extension were both 0.14.2. `brief` is the payload a planning caller reads, and it
    said nothing about the extension, so the skew stayed invisible for a whole session.
    """

    from scholar_search.adapters.bridge import BridgeAdapter
    from scholar_search.bootstrap import build_service

    directory = _extension(tmp_path, "0.12.53")
    recorded = BrowserConfig(
        browser="edge",
        executable="msedge.exe",
        profile_dir=str(tmp_path / "profile"),
        extension_dir=str(directory),
    )
    monkeypatch.setattr("scholar_search.core.browser.load", lambda: recorded)
    monkeypatch.setattr(BridgeAdapter, "probe", classmethod(lambda cls: True))

    brief = build_service().status(brief=True)

    assert brief["extension_version"] == "0.12.53"
    assert brief["extension_version_mismatch"] is True
