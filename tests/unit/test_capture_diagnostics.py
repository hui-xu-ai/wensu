"""A capture timeout must say what the page held, not just that time ran out.

`wait_for failed: timeout (stage wait.capture)` appeared in four acceptance runs. Each
time the only fact available was that it had timed out, and three very different
failures produce that identical symptom:

* the data stream never started;
* it started and never finished;
* the records arrived and the readiness flag was never raised.

Each needs a different fix, so the page is asked which one it was. The probe is a
`read_text` on the capture node — not a network verb, so it costs nothing and cannot
start new traffic.
"""

from __future__ import annotations

import pytest

from scholar_search.channels.webofscience.v2026_11 import get_channel
from scholar_search.core.errors import ActionError
from scholar_search.server import _payload


@pytest.fixture(scope="module")
def hook():  # type: ignore[no-untyped-def]
    return get_channel().capture_state()


def test_the_probe_reads_the_capture_node(hook) -> None:  # type: ignore[no-untyped-def]
    assert hook.selector == "#wensu-wos-capture"


def test_nothing_captured_is_distinguishable_from_metadata_only(hook) -> None:  # type: ignore[no-untyped-def]
    empty = hook.describe("")
    metadata = hook.describe('{"id":0,"key":"searchInfo","payload":{"RecordsFound":115}}')

    assert empty["verdict"] == "no_stream"
    assert metadata["verdict"] == "metadata_only"
    # The site told us it would send 115 — so waiting is still right, and this is not
    # "the topic has no papers".
    assert metadata["declared_records"] == 115


def test_records_that_arrived_without_a_ready_flag_are_named_as_such(hook) -> None:  # type: ignore[no-untyped-def]
    """The failure mode that made 0.12.40's readiness rule a deadlock."""

    payload = (
        '{"id":0,"key":"searchInfo","payload":{"RecordsFound":2}}\n'
        '{"id":1,"key":"records","payload":[{},{}]}'
    )
    described = hook.describe(payload)
    assert described["verdict"] == "records_present_not_ready"
    assert described["has_records_block"] is True


def test_a_stream_that_started_but_carried_nothing_is_named(hook) -> None:  # type: ignore[no-untyped-def]
    described = hook.describe('{"id":0,"key":"somethingElse","payload":{}}')
    assert described["verdict"] == "stream_started_no_records"


def test_the_diagnostic_never_contains_page_content(hook) -> None:  # type: ignore[no-untyped-def]
    """Counts and verdicts only — the payload is not echoed back."""

    described = hook.describe('{"id":0,"key":"records","payload":[{"title":"SECRET"}]}')
    assert "SECRET" not in str(described)


def test_the_payload_carries_diagnostics_beside_stage() -> None:
    error = ActionError(
        "wait_for failed: timeout (step 4/4, stage wait.capture)",
        verb="wait_for",
        code="timeout",
        stage="wait.capture",
        diagnostics={"verdict": "no_stream", "bytes": 0},
    )
    payload = _payload(error)
    assert payload["stage"] == "wait.capture"
    assert payload["diagnostics"] == {"verdict": "no_stream", "bytes": 0}


def test_no_diagnostics_means_no_field() -> None:
    """An absent field beats a confident guess — the 0.12.47 lesson."""

    error = ActionError("boom", verb="goto", code="action.failed", stage="navigate.open")
    assert "diagnostics" not in _payload(error)


def test_a_channel_without_the_hook_produces_nothing() -> None:
    """CNKI has no capture stream; asking it must not fabricate a verdict."""

    from scholar_search.channels.cnki.v2026_10 import get_channel as cnki

    assert not hasattr(cnki(), "capture_state")
