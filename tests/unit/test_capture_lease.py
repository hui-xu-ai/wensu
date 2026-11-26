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
