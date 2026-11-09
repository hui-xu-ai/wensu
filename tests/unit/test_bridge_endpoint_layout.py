"""Discovery must survive the endpoint layout the host actually writes.

A review of the first ambiguity check (report 3, item 1) found it counted *files*, and
one host writes two of them:

    host/bridge.json                  the legacy alias
    host/hosts/bridge-<pid>.json      the registry entry

So a perfectly normal single-browser setup looked like two hosts with the same
profile, and the check refused to connect at all — a regression worse than the problem
it was meant to catch.

These tests use the real writer from `native-host/main.py` rather than hand-built
files, so the layout cannot drift away from what discovery expects.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from scholar_search.adapters.bridge import BridgeAdapter


def _load_host_module() -> object:
    """The native host's own module, so the endpoint writer is the real one."""

    path = Path(__file__).resolve().parents[2] / "native-host" / "main.py"
    spec = importlib.util.spec_from_file_location("wensu_native_host_main", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "host"
    (root / "hosts").mkdir(parents=True)
    monkeypatch.setattr("scholar_search.adapters.bridge.host_runtime_dir", lambda: root)
    monkeypatch.setattr("scholar_search.core.config.host_runtime_dir", lambda: root)
    return root


def test_one_host_writing_two_files_is_one_candidate(
    runtime: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression: the real writer produces two files for one process.

    Discovery has to see one host, or every normal setup hits the ambiguity branch.
    """

    host = _load_host_module()
    monkeypatch.setattr(host, "_profile_dir", lambda: r"E:\ProfileA")
    host.write_endpoint(port=5555, token="t")

    written = sorted(path.name for path in (runtime / "hosts").glob("*.json"))
    assert len(written) == 1
    assert (runtime / "bridge.json").exists(), "the writer also writes the alias"

    monkeypatch.setenv("WENSU_PROFILE", r"E:\ProfileA")
    candidates = BridgeAdapter()._candidates()
    assert len(candidates) == 1, "two files, one host"


def test_two_real_hosts_with_the_same_label_are_still_ambiguous(
    runtime: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deduplication must not go so far that it hides a genuine second host."""

    from scholar_search.core.errors import BridgeAmbiguous

    for pid, port in ((101, 1), (202, 2)):
        payload = {"port": port, "token": "t", "pid": pid, "profile_dir": r"E:\ProfileA"}
        (runtime / "hosts" / f"bridge-{pid}.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("WENSU_PROFILE", r"E:\ProfileA")

    with pytest.raises(BridgeAmbiguous):
        BridgeAdapter()._candidates()


def test_a_host_without_a_readable_pid_is_still_a_candidate(runtime: Path) -> None:
    """A malformed record must not silently remove a host from consideration."""

    good = {"port": 1, "token": "t", "pid": 101}
    (runtime / "hosts" / "bridge-101.json").write_text(json.dumps(good), encoding="utf-8")
    (runtime / "hosts" / "legacy.json").write_text("{not json", encoding="utf-8")

    assert len(BridgeAdapter()._candidates()) == 2
