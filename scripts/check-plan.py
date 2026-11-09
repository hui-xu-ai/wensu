#!/usr/bin/env python
"""Feed every channel's plan through both validation layers before deploying.

The two layers exist on purpose — the kernel decides what may be planned, the
native host decides what may be executed — but they keep separate copies of the
rules, so changing one and forgetting the other produces a plan the kernel
accepts and the host rejects. That failure only surfaces after the extension has
been reloaded and a site quota has been spent, which is the most expensive place
to find it.

Run this before every deploy:

    python scripts/check-plan.py

Exits non-zero on the first plan either layer refuses.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scholar_search.adapters.bridge.policy import validate_request  # noqa: E402
from scholar_search.core.contracts import SearchQuery  # noqa: E402
from scholar_search.core.errors import ScholarSearchError  # noqa: E402
from scholar_search.core.policy import PolicyEngine  # noqa: E402
from scholar_search.core.registry import ChannelRegistry  # noqa: E402

# Every shape a caller can ask for: the default path, a page turn, an explicit
# sort, and the page-two-with-sort combination if the channel supports it.
VARIANTS: tuple[tuple[str, dict[str, object]], ...] = (
    ("default", {}),
    ("page 2", {"page": 2}),
    ("sort by date", {"sort": "date"}),
    ("sort by citation", {"sort": "citation"}),
)


def check_channel(registry: ChannelRegistry, name: str, manifest: object) -> list[str]:
    problems: list[str] = []
    engine = PolicyEngine()
    for label, extra in VARIANTS:
        query = SearchQuery(text="plan check", channel=name, **extra)  # type: ignore[arg-type]
        try:
            channel = registry.load(name)
            plan = channel.plan_search(query)
        except ScholarSearchError as error:
            # A channel may legitimately refuse a combination (budget, unsupported
            # paging). That is a designed answer, not a defect.
            print(f"  {name:<14} {label:<16} refused by channel: {error}")
            continue

        try:
            engine.validate_plan(plan, manifest)  # type: ignore[arg-type]
        except ScholarSearchError as error:
            problems.append(f"{name} / {label}: kernel refused: {error}")
            continue

        for action in plan.actions:
            message = {"action": action.verb, "params": dict(action.params)}
            error_code = validate_request(message, manifest.domains)  # type: ignore[attr-defined]
            if error_code:
                problems.append(f"{name} / {label}: host refused {action.verb}: {error_code}")
                break
        else:
            print(f"  {name:<14} {label:<16} ok ({len(plan.actions)} actions)")
    return problems


def main() -> int:
    registry = ChannelRegistry()
    specs = registry.discover()
    if not specs:
        print("no channels discovered", file=sys.stderr)
        return 1

    problems: list[str] = []
    for spec in specs:
        problems.extend(check_channel(registry, spec.name, spec.manifest))

    if problems:
        print(file=sys.stderr)
        for line in problems:
            print(f"FAIL {line}", file=sys.stderr)
        return 1
    print("\nboth layers accept every plan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
