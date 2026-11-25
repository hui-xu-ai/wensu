"""The `figures` report has to reach the caller, and the bytes have to land beside the page.

The extension reads a figure out of the browser's own downloaded response (ADR 0026) and hands it
back over the `snapshot` token path; this pins the kernel half: assembly, the file on disk, the
`index.json` that `page2md` rewrites links from, and the report a caller sees. Two live runs found
figures in the browser while the reply carried none, so the wiring is what this catches.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from test_page_read import ARTICLE_HTML, build_service, write_mhtml

DOI = "10.3390/s26041303"
URL = "https://www.mdpi.com/1424-8220/26/4/1303"
FIGURE_URL = "https://mdpi-res.com/sensors/sensors-26-01303-g001-550.webp"
FIGURE_BYTES = b"RIFF....WEBP"


def _script(blob: bytes) -> list[dict[str, object]]:
    return [
        {"verb": "goto", "data": {"url": URL, "title": "A paper", "status": 200}},
        {"verb": "sleep", "data": {"ms": 1_200}},
        {"verb": "sleep", "data": {"ms": 2_400}},
        {"verb": "sleep", "data": {"ms": 2_400}},
        {
            "verb": "snapshot",
            "data": {
                "token": "t1",
                "total": len(blob),
                "base64": base64.b64encode(blob).decode("ascii"),
                "url": URL,
                "title": "A paper",
                "captcha_visible": False,
                "figures": [
                    {
                        "index": 0,
                        "url": FIGURE_URL,
                        "mime": "image/webp",
                        "size": len(FIGURE_BYTES),
                        "chunks": 1,
                    }
                ],
                "figures_skipped": [
                    {"url": "https://uct.service.usercentrics.eu/uct?v=2", "reason": "not_a_figure"}
                ],
            },
        },
        {
            "verb": "snapshot",
            "data": {
                "token": "t1",
                "asset": 0,
                "offset": 0,
                "chunk": base64.b64encode(FIGURE_BYTES).decode("ascii"),
                "done": True,
                "total": len(base64.b64encode(FIGURE_BYTES)),
                "mime": "image/webp",
                "url": FIGURE_URL,
            },
        },
    ]


def test_the_figures_report_reaches_the_caller(tmp_path: Path) -> None:
    blob = write_mhtml(tmp_path / "page.mhtml", ARTICLE_HTML).read_bytes()
    service = build_service(tmp_path, [_script(blob)])

    result = service.read_page(doi=DOI, figures=True)

    assert result["status"] == "ok", result
    figures = result["figures"]
    assert figures["saved"] == 1, figures
    assert figures["files"] == {FIGURE_URL: "assets/01.webp"}, figures
    # A beacon that was skipped is still named, so the caller can say what did not arrive.
    assert figures["skipped"] == [
        {"url": "https://uct.service.usercentrics.eu/uct?v=2", "reason": "not_a_figure"}
    ], figures


def test_the_figure_lands_beside_the_page_with_its_index(tmp_path: Path) -> None:
    blob = write_mhtml(tmp_path / "page.mhtml", ARTICLE_HTML).read_bytes()
    service = build_service(tmp_path, [_script(blob)])

    result = service.read_page(doi=DOI, figures=True)

    page_dir = Path(str(result["mhtml_path"])).parent
    assert (page_dir / "assets" / "01.webp").read_bytes() == FIGURE_BYTES
    index = json.loads((page_dir / "assets" / "index.json").read_text(encoding="utf-8"))
    assert index == {FIGURE_URL: "assets/01.webp"}


def test_a_read_without_figures_says_so_instead_of_omitting_the_field(tmp_path: Path) -> None:
    """`figures` is always present: a caller should not have to guess whether it was asked for."""

    blob = write_mhtml(tmp_path / "page.mhtml", ARTICLE_HTML).read_bytes()
    script = [
        {"verb": "goto", "data": {"url": URL, "title": "A paper", "status": 200}},
        {"verb": "sleep", "data": {"ms": 1_200}},
        {
            "verb": "snapshot",
            "data": {
                "token": "t1",
                "total": len(blob),
                "base64": base64.b64encode(blob).decode("ascii"),
                "url": URL,
                "title": "A paper",
                "captcha_visible": False,
            },
        },
    ]
    service = build_service(tmp_path, [script])

    result = service.read_page(doi=DOI)

    assert result["figures"] == {"saved": 0, "skipped": [], "bytes": 0, "files": {}}
