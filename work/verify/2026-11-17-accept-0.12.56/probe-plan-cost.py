"""Count the network actions each channel's plan actually contains.

Free: no browser, no quota. Used to explain why `quota_charged` disagreed with
`status.action_cost` during the 0.12.56 acceptance run.

Run:  D:\\Python\\Python314\\python.exe work\\verify\\2026-11-17-accept-0.12.56\\probe-plan-cost.py
"""

from __future__ import annotations

from scholar_search.core.contracts import SearchQuery
from scholar_search.core.registry import ChannelRegistry


def count(channel: str, text: str, **kw: object) -> None:
    impl = ChannelRegistry().load(channel)
    query = SearchQuery(text=text, channel=channel, **kw)  # type: ignore[arg-type]
    plan = impl.plan_search(query)
    actions = list(getattr(plan, "actions", plan))
    verbs = [getattr(action, "verb", type(action).__name__) for action in actions]
    print(f"{channel}: {len(verbs)} actions -> {len(verbs)} quota units (1 unit = 1 reserved slot)")
    print(f"  verbs: {verbs}")
    try:
        print(f"  query_effective: {impl.effective_query(query)}")
    except Exception as error:  # a channel without one is fine
        print(f"  query_effective: <none: {type(error).__name__}>")
    print()


count("cnki", "柔性 驱动器", limit=5)
count("webofscience", "TS=(ionic AND actuator)", limit=3, year_from=2024)
count("webofscience", "TS=(ionic AND actuator) AND PY=(2024-2026)", limit=3)
