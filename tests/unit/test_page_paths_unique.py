"""Two articles whose titles agree on their first 80 characters landed in one directory.

`page_read` stores a capture at `<home>/pages/<slug>/page.mhtml`, and the slug was the document
title cut at 80 characters — `…Proximity-Sensing-and` in the 2026-11-25 report (P9). A follow-up
paper in the same series therefore wrote into the other one's folder: the second capture replaced
the first, and `page2md` then produced Markdown of the wrong article for the first path.

The readable part stays, because a person reads these folder names in a file manager; a short hash
of the URL makes them unique. Captures already on disk keep working: the page cache stores the
path it wrote, and nothing here rewrites it.
"""

from __future__ import annotations

from scholar_search.core.service import _page_dir_slug

SHARED_PREFIX = "A Multifunctional Ionograsper for Proximity Sensing and Actuation Part"
FIRST = {
    "title": f"{SHARED_PREFIX} I",
    "url": "https://advanced.onlinelibrary.wiley.com/doi/10.1002/adma.74981",
}
SECOND = {
    "title": f"{SHARED_PREFIX} II",
    "url": "https://advanced.onlinelibrary.wiley.com/doi/10.1002/adma.75384",
}


def test_two_articles_with_the_same_title_prefix_get_different_directories() -> None:
    assert _page_dir_slug(FIRST) != _page_dir_slug(SECOND)


def test_the_name_stays_readable() -> None:
    slug = _page_dir_slug(FIRST)

    assert slug.startswith("A-Multifunctional-Ionograsper"), slug


def test_the_name_stays_short_enough_for_a_folder() -> None:
    slug = _page_dir_slug(FIRST)

    assert len(slug) <= 72, len(slug)
    assert not slug.startswith("-") and not slug.endswith("-"), slug


def test_the_same_page_always_gets_the_same_directory() -> None:
    assert _page_dir_slug(dict(FIRST)) == _page_dir_slug(FIRST)


def test_a_page_without_a_title_falls_back_to_its_url() -> None:
    slug = _page_dir_slug({"url": FIRST["url"]})

    assert slug.startswith("https-advanced.onlinelibrary.wiley.com"), slug


def test_a_page_with_neither_still_gets_a_unique_name() -> None:
    first = _page_dir_slug({})
    second = _page_dir_slug({"title": "论文标题"})

    assert first.startswith("page-"), first
    # A title the slug rule drops entirely (CJK) still gets its own directory rather than "page".
    assert second.startswith("page-"), second
    assert first != second
