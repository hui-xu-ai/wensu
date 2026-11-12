"""A reset has to reach processes that are already running.

The MCP server is long-lived: it holds its own `RiskGuard`, and a cooldown it tripped stays
in that object's memory even after another process (`wensu reset --confirm`) lifts it. The
guard's own error message tells the user to do exactly that, so following the instruction
used to leave the service locked for the full 24 hours with no explanation — the user saw
`signal: cooldown` and a deadline they had already cleared.

These tests pin the contract: a clear is visible to every guard, and a later trip is not
undone by an older clear.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scholar_search.core.errors import RiskBlocked
from scholar_search.core.risk import RiskGuard, RiskSignal


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture()
def state(tmp_path: Path) -> Path:
    return tmp_path / "cooldown.json"


def _guards(state: Path, clock: Clock) -> tuple[RiskGuard, RiskGuard]:
    """Two guards over one state file: the long-lived server and a one-shot CLI."""

    return (
        RiskGuard(state_path=state, now=clock, cooldown_hours=24),
        RiskGuard(state_path=state, now=clock, cooldown_hours=24),
    )


def test_a_running_guard_honours_a_reset_from_another_process(state: Path) -> None:
    clock = Clock()
    server, cli = _guards(state, clock)

    server.trip(RiskSignal.VERIFY_REDIRECT, "verify_redirect after goto at kns.cnki.net")
    clock.advance(60)
    assert server.cooldown_until() is not None

    cli.clear()  # what `wensu reset --confirm` does
    clock.advance(1)

    assert server.cooldown_until() is None, "the long-lived guard must see the clear"
    server.ensure_ready()  # must not raise


def test_a_later_trip_is_not_undone_by_an_earlier_clear(state: Path) -> None:
    clock = Clock()
    server, cli = _guards(state, clock)

    cli.clear()
    clock.advance(60)
    server.trip(RiskSignal.CAPTCHA, "captcha visible")

    assert server.cooldown_until() is not None
    with pytest.raises(RiskBlocked):
        server.ensure_ready()


def test_a_guard_that_never_tripped_sees_a_clear_normally(state: Path) -> None:
    clock = Clock()
    server, cli = _guards(state, clock)

    server.trip(RiskSignal.RATE_LIMITED, "429")
    clock.advance(5)
    fresh = RiskGuard(state_path=state, now=clock, cooldown_hours=24)
    assert fresh.cooldown_until() is not None

    cli.clear()
    assert fresh.cooldown_until() is None


def test_a_state_file_written_before_this_change_still_blocks(state: Path) -> None:
    clock = Clock()
    until = clock.now + timedelta(hours=12)
    state.write_text(
        json.dumps({"signal": "verify_redirect", "reason": "old", "until": until.isoformat()}),
        encoding="utf-8",
    )
    guard = RiskGuard(state_path=state, now=clock, cooldown_hours=24)
    assert guard.cooldown_until() == until


def test_an_expired_cooldown_does_not_block(state: Path) -> None:
    clock = Clock()
    guard = RiskGuard(state_path=state, now=clock, cooldown_hours=1)
    guard.trip(RiskSignal.CAPTCHA, "captcha")
    clock.advance(2 * 3600)
    assert guard.cooldown_until() is not None  # still recorded
    guard.ensure_ready()  # but no longer in force
