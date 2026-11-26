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

# Markers that mean the body itself is behind a wall. These decide even when the page looks like an
# article: a `<section>` wrapper around an abstract is not a body.
BLOCKING_PAYWALL_MARKERS: tuple[str, ...] = (
    "purchase pdf",
    "sign in to view",
    "buy article",
    "rent this article",
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
# How much may follow the marker and still be a site name rather than an article title. Same value
# `risk._title_is_gate` uses, so the two rules cannot drift apart again.
_TITLE_TAIL_CHARS = 32


def challenge_in_title(title: str) -> str | None:
    """The marker that made this title a wall, or None. Never captures anything.

    An exact match always counts. A prefix match counts only when the remainder looks like a site
    name — short, and free of CJK — which is the rule `risk._title_is_gate` already applies. A
    plain substring match was too wide: an article titled "Loading: Just a moment please — Journal
    of the American Chemical Society" was reported as a wall (measured 2026-11-26, T0 1c).
    """

    text = " ".join((title or "").split()).casefold()
    if not text:
        return None
    for marker in CHALLENGE_TITLES:
        if text == marker:
            return marker
        if not text.startswith(marker):
            continue
        tail = text[len(marker) :]
        if any("\u4e00" <= char <= "\u9fff" for char in tail):
            continue
        if len(tail) <= _TITLE_TAIL_CHARS:
            return marker
    return None


# A DOI that does not resolve lands on the publisher's own error page instead of an article.
# Elsevier renders `<h1>Error: DOI Not Found</h1>` / `<title>Error: DOI Not Found</title>`
# (measured 2026-11-25 with `10.1016/j.snb.2026.000001`). Such a page has none of the article's
# structure, so the rules below classified it `abstract_only` — "ask the user to sign in" — and
# the 267 KB of error page was kept as if it were the article. It is neither a paywall nor a
# preview: the identifier itself is wrong, and no session changes that.
DOI_NOT_FOUND_MARKERS: tuple[str, ...] = (
    "doi not found",
    "doi cannot be found",
    "the doi you requested",
    "article not found",
)


def doi_not_found_in(title: str) -> str | None:
    """The marker that made this page a "no such DOI" answer, or None."""

    lowered = (title or "").strip().lower()
    if not lowered:
        return None
    for marker in DOI_NOT_FOUND_MARKERS:
        if marker in lowered:
            return marker
    return None


_META_TAG = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_META_CONTENT = re.compile(r"""content\s*=\s*["']([^"']*)""", re.IGNORECASE)


def meta_content(markup: str, name: str) -> str:
    """The `content` of the page's own `<meta name="…">`, or "".

    Publishers print facts about the page in machine-readable tags. Reading the page's own claim
    is how a capture can be identified without trusting the tab's address, and how a full-text
    view can be found without hard-coding one URL shape per publisher.
    """

    for tag in _META_TAG.findall(markup):
        if name not in tag.casefold():
            continue
        found = _META_CONTENT.search(tag)
        if found:
            return found.group(1).strip()
    return ""


def citation_doi(path: Path) -> str:
    """The DOI the page says it is, from its own `<meta name="citation_doi">`, or "".

    Publishers print the identifier in the page, but not always in the URL: ACS landing pages
    read `/jacsat/article/146/41/28131/…` with no DOI in sight (measured 2026-11-26). Reading the
    page's own claim is what lets a capture be identified without trusting the tab's address.
    """

    try:
        raw = _html_of(path)
    except OSError:
        return ""
    return meta_content(raw, "citation_doi")


def citation_fulltext_url(path: Path) -> str:
    """The page's own full-text HTML address, from `<meta name="citation_fulltext_html_url">`.

    Nearly every Highwire-style publisher prints it (measured 2026-11-26 on a Wiley page:
    `https://onlinelibrary.wiley.com/doi/full/10.1002/chem.201901671`). A landing page that only
    shows the abstract therefore carries the address of the view that has the body — a per-page
    fact, which beats a per-publisher URL template table that has to be guessed and maintained.
    """

    try:
        raw = _html_of(path)
    except OSError:
        return ""
    return meta_content(raw, "citation_fulltext_html_url")


SECTION_MARKERS: tuple[str, ...] = ('class="section-title"', "<section id=")
# Without a numbered heading, only a page that wraps this many sections is still trusted as
# the article itself; fewer means "abstract shell" (or "still rendering", see service.py).
FULL_TEXT_SECTIONS = 6
# The Nature-style shape: an `<article>` element and several unnumbered headings.
BODY_HEADINGS = 6

# A real body — letter or not — is many long paragraphs. An abstract page has one or two. These are
# the numbers the classifier actually trusts, because section headings do not exist in Letter /
# Communication formats (measured 2026-11-25: `10.1021/acs.inorgchem.1c03019` holds 19 long
# paragraphs and 3,817 words, and has no headings at all).
PROSE_PARAGRAPH_WORDS = 25
PROSE_WORDS = 1_200
PROSE_PARAGRAPHS = 5
_PARAGRAPH = re.compile(r"(?is)<p[^>]*>(.*?)</p>")

# Section names a real article body has. Two of them in the prose is the cheapest honest evidence
# that the page is the paper and not a landing page with headings.
ARTICLE_SECTION_NAMES: tuple[str, ...] = (
    "introduction",
    "experimental section",
    "results and discussion",
    "results",
    "discussion",
    "conclusion",
    "materials and methods",
    "methods",
)
_ARTICLE_TAG = re.compile(r"<article[ >]", re.IGNORECASE)
_BODY_HEADING = re.compile(r"<h[23][ >]", re.IGNORECASE)
# `<h2>1. Introduction</h2>` / `<h3><span>2.3</span> Method</h3>`: the article's own numbering.
_NUMBERED_HEADING = re.compile(
    r"<h[1-3][^>]*>(?:\s|<[^>]+>)*[1-9]\d?\.?(?:&#xA0;|&nbsp;|\s)+[A-Z]",
    re.IGNORECASE,
)
_PDF_LINK = re.compile(r'href="(https?://[^"]+?\.pdf[^"]*)"', re.IGNORECASE)
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_DOC_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
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
    doc_title = _DOC_TITLE.search(raw)
    document_title = _text_of(doc_title.group(1))[:300] if doc_title else ""

    # Prose volume, not headings: a Letter / Communication has no section headings at all, and
    # counting them reported "no body" for a page holding 3,817 words of continuous text
    # (measured 2026-11-25 on `10.1021/acs.inorgchem.1c03019` — the reader was right and the rule
    # was wrong). A paywall or an abstract page has a couple of short paragraphs; a real article,
    # letter or not, has many long ones.
    paragraphs = _PARAGRAPH.findall(lowered)
    long_paragraphs = [
        _text_of(match)
        for match in paragraphs
        if len(_text_of(match).split()) >= PROSE_PARAGRAPH_WORDS
    ]
    prose_words = sum(len(item.split()) for item in long_paragraphs)
    has_prose = prose_words >= PROSE_WORDS and len(long_paragraphs) >= PROSE_PARAGRAPHS

    # Blocking markers mean the body is behind a wall. These decide even when the page looks like an
    # article: a `<section>` wrapper around an abstract is not a body.
    blocking = sum(1 for marker in BLOCKING_PAYWALL_MARKERS if marker in _text_of(lowered))

    counts = {
        "sections": sections,
        "headings": headings,
        "article_tags": article_tags,
        "body_headings": body_headings,
        "paywall_hits": hits,
        "blocking_hits": blocking,
        "prose_words": prose_words,
        "prose_paragraphs": len(long_paragraphs),
        "pdf_url": pdf_url,
        "title": title,
    }
    # Cloudflare writes `ray id` into ordinary pages too, so the body markers only mean a wall when
    # there is no prose to speak of. A page with a body is a page, whatever its comments say.
    signal = _challenge_signal(lowered, url) if prose_words < PROSE_WORDS else ""
    if signal:
        return {"status": "blocked", "reason": "challenge", "signal": signal, **counts}

    # A page that answers "there is no such DOI" is not a page that holds the article's
    # abstract: it holds nothing. Decided before the structure rules, because those rules can
    # only describe *why* an article is missing, and here none of their reasons is true.
    if doi_not_found_in(f"{title} {document_title}"):
        return {"status": "no_html", "reason": "doi_not_found", **counts}

    # An abstract page still carries `<section id=` wrappers (highlights, related work), so
    # counting them called a ScienceDirect abstract page `ok` while holding no article body
    # (0.12.58, real run). A numbered article heading ("1. Introduction") is the honest
    # signal: an abstract page has none. When the page is the article, keep `ok` even if a
    # publisher prints a price somewhere.
    # Not every marker blocks the text. "Purchase PDF" / "Sign in to view" mean the body is behind
    # an access wall, so they decide on their own. "Access through your organization" and
    # "institutional access" are printed in the sidebar of pages an entitled reader is already
    # reading — measured 2026-11-25 on `10.1002/anie.202005087` (Wiley): a capture holding
    # Abstract / Introduction / Results and Discussion / Conclusion with `body_headings: 41` was
    # reported `no_html` / `paywall` because of one such mention, and the reader was told the tool
    # could not capture an article that was right there.
    blocking = sum(1 for marker in BLOCKING_PAYWALL_MARKERS if marker in _text_of(lowered))
    # A page shell can carry plenty of `<h2>` — navigation, "Supporting Information", "Figures" —
    # without any of the article's own sections. Measured 2026-11-25 on
    # `10.1021/acs.inorgchem.1c03019`: `article_tags: 2`, `body_headings: 16`, and zero body, which
    # the earlier rule happily called `ok`. Requiring two of the article's section names is what
    # separates a body from a shell.
    prose = _text_of(lowered)
    body_sections = sum(1 for name in ARTICLE_SECTION_NAMES if name in prose)
    article_shaped = sections >= FULL_TEXT_SECTIONS or (
        bool(article_tags) and body_headings >= BODY_HEADINGS and body_sections >= 3
    )
    if blocking:
        status, reason = "no_html", "paywall"
    elif has_prose or headings or article_shaped:
        status, reason = "ok", ""
    elif hits:
        status, reason = "no_html", "paywall"
    elif pdf_url:
        # The page offers the article as a file and no body at all. That is not an abstract and
        # not a permission problem — it is "this site only gives you the PDF" (2026-11-26 report:
        # such a page was reported `abstract_only`, which the caller read as "no access").
        status, reason = "no_html", "pdf_only"
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
