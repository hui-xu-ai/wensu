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

# A human-verification wall is neither a paywall nor an "abstract shell": it is the site
# asking for a person. Measured 2026-11-22 on Wiley (`10.1002/adma.75384`): Cloudflare
# answered the plain article URL, so the URL check below sees nothing — only these body
# markers identify it, and the tool must stop there (ADR 0004: 遇风控即停). Before this
# list existed, such a page fell through to `abstract_only`, which (a) sent the caller off
# to "sign in to the publisher" and (b) matched `_still_rendering()`, so the service took a
# *second snapshot of the wall*.
CHALLENGE_MARKERS: tuple[str, ...] = (
    "challenge-platform",
    "__cf_chl_opt",
    "__cf_chl_rt_tk",
    "cf-challenge",
    "ray id",
    "performance &amp; security by cloudflare",
    "just a moment",
    "verifying you are human",
    "checking your browser",
    "enable javascript and cookies to continue",
    "请稍候",
    "正在进行安全验证",
)
# URL features, checked first: a wall that redirects leaves them in the address bar.
CHALLENGE_URL_MARKERS: tuple[str, ...] = (
    "__cf_chl_rt_tk",
    "/cdn-cgi/challenge-platform/",
    "/challenge-platform/",
)

# Titles a wall uses. Checked on the `goto` reply, *before* anything is captured: the wall's
# bytes are not the article, capturing them costs a quota point, and — measured 2026-11-24 on
# Wiley — the capture replaces a body that had already been saved. Cloudflare titles that
# page 「请稍候…」, and the extension already reports the tab title with every `goto`, so the
# wall is recognizable for free. This list stays short and unambiguous on purpose: a false
# positive would call a readable article a wall.
CHALLENGE_TITLES: tuple[str, ...] = (
    "just a moment",
    "请稍候",
    "verifying you are human",
    "checking your browser",
    "正在进行安全验证",
    "attention required",
)


def challenge_in_title(title: str) -> str | None:
    """The marker that made this title a wall, or None. Never captures anything."""

    lowered = (title or "").strip().lower()
    if not lowered:
        return None
    for marker in CHALLENGE_TITLES:
        if marker in lowered:
            return marker
    return None


SECTION_MARKERS: tuple[str, ...] = ('class="section-title"', "<section id=")
# Without a numbered heading, only a page that wraps this many sections is still trusted as
# the article itself; fewer means "abstract shell" (or "still rendering", see service.py).
FULL_TEXT_SECTIONS = 6
# The Nature-style shape: an `<article>` element and several unnumbered headings.
BODY_HEADINGS = 6
_ARTICLE_TAG = re.compile(r"<article[ >]", re.IGNORECASE)
_BODY_HEADING = re.compile(r"<h[23][ >]", re.IGNORECASE)
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


def classify_mhtml(path: Path, *, url: str = "") -> dict[str, object]:
    """`{status, reason, signal, sections, headings, paywall_hits, pdf_url, title}`.

    A challenge wall is reported before anything else is considered: it is not a paywall,
    not an abstract shell and not a page that is still painting.
    """

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
    article_tags = len(_ARTICLE_TAG.findall(raw))
    body_headings = len(_BODY_HEADING.findall(raw))
    hits = sum(1 for marker in PAYWALL_MARKERS if marker in _text_of(lowered))

    pdf_match = _PDF_LINK.search(raw)
    pdf_url = pdf_match.group(1) if pdf_match else ""

    heading = _H1.search(raw)
    title = _text_of(heading.group(1))[:300] if heading else ""

    counts = {
        "sections": sections,
        "headings": headings,
        "article_tags": article_tags,
        "body_headings": body_headings,
        "paywall_hits": hits,
        "pdf_url": pdf_url,
        "title": title,
    }
    signal = _challenge_signal(lowered, url)
    if signal:
        return {"status": "blocked", "reason": "challenge", "signal": signal, **counts}

    # An abstract page still carries `<section id=` wrappers (highlights, related work), so
    # counting them called a ScienceDirect abstract page `ok` while holding no article body
    # (0.12.58, real run). A numbered article heading ("1. Introduction") is the honest
    # signal: an abstract page has none. When the page is the article, keep `ok` even if a
    # publisher prints a price somewhere.
    if headings:
        status, reason = "ok", ""
    elif hits:
        status, reason = "no_html", "paywall"
    elif sections >= FULL_TEXT_SECTIONS or (article_tags and body_headings >= BODY_HEADINGS):
        # Two publisher shapes count as the article itself:
        #   * plenty of `<section id=…>` wrappers (Elsevier style);
        #   * an `<article>` element with several `<h2>`/`<h3>` headings (Nature style — its
        #     sections are unnumbered and carry no `section id`, which made a full article
        #     look like an abstract shell on the 0.13.3 rule; live run on
        #     `10.1038/s41586-020-2649-2`).
        status, reason = "ok", ""
    else:
        status, reason = "no_html", "abstract_only"
    return {"status": status, "reason": reason, **counts}


def _challenge_signal(lowered_html: str, url: str) -> str:
    """Name the marker that identified a wall, or "" when the page is not one."""

    lowered_url = (url or "").casefold()
    for marker in CHALLENGE_URL_MARKERS:
        if marker in lowered_url:
            return f"url:{marker}"
    for marker in CHALLENGE_MARKERS:
        if marker in lowered_html:
            return f"body:{marker}"
    return ""
