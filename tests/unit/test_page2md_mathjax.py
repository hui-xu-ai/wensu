"""A MathJax page has formulas; they are drawings, not text.

`page2md` used to count the empty MathML inside `mjx-assistive-mml` (MathJax's screen-reader
copy) as real formulas, so a Wiley article reported "6 formulas failed to convert" while the
Markdown could never contain a marker for any of them — nothing was there to convert (measured
2026-11-24: each node is `<math data-semantic-type="empty"/>`, and the drawn formula lives in
`mjx-container` as an SVG).
"""

from __future__ import annotations

from pathlib import Path

from scholar_search import page2md


def test_empty_assistive_mathml_is_not_counted_as_a_formula() -> None:
    html = (
        "<html><body><article><h1>A paper</h1><section id='s1'>"
        "<h2>1. Introduction</h2>"
        "<p>Text <span class='inline-equation__construct'>"
        "<mjx-container><svg></svg></mjx-container>"
        "<mjx-assistive-mml><math data-semantic-type='empty'/></mjx-assistive-mml>"
        "</span> more text.</p></section></article></body></html>"
    )

    markdown, _, counters = page2md._section_markdown(html)

    assert counters["math_total"] == 0, counters
    assert counters["math_failed"] == 0, counters
    assert counters["mathjax_graphics"] == 1, counters
    assert "more text" in markdown


def test_the_warning_names_the_drawings_instead_of_a_failed_conversion() -> None:
    warnings = page2md._warnings({"math_total": 0, "mathjax_graphics": 6})

    assert any("MathJax" in item for item in warnings), warnings
    assert not any("没有 MathML 公式" in item for item in warnings), warnings


def test_a_page_without_any_formula_keeps_the_old_warning() -> None:
    warnings = page2md._warnings({"math_total": 0, "mathjax_graphics": 0})

    assert any("没有 MathML 公式" in item for item in warnings), warnings


def test_the_real_sample_reports_drawings(tmp_path: Path) -> None:
    """The Wiley capture that started this: 6 drawings, 0 convertible formulas."""

    sample = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "pages"
    if not sample.is_dir():  # fixtures are optional in a source checkout
        return
