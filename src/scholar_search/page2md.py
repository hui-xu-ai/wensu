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
import threading
from collections.abc import Sequence
from email import policy
from pathlib import Path
from typing import Any, cast

TOOL_VERSION = "0.3.0-m1"
SUFFIXES = {".html", ".htm", ".mhtml", ".mht"}
# One formula, at most this many characters. Beyond it the Markdown grows without being
# readable (and every consumer pays for it), so it is cut with an explicit warning instead.
MATH_MAX_CHARS = 4_000
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
                raw = payload if isinstance(payload, bytes) else str(payload).encode("utf-8")
                return raw.decode(charset, errors="replace"), "mhtml"
        raise SystemExit(f"page2md: {path.name} 里没有 text/html 部分")
    return path.read_text(encoding="utf-8", errors="replace"), "html"


# ------------------------------------------------------------------- 公式与行内渲染


def _text(node: Any) -> str:
    return " ".join(node.text_content().split())


def _mathml_to_latex(node: Any) -> str:
    """MathML → LaTeX 子集。

    覆盖 mrow/mi/mn/mo/msup/msub/msubsup/mfrac/msqrt/mroot/mfenced/mtext/mtable。
    """

    tag = node.tag if isinstance(node.tag, str) else ""

    def children_latex(element: Any) -> str:
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


def _latex_from_math_element(element: Any) -> str:
    """把一个公式节点变成 LaTeX；转换不出来时返回空串，由调用方给一个短标记。

    优先用 pandoc 批量转换的结果（实测在积分上下限、矩阵、括号尺寸上准确得多）；
    没有 pandoc 或没命中时退回自研的 MathML 子集转换器。
    """

    from lxml import etree

    key = etree.tostring(element, encoding="unicode")
    cached = _MATH_PANDOC.get(key)
    if cached:
        return cached
    return _mathml_to_latex(element).strip()


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


def _prime_pandoc(doc: Any, limit: int = 500) -> int:
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


def _render_inline(element: Any, counters: dict[str, int]) -> str:
    """把节点渲染成 markdown 行内文本：公式成 `$…$`，强调/上下标保留。"""

    pieces: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node.tag, str) and node.tag == "math":
            latex = _latex_from_math_element(node)
            counters["math_total"] += 1
            if not latex:
                # A short marker, not the flattened tree: a matrix or an aligned system
                # flattens into hundreds of characters of symbol soup, which inflates the
                # Markdown (and every token bill that reads it) without being readable.
                # 2026-11-24: the unbounded `_text()` fallback did exactly that.
                counters["math_failed"] += 1
                pieces.append(" [math] ")
                return
            if len(latex) > MATH_MAX_CHARS:
                counters["math_truncated"] += 1
                latex = latex[:MATH_MAX_CHARS].rstrip() + "…"
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


def _table_markdown(table: Any, counters: dict[str, int]) -> str:
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


def _own_blocks(section: Any) -> list[str]:
    """按文档顺序把 section 变成 markdown 块；跳过嵌套 section（外层不吞子节）。

    为什么不能只扫 `<p>`：实测这份 Elsevier 全文里 `<p>` 只有 13 个、**0 个含公式**，
    114 个公式散在 `div`/`span` 里。所以这里递归下钻，只要"块级容器里最内层"的节点。
    """

    counters = {
        "math_total": 0,
        "math_failed": 0,
        "math_truncated": 0,
        "tables_rendered": 0,
        "tables_skipped_inline": 0,
        "images_inline": 0,
    }
    blocks: list[str] = []

    def walk(element: Any) -> None:
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
            if child.xpath('.//*[contains(@class, "section-title")]'):
                # 同上，但 ACS 用的是 `class="section-title"` 而不是 `<section id>`：外层标题的
                # 容器把 13 个子节的正文全吞了进去（2026-11-26 报告 P1-5，`01-introduction`
                # 24,576 tokens、其余各 613）。两种嵌套形式必须一视同仁。
                continue
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
# One conversion at a time uses the module-level counters and the pandoc cache. The lock does not
# make those values good design — it makes them unobservable across documents, which is what the
# concurrent-conversion bug needed (audit 2026-11-26, F09). Sections no longer live here at all.
_CONVERT_LOCK = threading.RLock()


def _section_entries(doc: Any) -> list[tuple[str, int, list[str]]]:
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

    return _without_shared_container_duplicates(front + entries)


def _without_shared_container_duplicates(
    entries: list[tuple[str, int, list[str]]],
) -> list[tuple[str, int, list[str]]]:
    """Keep one entry per distinct block list.

    ACS hangs every section title off the *same* container, so `getparent()` returns the whole
    article for each of them: all fourteen entries came back with the same 529 blocks (measured
    2026-11-26 on `10.1021/jacs.6c13448`). The de-duplicator downstream then left the first entry
    holding the entire body and thirteen behind holding their unique leftover furniture — which
    is what "正文集中在 01-introduction" looked like from outside. Keeping one entry is the honest
    result: the split did not work, and the caller is told so in `warnings`.
    """

    seen: list[list[str]] = []
    unique: list[tuple[str, int, list[str]]] = []
    for entry in entries:
        if entry[2] in seen:
            continue
        seen.append(entry[2])
        unique.append(entry)
    return unique


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


def _core_titles(sections: list[tuple[str, int, list[str]]]) -> set[str]:
    """Which section titles count as "core reading".

    Normally the abstract/introduction/conclusion ones. A body recovered by the paragraph
    fallback has whatever headings the page used and may match none of them — an ACS article
    whose index was rebuilt from the body still reported `core_tokens: 0` (audit 2026-11-26,
    R31-02). When nothing matches, the first section is the honest stand-in: it is the only
    body text there is, and reporting zero hides the article from a core reading.
    """

    chosen = {title for title, _level, _paragraphs in sections if _is_core(title)}
    if not chosen and sections:
        chosen = {sections[0][0]}
    return chosen


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


def _collect_sections(doc: Any) -> list[tuple[str, int, list[str]]]:
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
    """Drop the publisher furniture the extractor merged in after the article.

    The section walk stops at the backmatter, but trafilatura's own body still carried the
    publisher's tail. Matching on literal headings was not enough: ScienceDirect prints no
    "Recommended articles" heading, it just re-exports the introduction, the section titles
    and every figure caption again, then the declarations and the recommendation cards — on
    the acceptance article that replayed tail was 37 % of `page.md` (round 4).

    So the cut is structural: backmatter phrases end the document, and so does a *replay* —
    a block that repeats earlier text while at least one of the next blocks repeats too.
    A single repeat is left alone: quoting an earlier paragraph is normal prose.
    """

    blocks = [block for block in markdown.split("\n\n") if block.strip()]
    kept: list[str] = []
    fingerprints: list[str] = []
    for start, block in enumerate(blocks):
        if _is_furniture_block(block):
            break
        key = _normalise(block)
        window = blocks[start : start + _TAIL_WINDOW]
        if _repeats(key, fingerprints) and _replays(window, fingerprints):
            break
        kept.append(block)
        if len(key) >= 20:
            fingerprints.append(key)
    if len(kept) == len(blocks):
        return _cut_tail_markers(markdown)
    return _cut_tail_markers("\n\n".join(kept) + "\n")


def _cut_tail_markers(text: str) -> str:
    """Cut the publisher's furniture that appears *as a heading*, and nothing else.

    The fallback used to look for the marker anywhere in the text, and "cited by" is a substring
    of ordinary prose: the real Springer capture that read "The mode is excited by light" lost its
    Fabrication Steps and Conclusion sections, with `terminal: ok` and `coverage: 0.365` — high
    enough not to warn (P5 acceptance 2026-11-26, F33-04). A marker now has to start a line.
    """

    cut = len(text)
    for marker in _TAIL_MARKERS:
        for pattern in (f"## {marker}", f"# {marker}", marker):
            found = re.search(rf"(?m)^[#\s]*{re.escape(pattern)}\s*$", text, re.IGNORECASE)
            if found is None:
                continue
            if found.start() < cut:
                cut = found.start()
    return text[:cut].rstrip() + "\n" if cut < len(text) else text


def _is_furniture_block(block: str) -> bool:
    """Blocks that are never part of the paper's argument, whatever their heading."""

    text = block.strip()
    if len(text) > _FURNITURE_MAX_CHARS:
        return False
    lowered = re.sub(r"^[#\s]+", "", text.casefold())
    return any(lowered.startswith(marker) for marker in _FURNITURE_MARKERS)


def _repeats(key: str, fingerprints: list[str]) -> bool:
    if len(key) < 20:
        return False
    for previous in fingerprints:
        if key == previous or _similar(key, previous):
            return True
        # A sentence re-exported on its own, out of a paragraph that already had it.
        if len(key) >= 60 and len(previous) >= 60 and (key in previous or previous in key):
            return True
    return False


def _replays(window: list[str], fingerprints: list[str]) -> bool:
    """Two repeating blocks inside one window = the extractor is replaying, not quoting."""

    repeats = sum(1 for block in window if _repeats(_normalise(block), fingerprints))
    return repeats >= 2


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


def _section_markdown(
    html: str,
) -> tuple[str, int, dict[str, int], list[tuple[str, int, list[str]]]]:
    """The body as Markdown, plus everything the caller needs, returned — not stashed.

    Sections used to travel through the module-level `_LAST_SECTIONS`, which `convert` read
    *after* this call returned. Two conversions in parallel therefore produced one document's
    `page.md` next to the other document's `index.json` (audit 2026-11-26, F09). They are a
    return value now, and the counters that remain module state (`_OWN_COUNTERS`,
    `_MATH_PANDOC`) are used only while the conversion lock is held.
    """

    from lxml import html as LH

    with _CONVERT_LOCK:
        _OWN_COUNTERS.clear()
        doc = LH.fromstring(html)
        for junk in doc.xpath(JUNK_XPATH):
            parent = junk.getparent()
            if parent is not None:
                parent.remove(junk)

        _OWN_COUNTERS["math_pandoc"] = _prime_pandoc(doc)
        # MathJax keeps a machine-readable copy of each formula in `mjx-assistive-mml` for screen
        # readers — and on the Wiley sample (2026-11-24) those copies are **empty**
        # (`data-semantic-type="empty"`, no children) while the real formula is drawn inside
        # `mjx-container` as an SVG. Counting them said "6 formulas failed" when nothing was
        # there to convert, and no marker could ever appear in the Markdown. Count what is real,
        # and count the drawings separately so the warning can say which case it is.
        for assistive in doc.xpath("//mjx-assistive-mml"):
            parent = assistive.getparent()
            if parent is not None:
                parent.remove(assistive)
        _OWN_COUNTERS["mathjax_graphics"] = len(doc.xpath("//mjx-container"))

        sections = _collect_sections(doc)
        blocks: list[str] = []
        characters = 0
        for title, level, paragraphs in sections:
            blocks.append(f"{'#' * level} {title}\n\n" + "\n\n".join(paragraphs))
            characters += sum(len(text) for text in paragraphs)
        return "\n\n".join(blocks), characters, dict(_OWN_COUNTERS), sections


# ------------------------------------------------------------------------ 图片


def _figure_block(figure: Any) -> str:
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


def _source_words(markup: str) -> int:
    """Roughly how much prose the capture holds, before any extraction.

    Deliberately crude and dependency-free: strip scripts/styles/tags and count tokens. It is a
    yardstick for "did the body survive", not a word count to show a reader.
    """

    stripped = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", markup)
    text = re.sub(r"(?s)<[^>]+>", " ", stripped)
    text = text.replace("&nbsp;", " ")
    return len([token for token in re.split(r"\s+", text) if len(token) > 1])


def _word_count(text: str | None) -> int:
    """Whitespace tokens worth counting, ignoring Markdown furniture."""

    if not text:
        return 0
    stripped = re.sub(r"(?m)^#{1,6} .*$", " ", text)
    stripped = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", stripped)
    return len([token for token in re.split(r"\s+", stripped) if len(token) > 1])


def _sections_from_markdown(markdown: str) -> list[tuple[str, int, list[str]]]:
    """Sections from the merged body, so every output derives from one representation.

    Used when the fallback replaced the body: a document with no headings becomes a single
    honest block titled 正文 rather than an empty index that silently hides the text.
    """

    sections: list[tuple[str, int, list[str]]] = []
    title, level = "", 2
    paragraphs: list[str] = []
    for block in [part.strip() for part in markdown.split("\n\n") if part.strip()]:
        heading = re.match(r"^(#{1,6})\s+(.*)$", block)
        if heading:
            if title or paragraphs:
                sections.append((title or "正文", level, paragraphs))
            level = len(heading.group(1))
            title = heading.group(2).strip()
            paragraphs = []
            continue
        paragraphs.append(block)
    if title or paragraphs:
        sections.append((title or "正文", level, paragraphs))
    return sections


def _paragraph_fallback(markup: str) -> str:
    """Headings and paragraphs straight from the document, when sections found nothing.

    The section walk needs the publisher's own containers. ACS prints its body in none of the
    shapes it recognises, so a 3,600-word article converted to 44 bytes of body plus "Supporting
    Information" (measured 2026-11-26 on 10.1021/acs.inorgchem.1c03019) — with `status: ok`.
    `trafilatura` is the documented supplement and it is optional, so the default install had
    nothing to fall back on. This is that fallback: no containers required.
    """

    from lxml import html as LH

    try:
        doc = LH.fromstring(markup)
    except (ValueError, TypeError):
        return ""
    for junk in doc.xpath(JUNK_XPATH):
        parent = junk.getparent()
        if parent is not None:
            parent.remove(junk)
    blocks: list[str] = []
    for element in doc.iter("h2", "h3", "h4", "p"):
        text = " ".join(element.text_content().split())
        if not text:
            continue
        tag = str(element.tag).lower()
        if tag in {"h2", "h3", "h4"}:
            level = {"h2": 2, "h3": 3, "h4": 4}[tag]
            blocks.append(f"{'#' * level} {text}")
            continue
        # Short fragments are captions and labels more often than prose, and the merged body is
        # what keeps a page usable when the containers are unhelpful.
        if len(text) >= 60:
            blocks.append(text)
    return "\n\n".join(blocks)


def _extract_body(html: str) -> tuple[str | None, dict[str, object]]:
    """Sections first, trafilatura as the supplement, markitdown as the last resort.

    `trafilatura` is optional: it is a heavy dependency and nothing the tool guarantees
    needs it (the section walk is its own code). Importing it unguarded made a missing
    package surface as `ModuleNotFoundError` before the documented markitdown fallback
    could ever run (reported 2026-11-22, E2).
    """

    info: dict[str, object] = {}
    main_body: str | None = None
    try:
        import trafilatura
    except ImportError:
        info["trafilatura_missing"] = True
    else:
        metadata = trafilatura.extract_metadata(html)
        info.update(
            {
                "title": getattr(metadata, "title", None),
                "authors": getattr(metadata, "author", None),
                "date": getattr(metadata, "date", None),
                "sitename": getattr(metadata, "sitename", None),
                "url": getattr(metadata, "url", None),
            }
        )
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

    sections, counters = "", dict[str, int]()
    found_sections: list[tuple[str, int, list[str]]] = []
    try:
        sections, _section_chars, counters, found_sections = _section_markdown(html)
    except Exception as error:
        info["sections_error"] = f"{type(error).__name__}: {error}"
    info["bytes_sections"] = len(sections.encode("utf-8"))
    info["sections_found"] = found_sections
    info.update(counters)

    body = _cut_tail(_dedupe_blocks(_merge_markdown(sections, main_body)))
    if sections and main_body:
        info["engine"] = "sections+trafilatura"
    else:
        info["engine"] = "sections" if sections else ("trafilatura" if main_body else "none")

    # A publisher whose pages carry no section containers leaves the walk with almost nothing,
    # and the optional supplement is not installed in a default install. Rather than report a
    # 3,600-word article as 44 bytes of body with `status: ok`, take the paragraphs themselves
    # (retest 2026-11-26, 新发现二).
    source_words = _source_words(html)
    info["source_words"] = source_words
    if source_words >= 300 and _word_count(body) < min(200, source_words // 4):
        fallback = _paragraph_fallback(html)
        if _word_count(fallback) > _word_count(body):
            body = _cut_tail(_dedupe_blocks(fallback))
            info["engine"] = "paragraphs"
            info["paragraph_fallback"] = True
            # The sections have to come from the body too: the walk above failed for this page,
            # and `index.json`, the brief, the selection and `page.core.md` are all built from
            # `sections_found`. Replacing only `page.md` left an ACS article with 16 KB of body
            # and an index holding "Supporting Information" (audit 2026-11-26, R31-02).
            info["sections_found"] = _sections_from_markdown(body)

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
            info["warning"] = "章节聚合没取到正文，且未安装 markitdown（trafilatura 可装可不装）"
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
        # The name comes from the content, never from the page: a location with a Windows
        # separator used to become a path component and the write landed outside `assets/`
        # (audit 2026-11-26, F02). A hash cannot contain a separator and cannot collide.
        parts[location] = (payload, _asset_name(payload, location))
    return parts


def _asset_name(payload: bytes, location: str) -> str:
    """A safe, content-addressed file name for an inline asset."""

    digest = hashlib.sha256(payload).hexdigest()[:16]
    suffix = Path(re.sub(r"[?#].*$", "", location)).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,5}", suffix or ""):
        suffix = ""
    return f"{digest}{suffix}"


def _inside(base: Path, candidate: Path) -> bool:
    """Whether `candidate` really sits under `base` once links are resolved."""

    try:
        candidate.resolve().relative_to(base.resolve())
    except (ValueError, OSError):
        return False
    return True


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
            if not _inside(assets, destination):
                missing += 1
                return match.group(0)
            if not destination.exists():
                destination.write_bytes(payload)
            copied += 1
            return f"![{alt}](assets/{name})"
        if re.match(r"^(https?:|data:)", target):
            return match.group(0)
        # A local image must stay inside the document's own directory: the reference used to be
        # resolved and read wherever it pointed, so a synthetic page could copy any file the
        # process can read into `assets/` (audit 2026-11-26, F01). Checked before any read.
        if (
            Path(target).is_absolute()
            or re.match(r"^[A-Za-z]:", target)
            or target.startswith(("\\\\", "//"))
        ):
            missing += 1
            return match.group(0)
        candidate = (source.parent / target).resolve()
        if not _inside(source.parent, candidate) or not candidate.is_file():
            missing += 1
            return match.group(0)
        assets.mkdir(parents=True, exist_ok=True)
        # Content-addressed like the inline resources: two different figures called
        # `figure.png` (a perfectly normal thing for two subdirectories to hold) used to resolve
        # to one file and the second silently replaced the first (retest 2026-11-26, F10). The
        # name is less readable on purpose — a wrong picture is worse than an opaque name.
        destination = assets / _asset_name(candidate.read_bytes(), candidate.name)
        if not _inside(assets, destination):
            missing += 1
            return match.group(0)
        # Copied every time: a second conversion into the same output directory used to keep the
        # first run's bytes, so a changed figure stayed stale (audit 2026-11-26, F10).
        shutil.copy2(candidate, destination)
        copied += 1
        return f"![{alt}](assets/{destination.name})"

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", rewrite, markdown), copied, missing


# --------------------------------------------------------------------- 主流程


def _warnings(meta: dict[str, Any]) -> list[str]:
    """保真度告警：有这些情况时，细节问题应提示用户拿 PDF 复核。"""

    found: list[str] = []
    failed = int(meta.get("math_failed") or 0)
    if failed:
        # "未能转成 LaTeX" is all that is known: some of these nodes are rendered as a
        # `[math]` marker, others sit in blocks the extractor drops. Claiming a marker
        # exists where the Markdown has none would send a reader looking for it (measured
        # on the Wiley sample, 2026-11-24: 6 failures, 0 markers in page.md).
        found.append(f"{failed} 个公式未能转成 LaTeX（复杂公式可能失真，建议看 PDF 复核）")
    truncated = int(meta.get("math_truncated") or 0)
    if truncated:
        found.append(f"{truncated} 个公式过长，已在 {MATH_MAX_CHARS} 字符处截断")
    graphics = int(meta.get("mathjax_graphics") or 0)
    if graphics:
        found.append(
            f"{graphics} 个公式由 MathJax 渲染为图形：页面未提供 MathML，Markdown 里没有对应 LaTeX"
            "（要精确公式请看 PDF；本地 OCR 尚未启用）"
        )
    if not meta.get("math_total"):
        if not graphics:
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
# Furniture that starts a block: the publisher prints no heading above these.
_FURNITURE_MARKERS = (
    "the authors declare",
    "declaration of competing",
    "competing interest",
    "acknowledg",
    "funding",
    "data availability",
    "credit author",
    "recommended articles",
    "cited by",
    "related articles",
    "further reading",
    "supplementary data",
)
_FURNITURE_MAX_CHARS = 400
_TAIL_WINDOW = 4
_EQ_LABEL = re.compile(r"\(\d{1,2}\)\s*[A-Za-z∇∂⇀]")
_STOPWORD_TEXT = (
    "the and for with that this from were was are has have not but its their which these those "
    "into than then also such can may using used use between under over more most only both each "
    "however therefore thus here there when while where been being does did doing our we they"
)
_STOPWORDS = frozenset(_STOPWORD_TEXT.split())


_BROKEN_DECIMAL = re.compile(r"(?<=\d)\.\s+(?=\d)")
# Two kinds of facts are worth a line in the map: a value with a unit / percentage, and a
# quantity only physics papers write that way — 0.70, 58.86°, 1 × 10⁻³. Round 5 lost Q2, Q4,
# Q8 and Q9 because only the first kind was captured: numbers regex matched "19.4%" but not
# "0.32", so the table bounds, the sensitivity 1×10⁻³ and α = 0 stayed invisible.
_NUMBER_FACT = re.compile(
    r"(?<![A-Za-z0-9-])"
    r"(?:[A-Za-zα-ωΑ-Ω]{1,3}\s*=\s*)?"
    r"(?:"
    r"\d+(?:\.\d+)?\s*[×x]\s*10[-−]?\d+"  # 1 × 10-3
    r"|\d+(?:\.\d+)?\s*-?\s*"  # a value keeps its unit when it has one
    r"(?:%|J·mol⁻¹|J/mol|K|MPa|kPa|W·m⁻²|W/m2|m·s⁻¹|mm|μm|nm|µm|mol|kg|mg|g/L|mL|grids)"
    r"|\d+\.\d{2,}\s*°?"  # 0.70, 58.86°, 0.31 — a bare quantity, no unit
    r")",
)
_MAX_PARAGRAPH_CHARS = 1200
_NUMBER_CTX_CHARS = 64
_GIST_CHARS = 130
_KEY_SENTENCE_CHARS = 200
_TABLE_CAPTION = re.compile(r"^Table\s+\d+[.:]")


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


def _numbers(
    paragraphs: list[str], limit: int = 8, *, ctx_chars: int = _NUMBER_CTX_CHARS
) -> list[dict[str, str]]:
    """Verbatim numeric facts **with the sentence they came from**.

    A bare `"15.5%"` is unusable: round 4 of the acceptance showed a reader that got the
    value could not tell what it measured and silently dropped the whole pool (4 of 10
    questions lost that way). The context sentence is copied, never paraphrased.

    Percentages and unit-bearing values are kept before the bare decimals: on the acceptance
    article the six slots of §3.1 filled up with `0.70`/`58.86°` and silently dropped
    `19.4%`/`26.4%` — the two numbers the section's claim actually rests on (round 6).
    """

    found: list[dict[str, str]] = []
    seen: set[str] = set()
    claimed: list[dict[str, str]] = []
    bare: list[dict[str, str]] = []
    table_caption = ""
    for text in paragraphs:
        stripped = text.strip()
        if _TABLE_CAPTION.match(stripped):
            table_caption = stripped
        for match in _NUMBER_FACT.findall(text):
            value = match.strip()
            if not value or value in seen:
                continue
            seen.add(value)
            fact = {"value": value, "ctx": _number_context(value, text, table_caption)}
            (claimed if _is_claim_number(value) else bare).append(fact)
    found = (claimed + bare)[:limit]
    return found


def _is_claim_number(value: str) -> bool:
    """A percentage or a unit-bearing quantity states something; `0.70` may be geometry."""

    return "%" in value or "× 10" in value or bool(re.search(r"\d\s*(?:[A-Za-zμµ°]|·)", value))


def _number_context(value: str, text: str, table_caption: str) -> str:
    """The room the value stands in: its own sentence, or the caption of its table."""

    if text.lstrip().startswith("|"):
        return _clip_around(table_caption, value, _NUMBER_CTX_CHARS)
    for sentence in _SENTENCE_END.split(text):
        if value in sentence:
            return _clip_around(sentence.strip(), value, _NUMBER_CTX_CHARS)
    return _clip_around(text.strip(), value, _NUMBER_CTX_CHARS)


def _clip_around(text: str, anchor: str, limit: int) -> str:
    """Shorten `text` to `limit` chars, never cutting `anchor` out, and stay on words.

    The window starts at the sentence's own beginning whenever the value fits there: a value
    quoted without its subject ("…are relatively improved by 19.4% and 26.4%") tells a reader
    nothing about what was improved.
    """

    if len(text) <= limit:
        return text
    position = text.find(anchor)
    if position < 0:
        return text[:limit].rstrip()
    if position + len(anchor) <= limit:
        start = 0
    else:
        start = max(0, position - (limit - len(anchor)) // 2)
        space = text.find(" ", start, position)
        if space > 0:
            start = space + 1
    end = min(len(text), start + limit)
    if end < len(text):
        space = text.rfind(" ", position + len(anchor), end)
        if space > 0:
            end = space
    return text[start:end].strip()


def _key_sentences(
    paragraphs: list[str], limit: int = 3, *, chars: int = _KEY_SENTENCE_CHARS
) -> list[str]:
    """2–3 sentences that carry the section: numbers, domain words, and the last sentence.

    The first gist was "the first sentence", which for a methods section says nothing
    (Q6/Q10 of the acceptance were lost exactly there). Scoring the sentences keeps the
    verbatim text and still fits a map.
    """

    joined = " ".join(paragraphs)
    sentences = [
        s.strip() for s in _SENTENCE_END.split(joined) if len(s.strip()) > 30 and "](http" not in s
    ]
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
        # Mechanism/direction sentences carry no number, so nothing else in the map would hold
        # them: round 6 lost Q9 ("the distribution tends to a radial gradient when α = 0").
        if any(
            word in lowered
            for word in ("gradient", "uniform", "tends to", "shift", "evolve", "increases with")
        ):
            score += 2.0
        if index == 0:
            score += 0.5
        if index == len(sentences) - 1:
            score += 0.3
        scored.append((score, index, sentence))
    top = sorted(scored, key=lambda item: (-item[0], item[1]))[:limit]
    kept = [sentence for _score, _index, sentence in sorted(top, key=lambda item: item[1])]
    return [_truncate_words(sentence, chars) for sentence in kept]


def _truncate_words(text: str, chars: int) -> str:
    """Cut at a word boundary; a map line must never end mid-word."""

    if len(text) <= chars:
        return text
    head = text[:chars].rsplit(" ", 1)[0].rstrip(",;:")
    return head + " …"


def _gist(paragraphs: list[str], limit: int = _GIST_CHARS) -> str:
    """One-line "what is this section about", built only from sentences that exist.

    No rewriting: the first sentence, any sentence carrying a number, and the last one.
    A reader can decide from this whether the section is worth its tokens. Truncation only
    happens at a sentence end, so a value is never cut in half.
    """

    if not paragraphs:
        return ""
    sentences = [s.strip() for s in _SENTENCE_END.split(" ".join(paragraphs)) if s.strip()]
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
                    "caption": caption[:260],
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
            lines.append("  values: " + " | ".join(fact["value"] for fact in numbers))
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
    figures = _figures_of(sections)
    captions = [_normalise(figure["caption"]) for figure in figures]
    core_titles = _core_titles(sections)
    for index, (title, level, paragraphs) in enumerate(sections, start=1):
        text = "\n\n".join(paragraphs)
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", title)[:60].strip("-").lower() or f"section-{index}"
        name = f"{index:02d}-{slug}.md"
        (directory / name).write_text(f"{'#' * level} {title}\n\n{text}\n", encoding="utf-8")
        tokens = _estimate_tokens(text)
        core = title in core_titles
        if core:
            core_tokens += tokens
        numbers = _numbers(paragraphs)
        # A section that states four or more values is a results section: it needs the third
        # key sentence (the mechanism sentence usually quotes no number, so nothing else
        # would carry it — round 6 lost Q9 exactly there).
        limit = 4 if len(numbers) >= 4 else (3 if core else 2)
        key_sentences = [
            sentence
            for sentence in _key_sentences(paragraphs, limit=limit)
            # A figure caption is already in `figures`; repeating it as a key sentence is noise.
            if not any(
                len(_normalise(sentence)) >= 30 and _normalise(sentence) in caption
                for caption in captions
            )
        ]
        numbers = _numbers(paragraphs)
        joined_key = " ".join(key_sentences)
        for number in numbers:
            # Already visible in a key sentence: the context would just be the same text twice.
            if number["value"] in joined_key:
                number["ctx"] = ""
        entries.append(
            {
                "title": title,
                "file": f"sections/{name}",
                "tokens": tokens,
                "gist": _gist(paragraphs),
                "key_sentences": key_sentences,
                "formula_dense": bool(_EQ_LABEL.search(text))
                or len(re.findall(r"[∇∂∑∫]", text)) >= 3,
                "numbers": numbers,
            }
        )
    payload = {
        "sections": entries,
        "total_tokens": sum(int(cast(int, entry["tokens"])) for entry in entries),
        "core_tokens": core_tokens,
        "figures": figures,
    }
    (out / "index.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return payload


def _core_markdown(sections: list[tuple[str, int, list[str]]]) -> str:
    titles = _core_titles(sections)
    blocks = [
        f"{'#' * level} {title}\n\n" + "\n\n".join(paragraphs)
        for title, level, paragraphs in sections
        if title in titles
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
    # Which bytes this conversion is about, and whether they were still the same bytes when it
    # finished. One article has one capture file, and a later read replaces it, so a conversion
    # that outlived its input must say so instead of looking complete (audit 2026-11-26, R31-04).
    capture_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    body, info = _extract_body(html)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, out / ("page.mhtml" if form == "mhtml" else "page.html"))

    markdown = ""
    if body:
        markdown, copied, missing = _localise_images(body, source, out, _mhtml_parts(source))
        # Figures the browser captured through the debugger (ADR 0026) sit beside the page with a
        # URL → file map, because the MHTML never carried them: its `<img src>` still points at the
        # publisher's CDN. Adopting them makes the Markdown directory self-contained.
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

    meta: dict[str, Any] = {
        **info,
        "source": str(source),
        "form": form,
        "tool": TOOL_VERSION,
        "sha256": capture_sha256[:16],
        # The full digest of the input, so a caller can prove which capture produced this output.
        "capture_sha256": capture_sha256,
        "bytes_in": source.stat().st_size,
        "bytes_md": len(markdown.encode("utf-8")),
        "headings": len(re.findall(r"(?m)^#{1,6} ", markdown)),
        "table_rows": len(re.findall(r"(?m)^\|", markdown)),
        "math_inline": int(cast(int, info.get("math_total") or 0)),
        "math_engine": "pandoc" if info.get("math_pandoc") else "builtin",
        "math_blocks": len(re.findall(r"\$\$", markdown)),
        "noise_hits": sorted({word for word in NOISE if word in markdown.lower()}),
    }
    # Recomputed after the work: a different digest means another capture replaced this file
    # while it was being read, so the Markdown may mix two versions of the page.
    input_changed = hashlib.sha256(source.read_bytes()).hexdigest() != capture_sha256
    meta["input_changed"] = input_changed
    if input_changed:
        cast(list[str], meta["warnings"]).append(
            "转换期间输入文件被替换（同一次读取被新的捕获覆盖），Markdown 可能混合两个版本；"
            "请重新转换一次。"
        )
    meta["warnings"] = _warnings(meta)
    # How much of the capture actually reached the Markdown. A conversion can succeed, save a
    # file and still carry almost none of the article — ACS's 3,600 words became 44 bytes of
    # body while the answer said `ok` (retest 2026-11-26, 新发现二). State the coverage so a
    # caller can refuse to draw conclusions from a body that is mostly missing.
    extracted_words = _word_count(markdown)
    counted = info.get("source_words")
    source_words = counted if isinstance(counted, int) and counted > 0 else _source_words(html)
    meta["coverage"] = {
        "source_words": source_words,
        "extracted_words": extracted_words,
        "ratio": round(extracted_words / source_words, 3) if source_words else None,
    }
    ratio = meta["coverage"]["ratio"] if isinstance(meta["coverage"], dict) else None
    # Nothing at all out of a page that had text is always worth saying, whatever its size: the
    # 500-word floor let a 404-word page convert to 0 words in silence (audit 2026-11-26, R31-08).
    if source_words > 0 and extracted_words == 0:
        cast(list[str], meta["warnings"]).append(
            f"正文未提取到内容：源页面约 {source_words} 词，转换结果为空。请核对原文或改用 PDF。"
        )
    elif source_words >= 300 and isinstance(ratio, float) and ratio < 0.3:
        cast(list[str], meta["warnings"]).append(
            f"正文可能大量缺失：源页面约 {source_words} 词，转换后仅 {extracted_words} 词"
            f"（{ratio:.0%}）。请核对原文，必要时看 PDF。"
        )
    # The sections of *this* document, handed back by the extraction that produced them.
    sections = list(cast(list[Any], info.get("sections_found") or []))
    chunks = _write_chunks(out, sections)
    _write_brief(out, sections, str(info.get("title") or source.stem))
    if query or window:
        _write_selection(out, sections, query=query, window=window)
    if mode == "core":
        (out / "page.core.md").write_text(_core_markdown(sections), encoding="utf-8")
    meta["sections_total"] = len(cast(list[Any], chunks["sections"]))
    meta["tokens_total"] = chunks["total_tokens"]
    meta["tokens_core"] = chunks["core_tokens"]
    # A long document in one or two sections is not a reading plan: the site gave no usable
    # section containers, so say so instead of letting a caller page through a heading that
    # holds the whole paper (2026-11-26 report P1-5).
    if (
        int(cast(int, meta["tokens_total"])) >= 5_000
        and int(cast(int, meta["sections_total"])) <= 2
    ):
        cast(list[str], meta["warnings"]).append(
            "正文章节不足：站点没有提供可用的章节容器，正文集中在少数小节里，按节阅读的效果有限"
        )
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def main(argv: Sequence[str] | None = None) -> int:
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
    arguments = parser.parse_args(argv)
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
        for warning in cast(list[str], meta["warnings"]):
            print(f"    ! {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
