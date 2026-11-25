"""A full article that mentions a price must not be reported as a paywall.

Measured 2026-11-25 on `10.1002/anie.202005087` (Wiley): the capture held Abstract / Introduction /
Results and Discussion / Conclusion with `article_tags: 2` and `body_headings: 41`, but one
"institutional access" string in the sidebar put it in the paywall branch — and the reader was told
the tool could not capture an article that was right there in the file.

The split is between markers that block the body ("purchase pdf", "sign in to view") and markers
a page prints for readers who *are* entitled ("institutional access"). A blocking marker decides
on its own; a soft one only counts when the page does not look like an article.
"""

from __future__ import annotations

import email.mime.multipart
import email.mime.text
from pathlib import Path

from scholar_search.core.pageprobe import classify_mhtml

URL = "https://onlinelibrary.wiley.com/doi/10.1002/anie.202005087"

SECTIONS = (
    "Abstract",
    "Introduction",
    "Experimental Section",
    "Results and Discussion",
    "Conclusion",
    "Acknowledgements",
    "References",
)

# Six or more `<h2>` inside `<article>` is what the probe treats as an article body.
BODY = "".join(
    f"<h2>{name}</h2><p>{('Discussion of ' + name + '. ') * 40}</p>" for name in SECTIONS
)


def _mhtml(tmp_path: Path, inner: str) -> Path:
    part = email.mime.text.MIMEText(inner, "html", "utf-8")
    outer = email.mime.multipart.MIMEMultipart("related")
    outer.attach(part)
    page = tmp_path / "page.mhtml"
    page.write_bytes(outer.as_bytes())
    return page


def test_a_body_with_headings_outranks_a_soft_price_marker(tmp_path: Path) -> None:
    inner = (
        "<html><body><article><h1>A paper</h1>"
        f"{BODY}"
        "</article><aside>Access through your organization — institutional access</aside>"
        "</body></html>"
    )

    probe = classify_mhtml(_mhtml(tmp_path, inner), url=URL)

    assert probe["status"] == "ok", probe
    assert probe["paywall_hits"] >= 1, probe


def test_a_blocking_marker_still_wins_over_an_article_shape(tmp_path: Path) -> None:
    """A `<section>` wrapper around an abstract is not a body."""

    inner = (
        "<html><body><article><h1>A paper</h1>"
        "<p>Sign in to view the full text.</p>"
        f"{BODY}"
        "</article></body></html>"
    )

    probe = classify_mhtml(_mhtml(tmp_path, inner), url=URL)

    assert probe["status"] == "no_html", probe
    assert probe["reason"] == "paywall", probe


def test_an_abstract_shell_without_markers_is_abstract_only(tmp_path: Path) -> None:
    inner = "<html><body><article><h1>A paper</h1><p>Abstract only.</p></article></body></html>"

    probe = classify_mhtml(_mhtml(tmp_path, inner), url=URL)

    assert probe["status"] == "no_html", probe
    assert probe["reason"] == "abstract_only", probe
