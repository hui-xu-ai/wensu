"""Real capture, three content findings (real-browser acceptance 2026-11-27, F53-01/02/03).

The fixture is built from the saved MDPI capture's *structure* — a section container plus a table
that sits outside every section, inside its own wrapper div — which is what made `_own_blocks`
never see the tables. No page text is copied: the strings below are made up.
"""

from __future__ import annotations

import email.mime.text
import json
from pathlib import Path

from scholar_search.core.pageprobe import classify_mhtml

HTML = """<!DOCTYPE html><html><head>
<meta name="citation_doi" content="10.9999/probe.2026.1">
<meta name="citation_pdf_url" content="https://example.org/arti/1/pdf">
<meta name="citation_title" content="A probe article">
</head><body>
<section id="s1"><h2>Results</h2>
<p>This paragraph is long enough to count as prose, with many words in it so that the extractor
keeps it rather than treating the page as an abstract shell with nothing on it at all.</p>
<p>Another paragraph of ordinary length follows here so the section is not dropped on a length
test, and the prose counter reaches the threshold the classifier uses for a real article body.</p>
</section>
<div class="html-table_show for-table"><table>
<tr><th>Sample Composition</th><th>Tensile Strength (KPa)</th></tr>
<tr><td>Mixture A</td><td>12.4</td></tr>
<tr><td>Mixture B</td><td>31.7</td></tr>
</table></div>
<p><a href="https://mdpi-res.example/journals/3/flyer.pdf">Journal flyer</a></p>
<section id="s2"><h2>Conclusions</h2>
<p>A closing paragraph that is also long enough to survive the filters, mentioning the mixtures and
their measured strengths once more for the reader who skips to the end of the paper.</p>
</section>
</body></html>"""


def _mhtml(tmp_path: Path) -> Path:
    part = email.mime.text.MIMEText(HTML, "html", "utf-8")
    path = tmp_path / "probe.mhtml"
    path.write_bytes(part.as_bytes())
    return path


def test_a_table_outside_every_section_is_kept(tmp_path: Path) -> None:
    """F53-01: three body tables vanished and `table_rows` stayed 0 with no warning."""

    from scholar_search import page2md

    out = tmp_path / "md"
    page2md.convert(_mhtml(tmp_path), out)

    page = (out / "page.md").read_text(encoding="utf-8")
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))

    assert "Sample Composition" in page, page[:400]
    assert "Tensile Strength (KPa)" in page
    assert "Mixture B" in page
    assert meta["tables_rendered"] >= 1, meta
    assert meta["table_rows"] >= 3, meta


def test_the_pdf_field_prefers_the_page_s_own_declaration(tmp_path: Path) -> None:
    """F53-02: the first `.pdf` on the page was a journal flyer, not the article."""

    result = classify_mhtml(_mhtml(tmp_path))

    assert result["pdf_url"] == "https://example.org/arti/1/pdf", result["pdf_url"]
    assert "flyer" not in str(result["pdf_url"])


def test_a_page_with_no_declaration_and_several_pdfs_reports_nothing(tmp_path: Path) -> None:
    """A plausible-looking wrong file is worse than an empty field."""

    html = HTML.replace(
        '<meta name="citation_pdf_url" content="https://example.org/arti/1/pdf">', ""
    ).replace(
        '<a href="https://mdpi-res.example/journals/3/flyer.pdf">Journal flyer</a>',
        '<a href="https://example.org/supplement.pdf">Supplement</a>'
        '<a href="https://example.org/errata.pdf">Errata</a>',
    )
    part = email.mime.text.MIMEText(html, "html", "utf-8")
    path = tmp_path / "ambiguous.mhtml"
    path.write_bytes(part.as_bytes())

    assert classify_mhtml(path)["pdf_url"] == ""


def test_a_declared_doi_is_echoed_with_the_identity_it_produced(tmp_path: Path) -> None:
    """F53-03: `identity: declared` without the value it declared."""

    from test_page_read import ARTICLE_HTML, build_service, write_mhtml

    doi = "10.1016/j.cej.2023.145123"
    # The known-good article body, inside a document that declares this DOI: only the identity
    # value changes, so a failure here is about `declared_doi` and nothing else. The declaration
    # has to sit in a real `<head>` — `meta_content` reads the head only on purpose (a reference's
    # quoted DOI once won because it appeared later in the body).
    body = ARTICLE_HTML.split("<body", 1)[-1]
    body = body.split(">", 1)[-1] if body else ARTICLE_HTML
    html = (
        "<!DOCTYPE html><html><head>"
        f'<meta name="citation_doi" content="{doi}">'
        "<title>An article</title></head><body>" + body
    )
    blob = write_mhtml(tmp_path / "page.mhtml", html).read_bytes()
    service = build_service(
        tmp_path,
        [
            [
                {"verb": "goto", "data": {"url": "https://example.org/arti/1"}},
                {"verb": "sleep", "data": {"ms": 1}},
                {
                    "verb": "snapshot",
                    "data": {
                        "token": "t1",
                        "total": len(blob),
                        "base64": __import__("base64").b64encode(blob).decode("ascii"),
                        "url": "https://example.org/arti/1",
                        "title": "An article",
                        "captcha_visible": False,
                    },
                },
            ]
        ],
    )

    answer = service.read_page(doi=doi)

    assert answer["identity"] == "declared", answer
    assert answer["declared_doi"] == doi, answer
