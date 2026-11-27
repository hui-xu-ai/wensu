"""A capture that never came back (ADR 0031, `capture_unconfirmed`).

The last uncovered branch had no sample: 200 ms of capture budget still finished, because a warm
page is fast. The branch is reached here the only honest way — a fixture whose capture never
answers — so the *shape of the answer* is pinned even when no live browser cooperates.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_page_read import build_service

URL = "https://www.sciencedirect.com/science/article/pii/S1385894723029534"


def test_a_capture_that_times_out_says_capture_not_navigation(tmp_path: Path) -> None:
    """0.14.60 fixed `status: timeout` being reported as `navigate`; this pins the answer shape."""

    service = build_service(
        tmp_path,
        [
            [
                {"verb": "goto", "data": {"url": URL, "title": "The article"}},
                {"verb": "sleep", "data": {"ms": 1200}},
                {
                    "verb": "snapshot",
                    "ok": False,
                    "error": "bridge.timeout",
                    "data": {"operation_id": "op-snapshot-1", "operation_issued": True},
                },
            ],
        ],
    )
    service._readiness_build = lambda: {"features": {}}  # type: ignore[method-assign]

    answer = service.read_page(url=URL)

    assert answer["status"] == "no_page", answer
    assert answer["reason"] == "capture_unconfirmed", answer
    assert answer["stage"] == "capture", answer
    assert answer["terminal"] == "timeout", answer
    assert answer["mhtml_path"] is None, answer
    assert answer["operation_id"] == "op-snapshot-1", answer
    assert answer["capture_issued"] is True, answer
    assert answer["quota_charged"] == 1, "the navigation happened and is billed; a capture is free"
    assert "navigation_status" in str(answer["next"]), answer


def test_the_answer_tells_the_caller_not_to_capture_again(tmp_path: Path) -> None:
    """A second capture would overlap the first one, which may still be running."""

    service = build_service(
        tmp_path,
        [
            [
                {"verb": "goto", "data": {"url": URL, "title": "The article"}},
                {"verb": "sleep", "data": {"ms": 1200}},
                {
                    "verb": "snapshot",
                    "ok": False,
                    "error": "bridge.timeout",
                    "data": {"operation_id": "op-snapshot-2"},
                },
            ],
        ],
    )
    service._readiness_build = lambda: {"features": {}}  # type: ignore[method-assign]

    answer = service.read_page(url=URL)

    assert answer["capture_issued"] is None, "unknown is not 'it never left'"
    assert "instead of capturing again" in str(answer["next"]).replace("\n", " ")
