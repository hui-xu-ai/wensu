"""Measure the quota cost of each documented action, per channel.

1 quota unit = 1 action whose verb is in NETWORK_VERBS (core/planner.py:74 →
policy.wait_turn → state.used += 1). So counting a plan's network verbs gives the
exact price of running it — no browser, no quota.

Run:  D:\\Python\\Python314\\python.exe work\\verify\\2026-11-17-accept-0.12.56\\probe-action-cost.py
"""

from __future__ import annotations

from scholar_search.core.contracts import SearchQuery
from scholar_search.core.policy import NETWORK_VERBS
from scholar_search.core.registry import ChannelRegistry

SAMPLES = {
    "cnki": "柔性 驱动器",
    "webofscience": "TS=(ionic AND actuator)",
}

SCENARIOS: list[tuple[str, dict[str, object]]] = [
    ("search (default sort, page 1)", {}),
    ("search page 2", {"page": 2}),
    ("search + site_sort=date", {"sort": "date"}),
]


def cost(channel: str, **kw: object) -> str:
    try:
        impl = ChannelRegistry().load(channel)
        query = SearchQuery(text=SAMPLES[channel], channel=channel, **kw)  # type: ignore[arg-type]
        plan = impl.plan_search(query)
    except Exception as error:  # a refused plan is an answer, not a crash
        return f"refused: {type(error).__name__}: {error}"
    verbs = [getattr(action, "verb", "?") for action in plan.actions]
    charged = [verb for verb in verbs if verb in NETWORK_VERBS]
    return f"{len(charged)}  {charged}"


for channel in SAMPLES:
    print(f"--- {channel}")
    for label, kw in SCENARIOS:
        print(f"  {label:<32} = {cost(channel, **kw)}")
    print()
