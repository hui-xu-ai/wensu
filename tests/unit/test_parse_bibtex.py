"""BibTeX export -> records.

The fixture is a real two-record export from `www.webofscience.com`: one article and one
conference paper. It is the whole reason this path exists, so the test parses the real file
rather than a hand-written approximation.
"""

from __future__ import annotations

from pathlib import Path

from scholar_search.channels.webofscience.v2026_11 import parse_bibtex, selectors
from scholar_search.core.contracts import SearchQuery

FIXTURE = Path(__file__).parent.parent / "fixtures" / "webofscience" / "export.bib"


def _parse(text: str | None = None, metrics: object = None):
    source = FIXTURE.read_text(encoding="utf-8") if text is None else text
    query = SearchQuery(text="TS=(ionogel)", channel="webofscience", limit=10)
    if metrics is None:
        return parse_bibtex.parse(source, query=query)
    return parse_bibtex.parse(source, query=query, metrics=metrics)  # type: ignore[arg-type]


def test_the_real_export_parses_into_two_records() -> None:
    page = _parse()
    assert page.total == 2
    assert [record.doc_type for record in page.records] == ["article", "proceedings paper"]


def test_the_entry_key_becomes_the_detail_url() -> None:
    """`@article{ WOS:…` — the key is the UT, so the URL needs no second source."""

    record = _parse().records[0]
    assert record.url == f"{selectors.DETAIL_PREFIX}WOS:001218812900001"


def test_a_folded_value_is_read_as_one_line() -> None:
    """WoS wraps long values with a three-space indent; both halves belong to the title."""

    record = _parse().records[0]
    assert record.title == (
        "Miniaturized ionogel-based bi-stable actuator with state-sensing capability"
    )


def test_escaped_braces_and_ampersands_are_undone() -> None:
    text = r"""
@article{ WOS:1,
Title = {A {[}bracketed{]} title \& more},
Year = {2024},
}
"""
    record = _parse(text).records[0]
    assert record.title == "A {bracketed} title & more"


def test_fields_that_matter_for_downstream_work_are_mapped() -> None:
    article, paper = _parse().records
    assert article.doi == "10.1016/j.sna.2024.115220"
    assert article.source == "SENSORS AND ACTUATORS A-PHYSICAL"
    assert article.year == 2024
    assert article.volume == "370"
    assert article.citations == 6
    assert article.authors[:2] == ["Lo, Li-Yu", "Lin, Pei-Ting"]
    assert "Miniaturized soft gripper" in article.keywords

    # A conference paper has no volume but does have pages, and its venue is Booktitle.
    assert paper.pages == "622-625"
    assert paper.volume is None
    assert paper.source is not None and "MEMS" in paper.source


def test_a_doi_written_as_a_url_is_reduced_to_the_identifier() -> None:
    text = "@article{ WOS:2,\nTitle = {T},\nDOI = {https://doi.org/10.1000/xyz},\n}\n"
    assert _parse(text).records[0].doi == "10.1000/xyz"


def test_a_record_without_a_title_is_skipped_rather_than_invented() -> None:
    text = "@article{ WOS:3,\nYear = {2024},\n}\n@article{ WOS:4,\nTitle = {Real},\n}\n"
    page = _parse(text)
    assert [record.title for record in page.records] == ["Real"]


def test_metrics_come_from_the_lookup_not_from_the_file() -> None:
    """The export carries no impact factor; it has to be supplied."""

    seen: list[tuple[str | None, str | None, str | None]] = []

    def metrics(name: str | None, issn: str | None, eissn: str | None):
        seen.append((name, issn, eissn))
        return (4.9, 2024)

    page = _parse(metrics=metrics)
    assert page.records[0].impact_factor == 4.9
    assert page.records[0].impact_factor_year == 2024
    assert seen[0][1] == "0924-4247", "the ISSN in the export must reach the lookup"


def test_without_a_lookup_the_metric_is_absent_not_zero() -> None:
    record = _parse().records[0]
    assert record.impact_factor is None
    assert record.impact_factor_year is None
