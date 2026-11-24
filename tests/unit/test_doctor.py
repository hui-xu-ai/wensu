"""`wensu doctor` must name the artefact that disagrees, and never invent a verdict.

The three versions live in three places (this package, a DSH profile's `node_modules`, the
browser's asset copy), so the check is only useful if an unknown one is reported as unknown —
2026-11-24: the answer `mismatch: false` was available all along, but only in the expensive
payload, and a stale CLI sat behind a fresh bundle for a whole session.
"""

from __future__ import annotations

import json
from pathlib import Path

from scholar_search.cli import build_parser
from scholar_search.core.doctor import find_bundle, pandoc_version, verdict


def _profile(home: Path, name: str, version: str | None) -> Path:
    profile = home / "profiles" / name
    manifest = profile / "node_modules" / "@hui-xu-ai" / "dsh-wensu" / "package.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    payload = {"name": "@hui-xu-ai/dsh-wensu"}
    if version is not None:
        payload["version"] = version
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    return profile


def test_the_bundle_version_is_read_from_the_profile(tmp_path: Path) -> None:
    _profile(tmp_path, "desktop", "0.14.3")

    found = find_bundle([tmp_path])

    assert found["version"] == "0.14.3"
    assert found["profile"] == "desktop"


def test_a_profile_without_the_bundle_is_not_a_finding(tmp_path: Path) -> None:
    (tmp_path / "profiles" / "web").mkdir(parents=True)

    assert find_bundle([tmp_path])["version"] is None


def test_three_equal_versions_are_ok() -> None:
    assert verdict(cli="0.14.3", extension="0.14.3", bundle="0.14.3") == "ok"


def test_a_stale_cli_is_a_mismatch_not_a_pass() -> None:
    assert verdict(cli="0.13.2", extension="0.14.3", bundle="0.14.3") == "mismatch"


def test_an_unknown_artefact_is_partial_rather_than_ok() -> None:
    """No DSH profile on this machine is a fact, not a pass."""

    assert verdict(cli="0.14.3", extension="0.14.3", bundle=None) == "partial"


def test_the_cli_offers_doctor() -> None:
    args = build_parser().parse_args(["doctor"])

    assert args.command == "doctor"


def test_pandoc_missing_is_reported_not_installed(monkeypatch) -> None:
    """No pandoc means a hint, never a download: installing a binary is the user's call."""

    monkeypatch.setattr("shutil.which", lambda name: None)

    assert pandoc_version() is None


def test_pandoc_version_is_read_from_the_binary(monkeypatch, tmp_path) -> None:
    fake = tmp_path / "pandoc.exe"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setattr("shutil.which", lambda name: str(fake))

    class Result:
        stdout = "pandoc 3.1.11\nFeatures: +server +lua\n"

    monkeypatch.setattr("subprocess.run", lambda *a, **k: Result())

    assert pandoc_version() == "3.1.11"
