"""The fixture adapter reports what a real one reports (audit 2026-11-26, F14).

The bridge takes the tab's address from the reply's own `url`/`data.url`: that is the page the
browser ended up on. The fixture used to put the *requested* address there instead, so a test
about URL attribution was checking a shape no real run ever produces.
"""

from __future__ import annotations

from scholar_search.adapters.fixture import FixtureAdapter
from scholar_search.core.contracts import Action

DOI_URL = "https://doi.org/10.1021/jacs.6c13448"
ARTICLE = "https://pubs.acs.org/doi/10.1021/jacs.6c13448"


def test_a_redirected_goto_reports_the_landing_address() -> None:
    adapter = FixtureAdapter([{"verb": "goto", "data": {"url": ARTICLE, "title": "A paper"}}])

    outcome = adapter.execute(Action("goto", {"url": DOI_URL}), timeout_ms=1_000)

    assert outcome.url == ARTICLE
    assert outcome.data["requested_url"] == DOI_URL


def test_a_goto_without_a_reported_address_keeps_the_requested_one() -> None:
    adapter = FixtureAdapter([{"verb": "goto"}])

    outcome = adapter.execute(Action("goto", {"url": DOI_URL}), timeout_ms=1_000)

    assert outcome.url == DOI_URL


def test_another_verb_does_not_invent_an_address() -> None:
    adapter = FixtureAdapter([{"verb": "read_text", "data": {"text": "body"}}])

    outcome = adapter.execute(Action("read_text", {"selector": "p"}), timeout_ms=1_000)

    assert outcome.url is None
