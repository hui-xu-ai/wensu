"""ADR 0030, second slice: the capture has to belong to the navigation this read issued.

The first slice only *reported* `navigation_id`; a real retest showed four distinct ids and a
top-level value matching the last goto every time. Now a capture that followed a *different*
navigation is refused, and a navigation the bridge gave up on is reported as unconfirmed rather
than as if nothing had been set in motion.
"""

from __future__ import annotations

import base64
from pathlib import Path

from test_page_read import ARTICLE_HTML, build_service, write_mhtml

DOI = "10.1016/j.cej.2023.145123"
URL = "https://www.sciencedirect.com/science/article/pii/X"


def _snapshot(blob: bytes, *, navigation_id: str | None) -> dict[str, object]:
    data: dict[str, object] = {
        "token": "t1",
        "total": len(blob),
        "base64": base64.b64encode(blob).decode("ascii"),
        "url": URL,
        "title": "An article",
        "captcha_visible": False,
        "status": 200,
        "tab_id": 7,
    }
    if navigation_id is not None:
        data["navigation_id"] = navigation_id
    return {"verb": "snapshot", "data": data}


def _goto(navigation_id: str = "nav-1") -> dict[str, object]:
    return {
        "verb": "goto",
        "data": {"url": URL, "tab_id": 7, "navigation_id": navigation_id},
    }


def _reading(tmp_path: Path, capture_navigation_id: str | None) -> dict[str, object]:
    blob = write_mhtml(tmp_path / "page.mhtml", ARTICLE_HTML).read_bytes()
    service = build_service(
        tmp_path,
        [
            [
                _goto(),
                {"verb": "sleep", "data": {"ms": 1}},
                _snapshot(blob, navigation_id=capture_navigation_id),
            ]
        ],
    )
    return service.read_page(doi=DOI)


def test_a_capture_from_the_navigation_this_read_issued_is_accepted(tmp_path: Path) -> None:
    result = _reading(tmp_path, "nav-1")

    assert result["status"] == "ok", result
    assert result["capture_navigation"] == "match", result
    assert result["navigation_id"] == "nav-1", result


def test_a_capture_from_another_navigation_is_refused(tmp_path: Path) -> None:
    result = _reading(tmp_path, "nav-other")

    assert result["status"] == "no_page", result
    assert result["reason"] == "unverified_capture", result
    assert result["capture_navigation"] == "mismatch", result
    assert result["mhtml_path"] is None, result
    assert not list((tmp_path / "pages").rglob("page.mhtml")), "must not be published"


def test_a_worker_that_reports_no_navigation_id_is_not_failed(tmp_path: Path) -> None:
    """Rolling upgrades leave older builds in place; absence is a note, not a verdict."""

    result = _reading(tmp_path, None)

    assert result["status"] == "ok", result
    assert result["capture_navigation"] == "absent", result


def test_two_navigations_are_compared_with_the_one_the_capture_followed(
    tmp_path: Path, monkeypatch
) -> None:
    """Publisher front page, then the article: the capture follows the **second** id.

    Comparing against the first id rejected a real MDPI read with
    `capture_navigation: mismatch` (2026-11-27) — the capture was right, the baseline was wrong.
    The two-goto shape is what the private navigation patch installs, so it is modelled here.
    """

    import scholar_search.core.service as service_module

    monkeypatch.setattr(
        service_module,
        "article_navigation",
        lambda _service, target, _publisher: (
            service_module.Action("goto", {"url": target, "wait": "load"}),
            service_module.Action("goto", {"url": target, "wait": "load"}),
        ),
    )
    blob = write_mhtml(tmp_path / "page.mhtml", ARTICLE_HTML).read_bytes()
    service = build_service(
        tmp_path,
        [
            [
                _goto("nav-front"),
                _goto("nav-article"),
                {"verb": "sleep", "data": {"ms": 1}},
                _snapshot(blob, navigation_id="nav-article"),
            ]
        ],
    )

    result = service.read_page(doi=DOI)

    assert result["status"] == "ok", result
    assert result["capture_navigation"] == "match", result
    assert result["navigation_id"] == "nav-article", result


def test_a_capture_left_on_the_first_of_two_navigations_is_still_refused(
    tmp_path: Path, monkeypatch
) -> None:
    """The tab moved on after the capture: the bytes are not the page this read ended on."""

    import scholar_search.core.service as service_module

    monkeypatch.setattr(
        service_module,
        "article_navigation",
        lambda _service, target, _publisher: (
            service_module.Action("goto", {"url": target, "wait": "load"}),
            service_module.Action("goto", {"url": target, "wait": "load"}),
        ),
    )
    blob = write_mhtml(tmp_path / "page.mhtml", ARTICLE_HTML).read_bytes()
    service = build_service(
        tmp_path,
        [
            [
                _goto("nav-front"),
                _goto("nav-article"),
                {"verb": "sleep", "data": {"ms": 1}},
                _snapshot(blob, navigation_id="nav-front"),
            ]
        ],
    )

    result = service.read_page(doi=DOI)

    assert result["status"] == "no_page", result
    assert result["capture_navigation"] == "mismatch", result
    assert result["reason"] == "unverified_capture", result


def test_the_capture_asks_for_the_tab_the_navigation_used(tmp_path: Path) -> None:
    """ADR 0030, third slice: the kernel names the tab instead of accepting the extension's pick.

    Additive on purpose — the extension falls back to its own choice when the named tab is gone,
    so this cannot fail a read; what it removes is the "captured some other tab" possibility.
    """

    blob = write_mhtml(tmp_path / "page.mhtml", ARTICLE_HTML).read_bytes()
    seen: list[dict[str, object]] = []

    from scholar_search.adapters.fixture import FixtureAdapter

    original = FixtureAdapter.execute

    def recording(self, action, *, timeout_ms):  # type: ignore[no-untyped-def]
        seen.append({"verb": action.verb, "params": dict(action.params)})
        return original(self, action, timeout_ms=timeout_ms)

    FixtureAdapter.execute = recording  # type: ignore[method-assign]
    try:
        service = build_service(
            tmp_path,
            [
                [
                    _goto(),
                    {"verb": "sleep", "data": {"ms": 1}},
                    _snapshot(blob, navigation_id="nav-1"),
                ]
            ],
        )
        result = service.read_page(doi=DOI)
    finally:
        FixtureAdapter.execute = original  # type: ignore[method-assign]

    assert result["status"] == "ok", result
    captures = [step for step in seen if step["verb"] == "snapshot"]
    assert captures, seen
    assert any(step["params"].get("tab_id") == 7 for step in captures), captures


def test_a_navigation_that_timed_out_is_reported_as_unconfirmed(tmp_path: Path) -> None:
    """The tab may land after the caller was told "timeout"; that is not "nothing happened"."""

    service = build_service(
        tmp_path,
        [[{"verb": "goto", "ok": False, "error": "bridge.timeout"}]],
    )

    result = service.read_page(doi=DOI)

    assert result["terminal"] == "timeout", result
    assert result["reason"] == "navigation_unconfirmed", result
    assert result["unconfirmed"] is True, result
    assert result["stage"] == "navigate", result
    assert "browser_busy" in result["next"], result["next"]
