"""A formula must not be able to inflate the Markdown.

`page2md` converts MathML with pandoc when it is installed, and with a builtin subset
converter otherwise. The builtin path used to fall back to the flattened text of the whole
tree, so a matrix or an aligned system arrived as hundreds of characters of symbol soup:
unreadable, and paid for by every consumer of the Markdown (2026-11-24). Failures now cost
one short marker, and a converted formula is cut at `MATH_MAX_CHARS` with a warning.
"""

from __future__ import annotations

from lxml import html as LH

from scholar_search import page2md


def _counters() -> dict[str, int]:
    return {
        "math_total": 0,
        "math_failed": 0,
        "math_truncated": 0,
        "tables_rendered": 0,
        "tables_skipped_inline": 0,
        "images_inline": 0,
    }


def _paragraph():
    return LH.fromstring("<p>before <math><mi>x</mi></math> after</p>")


def test_a_formula_that_cannot_be_converted_becomes_a_short_marker(monkeypatch) -> None:
    monkeypatch.setattr(page2md, "_latex_from_math_element", lambda node: "")

    counters = _counters()
    rendered = page2md._render_inline(_paragraph(), counters)

    assert "[math]" in rendered
    assert counters["math_failed"] == 1
    assert counters["math_truncated"] == 0


def test_a_very_long_formula_is_cut_at_the_budget(monkeypatch) -> None:
    monkeypatch.setattr(page2md, "_latex_from_math_element", lambda node: "x" * 500)

    counters = _counters()
    rendered = page2md._render_inline(_paragraph(), counters)

    assert len(rendered) < page2md.MATH_MAX_CHARS + 40, len(rendered)
    assert counters["math_truncated"] == 1
    assert counters["math_failed"] == 0


def test_the_placeholder_does_not_carry_the_original_tree(monkeypatch) -> None:
    """The marker is a marker: the flattened tree must not travel with it."""

    monkeypatch.setattr(page2md, "_latex_from_math_element", lambda node: "")

    rendered = page2md._render_inline(_paragraph(), _counters())

    assert len(rendered) < 60, rendered
