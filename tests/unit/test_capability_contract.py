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
