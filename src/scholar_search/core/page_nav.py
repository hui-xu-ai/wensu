"""The one navigation a page read performs.

Kept in its own module on purpose: it is the only place that decides how `page_read` reaches an
article, so a reader can see it in one screen without following a request through the service. It
holds no state, reads no configuration, and returns plain actions the kernel already validates.
"""

from __future__ import annotations

from typing import Any

from .contracts import Action


def article_navigation(service: Any, target: str, publisher: Any) -> tuple[Action, ...]:
    """Open `target` directly, with the gate markers the extension needs to stop early.

    `publisher` is accepted because the caller has it and a reader may wonder; this release does
    not use it.
    """

    del publisher
    return (Action("goto", service._page_goto_params(target)),)
