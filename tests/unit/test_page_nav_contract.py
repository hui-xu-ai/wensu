"""The navigation contract `page_read` relies on.

`page_nav.article_navigation` is the single place a page read decides how it reaches an article.
The test pins the signature and the "exactly one navigation" rule so a refactor cannot quietly
change how many requests a read makes.
"""

from __future__ import annotations

from typing import Any

from scholar_search.core.contracts import Action
from scholar_search.core.page_nav import article_navigation
from scholar_search.core.publishers import publisher_for_doi


class _Service:
    """The only thing the navigation asks of the service."""

    def _page_goto_params(self, target: str) -> dict[str, Any]:
        return {"url": target, "halt_titles": ["just a moment"]}


def test_the_signature_is_service_target_publisher() -> None:
    import inspect

    parameters = list(inspect.signature(article_navigation).parameters)
    assert parameters == ["service", "target", "publisher"]


def test_one_navigation_to_the_article() -> None:
    publisher = publisher_for_doi("10.3390/s26041303")
    assert publisher is not None

    actions = article_navigation(_Service(), "https://www.mdpi.com/1424-8220/26/4/1303", publisher)

    assert len(actions) == 1, actions
    assert isinstance(actions[0], Action)
    assert actions[0].verb == "goto"
    assert actions[0].params["url"] == "https://www.mdpi.com/1424-8220/26/4/1303"


def test_the_gate_markers_come_from_the_service() -> None:
    publisher = publisher_for_doi("10.3390/s26041303")
    assert publisher is not None

    actions = article_navigation(_Service(), "https://www.mdpi.com/x", publisher)

    assert actions[0].params["halt_titles"] == ["just a moment"]
