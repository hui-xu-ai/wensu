"""Parse a CNKI article detail page (2026.10 layout).

The header is a list of ``li.top-space`` rows (DOI, 专辑, 专题, 分类号,
网络出版时间, …), authors live in ``h3.author``, and the abstract is
``#ChDivSummary``. Volume/issue/pages only exist for print issues; online-first
articles have a publication date instead.
"""

from __future__ import annotations

import datetime as dt
import re

from bs4 import BeautifulSoup, Tag

from ....core.contracts import Record
from ....core.errors import ParseError
from . import doc_types
from .selectors import DETAIL

_SUFFIX = re.compile(r"\s*(?:附视频|[（(](?:视频|网络首发|优先出版)[）)])\s*$")
_YEAR = re.compile(r"(19|20)\d{2}")
_AFFILIATION_MARK = re.compile(r"[\d,，\s]+$")
_TIME_KEYS = ("在线公开时间", "网络出版时间", "出版时间", "发表时间")

# A word split across a PDF line arrives as `驱-动`. Only the CJK-CJK case is joined:
# in `F-P-θ` or `Mo-S-O` the hyphen is part of the name and must survive.
_CJK_HYPHEN = re.compile(r"([\u4e00-\u9fff])-\s*([\u4e00-\u9fff])")

# Dissertation DOIs look like 10.27009/d.cnki.gdblu.2026.000024 — the four digits
# before the sequence number are the degree year.
_THESIS_DOI_YEAR = re.compile(r"/d\.cnki\.[a-z0-9]+\.(19\d{2}|20\d{2})\.", re.IGNORECASE)

# The journal header links to the journal database page; theses/conferences do not.
_JOURNAL_HINT = "查看该刊"

# Print issues put the citation line in ``.top-first``:
#   力学学报 . 2022 ,54 (01) : 184-195 查看该刊数据库收录来源
_TOP_LINE = re.compile(
    r"\.\s*(?P<year>(?:19|20)\d{2})\s*,\s*(?P<volume>\d+)\s*"
    r"(?:\((?P<issue>[^)]*)\))?\s*:\s*(?P<pages>[0-9\-–,]+)"
)


def _text(node: Tag | None) -> str | None:
    if node is None:
        return None
    value = node.get_text(" ", strip=True)
    return value or None


def _clean_title(value: str) -> str:
    return _SUFFIX.sub("", value).strip()


def _rows(soup: BeautifulSoup) -> dict[str, str]:
    rows: dict[str, str] = {}
    for item in soup.select("li.top-space"):
        label = item.select_one(".rowtit")
        value = item.select_one("p")
        if label is None or value is None:
            continue
        key = re.sub(r"[：:\s]", "", label.get_text())
        text = value.get_text(" ", strip=True)
        if key and text:
            rows[key] = text
    return rows


def _pick(rows: dict[str, str], *needles: str) -> str | None:
    """Exact label first, then substring.

    Substring-only matching let "卷" match "卷期" and returned whichever entry
    happened to come first, so volume and issue could be swapped. A label that
    matches exactly now wins.
    """

    if len(needles) == 1:
        target = needles[0]
        for key, value in rows.items():
            if key.strip() == target:
                return value
    for key, value in rows.items():
        if all(needle in key for needle in needles):
            return value
    return None


def _authors(soup: BeautifulSoup) -> tuple[list[str], str | None]:
    blocks = soup.select("h3.author")
    if not blocks:
        return [], None

    authors: list[str] = []
    for link in blocks[0].select("a"):
        name = _AFFILIATION_MARK.sub("", link.get_text(strip=True))
        if name and "@" not in name:
            authors.append(name)
    institution = _text(blocks[1]) if len(blocks) > 1 else None
    return authors, institution


def _source(soup: BeautifulSoup) -> tuple[str | None, str]:
    """The journal name, or the awarding institution for a thesis.

    Journal pages read `机械设计 . 2026 ,43 (11) : 21-26`, so the name is everything
    before the ` . ` separator. Thesis pages have no citation at all — the same node
    holds `东北林业大学 黑龙江省 211工程院校 教育部直属院校`, which used to be returned
    whole as if it were a journal name. There the name is the first word.
    """

    node = soup.select_one(".top-first")
    if node is None:
        return None, ""
    value = node.get_text(" ", strip=True)
    if " . " in value:
        source = value.split(" . ")[0].strip()
    else:
        words = value.split()
        source = words[0] if words else ""
    return source or None, value

def _abstract(soup: BeautifulSoup) -> str | None:
    """The complete abstract, preferring the hidden input CNKI keeps for it.

    The page holds two copies:

    * `input#abstract_text` — the full text in its `value` attribute, with real
      newlines between paragraphs and no ellipsis;
    * `span#ChDivSummary` — the visible preview, cut at a few hundred characters and
      ending in `...` with a「更多」control beside it.

    Reading the span gave every caller a truncated abstract while the complete one
    sat in the same document. The input is tried first; the span stays as a fallback
    for pages that ship only the visible copy.

    CNKI stores the text lifted from the PDF, so a word split across a line arrives
    as `驱-动`. Removing the hyphen between two CJK characters fixes that without
    touching `F-P-θ` or `Mo-S-O`, where the hyphen is part of the formula.
    """

    hidden = soup.select_one("#abstract_text")
    if hidden is not None:
        value = hidden.get("value")
        if isinstance(value, str) and value.strip():
            return _CJK_HYPHEN.sub(r"\1\2", value).strip()

    node = soup.select_one(DETAIL["abstract"])
    if node is None:
        return None
    text = node.get_text(" ", strip=True)
    if not text:
        return None
    return _CJK_HYPHEN.sub(r"\1\2", text)


def _document_type(soup: BeautifulSoup) -> str | None:
    # A labelled type field outranks a compact header. Funding, subjects and
    # source names are not type fields, even when they contain type words.
    for label, value in _rows(soup).items():
        if label in doc_types.LABELS and (token := doc_types.normalize(value)) is not None:
            return token
    for selector in (".doc-top", ".top-tip", ".top-first"):
        for node in soup.select(selector):
            if (token := doc_types.normalize(node.get_text(" ", strip=True))) is not None:
                return token
    return None


def parse(html: str, url: str) -> Record:
    soup = BeautifulSoup(html, "lxml")

    # A bare <h1> is not enough: error pages ("Service unavailable") have one.
    titled = soup.select_one(DETAIL["title"])
    if titled is None and soup.select_one(DETAIL["abstract"]) is None:
        raise ParseError("detail page has no article header or abstract")
    title_node = titled or soup.select_one("h1")
    raw_title = _text(title_node)
    if not raw_title:
        raise ParseError("detail page has no title")
    title = _clean_title(raw_title)

    authors, institution = _authors(soup)
    rows = _rows(soup)

    doi = _pick(rows, "DOI")
    published = next((rows[key] for key in _TIME_KEYS if key in rows), None)
    year = None
    if published:
        match = _YEAR.search(published)
        year = int(match.group()) if match else None

    doc_type = _document_type(soup)
    source, top_line = _source(soup)
    volume = issue = pages = None
    match = _TOP_LINE.search(top_line)
    if match:
        year = year or int(match.group("year"))
        # A concrete volume/issue/pages citation is journal evidence, but it must
        # not overrule an explicit type word: CNKI stamps conference papers with
        # "文献类型：会议" while still showing a proceedings citation with volume and
        # pages. Overwriting here exported conference papers as journal articles.
        if doc_type is None:
            doc_type = "journal"
        volume = match.group("volume")
        issue = match.group("issue")
        pages = match.group("pages")
    elif _JOURNAL_HINT in top_line and doc_type is None:
        # Online-first journal articles carry no volume/issue; this link text is
        # article-level structural evidence, not body text.
        doc_type = "journal"

    if doc_type is None and doi and "/d.cnki." in doi.casefold():
        # CNKI dissertation DOIs use the /d.cnki. namespace.
        doc_type = "thesis"

    if year is None and doi:
        # A thesis page carries no publication-time row and no citation line, but
        # its DOI is shaped d.cnki.<school>.<year>.<seq> — the same year the list row
        # shows. Without this, `year` was present in search results and null in the
        # detail for the very same record. Only used as a fallback, and only for the
        # dissertation namespace, so a journal DOI cannot override a real date.
        thesis_year = _THESIS_DOI_YEAR.search(doi)
        if thesis_year is not None:
            year = int(thesis_year.group(1))

    keywords = [
        link.get_text(strip=True).strip(";；,，、")
        for link in soup.select("p.keywords a")
        if link.get_text(strip=True)
    ]

    abstract = _abstract(soup)

    return Record(
        channel="cnki",
        title=title,
        authors=authors,
        institution=institution,
        source=source,
        year=year,
        volume=volume or _pick(rows, "卷"),
        issue=issue or _pick(rows, "期"),
        pages=pages or _pick(rows, "页"),
        doi=doi,
        abstract=abstract,
        keywords=keywords,
        url=url,
        doc_type=doc_type,
        # Stamped here because this is the moment the page was read. Without it a
        # CNKI detail carried `fetched_at: null` while a Web of Science one carried a
        # timestamp, and a caller had no way to tell a fresh record from a stale one
        # or to know whether the cache had served it.
        fetched_at=dt.datetime.now(dt.UTC),
    )
