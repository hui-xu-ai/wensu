"""The figure files a capture leaves on disk, and the links that point at them.

`page_read(..., figures=True)` can only write bytes the browser had already downloaded, so the two
things worth pinning are local and cheap: a stable file name/extension per figure, and the map the
Markdown is rewritten from (ADR 0026). The capture itself is verified against the real browser.
"""

from __future__ import annotations

import json
from pathlib import Path

from scholar_search.core.service import _figure_suffix, _write_figures
from scholar_search.page2md import _adopt_figure_assets


def test_the_extension_follows_the_mime_type_then_the_url() -> None:
    assert _figure_suffix("image/png", "https://cdn/x") == ".png"
    assert _figure_suffix("image/jpeg; charset=binary", "https://cdn/x") == ".jpg"
    assert _figure_suffix("image/svg+xml", "https://cdn/x") == ".svg"
    # No usable mime: the URL's own tail decides, and a query string does not confuse it.
    assert _figure_suffix("", "https://cdn/figures/p3.webp?token=1") == ".webp"
    assert _figure_suffix("application/octet-stream", "https://cdn/blob") == ".bin"


def test_figures_land_beside_the_page_with_an_index(tmp_path: Path) -> None:
    page = tmp_path / "page.mhtml"
    page.write_bytes(b"mhtml")
    report = _write_figures(
        page,
        {
            "assets": [
                {"url": "https://cdn/a.png", "mime": "image/png", "data": b"one"},
                {"url": "https://cdn/b.jpg", "mime": "image/jpeg", "data": b"two"},
            ],
            "skipped": [{"url": "https://cdn/huge.png", "reason": "too_large"}],
            "bytes": 6,
        },
    )

    assert report["saved"] == 2, report
    assert report["bytes"] == 6, report
    assert (tmp_path / "assets" / "01.png").read_bytes() == b"one"
    assert (tmp_path / "assets" / "02.jpg").read_bytes() == b"two"
    index = json.loads((tmp_path / "assets" / "index.json").read_text(encoding="utf-8"))
    assert index == {"https://cdn/a.png": "assets/01.png", "https://cdn/b.jpg": "assets/02.jpg"}
    # A figure that could not be read is named, never silently dropped.
    assert report["skipped"] == [{"url": "https://cdn/huge.png", "reason": "too_large"}]


def test_a_capture_without_figures_writes_nothing(tmp_path: Path) -> None:
    page = tmp_path / "page.mhtml"
    page.write_bytes(b"mhtml")

    report = _write_figures(page, {"assets": [], "skipped": [], "bytes": 0})

    assert report == {"saved": 0, "skipped": [], "bytes": 0, "files": {}}
    assert not (tmp_path / "assets").exists()


def test_page2md_adopts_the_figures_and_maps_the_urls(tmp_path: Path) -> None:
    page_dir = tmp_path / "page"
    (page_dir / "assets").mkdir(parents=True)
    (page_dir / "page.mhtml").write_bytes(b"mhtml")
    (page_dir / "assets" / "01.png").write_bytes(b"one")
    (page_dir / "assets" / "index.json").write_text(
        json.dumps({"https://cdn/a.png": "assets/01.png"}), encoding="utf-8"
    )
    out = page_dir / "md"

    adopted = _adopt_figure_assets(page_dir / "page.mhtml", out)

    assert adopted == {"https://cdn/a.png": "assets/01.png"}
    assert (out / "assets" / "01.png").read_bytes() == b"one"


def test_page2md_ignores_a_missing_index(tmp_path: Path) -> None:
    page = tmp_path / "page.mhtml"
    page.write_bytes(b"mhtml")

    assert _adopt_figure_assets(page, tmp_path / "md") == {}
