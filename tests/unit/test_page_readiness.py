"""P2 of ADR 0031: the capture is timed by evidence, and a timing-out budget never decides.

The kernel asks the worker to watch tab metadata (`snapshot(mode=observe)`, zero bytes) and starts
the capture on a `candidate` — or when the observation budget runs out, in which case the capture
happens anyway and the evidence says so. A worker that cannot observe keeps the old fixed settle.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_page_read import build_service, write_mhtml

URL = "https://www.sciencedirect.com/science/article/pii/S1385894723029534"
READY = {"features": {"readiness_observe": 1, "capture_receipts": 1}}
OLD = {"features": {"lease_control": 1, "operation_receipts": 1}}

ARTICLE = """<!DOCTYPE html><html><head>
<meta name="citation_doi" content="10.1016/j.cej.2023.144222">
<title>The article</title></head><body><article>
<h2>1. Introduction</h2>
<p>This paragraph is long enough to be counted as prose, and it mentions the material, the
measurement and the conclusion so that a reader would call it body text.</p>
<p>A second paragraph follows, also long enough to count, describing another measurement and its
outcome in the same register as the first one.</p>
</article></body></html>"""


def _capture(blob: bytes) -> dict[str, object]:
    return {
        "verb": "snapshot",
        "data": {
            "token": "t1",
            "total": len(blob),
            "base64": base64.b64encode(blob).decode("ascii"),
            "url": URL,
            "title": "The article",
            "captcha_visible": False,
        },
    }


def _observe(state: str, *, elapsed: int = 4_000, title: str = "The article") -> dict[str, object]:
    return {
        "verb": "snapshot",
        "data": {
            "mode": "observe",
            "state": state,
            "elapsed_ms": elapsed,
            "page_state": {"status": "complete", "url": URL, "title": title},
        },
    }


def _service(tmp_path: Path, steps: list[dict[str, object]]):
    blob = write_mhtml(tmp_path / "page.mhtml", ARTICLE).read_bytes()
    script = [
        {"verb": "goto", "data": {"url": URL, "title": "The article"}},
        *steps,
        _capture(blob),
    ]
    return build_service(tmp_path, [script])


def test_a_candidate_starts_the_capture_without_a_fixed_sleep(tmp_path: Path) -> None:
    service = _service(tmp_path, [_observe("candidate")])
    service._readiness_build = lambda: READY  # type: ignore[method-assign]

    answer = service.read_page(url=URL)

    assert answer["status"] == "ok", answer
    assert answer["readiness"]["strategy"] == "observe", answer
    assert answer["readiness"]["state"] == "candidate", answer
    assert answer["readiness"]["budget_exhausted"] is False, answer
    assert answer["quota_charged"] == 1, "observation and capture cost nothing"


def test_a_budget_that_runs_out_still_captures(tmp_path: Path) -> None:
    """The invariant I3: no path may report "not ready" and return without a capture attempt."""

    service = _service(
        tmp_path,
        [
            _observe("observing", elapsed=8_000),
            _observe("observing", elapsed=8_000),
            _observe("observing", elapsed=8_000),
            _observe("observing", elapsed=8_000),
        ],
    )
    service._readiness_build = lambda: READY  # type: ignore[method-assign]

    answer = service.read_page(url=URL)

    assert answer["status"] == "ok", answer
    assert answer["readiness"]["state"] == "observing", answer
    assert answer["readiness"]["budget_exhausted"] is True, answer
    assert answer["mhtml_path"], "a capture happened anyway"


def test_a_worker_that_cannot_observe_keeps_the_old_settle(tmp_path: Path) -> None:
    service = _service(tmp_path, [{"verb": "sleep", "data": {"ms": 1200}}])
    service._readiness_build = lambda: OLD  # type: ignore[method-assign]

    answer = service.read_page(url=URL)

    assert answer["status"] == "ok", answer
    assert answer["readiness"]["strategy"] == "settle", answer
    assert answer["readiness"]["state"] == "not_observed", answer


def test_a_risk_state_stops_before_any_capture(tmp_path: Path) -> None:
    """I2/I7: a wall seen in the metadata means zero captures, not one wasted capture."""

    blob = write_mhtml(tmp_path / "page.mhtml", ARTICLE).read_bytes()
    service = build_service(
        tmp_path,
        [
            [
                {"verb": "goto", "data": {"url": URL, "title": "请稍候…"}},
                {
                    "verb": "await_gate_clear",
                    "data": {"cleared": False, "url": URL, "title": "请稍候…"},
                },
                _observe("risk", title="请稍候…"),
                _capture(blob),  # must stay unconsumed
            ]
        ],
    )
    service._readiness_build = lambda: READY  # type: ignore[method-assign]

    answer = service.read_page(url=URL)

    assert answer["status"] == "blocked", answer
    assert answer["terminal"] in {"blocked", "timeout"}, answer
