"""The daily counter and the per-call charges disagreed by one unit and nothing could say why.

`state/quota.json` keeps one number per day — `{"day": …, "used": N, "last": …}` — so the 2026-11-25
acceptance ledger (P7) could not reconcile `quota_remaining` against the `quota_charged` values it
had collected, and one investigation went looking for a bug in the billing that was not there. The
audit trail does not help: it records *actions*, and several actions belong to one call.

Every debit now leaves one line in `state/quota-ledger-<day>.jsonl`: when, what for (channel and
verb), how much, and the counter afterwards. Nothing about the page — the privacy rules allow
actions and amounts, not content. One file per day, which bounds it at the daily cap (300 lines).

The counter stays the authority: a ledger that cannot be written must never stop a charge.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from scholar_search.core.policy import PolicyEngine

# What one line is allowed to carry. Anything else is either page content or an invitation to
# put some there later.
_ALLOWED_KEYS = {"ts", "day", "op", "amount", "used", "channel", "verb"}


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _engine(tmp_path: Path) -> PolicyEngine:
    clock = _Clock()
    return PolicyEngine(
        clock=clock.time,
        sleeper=clock.sleep,
        jitter=lambda: 0.0,
        state_path=tmp_path / "quota.json",
    )


def _lines(tmp_path: Path) -> list[dict[str, object]]:
    files = sorted(tmp_path.glob("quota-ledger-*.jsonl"))
    assert len(files) == 1, [path.name for path in files]
    text = files[0].read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def test_every_charge_leaves_one_line(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    engine.wait_turn(channel="webofscience", verb="click")
    engine.wait_turn(channel="webofscience", verb="type")

    lines = _lines(tmp_path)
    assert [line["amount"] for line in lines] == [1, 1]
    assert [line["used"] for line in lines] == [1, 2]
    assert [line["verb"] for line in lines] == ["click", "type"]
    assert [line["channel"] for line in lines] == ["webofscience", "webofscience"]
    assert all(line["op"] == "charge" for line in lines)
    assert engine.used_today == 2


def test_a_line_carries_nothing_about_the_page(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    engine.wait_turn(channel="webofscience", verb="goto")

    (line,) = _lines(tmp_path)
    assert set(line) == _ALLOWED_KEYS, sorted(set(line))


def test_a_refund_is_recorded_too(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    engine.wait_turn(channel="cnki", verb="goto")
    assert engine.refund(1) is True

    lines = _lines(tmp_path)
    assert [line["op"] for line in lines] == ["charge", "refund"]
    assert [line["amount"] for line in lines] == [1, -1]
    assert lines[-1]["used"] == 0


def test_a_ledger_that_cannot_be_written_does_not_stop_the_charge(
    tmp_path: Path, monkeypatch
) -> None:
    """The counter is the authority; the trail is a convenience."""

    engine = _engine(tmp_path)
    monkeypatch.setattr(
        PolicyEngine, "_ledger_path", lambda self, day: tmp_path / "missing" / "ledger.jsonl"
    )

    engine.wait_turn(channel="cnki", verb="goto")

    assert engine.used_today == 1


def test_the_file_is_named_for_the_day(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    engine.wait_turn(channel="cnki", verb="goto")

    (path,) = tmp_path.glob("quota-ledger-*.jsonl")
    assert path.name == f"quota-ledger-{date.today().isoformat()}.jsonl"


def test_the_planner_writes_what_the_slot_was_for(tmp_path: Path) -> None:
    """End to end: the entry names the channel and the verb that took the slot."""

    from test_service import build_service

    from scholar_search.core.contracts import SearchQuery
    from support import FakeChannel, make_manifest, make_record

    channel = FakeChannel(manifest=make_manifest(), records=[make_record("Paper A")])
    service = build_service(
        tmp_path,
        channel,
        [[{"verb": "goto", "data": {}}, {"verb": "read_html", "data": {"html": "<html>x</html>"}}]],
    )

    service.search(SearchQuery(text="x", channel="fake"))

    lines = _lines(tmp_path)
    # `read_html` is not a network verb: one action, one reservation, one line.
    assert [(line["channel"], line["verb"]) for line in lines] == [("fake", "goto")]
