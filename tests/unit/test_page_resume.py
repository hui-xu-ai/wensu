"""P1 of ADR 0031: a resume captures the page the person cleared, and never navigates.

Before this, the only way to continue after a wall was to call `page_read` again — which
navigated, refreshed away the page the person had just let through, and charged another unit.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

from scholar_search.core.errors import PolicyError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_page_read import build_service, write_mhtml

URL = "https://www.sciencedirect.com/science/article/pii/S1385894723029534"
DOI = "10.1016/j.cej.2023.145123"

ARTICLE = """<!DOCTYPE html><html><head>
<meta name="citation_doi" content="10.1016/j.cej.2023.145123">
<title>The article</title></head><body><article>
<h2>1. Introduction</h2>
<p>This paragraph is long enough to be counted as prose, and it mentions the material, the
measurement and the conclusion so that a reader would call it body text.</p>
<p>A second paragraph follows, also long enough to count, describing another measurement and its
outcome in the same register as the first one.</p>
</article></body></html>"""


def _snapshot_step(blob: bytes) -> dict[str, object]:
    return {
        "verb": "snapshot",
        "data": {
            "token": "t1",
            "total": len(blob),
            "base64": base64.b64encode(blob).decode("ascii"),
            "url": URL,
            "title": "The article",
            "captcha_visible": False,
        },
    }


def test_a_resume_captures_without_navigating(tmp_path: Path) -> None:
    blob = write_mhtml(tmp_path / "page.mhtml", ARTICLE).read_bytes()
    # Two scripts, consumed in order: the first read hits the wall, the resume may only capture.
    # A stray navigation in the resume would exhaust its script and fail loudly.
    service = build_service(
        tmp_path,
        [
            [
                {"verb": "goto", "data": {"url": URL, "title": "请稍候…"}},
                {
                    "verb": "await_gate_clear",
                    "data": {"waited": True, "cleared": False, "title": "请稍候…"},
                },
            ],
            [{"verb": "sleep", "data": {"ms": 1200}}, _snapshot_step(blob)],
        ],
    )
    first = service.read_page(url=URL)

    assert first["terminal"] == "timeout", first
    assert first["stage"] == "wall", first
    job_id = str(first["job_id"])

    resumed = service.read_page(resume_job_id=job_id)

    assert resumed["status"] == "ok", resumed
    assert resumed["quota_charged"] == 0, resumed
    assert resumed["resumed_from"] == job_id, resumed
    assert resumed["job_id"] != job_id, "a resume is its own job; the old verdict is not rewritten"
    assert Path(str(resumed["mhtml_path"])).is_file()


def test_a_resume_cannot_be_asked_to_navigate(tmp_path: Path) -> None:
    service = build_service(
        tmp_path,
        [
            [
                {"verb": "goto", "data": {"url": URL, "title": "请稍候…"}},
                {
                    "verb": "await_gate_clear",
                    "data": {"waited": True, "cleared": False, "title": "请稍候…"},
                },
            ]
        ],
    )
    first = service.read_page(url=URL)

    with pytest.raises(PolicyError) as raised:
        service.read_page(resume_job_id=str(first["job_id"]), refresh=True)

    assert getattr(raised.value, "rule", "") == "policy.params", raised.value


def test_a_resume_of_something_that_is_not_the_last_read_is_refused(tmp_path: Path) -> None:
    service = build_service(tmp_path, [[]])

    with pytest.raises(PolicyError) as raised:
        service.read_page(resume_job_id="not-a-job")

    assert getattr(raised.value, "rule", "") == "policy.resume_unknown", raised.value
