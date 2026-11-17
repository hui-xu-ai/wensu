"""An upgrade must refresh the copied assets, and must not lie about it.

Installing a new wheel only replaces `site-packages/.../assets`; the browser keeps
loading the *copy* under `<home>/browser/extension` that `setup` made earlier. The
0.12.56 acceptance run found that copy three versions behind while `wensu setup`
printed "done" and exited 0 — `copy_assets` raised `FileExistsError`, the caller
swallowed it, and nothing in the output distinguished "refreshed" from "did nothing".

So: identical trees are skipped (and said so), different trees are refreshed without
needing a flag, and `--force` is split in two because refreshing assets must not
delete hand-edited skills.
"""

from __future__ import annotations

import json
from pathlib import Path

from scholar_search import assets, browser_setup


def _source_tree(root: Path, version: str = "0.12.56") -> Path:
    """A stand-in for the packaged assets: three directories, four files."""

    root.mkdir(parents=True, exist_ok=True)
    (root / "native-host").mkdir()
    (root / "native-host" / "install.ps1").write_text("host v" + version, encoding="utf-8")
    (root / "extension").mkdir()
    (root / "extension" / "background.js").write_text("js v" + version, encoding="utf-8")
    (root / "extension" / "manifest.json").write_text(
        json.dumps({"version": version}), encoding="utf-8"
    )
    (root / "schemas").mkdir()
    (root / "schemas" / "record.json").write_text("{}", encoding="utf-8")
    return root


def _patch_source(monkeypatch, source: Path) -> None:
    monkeypatch.setattr(assets, "assets_root", lambda: source)


def _version_of(directory: Path) -> str:
    return json.loads((directory / "extension" / "manifest.json").read_text(encoding="utf-8"))[
        "version"
    ]


def test_a_first_copy_reports_every_directory(tmp_path: Path, monkeypatch) -> None:
    _patch_source(monkeypatch, _source_tree(tmp_path / "source"))

    copied = assets.copy_assets(tmp_path / "target")

    assert sorted(path.name for path in copied) == ["extension", "native-host", "schemas"]
    assert _version_of(tmp_path / "target") == "0.12.56"


def test_an_identical_tree_is_skipped_without_an_error(tmp_path: Path, monkeypatch) -> None:
    _patch_source(monkeypatch, _source_tree(tmp_path / "source"))
    target = tmp_path / "target"
    assets.copy_assets(target)

    assert assets.copy_assets(target) == []


def test_a_stale_copy_is_refreshed_without_being_asked(tmp_path: Path, monkeypatch) -> None:
    """The upgrade path: no flag, and the copy still ends up current."""

    target = tmp_path / "target"
    _patch_source(monkeypatch, _source_tree(tmp_path / "source", version="0.12.53"))
    assets.copy_assets(target)
    assert _version_of(target) == "0.12.53"

    _patch_source(monkeypatch, _source_tree(tmp_path / "newer", version="0.12.56"))
    refreshed = assets.copy_assets(target)

    # Only what actually changed: the fake schemas/record.json is version-blind, so it
    # is skipped rather than rewritten for nothing.
    assert [path.name for path in refreshed] == ["native-host", "extension"]
    assert _version_of(target) == "0.12.56"


def test_force_replaces_an_identical_tree_as_well(tmp_path: Path, monkeypatch) -> None:
    _patch_source(monkeypatch, _source_tree(tmp_path / "source"))
    target = tmp_path / "target"
    assets.copy_assets(target)

    assert len(assets.copy_assets(target, force=True)) == 3


def test_refreshing_assets_leaves_edited_skills_alone(tmp_path: Path, monkeypatch) -> None:
    """One flag used to do both, so upgrading the extension deleted your edits."""

    _patch_source(monkeypatch, _source_tree(tmp_path / "source", version="0.12.53"))
    skills_dir = tmp_path / "skills"
    skill = skills_dir / "scholar-search"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("my edits", encoding="utf-8")

    _patch_source(monkeypatch, _source_tree(tmp_path / "newer", version="0.12.56"))
    target = tmp_path / "target"
    code = browser_setup.setup_browser(
        target, skills_dir=skills_dir, register_host=False, force_assets=False
    )

    assert code == 0
    assert _version_of(target) == "0.12.56"
    assert (skill / "SKILL.md").read_text(encoding="utf-8") == "my edits"


def test_machine_local_host_files_stay_out_of_the_copy(tmp_path: Path, monkeypatch) -> None:
    """`install.ps1` writes these per machine, and the repository ignores them.

    Copying a checkout's `python-path.txt` into a runtime directory ships one
    machine's paths to another: the acceptance run found
    `browser/native-host/python-path.txt` pointing at the developer's `.venv`.
    """

    source = _source_tree(tmp_path / "source")
    (source / "native-host" / "python-path.txt").write_text(
        r"D:\dev\.venv\Scripts\python.exe", encoding="utf-8"
    )
    (source / "native-host" / "scholar-host.exe").write_text("exe", encoding="utf-8")
    _patch_source(monkeypatch, source)
    target = tmp_path / "target"

    assets.copy_assets(target)

    assert (target / "native-host" / "install.ps1").is_file()
    assert not (target / "native-host" / "python-path.txt").exists()
    assert not (target / "native-host" / "scholar-host.exe").exists()
