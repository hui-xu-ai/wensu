"""Untrusted local state is validated, not trusted (audit 2026-11-26, F11 / F12).

The quota file and the HTTP token file are just files on the machine: either can be edited by a
person, truncated by a crash, or produced by an older build. Both used to be read with a
conversion that happened to succeed — `int(-20)`, and `""` respectively — so a negative count
reported *more* quota than the limit and an empty token authenticated every request that forgot
the header.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from scholar_search.core.policy import PolicyEngine
from scholar_search.transports import http as http_transport


def _engine(tmp_path: Path) -> PolicyEngine:
    def clock() -> float:
        return 1000.0  # a fixed clock keeps pacing out of these tests

    return PolicyEngine(
        clock=clock, sleeper=lambda seconds: None, state_path=tmp_path / "quota.json"
    )


def _write(tmp_path: Path, payload: dict[str, object]) -> None:
    (tmp_path / "quota.json").write_text(json.dumps(payload), encoding="utf-8")


def test_a_negative_count_is_corrupt_and_never_reports_extra_quota(tmp_path: Path) -> None:
    from datetime import date

    _write(tmp_path, {"day": date.today().isoformat(), "used": -20})
    engine = _engine(tmp_path)

    assert engine.remaining_today is None, "a corrupt state must not report a number"
    assert engine.state_error == "corrupt"


def test_a_boolean_count_is_not_a_count(tmp_path: Path) -> None:
    from datetime import date

    _write(tmp_path, {"day": date.today().isoformat(), "used": True})

    assert _engine(tmp_path).remaining_today is None


def test_an_impossible_day_is_corrupt(tmp_path: Path) -> None:
    _write(tmp_path, {"day": "2026-02-31", "used": 1})

    assert _engine(tmp_path).remaining_today is None


def test_a_timestamp_from_the_future_is_corrupt(tmp_path: Path) -> None:
    from datetime import date

    _write(tmp_path, {"day": date.today().isoformat(), "used": 1, "last": time.time() + 86_400})

    assert _engine(tmp_path).remaining_today is None


def test_a_healthy_state_is_still_read(tmp_path: Path) -> None:
    from datetime import date

    _write(tmp_path, {"day": date.today().isoformat(), "used": 3, "last": time.time()})

    assert _engine(tmp_path).remaining_today is not None


def test_an_empty_token_file_refuses_to_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SCHOLAR_SEARCH_HOME", str(tmp_path))
    (tmp_path / http_transport.TOKEN_NAME).write_text("", encoding="utf-8")

    with pytest.raises(ValueError):
        http_transport.load_token()


def test_a_short_token_file_refuses_to_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SCHOLAR_SEARCH_HOME", str(tmp_path))
    (tmp_path / http_transport.TOKEN_NAME).write_text("abc", encoding="utf-8")

    with pytest.raises(ValueError):
        http_transport.load_token()


def test_a_missing_token_is_generated_once_and_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SCHOLAR_SEARCH_HOME", str(tmp_path))

    first = http_transport.load_token()
    second = http_transport.load_token()

    assert first == second
    assert len(first) >= http_transport.MIN_TOKEN_CHARS
    assert (tmp_path / http_transport.TOKEN_NAME).read_text(encoding="utf-8") == first
