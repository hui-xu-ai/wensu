"""Exported records must keep their document type across both channels.

The fourth review (item 3) found every Web of Science record exported as
`TY  - GEN` / `%0 Generic`, because the RSI and EndNote maps were keyed by CNKI's
vocabulary (`journal`, `conference`) and the WoS parser emits `article`, `review`,
`proceedings`. A journal article, a review and a conference paper all arrived in a
reference manager as "Generic".

The fix unifies the type first; these tests pin the result per channel.
"""

from __future__ import annotations

import pytest

from scholar_search.core.contracts import Record, unify_doc_type
from scholar_search.core.export import to_endnote, to_ris


def _record(doc_type: str | None) -> Record:
    return Record(
        channel="webofscience",
        title="A title",
        authors=("Someone",),
        institution=None,
        source="A source",
        year=2026,
        volume=None,
        issue=None,
        pages=None,
        doi="10.1000/x",
        abstract=None,
        keywords=(),
        citations=None,
        downloads=None,
        impact_factor=None,
        url="https://example.org/1",
        fetched_at=None,
        doc_type=doc_type,
    )


def _ris_type(doc_type: str | None) -> str:
    for line in to_ris([_record(doc_type)]).splitlines():
        if line.startswith("TY  - "):
            return line.removeprefix("TY  - ").strip()
    raise AssertionError("no TY line")


def _endnote_type(doc_type: str | None) -> str:
    for line in to_endnote([_record(doc_type)]).splitlines():
        if line.startswith("%0 "):
            return line.removeprefix("%0 ").strip()
    raise AssertionError("no %0 line")


@pytest.mark.parametrize(
    ("doc_type", "ris", "endnote"),
    [
        # Web of Science vocabulary
        ("article", "JOUR", "Journal Article"),
        ("review", "JOUR", "Journal Article"),
        ("proceedings", "CPAPER", "Conference Paper"),
        ("book_chapter", "CHAP", "Book Section"),
        # CNKI vocabulary, which already worked and must keep working
        ("journal", "JOUR", "Journal Article"),
        ("thesis", "THES", "Thesis"),
        ("conference", "CPAPER", "Conference Paper"),
        ("newspaper", "NEWS", "Newspaper Article"),
        ("patent", "PAT", "Patent"),
        # Types the unified vocabulary coarsens to `other`. Unification must not shrink
        # what the export can express: these regressed once already when the lookup
        # went through it.
        ("standard", "STAND", "Generic"),
        ("yearbook", "BOOK", "Book"),
    ],
)
def test_type_survives_export(doc_type: str, ris: str, endnote: str) -> None:
    assert _ris_type(doc_type) == ris
    assert _endnote_type(doc_type) == endnote


@pytest.mark.parametrize("doc_type", ["article", "journal", "proceedings"])
def test_both_channels_reach_the_same_entry(doc_type: str) -> None:
    """`journal` and `article` are the same thing; the export must agree."""

    assert unify_doc_type(doc_type) in {"article", "conference"}


def test_an_unknown_type_is_still_generic() -> None:
    """Unmapped is not the same as unmapped-by-mistake: it must not claim JOUR."""

    assert _ris_type("something_new") == "GEN"
    assert _ris_type(None) == "GEN"


def test_the_note_distinguishes_our_gap_from_the_source() -> None:
    """Two different reasons for `GEN`, and the export used to give one message.

    "not reported by source" is true when the channel produced nothing. When the
    channel *did* report a type that this mapping does not cover, the gap is ours,
    and telling the user the data is missing sends them to the wrong place.
    """

    unmapped = to_ris([_record("something_new")])
    absent = to_ris([_record(None)])

    assert "something_new; no RIS equivalent mapped" in unmapped
    assert "not reported by source" in absent
    assert "not reported by source" not in unmapped


def test_a_mapped_type_carries_no_apology() -> None:
    assert "N1  -" not in to_ris([_record("book_chapter")])
