#!/usr/bin/env python
"""把「已存下来的」文献网页转成 agent 能直接读的 Markdown。

输入两种形态，都来自浏览器：
  * Ctrl+S「网页，全部」→ 一个 .html + 同名 `_files/` 目录（图片/CSS 在磁盘上）；
  * `chrome.pageCapture`（M2 起）→ 单个 .mhtml（资源内联）。

输出 `<out>/page.md` + `<out>/page.html`（或 page.mhtml）+ `<out>/meta.json`，引用的图片拷进
`<out>/assets/`。`meta.json.warnings` 记录**保真度受损的地方**（公式/表格/图没能完整还原），
技能据此决定要不要提醒用户下载 PDF 复核。

抽取两路合并（样本实测单用任一路都缺内容）：
  1. 章节聚合 —— `section[@id]` 内标题 / `*[class~="section-title"]`，负责结构；
  2. trafilatura —— 负责长段落正文；
  3. 按段落去重合并；都失败才退 markitdown。

公式处理顺序：MathML(`<math>`) → LaTeX；`math/tex` 脚本原文；KaTeX `data-latex`；
`<img alt="…tex…">` 取 alt。表格 → GFM 管道表。

用法：
    python tools/page2md.py --in "<保存的页面>.html" --out work/tools/out/<slug>
    python tools/page2md.py --in <目录> --out <目录>
"""

from __future__ import annotations

import argparse
import email
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from email import policy
from pathlib import Path

TOOL_VERSION = "0.3.0-m1"
SUFFIXES = {".html", ".htm", ".mhtml", ".mht"}
NOISE = ("cookie", "subscribe", "sign in", "advertisement", "related articles", "purchase pdf")
JUNK_XPATH = "//script|//style|//noscript|//nav|//footer|//aside|//form"
BLOCK_XPATH = ".//p|.//li|.//caption|.//figcaption"
# Everything from the first of these headings onwards is dropped: it is not the paper.
BACKMATTER_MARKERS: tuple[str, ...] = (
    "references",
    "bibliography",
    "reference",
    "further reading",
    "literature cited",
    "cited by",
    "data availability",
    "data availability statement",
    "acknowledg",
    "declaration of competing",
    "competing interest",
    "conflict of interest",
    "author contribution",
    "credit authorship",
    "funding",
    "supplementary",
    "appendix",
    "about the journal",
    "related article",
    "recommended article",
)

# MathML 运算符 → LaTeX
MATH_OPS = {
    "−": "-",
    "–": "-",
    "×": r"\times",
    "·": r"\cdot",
    "÷": r"\div",
    "±": r"\pm",
    "∓": r"\mp",
    "≤": r"\le",
    "≥": r"\ge",
    "≠": r"\ne",
    "≈": r"\approx",
    "∼": r"\sim",
    "∝": r"\propto",
    "∂": r"\partial",
    "∇": r"\nabla",
    "∑": r"\sum",
    "∏": r"\prod",
    "∫": r"\int",
    "√": r"\sqrt",
    "∞": r"\infty",
    "→": r"\to",
    "←": r"\leftarrow",
    "↔": r"\leftrightarrow",
    "⇒": r"\Rightarrow",
    "∈": r"\in",
    "∉": r"\notin",
    "⊂": r"\subset",
    "∪": r"\cup",
    "∩": r"\cap",
    "α": r"\alpha",
    "β": r"\beta",
    "γ": r"\gamma",
    "δ": r"\delta",
    "ε": r"\varepsilon",
    "ζ": r"\zeta",
    "η": r"\eta",
    "θ": r"\theta",
    "κ": r"\kappa",
    "λ": r"\lambda",
    "μ": r"\mu",
    "ν": r"\nu",
    "ξ": r"\xi",
    "π": r"\pi",
    "ρ": r"\rho",
    "σ": r"\sigma",
    "τ": r"\tau",
    "φ": r"\varphi",
    "χ": r"\chi",
    "ψ": r"\psi",
    "ω": r"\omega",
    "Δ": r"\Delta",
    "Σ": r"\Sigma",
    "Ω": r"\Omega",
    "Φ": r"\Phi",
    "Ψ": r"\Psi",
    "Γ": r"\Gamma",
    "Λ": r"\Lambda",
    "Θ": r"\Theta",
    "Π": r"\Pi",
}


# --------------------------------------------------------------------------- 读入


def _read_html(path: Path) -> tuple[str, str]:
    """返回 (html 文本, 形态标签)。.mhtml 里挑第一个 text/html 部分。"""

    if path.suffix.lower() in {".mhtml", ".mht"}:
        message = email.message_from_bytes(path.read_bytes(), policy=policy.default)
        for part in message.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace"), "mhtml"
        raise SystemExit(f"page2md: {path.name} 里没有 text/html 部分")
    return path.read_text(encoding="utf-8", errors="replace"), "html"


# ------------------------------------------------------------------- 公式与行内渲染


def _text(node) -> str:
    return " ".join(node.text_content().split())


def _mathml_to_latex(node) -> str:
    """MathML → LaTeX 子集。

    覆盖 mrow/mi/mn/mo/msup/msub/msubsup/mfrac/msqrt/mroot/mfenced/mtext/mtable。
    """

    tag = node.tag if isinstance(node.tag, str) else ""

    def children_latex(element) -> str:
        return "".join(_mathml_to_latex(child) for child in element if isinstance(child.tag, str))

    if tag in {"math", "mrow", "semantics", "mstyle", "mpadded", "menclose"}:
        return children_latex(node)
    if tag == "mi":
        name = _text(node)
        return name if len(name) <= 2 else rf"\mathrm{{{name}}}"
    if tag == "mn":
        return _text(node)
    if tag == "mo":
        raw = _text(node)
        return MATH_OPS.get(raw, raw)
    if tag == "mtext":
        return rf"\text{{{_text(node)}}}"
    if tag == "msup":
        parts = [child for child in node if isinstance(child.tag, str)]
        if len(parts) == 2:
            return "{" + _mathml_to_latex(parts[0]) + "}^{" + _mathml_to_latex(parts[1]) + "}"
        return children_latex(node)
    if tag == "msub":
        parts = [child for child in node if isinstance(child.tag, str)]
        if len(parts) == 2:
            return "{" + _mathml_to_latex(parts[0]) + "}_{" + _mathml_to_latex(parts[1]) + "}"
        return children_latex(node)
    if tag == "msubsup":
        parts = [child for child in node if isinstance(child.tag, str)]
        if len(parts) == 3:
            base, sub, sup = (_mathml_to_latex(part) for part in parts)
            return f"{{{base}}}_{{{sub}}}^{{{sup}}}"
        return children_latex(node)
    if tag == "mfrac":
        parts = [child for child in node if isinstance(child.tag, str)]
        if len(parts) == 2:
            return rf"\frac{{{_mathml_to_latex(parts[0])}}}{{{_mathml_to_latex(parts[1])}}}"
        return children_latex(node)
    if tag == "msqrt":
        return rf"\sqrt{{{children_latex(node)}}}"
    if tag == "mroot":
        parts = [child for child in node if isinstance(child.tag, str)]
        if len(parts) == 2:
            return rf"\sqrt[{_mathml_to_latex(parts[1])}]{{{_mathml_to_latex(parts[0])}}}"
        return children_latex(node)
    if tag == "mfenced":
        open_token = node.get("open") or "("
        close_token = node.get("close") or ")"
        return f"{open_token}{children_latex(node)}{close_token}"
    if tag == "mtable":
        rows = [children_latex(row) for row in node if isinstance(row.tag, str)]
        return r" \begin{matrix}" + r" \\ ".join(rows) + r" \end{matrix}"
    return children_latex(node)


def _latex_from_math_element(element) -> str:
    """把一个公式节点变成 LaTeX。

    优先用 pandoc 批量转换的结果（实测在积分上下限、矩阵、括号尺寸上准确得多）；
    没有 pandoc 或没命中时退回自研的 MathML 子集转换器。
    """

    from lxml import etree

    key = etree.tostring(element, encoding="unicode")
    cached = _MATH_PANDOC.get(key)
    if cached:
        return cached
    raw = _mathml_to_latex(element).strip()
    if raw:
        return raw
    return _text(element)


_MATH_PANDOC: dict[str, str] = {}


def _strip_math_delimiters(text: str) -> str:
    """去掉 pandoc 的外层包裹：`::: {}` 围栏、`\\[...\\]`、`\\(...\\)`、`$$…$$`、`$…$`。"""

    cleaned = text.strip()
    cleaned = re.sub(r"^:::+[^\n]*", "", cleaned).strip()
    cleaned = re.sub(r":::+$", "", cleaned).strip()
    for opening, closing in ((r"\[", r"\]"), (r"\(", r"\)"), ("$$", "$$"), ("$", "$")):
        if (
            cleaned.startswith(opening)
            and cleaned.endswith(closing)
            and len(cleaned) > len(opening) + len(closing)
        ):
            return cleaned[len(opening) : -len(closing)].strip()
    return cleaned


def _prime_pandoc(doc, limit: int = 500) -> int:
    """一次 pandoc 调用把整页 MathML 批量转成 LaTeX，填进 `_MATH_PANDOC`。返回转换成功的条数。"""

    from lxml import etree

    _MATH_PANDOC.clear()
    if shutil.which("pandoc") is None:
        return 0
    keys: list[str] = []
    seen: set[str] = set()
    for node in doc.xpath("//math"):
        text = etree.tostring(node, encoding="unicode")
        if text in seen or len(text) > 20000:
            continue
        seen.add(text)
        keys.append(text)
        if len(keys) >= limit:
            break
    if not keys:
        return 0

    blocks = [f"<p>WENSUMARK{i}END</p>\n<div>{key}</div>" for i, key in enumerate(keys)]
    document = "<html><body>\n" + "\n".join(blocks) + "\n</body></html>"
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as handle:
        handle.write(document)
        path = handle.name
    try:
        completed = subprocess.run(
            ["pandoc", "-f", "html", "-t", "markdown", "--wrap=none", path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    finally:
        Path(path).unlink(missing_ok=True)
    output = completed.stdout or ""
    if "WENSUMARK" not in output:
        return 0

    for index, key in enumerate(keys):
        marker = f"WENSUMARK{index}END"
        start = output.find(marker)
        if start < 0:
            continue
        start += len(marker)
        following = output.find("WENSUMARK", start)
        chunk = output[start : following if following > 0 else len(output)]
        latex = _strip_math_delimiters(chunk)
        latex = re.sub(r"\s*\n\s*", " ", latex).strip()
        if latex:
            _MATH_PANDOC[key] = latex
    return len(_MATH_PANDOC)


def _render_inline(element, counters: dict[str, int]) -> str:
    """把节点渲染成 markdown 行内文本：公式成 `$…$`，强调/上下标保留。"""

    pieces: list[str] = []

    def walk(node) -> None:
        if isinstance(node.tag, str) and node.tag == "math":
            latex = _latex_from_math_element(node)
            counters["math_total"] += 1
            if not latex:
                counters["math_failed"] += 1
            if element is not node and node.get("display") == "block":
                pieces.append(f" $${latex}$ ")
            else:
                pieces.append(f" ${latex}$ ")
            return
        if isinstance(node.tag, str) and node.tag in {"script", "style", "noscript"}:
            return
        if isinstance(node.tag, str) and node.tag == "img":
            source = node.get("src") or ""
            alt = re.sub(r"[\[\]()\r\n]+", " ", node.get("alt") or "image").strip()[:120]
            if source and not source.startswith("data:"):
                pieces.append(f"![{alt}]({source})")
            counters["images_inline"] += 1
            return
        if isinstance(node.tag, str) and node.tag == "table":
            counters["tables_skipped_inline"] += 1
            return
        if isinstance(node.tag, str) and node.tag in {"em", "i"}:
            inner = "".join(
                _render_inline(child, counters) for child in node if isinstance(child.tag, str)
            )
            inner = inner or _text(node)
            pieces.append(f" *{inner.strip()}* ")
            return
        if isinstance(node.tag, str) and node.tag in {"strong", "b"}:
            inner = "".join(
                _render_inline(child, counters) for child in node if isinstance(child.tag, str)
            )
            inner = inner or _text(node)
            pieces.append(f" **{inner.strip()}** ")
            return
        if isinstance(node.tag, str) and node.tag == "sub":
            inner = "".join(
                _render_inline(child, counters) for child in node if isinstance(child.tag, str)
            )
            pieces.append(f"<sub>{inner.strip() or _text(node)}</sub>")
            return
        if isinstance(node.tag, str) and node.tag == "sup":
            inner = "".join(
                _render_inline(child, counters) for child in node if isinstance(child.tag, str)
            )
            pieces.append(f"<sup>{inner.strip() or _text(node)}</sup>")
            return

        if node.text:
            pieces.append(node.text)
        for child in node:
            if isinstance(child.tag, str):
                walk(child)
            if child.tail:
                pieces.append(child.tail)

    if element.text:
        pieces.append(element.text)
    for child in element:
        if isinstance(child.tag, str):
            walk(child)
        if child.tail:
            pieces.append(child.tail)

    text = "".join(pieces)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)  # 行内块里的换行一律拍平成空格
    text = re.sub(r"\s+([,.;:)\]])", r"\1", text)
    return text.strip()


def _table_markdown(table, counters: dict[str, int]) -> str:
    """`<table>` → GFM 管道表；`<math>` 等行内元素照常转换。"""

    rows: list[list[str]] = []
    for row in table.xpath(".//tr"):
        cells = row.xpath("./th|./td")
        if not cells:
            continue
        rendered: list[str] = []
        for cell in cells:
            span = 1
            try:
                span = max(1, min(20, int(cell.get("colspan") or 1)))
            except ValueError:
                span = 1
            value = _render_inline(cell, counters).replace("|", r"\|").strip() or " "
            rendered.append(value)
            rendered.extend([" "] * (span - 1))
        rows.append(rendered)
    if len(rows) < 1:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [" "] * (width - len(row)) for row in rows]
    header, body = rows[0], rows[1:]
    counters["tables_rendered"] += 1
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join([" --- "] * width) + "|"]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


# --------------------------------------------------------------------- 章节聚合


BLOCK_CONTAINER_XPATH = "./div|./p|./section|./table|./ol|./ul|./figure|./figcaption|./dl"


def _own_blocks(section) -> list[str]:
    """按文档顺序把 section 变成 markdown 块；跳过嵌套 section（外层不吞子节）。

    为什么不能只扫 `<p>`：实测这份 Elsevier 全文里 `<p>` 只有 13 个、**0 个含公式**，
    114 个公式散在 `div`/`span` 里。所以这里递归下钻，只要"块级容器里最内层"的节点。
    """

    counters = {
        "math_total": 0,
        "math_failed": 0,
        "tables_rendered": 0,
        "tables_skipped_inline": 0,
        "images_inline": 0,
    }
    blocks: list[str] = []

    def walk(element) -> None:
        for child in element:
            if not isinstance(child.tag, str):
                continue
            tag = child.tag
            if tag == "figure":
                markdown = _figure_block(child)
                if markdown:
                    blocks.append(markdown)
                continue
            if tag in {"script", "style", "noscript", "form", "button"}:
                continue
            if tag == "table":
                markdown = _table_markdown(child, counters)
                if markdown:
                    blocks.append(markdown)
                continue
            if tag in {"h1", "h2", "h3", "h4"}:
                continue  # 标题由 _section_entries 负责
            if (
                tag == "section"
                and child.get("id")
                and child.xpath(".//*[self::h1 or self::h2 or self::h3][1]")
            ):
                continue  # 有标题的子节会被独立枚举，这里跳过去免得内容被外层吞掉
            if child.xpath(BLOCK_CONTAINER_XPATH):
                walk(child)
                continue
            text = _render_inline(child, counters)
            if len(text) < 2 or text.lower().startswith("download"):
                continue
            # 整块基本只有一个公式（可能带 "(4)" 这类编号）→ 输出行间公式
            single = re.fullmatch(
                r"(?P<pre>[^$]{0,12}?)(?P<math>\$[^$]{2,}\$)(?P<post>[^$]{0,12}?)", text
            )
            if single and len(text) < 800:
                latex = single.group("math").strip("$ ")
                label = " ".join(
                    part
                    for part in (single.group("pre").strip(), single.group("post").strip())
                    if part
                )
                blocks.append(f"$${latex}$$" + (f" {label}" if label else ""))
                continue
            if len(text) >= 12:
                blocks.append(text)

    walk(section)
    _OWN_COUNTERS.update(
        {key: _OWN_COUNTERS.get(key, 0) + value for key, value in counters.items()}
    )
    return blocks


_OWN_COUNTERS: dict[str, int] = {}
_LAST_SECTIONS: list[tuple[str, int, list[str]]] = []


def _section_entries(doc) -> list[tuple[str, int, list[str]]]:
    entries: list[tuple[str, int, list[str]]] = []
    seen_titles: set[str] = set()

    for section in doc.xpath("//section[@id]"):
        heads = section.xpath(".//*[self::h1 or self::h2 or self::h3][1]")
        if not heads:
            continue
        title = _text(heads[0])
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        level = 2 if heads[0].tag in {"h1", "h2"} else 3
        entries.append((title, level, _own_blocks(section)))

    for title_element in doc.xpath('//*[contains(@class, "section-title")]'):
        title = _text(title_element)
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        container = title_element.getparent()
        level = 2 if title_element.tag in {"h1", "h2"} else 3
        paragraphs = _own_blocks(container) if container is not None else []
        if not paragraphs and container is not None:
            sibling = container.getnext()
            while sibling is not None and len(paragraphs) < 40:
                if sibling.xpath('.//*[contains(@class, "section-title")]'):
                    break
                paragraphs.extend(_own_blocks(sibling))
                sibling = sibling.getnext()
        entries.append((title, level, paragraphs))

    # Elsevier puts the abstract and the highlights outside any `<section>`: the abstract
    # is `div.abstract` (with the heading as a `section-title` sibling that the walk above
    # never reaches), the highlights are `div.author-highlights` with `<li>` bullets. Both
    # are the cheapest part of the paper to read, so they are pulled in explicitly.
    front: list[tuple[str, int, list[str]]] = []
    for highlight_block in doc.xpath(
        '//*[contains(@class, "author-highlights") or contains(@class, "highlights")]'
    )[:1]:
        bullets = [_text(item) for item in highlight_block.xpath(".//li") if len(_text(item)) >= 12]
        if bullets:
            front.append(("Highlights", 2, bullets))
    if "abstract" not in {title.casefold() for title, _level, _items in entries}:
        for abstract_block in doc.xpath('//*[contains(@class, "abstract")]')[:1]:
            paragraphs = [
                text
                for text in (_text(node) for node in abstract_block.xpath(BLOCK_XPATH))
                if len(text) >= 12
            ]
            if paragraphs:
                front.append(("Abstract", 2, paragraphs))

    return front + entries


def _normalise(text: str) -> str:
    """Fingerprint text for duplicate detection: letters and digits only, lowercased."""

    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.casefold())


def _is_backmatter(title: str) -> bool:
    """References and everything that follows them is not part of the paper's argument.

    A publisher page ends with a long bibliography, funding notes, competing-interest
    statements and "further reading" — on a real Elsevier article that tail was 60 % of the
    bytes and none of the meaning. The list is matched on the heading text, so a section
    called "References and notes" is caught as well.
    """

    lowered = re.sub(r"^[\d.\s]+", "", title).casefold()
    return any(marker in lowered for marker in BACKMATTER_MARKERS)


CORE_MARKERS: tuple[str, ...] = (
    "abstract",
    "summary",
    "highlights",
    "keywords",
    "introduction",
    "background",
    "conclusion",
    "conclusions",
    "concluding",
    "outlook",
)


def _is_core(title: str) -> bool:
    lowered = re.sub(r"^[\d.\s]+", "", title).casefold()
    return any(marker in lowered for marker in CORE_MARKERS)


def _similar(left: str, right: str) -> bool:
    """Two paragraphs that only differ by a few characters are the same paragraph.

    `_merge_markdown` deduplicated on an exact prefix, so the same sentence with one word
    changed (a citation number, a line-wrap hyphen) survived twice. That is where the
    repeated content in the first real run came from.
    """

    if not left or not right:
        return False
    if abs(len(left) - len(right)) > max(40, len(left) // 4):
        return False
    from difflib import SequenceMatcher

    return SequenceMatcher(None, left, right).quick_ratio() > 0.9 and (
        SequenceMatcher(None, left, right).ratio() > 0.85
    )


def _collect_sections(doc) -> list[tuple[str, int, list[str]]]:
    """Sections in document order, backmatter cut, near-duplicate paragraphs removed."""

    collected: list[tuple[str, int, list[str]]] = []
    fingerprints: list[str] = []
    for title, level, paragraphs in _section_entries(doc):
        if _is_backmatter(title):
            break
        kept: list[str] = []
        for text in paragraphs:
            if text == title:
                continue
            key = _normalise(text)
            # Tables, block equations and images are short after normalisation but carry
            # structure, not prose: never drop those on a length test.
            structural = text.startswith(("|", "$$", "![", "<"))
            if len(key) < 12 and not structural:
                continue
            if len(key) >= 20 and any(
                key == previous or _similar(key, previous) for previous in fingerprints
            ):
                continue
            fingerprints.append(key)
            kept.extend(_split_long(_fix_decimals(text)))
        if kept:
            collected.append((title, level, kept))
    return collected


def _cut_tail(markdown: str) -> str:
    """Drop a trailing "Recommended articles" block that the extractor merged in.

    The section walk stops at the backmatter, but trafilatura's own body still carried the
    publisher's recommendation widgets: the acceptance run found ~60 lines of another
    paper's abstract at the end of `page.md`.
    """

    lowered = markdown.casefold()
    cut = len(markdown)
    for marker in _TAIL_MARKERS:
        position = lowered.find("## " + marker)
        if position < 0:
            position = lowered.find(marker)
        if 0 <= position < cut:
            cut = position
    return markdown[:cut].rstrip() + "\n" if cut < len(markdown) else markdown


def _dedupe_blocks(markdown: str) -> str:
    """Drop paragraphs that repeat one already kept.

    Two extractors are merged, so the same sentence can arrive twice with a different
    literal (a citation number, a soft hyphen). Comparing on the normalised form catches
    those, which the earlier exact-prefix check did not: the first real page carried 14
    repeated paragraphs out of 108.
    """

    kept: list[str] = []
    fingerprints: list[str] = []
    for block in markdown.split("\n\n"):
        text = block.strip()
        if not text:
            continue
        if text.startswith("#") or text.startswith("![") or text.startswith("$$"):
            kept.append(text)
            continue
        key = _normalise(text)
        if len(key) >= 20 and any(
            key == previous or _similar(key, previous) for previous in fingerprints
        ):
            continue
        if len(key) >= 20:
            fingerprints.append(key)
        kept.append(text)
    return "\n\n".join(kept)


def _section_markdown(html: str) -> tuple[str, int, dict[str, int]]:
    from lxml import html as LH

    _OWN_COUNTERS.clear()
    doc = LH.fromstring(html)
    for junk in doc.xpath(JUNK_XPATH):
        parent = junk.getparent()
        if parent is not None:
            parent.remove(junk)

    _OWN_COUNTERS["math_pandoc"] = _prime_pandoc(doc)

    sections = _collect_sections(doc)
    _LAST_SECTIONS.clear()
    _LAST_SECTIONS.extend(sections)
    blocks: list[str] = []
    characters = 0
    for title, level, paragraphs in sections:
        blocks.append(f"{'#' * level} {title}\n\n" + "\n\n".join(paragraphs))
        characters += sum(len(text) for text in paragraphs)
    return "\n\n".join(blocks), characters, dict(_OWN_COUNTERS)


# ------------------------------------------------------------------------ 图片


def _figure_block(figure) -> str:
    """单个 `<figure>` → 一行 `![caption](src)`。位置由调用方决定（正文里就地插入）。"""

    images = figure.xpath(".//img")
    if not images:
        return ""
    source = images[0].get("src") or ""
    if not source or source.startswith("data:"):
        return ""
    captions = figure.xpath('.//*[contains(@class, "caption") or self::figcaption]')
    caption = ""
    for node in captions:
        text = _text(node)
        if text and not text.lower().startswith("download"):
            caption = text
            break
    if not caption:
        caption = f"figure {figure.get('id') or ''}".strip()
    caption = re.sub(r"[\[\]()\r\n]+", " ", caption).strip()[:200] or "figure"
    return f"![{caption}]({source})"


def _figure_markdown(html: str, limit: int = 40) -> str:
    """兜底：**不在任何 section 里**的图（表头/版面图），统一收到文末。"""

    from lxml import html as LH

    doc = LH.fromstring(html)
    lines: list[str] = []
    for figure in doc.xpath("//figure[not(ancestor::section[@id])]")[:limit]:
        markdown = _figure_block(figure)
        if markdown:
            lines.append(markdown)
    return "\n\n".join(lines)


# ----------------------------------------------------------------------- 合并


def _merge_markdown(sections: str, main_body: str | None, *, min_chars: int = 60) -> str:
    if not main_body:
        return sections
    if not sections:
        return main_body

    def fingerprint(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip().lower()[:160]

    seen = {fingerprint(block) for block in sections.split("\n\n") if block.strip()}
    extra: list[str] = []
    for block in main_body.split("\n\n"):
        text = block.strip()
        if not text or text.startswith("#") or text.startswith("![") or len(text) < min_chars:
            continue
        if fingerprint(text) in seen:
            continue
        seen.add(fingerprint(text))
        extra.append(text)
    return sections + ("\n\n" + "\n\n".join(extra) if extra else "")


# ------------------------------------------------------------------------ 抽取


def _extract_body(html: str) -> tuple[str | None, dict[str, object]]:
    import trafilatura

    metadata = trafilatura.extract_metadata(html)
    info: dict[str, object] = {
        "title": getattr(metadata, "title", None),
        "authors": getattr(metadata, "author", None),
        "date": getattr(metadata, "date", None),
        "sitename": getattr(metadata, "sitename", None),
        "url": getattr(metadata, "url", None),
    }

    main_body = trafilatura.extract(
        html,
        output_format="markdown",
        include_tables=True,
        include_images=True,
        include_links=True,
        include_formatting=True,
        favor_precision=True,
    )
    info["bytes_trafilatura"] = len(main_body.encode("utf-8")) if main_body else 0

    sections, counters = "", {}
    try:
        sections, _section_chars, counters = _section_markdown(html)
    except Exception as error:
        info["sections_error"] = f"{type(error).__name__}: {error}"
    info["bytes_sections"] = len(sections.encode("utf-8"))
    info.update(counters)

    body = _cut_tail(_dedupe_blocks(_merge_markdown(sections, main_body)))
    info["engine"] = (
        "sections+trafilatura"
        if sections and main_body
        else ("sections" if sections else "trafilatura")
    )

    figures = ""
    try:
        figures = _figure_markdown(html)
    except Exception as error:
        info["figures_error"] = f"{type(error).__name__}: {error}"
    if figures:
        body = (body + "\n\n## Figures\n\n" + figures).lstrip()

    if not body:
        try:
            from markitdown import MarkItDown

            body = MarkItDown().convert_string(html, file_extension=".html").text_content
            info["engine"] = "markitdown"
        except ImportError:
            info["engine"] = "none"
            info["warning"] = "章节聚合与 trafilatura 都没取到正文，且未安装 markitdown"
    return body, info


# ------------------------------------------------------------------ 图片落盘


def _mhtml_parts(path: Path) -> dict[str, tuple[bytes, str]]:
    """MHTML 里内联的资源：`Content-Location` → (bytes, 文件名)。

    `pageCapture` 打出的 MHTML 把图片存成独立 part，而 `<img src>` 仍保留原始绝对 URL。
    要保住图片，就得按 `Content-Location` 建索引，再把 markdown 里的同 URL 换成 `assets/`。
    """

    if path.suffix.lower() not in {".mhtml", ".mht"}:
        return {}
    message = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    parts: dict[str, tuple[bytes, str]] = {}
    for part in message.walk():
        if part.get_content_maintype() == "text" and part.get_content_subtype() == "html":
            continue
        location = (part.get("Content-Location") or "").strip()
        payload = part.get_payload(decode=True)
        if not location or not isinstance(payload, bytes):
            continue
        name = location.rsplit("/", 1)[-1].split("?")[0] or "asset"
        parts[location] = (payload, name)
    return parts


def _localise_images(
    markdown: str,
    source: Path,
    out: Path,
    parts: dict[str, tuple[bytes, str]] | None = None,
) -> tuple[str, int, int]:
    assets = out / "assets"
    copied = missing = 0
    inline = parts or {}

    def rewrite(match: re.Match[str]) -> str:
        nonlocal copied, missing
        alt, target = match.group(1), match.group(2).strip()
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1].strip()
        if target in inline:
            payload, name = inline[target]
            assets.mkdir(parents=True, exist_ok=True)
            destination = assets / name
            if not destination.exists():
                destination.write_bytes(payload)
            copied += 1
            return f"![{alt}](assets/{name})"
        if re.match(r"^(https?:|data:)", target):
            return match.group(0)
        candidate = (source.parent / target).resolve()
        if not candidate.is_file():
            missing += 1
            return match.group(0)
        assets.mkdir(parents=True, exist_ok=True)
        destination = assets / candidate.name
        if not destination.exists():
            shutil.copy2(candidate, destination)
        copied += 1
        return f"![{alt}](assets/{destination.name})"

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", rewrite, markdown), copied, missing


# --------------------------------------------------------------------- 主流程


def _warnings(meta: dict[str, object]) -> list[str]:
    """保真度告警：有这些情况时，细节问题应提示用户拿 PDF 复核。"""

    found: list[str] = []
    failed = int(meta.get("math_failed") or 0)
    if failed:
        found.append(f"{failed} 个公式退化成线性文本（LaTeX 转换失败）")
    if not meta.get("math_total"):
        found.append("页面没有 MathML 公式；公式可能是图片，需看 PDF 或 OCR")
    elif not meta.get("math_pandoc"):
        found.append("公式由自研转换器渲染（未找到 pandoc），复杂公式可能失真")
    if int(meta.get("tables_skipped_inline") or 0):
        found.append(f"{meta['tables_skipped_inline']} 个表格嵌在段落里未能单独成表")
    if meta.get("images_missing"):
        found.append(f"{meta['images_missing']} 张图片在本地找不到文件")
    if meta.get("noise_hits"):
        found.append(f"疑似残留导航/广告词：{', '.join(meta['noise_hits'])}")
    return found


def _estimate_tokens(text: str) -> int:
    """Rough budget: ~4 characters per token in English, ~1.6 for CJK."""

    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    other = len(text) - cjk
    return int(cjk / 1.6 + other / 4)


_SENTENCE = re.compile(r"[^.!?。！？]+[.!?。！？]?")
# Sentence ends that are safe to split on: not after Fig./Eq./Ref./et al./e.g., and not
# immediately before a digit ("Fig. 9b" must not become "Fig." + "9b, the performance…").
_SENTENCE_END = re.compile(
    r"(?<!\bFig)(?<!\bEq)(?<!\bRef)(?<!\bal)(?<!\be\.g)(?<!\bi\.e)(?<!\bvs)(?<!\bNo)"
    r"(?<=[.!?。！？])\s+(?![\d‥])",
)
_TAIL_MARKERS = ("recommended articles", "cited by", "related articles", "further reading")
_STOPWORD_TEXT = (
    "the and for with that this from were was are has have not but its their which these those "
    "into than then also such can may using used use between under over more most only both each "
    "however therefore thus here there when while where been being does did doing our we they"
)
_STOPWORDS = frozenset(_STOPWORD_TEXT.split())


_BROKEN_DECIMAL = re.compile(r"(?<=\d)\.\s+(?=\d)")
_NUMBER_FACT = re.compile(
    r"(?:[A-Za-z]{1,3}\s*=\s*)?\d+(?:\.\d+)?(?:\s*[×x]\s*10[-−]?\d+)?\s*"
    r"(?:%|J·mol⁻¹|J/mol|K|MPa|kPa|Pa|mm|μm|nm|µm|h|min|s|mol|kg|mg|g/L|mL)",
)
_MAX_PARAGRAPH_CHARS = 1200


def _fix_decimals(text: str) -> str:
    """`30. 9%` → `30.9%`: publishers split a number across spans, and a gist that keeps the
    space both reads wrong and hides the value from a later search."""

    return _BROKEN_DECIMAL.sub(".", text)


def _split_long(text: str, limit: int = _MAX_PARAGRAPH_CHARS) -> list[str]:
    """Break a very long block at sentence ends so no reader truncates it silently.

    One paragraph in the acceptance article ran 2 443 characters; a reader capped at 2 000
    lost the two percentages at its end. Splitting keeps every number addressable.
    """

    if len(text) <= limit:
        return [text]
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text):
        candidate = (current + " " + sentence).strip()
        if len(candidate) > limit and current:
            pieces.append(current)
            current = sentence.strip()
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces or [text]


def _numbers(paragraphs: list[str], limit: int = 10) -> list[str]:
    """Verbatim numeric facts of a section, so a map can carry the constants a reader needs."""

    found: list[str] = []
    for text in paragraphs:
        for match in _NUMBER_FACT.findall(text):
            value = match.strip()
            if value and value not in found:
                found.append(value)
            if len(found) >= limit:
                return found
    return found


def _key_sentences(paragraphs: list[str], limit: int = 3) -> list[str]:
    """2–3 sentences that carry the section: numbers, domain words, and the last sentence.

    The first gist was "the first sentence", which for a methods section says nothing
    (Q6/Q10 of the acceptance were lost exactly there). Scoring the sentences keeps the
    verbatim text and still fits a map.
    """

    joined = " ".join(paragraphs)
    sentences = [s.strip() for s in _SENTENCE_END.split(joined) if len(s.strip()) > 30]
    if not sentences:
        return []
    keywords = set(_keywords(paragraphs, limit=12))
    scored: list[tuple[float, int, str]] = []
    for index, sentence in enumerate(sentences):
        score = 0.0
        if re.search(r"\d", sentence):
            score += 2.0
        lowered = sentence.casefold()
        score += sum(0.5 for word in keywords if word in lowered)
        if any(
            word in lowered
            for word in ("assum", "neglect", "ideal", "hypothes", "model", "constant")
        ):
            score += 2.5
        if index == 0:
            score += 0.5
        if index == len(sentences) - 1:
            score += 0.3
        scored.append((score, index, sentence))
    top = sorted(scored, key=lambda item: (-item[0], item[1]))[:limit]
    return [sentence for _score, _index, sentence in sorted(top, key=lambda item: item[1])]


def _gist(paragraphs: list[str], limit: int = 200) -> str:
    """One-line "what is this section about", built only from sentences that exist.

    No rewriting: the first sentence, any sentence carrying a number, and the last one.
    A reader can decide from this whether the section is worth its tokens. Truncation only
    happens at a sentence end, so a value is never cut in half.
    """

    if not paragraphs:
        return ""
    sentences = [s.strip() for s in _SENTENCE.findall(" ".join(paragraphs)) if s.strip()]
    if not sentences:
        return ""
    picked = [sentences[0]]
    for sentence in sentences[1:-1]:
        if re.search(r"\d", sentence) and sentence not in picked:
            picked.append(sentence)
            break
    if len(sentences) > 1:
        picked.append(sentences[-1])
    gist = " ".join(dict.fromkeys(picked)).strip()
    if len(gist) <= limit:
        return gist
    cut = gist.rfind(". ", 0, limit)
    if cut > 0:
        return gist[: cut + 1].strip()
    # No sentence ends before the limit: take the next one instead of cutting mid-word,
    # otherwise a gist ends with "…synergistically enha".
    following = gist.find(". ", limit)
    if 0 < following < limit * 2:
        return gist[: following + 1].strip()
    return gist[:limit].strip()


def _keywords(paragraphs: list[str], limit: int = 8) -> list[str]:
    """Frequency keywords, no model: ASCII words ≥4 letters and CJK bigrams."""

    text = " ".join(paragraphs).casefold()
    counts: dict[str, int] = {}
    for word in re.findall(r"[a-z][a-z-]{3,}", text):
        if word in _STOPWORDS:
            continue
        counts[word] = counts.get(word, 0) + 1
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        for index in range(len(run) - 1):
            bigram = run[index : index + 2]
            counts[bigram] = counts.get(bigram, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [word for word, count in ranked[:limit] if count >= 2]


def _flat_paragraphs(sections: list[tuple[str, int, list[str]]]) -> list[str]:
    return [text for _title, _level, paragraphs in sections for text in paragraphs]


def _figures_of(sections: list[tuple[str, int, list[str]]]) -> list[dict[str, str]]:
    """Figure labels and captions, so a map can answer "what does Fig. 5 show"."""

    found: list[dict[str, str]] = []
    for title, _level, paragraphs in sections:
        for text in paragraphs:
            match = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", text)
            if not match:
                continue
            caption = " ".join(match.group(1).split())
            label = re.match(r"(Fig(?:ure)?\.?\s*\d+[a-z]?)", caption, re.IGNORECASE)
            found.append(
                {
                    "label": label.group(1) if label else f"figure-{len(found) + 1}",
                    "caption": caption[:120],
                    "section": title,
                }
            )
    return found


def _write_brief(out: Path, sections: list[tuple[str, int, list[str]]], title: str) -> None:
    """`page.brief.md`: the map in one small file (title + one gist per section)."""

    lines = [f"# {title}", ""]
    for index, (section_title, level, paragraphs) in enumerate(sections, start=1):
        gist = _gist(paragraphs)
        marks = f"[{index:02d}] {'#' * level} {section_title} — {len(' '.join(paragraphs))} chars"
        lines.append(marks)
        if gist:
            lines.append(f"  {gist}")
        for sentence in _key_sentences(paragraphs, limit=2):
            lines.append(f"  · {sentence}")
        numbers = _numbers(paragraphs)
        if numbers:
            lines.append("  values: " + " | ".join(numbers))
    figures = _figures_of(sections)
    if figures:
        lines.extend(["", f"## Figures ({len(figures)})"])
        for figure in figures:
            lines.append(f"  {figure['label']} [{figure['section']}] {figure['caption']}")
    (out / "page.brief.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_selection(
    out: Path,
    sections: list[tuple[str, int, list[str]]],
    *,
    query: str = "",
    window: str = "",
) -> None:
    """`--slice a:b` / `--query text` → `page.slice.md`, paragraphs prefixed with `[pN]`."""

    paragraphs = _flat_paragraphs(sections)
    selected: list[tuple[int, str]] = []
    if window:
        start_text, _, end_text = window.partition(":")
        start = max(0, int(start_text or 0))
        end = int(end_text) if end_text.strip() else len(paragraphs)
        selected = [(index, text) for index, text in enumerate(paragraphs) if start <= index < end]
    else:
        needle = query.casefold()
        hits = [index for index, text in enumerate(paragraphs) if needle in text.casefold()]
        wanted: set[int] = set()
        for hit in hits:
            wanted.update({hit - 1, hit, hit + 1})
        selected = [
            (index, paragraphs[index]) for index in sorted(wanted) if 0 <= index < len(paragraphs)
        ]
    lines = [f"<!-- {len(selected)} paragraphs of {len(paragraphs)} -->", ""]
    for index, text in selected:
        lines.append(f"[p{index}] {text}")
    (out / "page.slice.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_chunks(out: Path, sections: list[tuple[str, int, list[str]]]) -> dict[str, object]:
    """One file per section plus an index, so a reader can take only what it needs.

    Reading a whole paper costs ~15–25 k tokens; the abstract, introduction and conclusion
    are a tenth of that and carry the claim. The index carries the price of each part so the
    caller can choose instead of guessing.
    """

    directory = out / "sections"
    directory.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []
    core_tokens = 0
    for index, (title, level, paragraphs) in enumerate(sections, start=1):
        text = "\n\n".join(paragraphs)
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", title)[:60].strip("-").lower() or f"section-{index}"
        name = f"{index:02d}-{slug}.md"
        (directory / name).write_text(f"{'#' * level} {title}\n\n{text}\n", encoding="utf-8")
        tokens = _estimate_tokens(text)
        core = _is_core(title)
        if core:
            core_tokens += tokens
        entries.append(
            {
                "index": index,
                "title": title,
                "level": level,
                "file": f"sections/{name}",
                "chars": len(text),
                "tokens": tokens,
                "core": core,
                "paragraphs": len(paragraphs),
                "gist": _gist(paragraphs),
                "key_sentences": _key_sentences(paragraphs),
                "formula_dense": text.count("$") // 2 >= 8,
                "numbers": _numbers(paragraphs),
                "keywords": _keywords(paragraphs),
            }
        )
    payload = {
        "sections": entries,
        "total_tokens": sum(int(entry["tokens"]) for entry in entries),
        "core_tokens": core_tokens,
        "figures": _figures_of(sections),
        "core_hint": "abstract + highlights + keywords + introduction + conclusion",
    }
    (out / "index.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def _core_markdown(sections: list[tuple[str, int, list[str]]]) -> str:
    blocks = [
        f"{'#' * level} {title}\n\n" + "\n\n".join(paragraphs)
        for title, level, paragraphs in sections
        if _is_core(title)
    ]
    return "\n\n".join(blocks)


def convert(
    source: Path,
    out: Path,
    *,
    mode: str = "full",
    query: str = "",
    window: str = "",
) -> dict[str, object]:
    html, form = _read_html(source)
    body, info = _extract_body(html)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, out / ("page.mhtml" if form == "mhtml" else "page.html"))

    markdown = ""
    if body:
        markdown, copied, missing = _localise_images(body, source, out, _mhtml_parts(source))
        info["images_copied"] = copied
        info["images_missing"] = missing
    title = info.get("title") or source.stem
    header = f"# {title}\n\n"
    facts = [
        f"{key}: {info[key]}" for key in ("authors", "date", "sitename", "url") if info.get(key)
    ]
    if facts:
        header += "> " + " · ".join(str(fact) for fact in facts) + "\n\n"
    (out / "page.md").write_text(header + (markdown or ""), encoding="utf-8")

    meta: dict[str, object] = {
        **info,
        "source": str(source),
        "form": form,
        "tool": TOOL_VERSION,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest()[:16],
        "bytes_in": source.stat().st_size,
        "bytes_md": len(markdown.encode("utf-8")),
        "headings": len(re.findall(r"(?m)^#{1,6} ", markdown)),
        "table_rows": len(re.findall(r"(?m)^\|", markdown)),
        "math_inline": int(info.get("math_total") or 0),
        "math_engine": "pandoc" if info.get("math_pandoc") else "builtin",
        "math_blocks": len(re.findall(r"\$\$", markdown)),
        "noise_hits": sorted({word for word in NOISE if word in markdown.lower()}),
    }
    meta["warnings"] = _warnings(meta)
    sections = list(_LAST_SECTIONS)
    chunks = _write_chunks(out, sections)
    _write_brief(out, sections, str(info.get("title") or source.stem))
    if query or window:
        _write_selection(out, sections, query=query, window=window)
    if mode == "core":
        (out / "page.core.md").write_text(_core_markdown(list(_LAST_SECTIONS)), encoding="utf-8")
    meta["sections_total"] = len(chunks["sections"])
    meta["tokens_total"] = chunks["total_tokens"]
    meta["tokens_core"] = chunks["core_tokens"]
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="文献网页 → Markdown")
    parser.add_argument(
        "--in", dest="source", required=True, help=".html/.mhtml 文件，或包含它们的目录"
    )
    parser.add_argument("--out", dest="out", required=True, help="输出目录")
    parser.add_argument(
        "--mode", choices=("full", "core"), default="full", help="core 另写 page.core.md"
    )
    parser.add_argument("--query", default="", help="只导出命中段落 ±1 句（page.slice.md）")
    parser.add_argument("--slice", dest="window", default="", help="按段号区间导出，如 12:30")
    arguments = parser.parse_args()
    source = Path(arguments.source)
    out = Path(arguments.out)

    targets = (
        sorted(p for p in source.iterdir() if p.suffix.lower() in SUFFIXES)
        if source.is_dir()
        else [source]
    )
    if not targets:
        print(f"page2md: {source} 下没有 .html/.mhtml", file=sys.stderr)
        return 2

    for target in targets:
        destination = out if source.is_file() else out / target.stem[:80]
        meta = convert(
            target, destination, mode=arguments.mode, query=arguments.query, window=arguments.window
        )
        print(
            f"{target.name}: {meta['bytes_md']} B md · 标题 {meta['headings']} · 表格行 "
            f"{meta['table_rows']} · 公式 {meta['math_inline']} · 图 "
            f"{meta.get('images_copied', 0)}/{meta.get('images_missing', 0)} 缺 · "
            f"噪声 {meta['noise_hits'] or '无'} · 引擎 {meta['engine']}"
        )
        for warning in meta["warnings"]:
            print(f"    ! {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
