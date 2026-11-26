"""Quota and cooldown belong to the browser, not to a home (ADR 0029, second slice).

Two `SCHOLAR_SEARCH_HOME` directories driving one browser used to keep two quota files and two
cooldowns: "300 a day" and a 24-hour cooldown were per-directory fictions, and a second home was a
free bypass. The files now live beside the browser lock, and the old per-home file is copied once —
read, written, never deleted — so a rollback still finds its own numbers.
"""

from __future__ import annotations

from pathlib import Path

from scholar_search.core.config import adopt_legacy_state
from scholar_search.core.contracts import RiskSignal
from scholar_search.core.policy import PolicyEngine
from scholar_search.core.risk import RiskGuard


def _quota(tmp_path: Path, name: str) -> PolicyEngine:
    return PolicyEngine(
        clock=lambda: 1000.0,
        sleeper=lambda seconds: None,
        state_path=tmp_path / name,
    )


def test_two_homes_share_one_allowance(tmp_path: Path) -> None:
    """Spending in one home is visible in the other: one browser, one day's allowance."""

    shared = tmp_path / "browser-state" / "state" / "quota.json"
    first = _quota(tmp_path, shared.relative_to(tmp_path).as_posix())
    second = _quota(tmp_path, shared.relative_to(tmp_path).as_posix())

    before = first.remaining_today
    first.wait_turn()
    after_second = second.remaining_today

    assert before is not None and after_second is not None
    assert after_second < before, (before, after_second)


def test_both_homes_see_the_same_cooldown(tmp_path: Path) -> None:
    shared = tmp_path / "browser-state" / "state" / "cooldown.json"
    first = RiskGuard(state_path=shared)
    second = RiskGuard(state_path=shared)

    first.trip(RiskSignal.HTTP_403, "refused")

    assert second.cooldown_until() is not None


def test_a_legacy_home_file_is_copied_once_and_never_deleted(tmp_path: Path) -> None:
    legacy = tmp_path / "home" / "state" / "quota.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"day": "2026-11-26", "used": 7}', encoding="utf-8")
    target = tmp_path / "browser-state" / "state" / "quota.json"

    assert adopt_legacy_state(legacy, target) is True
    assert target.read_text(encoding="utf-8") == legacy.read_text(encoding="utf-8")
    assert legacy.is_file(), "migration must not delete the file an older build still reads"

    # Second run: the shared file wins, the old one is not read again.
    legacy.write_text('{"day": "2026-11-26", "used": 99}', encoding="utf-8")
    assert adopt_legacy_state(legacy, target) is False
    assert '"used": 7' in target.read_text(encoding="utf-8").replace(" ", " ")


def test_migration_is_a_no_op_when_there_is_nothing_to_copy(tmp_path: Path) -> None:
    assert adopt_legacy_state(tmp_path / "missing.json", tmp_path / "target.json") is False
    assert not (tmp_path / "target.json").exists()
