"""The export path: how the global site's results are read.

The mirror's capture path is covered in `test_channel_webofscience.py`. This module covers
the other half — the one that exists because `www.webofscience.com` never lets its result
payload through the page's `fetch`/`XMLHttpRequest`.

The selectors asserted here were observed on the live site, not invented; the test's job is
to keep them wired in the right order, and to make the cost visible.
"""

from __future__ import annotations

import pytest

from scholar_search.channels.webofscience.v2026_11 import plan_search, selectors
from scholar_search.core.config import HARD
from scholar_search.core.contracts import SearchQuery
from scholar_search.core.errors import ChannelError
from scholar_search.core.policy import NETWORK_VERBS


def _query(**kwargs: object) -> SearchQuery:
    return SearchQuery(text="TS=(ionogel AND actuator)", channel="webofscience", **kwargs)


def test_the_global_host_is_read_through_an_export() -> None:
    assert plan_search.uses_export()
    assert selectors.ADVANCED_SEARCH.startswith("https://www.webofscience.com/")
    # Core Collection, not All Databases: `ut` there is `MEDLINE:…`, which would break the
    # detail URL, the exclusion expression and the JCR lookup at once.
    assert "/wos/woscc/" in selectors.ADVANCED_SEARCH


def test_the_export_chain_is_wired_in_the_order_the_site_reveals_it() -> None:
    """Each step only exists after the previous one: menu, then dialog, then the option."""

    tail = plan_search.build_after_click(_query())
    clicks = [action.params.get("selector") for action in tail.actions if action.verb == "click"]
    assert clicks == [
        selectors.EXPORT_TRIGGER,
        selectors.EXPORT_BIBTEX,
        selectors.EXPORT_CONTENT_COMBO,
        selectors.EXPORT_CONTENT_FULL,
        selectors.EXPORT_CONFIRM,
    ]


def test_only_the_last_click_asks_for_the_file() -> None:
    tail = plan_search.build_after_click(_query())
    confirm = tail.actions[-1]
    assert confirm.params.get("selector") == selectors.EXPORT_CONFIRM
    assert confirm.params.get("expect_download") is True
    assert sum(1 for a in tail.actions if a.params.get("expect_download")) == 1


def test_the_dialog_default_is_overridden_on_purpose() -> None:
    """The dialog opens on 作者、标题、来源出版物, which carries neither DOI nor abstract.

    Selecting 完整记录 is what makes the file usable, so the plan must do it every time
    rather than rely on whatever the previous session left selected.
    """

    tail = plan_search.build_after_click(_query())
    selectors_in_order = [
        action.params.get("selector") for action in tail.actions if action.verb == "click"
    ]
    assert selectors.EXPORT_CONTENT_FULL in selectors_in_order
    assert selectors_in_order.index(selectors.EXPORT_CONTENT_FULL) < len(selectors_in_order) - 1


def test_the_export_plan_fits_the_budget_and_the_verb_set() -> None:
    head, tail = plan_search.build_until_click(_query()), plan_search.build_after_click(_query())
    total = sum(a.timeout_ms for a in (*head.actions, *tail.actions))
    assert total <= HARD.max_plan_seconds * 1000
    assert {a.verb for a in (*head.actions, *tail.actions)} <= NETWORK_VERBS | {
        "sleep",
        "wait_for",
    }


def test_a_page_turn_is_refused_with_the_alternative_that_actually_works() -> None:
    with pytest.raises(ChannelError, match="exclude_ut"):
        plan_search.build_after_click(_query(page=2))


def test_the_export_path_costs_five_network_actions_after_the_search() -> None:
    """A number worth holding still: it is the whole per-search price on this host."""

    tail = plan_search.build_after_click(_query())
    assert sum(1 for a in tail.actions if a.verb in NETWORK_VERBS) == 5
