"""P0 of ADR 0031: the observation contract, with no behaviour behind it yet.

Nothing here sends `mode=observe` — the worker of this build does not advertise
`readiness_observe`, and these tests pin exactly that: the parameter is *known* (so a future
worker may receive it) and *refused* until it is negotiated.
"""

from __future__ import annotations

from scholar_search.adapters.bridge.policy import validate_request
from scholar_search.core.lease import READINESS_FEATURES, readiness_supported
from scholar_search.core.params import MAX_OBSERVE_MS, validate_params

DOMAINS = ("pubs.acs.org",)


def _request(params: dict[str, object]) -> dict[str, object]:
    return {
        "type": "action",
        "id": "r1",
        "action": "snapshot",
        "params": params,
        "domains": list(DOMAINS),
        "context": {"version": 1},
    }


def test_the_features_are_named_and_not_yet_claimed() -> None:
    """The worker of the current build advertises neither; the kernel must not assume them."""

    assert READINESS_FEATURES == {"readiness_observe": 1, "capture_receipts": 1}
    assert readiness_supported(None) is False
    assert readiness_supported({}) is False
    assert readiness_supported({"features": {"lease_control": 1}}) is False
    assert readiness_supported({"features": {"readiness_observe": 1}}) is False, "both are needed"
    assert (
        readiness_supported({"features": {"readiness_observe": 1, "capture_receipts": 1}}) is True
    )


def test_an_observation_is_a_mode_not_a_boolean() -> None:
    assert validate_params("snapshot", {"mode": "observe"}) is None
    assert validate_params("snapshot", {"mode": "capture"}) is None
    assert validate_params("snapshot", {}) is None
    assert validate_params("snapshot", {"mode": "probe"}) == "policy.params"
    assert validate_params("snapshot", {"mode": True}) == "policy.params"


def test_observing_a_transfer_is_refused() -> None:
    """One request cannot both watch tab metadata and continue a capture already in flight."""

    assert validate_params("snapshot", {"mode": "observe", "token": "t1"}) == "policy.params"
    assert validate_params("snapshot", {"mode": "observe", "offset": 0}) == "policy.params"
    # The transfer parameters stay valid on their own.
    assert validate_params("snapshot", {"token": "t1", "offset": 0}) is None


def test_the_observation_budget_is_bounded() -> None:
    assert validate_params("snapshot", {"mode": "observe", "observe_ms": 30_000}) is None
    assert validate_params("snapshot", {"mode": "observe", "observe_ms": 0}) == "policy.params"
    assert (
        validate_params("snapshot", {"mode": "observe", "observe_ms": MAX_OBSERVE_MS + 1})
        == "policy.params"
    )
    assert validate_params("snapshot", {"mode": "observe", "observe_ms": True}) == "policy.params"
    # A budget without the mode it belongs to is a request the worker cannot interpret.
    assert validate_params("snapshot", {"observe_ms": 5_000}) == "policy.params"


def test_the_host_accepts_and_refuses_the_same_shapes() -> None:
    """Both layers run the same closed schema; the host is not a weaker cousin."""

    assert validate_request(_request({"mode": "observe", "observe_ms": 30_000})) is None
    assert validate_request(_request({"mode": "observe", "token": "t1"})) == "policy.params"
    assert validate_request(_request({"mode": "nonsense"})) == "policy.params"
    assert validate_request(_request({"observe_ms": 1_000})) == "policy.params"
    # And an unknown parameter is still unknown.
    assert validate_request(_request({"probe_only": True})) == "policy.params"
