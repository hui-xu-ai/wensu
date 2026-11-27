"""The diagnostic budgets (ADR 0031): how a branch gets exercised without waiting for a fault.

Two branches had no sample — an observation budget that runs out, and a capture that times out
while the browser is still working. Both are timing branches, so both can be reached on one
ordinary read by shrinking the budget instead of manufacturing a slow site or a wall.
"""

from __future__ import annotations

import inspect

import pytest

from scholar_search.core import config
from scholar_search.core.params import validate_params
from scholar_search.core.service import SNAPSHOT_TIMEOUT_MS


def test_the_defaults_are_the_shipped_ones() -> None:
    assert SNAPSHOT_TIMEOUT_MS == 55_000
    assert config.readiness_budget_ms() == 30_000
    assert config.snapshot_timeout_ms() == 55_000


def test_the_budgets_can_be_shrunk_for_diagnostics(monkeypatch) -> None:
    monkeypatch.setenv(config.ENV_READINESS_BUDGET_MS, "50")
    monkeypatch.setenv(config.ENV_SNAPSHOT_TIMEOUT_MS, "300")

    assert config.readiness_budget_ms() == 50
    assert config.snapshot_timeout_ms() == 300


def test_a_diagnostic_can_shrink_but_never_widen(monkeypatch) -> None:
    """The ceiling is the host's single-RPC limit; a bigger number would be cut off at the wire."""

    monkeypatch.setenv(config.ENV_SNAPSHOT_TIMEOUT_MS, "600000")
    assert config.snapshot_timeout_ms() == 55_000

    monkeypatch.setenv(config.ENV_READINESS_BUDGET_MS, "99999999")
    assert config.readiness_budget_ms() == 300_000

    # And a value below the floor is not a budget, it is a broken read.
    monkeypatch.setenv(config.ENV_READINESS_BUDGET_MS, "1")
    monkeypatch.setenv(config.ENV_SNAPSHOT_TIMEOUT_MS, "1")
    assert config.readiness_budget_ms() == 50
    assert config.snapshot_timeout_ms() == 200


def test_a_nonsense_value_falls_back_to_the_default(monkeypatch) -> None:
    monkeypatch.setenv(config.ENV_READINESS_BUDGET_MS, "soon")
    monkeypatch.setenv(config.ENV_SNAPSHOT_TIMEOUT_MS, "")

    assert config.readiness_budget_ms() == 30_000
    assert config.snapshot_timeout_ms() == 55_000


def test_a_caller_cannot_ask_for_a_budget() -> None:
    """These are this process's environment, not a request field: the schema stays closed."""

    assert validate_params("snapshot", {"mode": "observe", "budget_ms": 50}) == "policy.params"
    assert validate_params("snapshot", {"timeout_ms": 50}) == "policy.params"
    assert "readiness_budget_ms" not in inspect.getsource(
        __import__("scholar_search.core.params", fromlist=["validate_params"]).validate_params
    )


def test_the_settings_have_one_place() -> None:
    """Both are read through `config`, so `status`/docs cannot drift from the code."""

    source = inspect.getsource(__import__("scholar_search.core.service", fromlist=["x"]))
    assert source.count("config.readiness_budget_ms()") >= 1
    assert source.count("config.snapshot_timeout_ms()") >= 1
    assert "SCHOLAR_SEARCH_SNAPSHOT_TIMEOUT_MS" not in source, "read it through config, once"


def test_the_observation_loop_compares_milliseconds() -> None:
    """The first draft mixed seconds with milliseconds and would have looped 30 000 times."""

    from scholar_search.core.service import ScholarService

    source = inspect.getsource(ScholarService._observe_before_capture)

    assert "spent_ms" in source
    assert "spent * 1000" not in source, "no implicit seconds"


@pytest.mark.parametrize("value", ["0", "-5"])
def test_a_zero_budget_is_clamped_up(monkeypatch, value: str) -> None:
    monkeypatch.setenv(config.ENV_READINESS_BUDGET_MS, value)
    assert config.readiness_budget_ms() == 50
