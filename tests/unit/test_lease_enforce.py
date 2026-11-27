"""`enforce` admission, kernel side only (plan §二.2, P2 first slice).

Observe is the default and changes nothing. When enabled, a call takes the shared lease or is
refused with one of the three `lease_*` reasons — before any action is planned, so it costs no
quota. Nothing here retries, waits out, or clears a cooldown.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scholar_search.core.errors import ScholarSearchError
from scholar_search.core.lease import LeaseStore, Operation, lease_mode


def _service(tmp_path: Path, *, features: dict[str, int] | None = None):
    from test_page_read import ARTICLE_HTML, build_service, write_mhtml

    blob = write_mhtml(tmp_path / "page.mhtml", ARTICLE_HTML).read_bytes()
    service = build_service(
        tmp_path,
        [
            [
                {"verb": "goto", "data": {"url": "https://www.sciencedirect.com/article/X"}},
                {"verb": "sleep", "data": {"ms": 1}},
                {
                    "verb": "snapshot",
                    "data": {
                        "token": "t1",
                        "total": len(blob),
                        "base64": __import__("base64").b64encode(blob).decode("ascii"),
                        "url": "https://www.sciencedirect.com/article/X",
                        "title": "A paper",
                        "captcha_visible": False,
                    },
                },
            ]
        ],
    )
    build = {"version": "0.14.51", "features": features if features is not None else {}}
    service._bridge_build = lambda: build  # type: ignore[method-assign]
    return service


def test_observe_is_the_default_and_takes_no_lease(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SCHOLAR_SEARCH_LEASE_MODE", raising=False)
    monkeypatch.setenv("SCHOLAR_SEARCH_BROWSER_STATE", str(tmp_path / "browser-state"))
    service = _service(tmp_path)

    assert lease_mode() == "observe"
    with service._browser_transaction():
        pass

    assert LeaseStore().read().state == "free", "observe must not create a lease"


def test_enforce_refuses_when_the_lease_is_unconfirmed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SCHOLAR_SEARCH_LEASE_MODE", "enforce")
    monkeypatch.setenv("SCHOLAR_SEARCH_BROWSER_STATE", str(tmp_path / "browser-state"))
    store = LeaseStore()
    lease = store.acquire(lease_id="L-old", job_id="old-job")
    assert lease is not None
    store.record_operation(
        "L-old",
        lease.fence,
        Operation(operation_id="op-old", action="goto", state="executing", navigation_issued=True),
    )
    store.finish(lease_id="L-old", fence=lease.fence, evidence="settled_with_receipt")
    assert store.read().state == "unconfirmed"

    service = _service(tmp_path, features={"lease_control": 1, "operation_receipts": 1})
    before = service._policy.remaining_today

    with pytest.raises(ScholarSearchError) as raised, service._browser_transaction():
        pass

    assert "lease_unconfirmed" in str(raised.value), raised.value
    assert service._policy.remaining_today == before, "a refusal must not spend quota"


def test_enforce_refuses_when_the_peer_does_not_advertise_lease_control(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SCHOLAR_SEARCH_LEASE_MODE", "enforce")
    monkeypatch.setenv("SCHOLAR_SEARCH_BROWSER_STATE", str(tmp_path / "browser-state"))
    service = _service(tmp_path, features={})

    with pytest.raises(ScholarSearchError) as raised, service._browser_transaction():
        pass

    assert "lease_control" in str(raised.value), raised.value
    assert LeaseStore().read().state == "free", "refusing must not leave a lease behind"


def test_enforce_admits_and_releases_when_the_call_finishes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SCHOLAR_SEARCH_LEASE_MODE", "enforce")
    monkeypatch.setenv("SCHOLAR_SEARCH_BROWSER_STATE", str(tmp_path / "browser-state"))
    service = _service(tmp_path, features={"lease_control": 1, "operation_receipts": 1})
    store = LeaseStore()

    with service._browser_transaction():
        inside = store.read()
        assert inside.state == "active", inside

    after = store.read()
    assert after.state == "free", after
    assert after.fence == inside.fence, "the same lease, not a new one"
