"""A Letter has no section headings — and it is still an article.

Measured 2026-11-25 on `10.1021/acs.inorgchem.1c03019` (Angewandte *Communication*): 19 long
paragraphs and 3,817 words of continuous prose, with **zero** `Introduction` / `Results and
Discussion` headings. The heading-based rule called it `abstract_only`, so the reader was told the
tool could not capture an article that was sitting in the capture. Prose volume decides now;
headings are only a fast path.
"""

from __future__ import annotations

import email.mime.multipart
import email.mime.text
from pathlib import Path

from scholar_search.core.pageprobe import classify_mhtml

URL = "https://pubs.acs.org/doi/10.1021/acs.inorgchem.1c03019"

SENTENCE = (
    "The yttrium hydroxyl core of the cluster connects twelve vertices and the analysis "
    "follows the same route as before. "
)
LETTER_BODY = "".join(f"<p>{SENTENCE * 12}</p>" for _ in range(10))

ABSTRACT_ONLY = (
    "<html><body><article><h1>A paper</h1>"
    "<p>Short abstract of about forty words that says what the paper claims to do and nothing "
    "more than a reader could learn from the title itself.</p>"
    "</article></body></html>"
)


def _mhtml(tmp_path: Path, inner: str) -> Path:
    part = email.mime.text.MIMEText(inner, "html", "utf-8")
    outer = email.mime.multipart.MIMEMultipart("related")
    outer.attach(part)
    page = tmp_path / "page.mhtml"
    page.write_bytes(outer.as_bytes())
    return page


def test_a_letter_without_any_headings_is_the_article(tmp_path: Path) -> None:
    inner = f"<html><body><article><h1>A communication</h1>{LETTER_BODY}</article></body></html>"

    probe = classify_mhtml(_mhtml(tmp_path, inner), url=URL)

    assert probe["status"] == "ok", probe
    assert probe["headings"] == 0, probe
    assert probe["prose_words"] >= 1_200, probe
    assert probe["prose_paragraphs"] >= 5, probe


def test_an_abstract_page_with_one_short_paragraph_is_not_the_article(tmp_path: Path) -> None:
    probe = classify_mhtml(_mhtml(tmp_path, ABSTRACT_ONLY), url=URL)

    assert probe["status"] == "no_html", probe
    assert probe["reason"] == "abstract_only", probe


def test_a_blocking_marker_still_wins_over_a_long_body(tmp_path: Path) -> None:
    inner = (
        "<html><body><article><h1>A paper</h1>"
        f"{LETTER_BODY}<p>Purchase PDF</p></article></body></html>"
    )

    probe = classify_mhtml(_mhtml(tmp_path, inner), url=URL)

    assert probe["status"] == "no_html", probe
    assert probe["reason"] == "paywall", probe
