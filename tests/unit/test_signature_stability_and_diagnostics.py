"""Three defects from the 0.12.48 acceptance, each with the test its report asked for.

1. CNKI appends `&t=<epoch ms>` to its navigation URL. The plan signature hashed it, so
   **every CNKI call was a new cache identity**: identical requests a second apart each
   paid 3 quota for the same page. The report asked for a *cross-time* invariance test —
   one that builds the plan twice with real time passing between, since two builds in
   the same millisecond can coincide by luck and hide the bug.

2. `capture_state` is a **method** on the channel; the service read `.selector` off it
   without calling it, so a capture timeout raised
   `AttributeError: 'function' object has no attribute 'selector'` while the real
   `ActionError` was being constructed — losing the timeout, the stage and the quota.
   The report asked for an integration test through the real service failure path.

3. `_cache_can_answer` refused a legitimately short last page: 128 records over three
   pages of 50 leaves 28 on page 3, and a request for 50 there can never be met.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from scholar_search.channels.cnki.v2026_10 import get_channel as cnki_channel
from scholar_search.channels.webofscience.v2026_11 import get_channel as wos_channel
from scholar_search.core.contracts import SearchPage, SearchQuery
from scholar_search.core.service import _cache_can_answer, _site_signature


def _signature(channel, **kwargs):  # type: ignore[no-untyped-def]
    kwargs.setdefault("channel", str(channel.manifest.channel))
    return _site_signature(channel, SearchQuery(**kwargs))  # type: ignore[arg-type]


# -- 1. the navigation nonce -----------------------------------------------


def test_cnki_identical_requests_agree_across_real_time() -> None:
    """The bug that made every CNKI call a cache miss.

    Deliberately sleeps between the two builds. Building twice in the same millisecond
    can produce the same `t=<ms>` by coincidence, which would let this pass while the
    cache stayed broken — the report called that out, and it is the difference between
    a test that checks the behaviour and one that checks the timing.
    """

    channel = cnki_channel()
    first = _signature(channel, text="离子 柔性 驱动器", limit=1)
    time.sleep(0.05)
    second = _signature(channel, text="离子 柔性 驱动器", limit=1)
    assert first == second


def test_the_nonce_is_what_was_volatile() -> None:
    """Guard the premise: the URL really does carry a per-call parameter.

    If CNKI ever stops appending it, this test says so rather than leaving a
    declaration behind that no longer describes anything.
    """

    channel = cnki_channel()
    plan_a = channel.plan_search(SearchQuery(text="x", channel="cnki"))
    time.sleep(0.02)
    plan_b = channel.plan_search(SearchQuery(text="x", channel="cnki"))
    urls_a = [a.params.get("url") for a in plan_a.actions if a.verb == "goto"]
    urls_b = [a.params.get("url") for a in plan_b.actions if a.verb == "goto"]
    assert urls_a != urls_b, "the nonce is gone; the declaration can go too"
    assert channel.volatile_url_params == frozenset({"t"})


def test_the_nonce_does_not_hide_a_real_difference() -> None:
    """Stripping the nonce must not strip the query.

    `limit` above 20 changes CNKI's plan, and that difference has to survive.
    """

    channel = cnki_channel()
    assert _signature(channel, text="x", limit=1) != _signature(channel, text="x", limit=50)


# -- 2. the diagnostic hook -------------------------------------------------


def test_capture_state_is_a_method_that_must_be_called() -> None:
    """The exact mistake: the bound method has no `.selector`."""

    channel = wos_channel()
    factory = channel.capture_state
    assert callable(factory)
    assert not hasattr(factory, "selector"), "if this ever gains an attribute, the bug is back"

    descriptor = factory()
    assert descriptor.selector == "#wensu-wos-capture"
    assert callable(descriptor.describe)


def _script_failing_the_capture_wait(channel, query, *, probe: dict[str, object]):
    """A fixture script that replays the channel's real plan and fails at the capture wait.

    Derived from the plan rather than written out by hand: the plan's action order is
    the thing under test, so a hand-written script silently stops exercising the same
    path the moment a channel adds an action.
    """

    script: list[dict[str, object]] = []
    for action in channel.plan_search(query).actions:
        params = action.params or {}
        if action.verb == "read_text":
            script.append({"verb": "read_text", "data": {"text": ""}, **probe})
        elif action.verb == "wait_for" and "wensu-wos-capture" in str(params.get("selector", "")):
            script.append({"verb": "wait_for", "data": {}, "ok": False, "error": "timeout"})
        else:
            script.append({"verb": action.verb, "data": {}})
    return script


def test_a_capture_timeout_keeps_its_error_and_gains_diagnostics(tmp_path: Path) -> None:
    """The integration path the report asked for: real channel, real service, real failure.

    The script fails the capture wait, then answers the diagnostic probe. Before the
    fix this raised `AttributeError` and the caller lost the timeout, the stage and the
    quota charge entirely.
    """

    from test_service_limit import build

    channel = wos_channel()
    query = SearchQuery(text="TS=(x)", channel="webofscience", limit=1)
    capture = '{"id":0,"key":"searchInfo","payload":{"RecordsFound":115}}'
    script = _script_failing_the_capture_wait(channel, query, probe={"data": {"text": capture}})
    service = build(tmp_path, channel, [script])

    with pytest.raises(Exception) as caught:
        service.search(query)

    error = caught.value
    assert type(error).__name__ == "ActionError", "the diagnostic must not replace the failure"
    assert getattr(error, "stage", None) == "wait.capture"
    diagnostics = getattr(error, "diagnostics", None)
    assert isinstance(diagnostics, dict), "the probe should have described the capture"
    assert diagnostics["verdict"] == "metadata_only"
    assert diagnostics["declared_records"] == 115


def test_a_broken_diagnostic_does_not_take_the_error_with_it(tmp_path: Path) -> None:
    """If the probe itself fails, the original failure must still arrive intact."""

    from test_service_limit import build

    channel = wos_channel()
    query = SearchQuery(text="TS=(x)", channel="webofscience", limit=1)
    script = _script_failing_the_capture_wait(
        channel, query, probe={"data": {}, "ok": False, "error": "not_found"}
    )
    service = build(tmp_path, channel, [script])

    with pytest.raises(Exception) as caught:
        service.search(query)

    assert type(caught.value).__name__ == "ActionError"
    assert getattr(caught.value, "stage", None) == "wait.capture"


# -- 3. a legitimately short last page -------------------------------------


def _page(records: int, *, total: int | None, page: int | None, page_count: int | None):
    from support import make_record

    return SearchPage(
        records=tuple(make_record(f"P{i}") for i in range(records)),
        total=total,
        page=page,
        page_count=page_count,
    )


def test_a_short_last_page_is_not_a_short_capture() -> None:
    """128 records, three pages, 28 on the last one. Asking for 50 cannot be met."""

    cached = _page(28, total=128, page=3, page_count=3)
    assert _cache_can_answer(cached, SearchQuery(text="x", channel="cnki", limit=50))


def test_a_short_middle_page_still_counts_as_incomplete() -> None:
    """Page 1 of 3 holding 28 of 128 is a truncation, not a last page."""

    cached = _page(28, total=128, page=1, page_count=3)
    assert not _cache_can_answer(cached, SearchQuery(text="x", channel="cnki", limit=50))
