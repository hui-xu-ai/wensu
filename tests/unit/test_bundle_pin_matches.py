"""The bundle's pin and its declared DSH engine must both be exact — and equal.

`@deepseek-ai/dsh-mcp-client` requires the ten DSH core packages at **exact** versions, so a
bundle is usable on exactly one DSH build. There are two ways to get that wrong, and both have
happened:

* `engines.dsh` written as a range while the dependency is exact — the 0.2.2-rc.2 incident. The
  range accepted rc.2, the row was denied anyway, and nothing reported why.
* the two drifting apart as they get bumped by hand, one at a time.

These assertions are the only thing that notices either one before a user does.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = json.loads((ROOT / "packages" / "dsh-wensu" / "package.json").read_text(encoding="utf-8"))
CLIENT = "@deepseek-ai/dsh-mcp-client"

# `0.2.2-rc.3` — one version, no range operators, no spaces, no `||`.
EXACT_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?$")


def test_the_client_dependency_is_pinned_exactly() -> None:
    pinned = BUNDLE["dependencies"][CLIENT]

    assert EXACT_VERSION.match(pinned), f"{CLIENT} must be pinned, got {pinned!r}"


def test_the_engine_is_a_pin_not_a_range() -> None:
    """A range here is a lie: it accepts cores the pinned client cannot run on."""

    engine = BUNDLE["engines"]["dsh"]

    assert EXACT_VERSION.match(engine), f"engines.dsh must be one exact version, got {engine!r}"


def test_the_engine_and_the_client_name_the_same_build() -> None:
    assert BUNDLE["engines"]["dsh"] == BUNDLE["dependencies"][CLIENT]
