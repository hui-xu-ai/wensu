"""An installed skill that differs from the bundled one must be visible.

Three copies of these skills exist on a working machine (the repository, the agent's
skill directory, and whatever `setup --skills-dir` wrote). Eight of twelve files
disagreed during the 0.12.56 acceptance run, and nothing said so — the same silence
that let the browser extension sit three versions behind. A stale skill is not an
error (the user may have edited it on purpose), but it has to be reportable.
"""

from __future__ import annotations

import json
from pathlib import Path

from scholar_search import assets, browser_setup


def _source_assets(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "native-host").mkdir(exist_ok=True)
    (root / "native-host" / "install.ps1").write_text("host", encoding="utf-8")
    (root / "extension").mkdir(exist_ok=True)
    (root / "extension" / "manifest.json").write_text(
        json.dumps({"version": "0.12.56"}), encoding="utf-8"
    )
    (root / "schemas").mkdir(exist_ok=True)
    (root / "schemas" / "record.json").write_text("{}", encoding="utf-8")
    return root


def _bundled_skills(root: Path) -> Path:
    for name in ("scholar-search", "scholar-detail"):
        directory = root / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "SKILL.md").write_text(f"bundled {name}", encoding="utf-8")
    return root


def test_a_stale_skill_is_reported_and_not_replaced(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(assets, "assets_root", lambda: _source_assets(tmp_path / "source"))
    monkeypatch.setattr(assets, "skills_root", lambda: _bundled_skills(tmp_path / "bundled"))

    skills_dir = tmp_path / "skills"
    edited = skills_dir / "scholar-search"
    edited.mkdir(parents=True)
    (edited / "SKILL.md").write_text("my edits", encoding="utf-8")

    code = browser_setup.setup_browser(
        tmp_path / "target", skills_dir=skills_dir, register_host=False
    )

    assert code == 0
    # The edit survives...
    assert (edited / "SKILL.md").read_text(encoding="utf-8") == "my edits"
    # ...the missing one is installed...
    assert (skills_dir / "scholar-detail" / "SKILL.md").is_file()
    # ...and the difference is stated rather than hidden.
    output = capsys.readouterr()
    message = output.out + output.err
    assert "scholar-search" in message, message
    assert "differ" in message, message


def test_nothing_is_reported_when_every_skill_matches(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(assets, "assets_root", lambda: _source_assets(tmp_path / "source"))
    monkeypatch.setattr(assets, "skills_root", lambda: _bundled_skills(tmp_path / "bundled"))
    skills_dir = tmp_path / "skills"
    browser_setup.setup_browser(tmp_path / "target", skills_dir=skills_dir, register_host=False)
    capsys.readouterr()  # first run installed them

    browser_setup.setup_browser(tmp_path / "target", skills_dir=skills_dir, register_host=False)

    message = capsys.readouterr().err
    assert "differ" not in message, message
