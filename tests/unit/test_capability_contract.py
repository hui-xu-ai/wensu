"""The extension's advertised capabilities must cover what the kernel plans (F33-01).

The capability gate reads the running worker's own list. `await_gate_clear` was implemented in
the worker but never advertised, so every read that hit a gate was refused before any action ran
— and the unit tests could not see it, because the fixture adapter answers no `info()` at all.
This test reads the lists out of the shipped worker file and compares them with the plans the
kernel actually builds.
"""

from __future__ import annotations

import re
from pathlib import Path

from scholar_search.core.contracts import VERBS
from scholar_search.core.publishers import publisher_for_doi
from scholar_search.core.service import ScholarService, _page_spec

ROOT = Path(__file__).resolve().parents[2]


def _worker_lists() -> tuple[set[str], set[str]]:
    worker = next(ROOT.glob("extension/background-*.js"))
    text = worker.read_text(encoding="utf-8")

    def listed(name: str) -> set[str]:
        block = re.search(rf"const {name} = \[(.*?)\];", text, re.DOTALL)
        assert block is not None, name
        return {item for item in re.findall(r'"([a-z_]+)"', block.group(1))}

    return listed("CAPABILITIES"), listed("CHANNEL_CAPABILITIES")


def test_the_worker_advertises_the_gate_wait() -> None:
    universal, _channel = _worker_lists()

    assert "await_gate_clear" in universal, sorted(universal)


def test_every_verb_a_publisher_plan_uses_is_advertised() -> None:
    universal, _channel = _worker_lists()
    publisher = publisher_for_doi("10.1021/jacs.6c13448")
    assert publisher is not None
    spec = _page_spec(publisher)

    planned = set(ScholarService._page_goto_params("https://pubs.acs.org/doi/10.1021/jacs.6c13448"))
    planned |= {"snapshot", "sleep", "await_gate_clear"}  # the read's own steps
    planned -= {"halt_titles", "halt_url_markers", "url"}  # parameters, not verbs

    assert planned <= universal, sorted(planned - universal)
    assert planned <= set(spec.manifest.verbs), sorted(planned - set(spec.manifest.verbs))


def test_every_planned_verb_is_a_known_verb() -> None:
    """A plan cannot use a verb the kernel's own vocabulary rejects."""

    assert {"goto", "snapshot", "sleep", "await_gate_clear"} <= VERBS


def test_the_worker_reports_the_tab_and_the_navigation() -> None:
    """ADR 0030, first slice: the reply names the tab and the navigation that produced it.

    Reported only — the identity checks still decide — but a caller can now say "this capture came
    from that navigation" instead of inferring it from the address afterwards.
    """

    worker = next(ROOT.glob("extension/background-*.js"))
    text = worker.read_text(encoding="utf-8")

    assert "tab_id: tab.id" in text
    assert "navigation_id: navigationId" in text
    assert "tabId: tab.id" in text  # the snapshot record carries its tab


def test_the_worker_honours_a_named_tab_and_still_falls_back() -> None:
    """ADR 0030, third slice: the kernel may name the tab; a missing tab must not fail the read."""

    worker = next(ROOT.glob("extension/background-*.js"))
    text = worker.read_text(encoding="utf-8")

    assert "resolveWorkTab(domains, requestedId)" in text
    assert "params.tab_id" in text
    assert "workTab(domains, params.tab_id)" in text


def test_the_worker_implements_the_lease_fence() -> None:
    """P2's third enforcement point, checked statically.

    The behavioural probe (a `lease_sync` round trip under a fake `chrome`) is **not** in place
    yet; until it is, this asserts the two pieces exist and are wired, and nothing more. Claiming
    more than that would be the same mistake as testing only the worker's capability list.
    """

    worker = next(ROOT.glob("extension/background-*.js"))
    text = worker.read_text(encoding="utf-8")

    assert 'message.type === "lease_sync"' in text
    assert 'type: "lease_ack"' in text
    assert "policy.fence" in text
    assert "let fencedFence = 0;" in text
    assert "WORKER_EPOCH" in text


def test_the_host_checks_the_senders_lease_before_writing_a_frame() -> None:
    """P2, second enforcement point: a superseded fence is refused before dispatch."""

    import io

    from scholar_search.adapters.bridge.host import BridgeHost

    seen: list[dict[str, object]] = []

    def checker(context: dict[str, object]) -> str | None:
        seen.append(context)
        return "policy.lease" if context.get("fence") == 1 else None

    host = BridgeHost(stdin=io.BytesIO(), stdout=io.BytesIO())
    host._lease_checker = checker
    host._handshaked = True

    refused = host.request(
        "sleep", {"ms": 1}, timeout_s=0.05, context={"version": 1, "fence": 1, "lease_id": "L1"}
    )

    assert refused["error"] == "policy.lease", refused
    assert seen and seen[0]["fence"] == 1, seen


def test_a_lease_claim_is_checked_against_the_record() -> None:
    from scholar_search.core.lease import Lease, lease_check

    active = Lease(lease_id="L2", fence=5, state="active")

    assert lease_check({"version": 1, "fence": 5, "lease_id": "L2"}, active) is None
    assert lease_check({"version": 1, "fence": 4, "lease_id": "L2"}, active) == "policy.lease"
    assert lease_check({"version": 1, "fence": 5, "lease_id": "L1"}, active) == "policy.lease"
    # A record that says `free` cannot vouch for any claim.
    assert lease_check({"version": 1, "fence": 5}, Lease(lease_id="", fence=5, state="free"))
    # No claim at all (observe mode): nothing to check.
    assert lease_check({"version": 1}, active) is None


def test_the_gate_wait_asks_for_a_focused_window() -> None:
    """A window that is maximized but behind everything is still invisible (P5 retest F34-01).

    Not a behavioural test — the branch needs a browser — but the one detail that was missing is
    a detail a reader can check, so the file has to keep asking for it.
    """

    worker = next(ROOT.glob("extension/background-*.js"))
    text = worker.read_text(encoding="utf-8")
    branch = text[text.index('action === "await_gate_clear"') :][:2000]

    assert 'state: "maximized"' in branch
    assert "focused: true" in branch


def test_the_native_host_accepts_every_verb_the_kernel_plans() -> None:
    """The host keeps its own copy of the vocabulary, and it was missing the gate wait.

    `await_gate_clear` passed the kernel's gate and was refused by the host one layer later with
    `policy.verb`, so the wait never reached the extension (P5 retest 2026-11-26, F34-01). Both
    copies — and the publisher manifest — have to agree with the shipped worker.
    """

    from scholar_search.adapters.bridge.policy import VERBS as HOST_VERBS
    from scholar_search.adapters.bridge.policy import validate_request

    universal, _channel = _worker_lists()
    publisher = publisher_for_doi("10.1021/jacs.6c13448")
    assert publisher is not None
    planned = set(ScholarService._page_goto_params("https://pubs.acs.org/doi/10.1021/jacs.6c13448"))
    planned |= {"snapshot", "sleep", "await_gate_clear"}
    planned -= {"halt_titles", "halt_url_markers", "url"}

    assert planned <= HOST_VERBS, sorted(planned - HOST_VERBS)
    assert planned <= universal, sorted(planned - universal)
    assert planned <= set(_page_spec(publisher).manifest.verbs)

    # And the host's own entry point agrees, with the parameters a read actually sends.
    error = validate_request(
        {
            "action": "await_gate_clear",
            "params": {
                "halt_titles": ["请稍候"],
                "halt_url_markers": [],
                "timeout_ms": 10_000,
                "poll_ms": 2_000,
            },
        }
    )
    assert error is None, error
