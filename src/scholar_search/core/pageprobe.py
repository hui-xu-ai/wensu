"""Decide whether a saved page actually holds the article.

`page_read` navigates first and captures second, so the honest question at the end is
"did that page contain the paper, or only its abstract / a paywall?". The answer comes
from the MHTML itself, with no extra browser action and no extra dependency: the counts
below are cheap markers that Elsevier-style and JATS-style pages both carry.
"""

from __future__ import annotations

import email
import re
from email import policy
from pathlib import Path

PAYWALL_MARKERS: tuple[str, ...] = (
    "purchase pdf",
    "get access",
    "access through your organization",
    "sign in to view",
    "buy article",
    "rent this article",
    "institutional access",
)

SECTION_MARKERS: tuple[str, ...] = ('class="section-title"', "<section id=")
# Without a numbered heading, only a page that wraps this many sections is still trusted as
# the article itself; fewer means "abstract shell" (or "still rendering", see service.py).
FULL_TEXT_SECTIONS = 6
# `<h2>1. Introduction</h2>` / `<h3><span>2.3</span> Method</h3>`: the article's own numbering.
_NUMBERED_HEADING = re.compile(
    r"<h[1-3][^>]*>(?:\s|<[^>]+>)*[1-9]\d?\.?(?:&#xA0;|&nbsp;|\s)+[A-Z]",
    re.IGNORECASE,
)
_PDF_LINK = re.compile(r'href="(https?://[^"]+?\.pdf[^"]*)"', re.IGNORECASE)
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_TAGS = re.compile(r"<[^>]+>")


def _html_of(path: Path) -> str:
    message = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    for part in message.walk():
        if part.get_content_type() == "text/html":
            payload = part.get_payload(decode=True)
            if not isinstance(payload, bytes):
                continue
            charset = part.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
    return ""


def _text_of(markup: str) -> str:
    return " ".join(_TAGS.sub(" ", markup).split())


def classify_mhtml(path: Path) -> dict[str, object]:
    """`{status, reason, sections, headings, paywall_hits, pdf_url, title}` for one saved page."""

    raw = _html_of(path)
    if not raw.strip():
        return {
            "status": "no_html",
            "reason": "no_html_part",
            "sections": 0,
            "headings": 0,
            "paywall_hits": 0,
        }

    lowered = raw.casefold()
    sections = sum(lowered.count(marker.casefold()) for marker in SECTION_MARKERS)
    headings = len(_NUMBERED_HEADING.findall(raw))
    hits = sum(1 for marker in PAYWALL_MARKERS if marker in _text_of(lowered))

    pdf_match = _PDF_LINK.search(raw)
    pdf_url = pdf_match.group(1) if pdf_match else ""

    heading = _H1.search(raw)
    title = _text_of(heading.group(1))[:300] if heading else ""

    # An abstract page still carries `<section id=` wrappers (highlights, related work), so
    # counting them called a ScienceDirect abstract page `ok` while holding no article body
    # (0.12.58, real run). A numbered article heading ("1. Introduction") is the honest
    # signal: an abstract page has none. When the page is the article, keep `ok` even if a
    # publisher prints a price somewhere.
    if headings:
        status, reason = "ok", ""
    elif hits:
        status, reason = "no_html", "paywall"
    elif sections >= FULL_TEXT_SECTIONS:
        # A publisher that prints unnumbered headings ("Introduction") is still a full
        # article: plenty of section wrappers and no sign-in prompt.
        status, reason = "ok", ""
    else:
        status, reason = "no_html", "abstract_only"
    return {
        "status": status,
        "reason": reason,
        "sections": sections,
        "headings": headings,
        "paywall_hits": hits,
        "pdf_url": pdf_url,
        "title": title,
    }
