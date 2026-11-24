"""`scholar_search/page2md.py` 的单元测试。

夹具全部是**自造的极简 HTML**，不含任何出版商内容（AGENTS.md：fixture 必须脱敏）。
不依赖 trafilatura：`_extract_body` 内部才 import 它，测试里只调纯 lxml 的部分。

（2026-11-24）转换器从 `tools/page2md.py` 搬进包里，随 wheel 一起发货；`tools/page2md.py`
只剩一层薄壳，所以这里改成直接 import 包内模块。
"""

from __future__ import annotations

import email.mime.multipart
import email.mime.text
import json
import shutil
import sys
from pathlib import Path

import pytest

from scholar_search import page2md

SECTION_HTML = """<!DOCTYPE html>
<html><head><title>Test paper</title></head><body>
<section id="s1"><h2>1. Introduction</h2>
  <div><p>Body text of the introduction with an inline formula
  <math><msup><mi>x</mi><mn>2</mn></msup><mo>=</mo><mi>y</mi></math> inside.</p></div>
</section>
<section id="s2"><h2>2. Results</h2>
  <div><math><mfrac><mn>1</mn><mn>2</mn></mfrac></math><span>(4)</span></div>
  <div><table>
    <thead><tr><th>k</th><th>value</th></tr></thead>
    <tbody><tr><td>1</td><td><math><mn>2</mn></math></td></tr>
           <tr><td>2</td><td><math><mn>3</mn></math></td></tr></tbody>
  </table></div>
  <figure id="f1"><img src="files/fig1.jpg" alt=""/>
    <div class="caption">Fig. 1. A caption.</div></figure>
</section>
</body></html>
"""

PLAIN_HTML = """<!DOCTYPE html>
<html><body><section id="s1"><h2>1. Text only</h2>
<div><p>Only words here, no formulas at all, long enough to be kept as a paragraph.</p></div>
</section></body></html>
"""


@pytest.fixture()
def sample_dir(tmp_path: Path) -> Path:
    assets = tmp_path / "files"
    assets.mkdir()
    (assets / "fig1.jpg").write_bytes(b"\xff\xd8\xff\xd9")  # 最小 JPEG 头尾
    page = tmp_path / "page.html"
    page.write_text(SECTION_HTML, encoding="utf-8")
    return page


@pytest.fixture(autouse=True)
def _no_pandoc(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认走自研转换器，保证测试与本机是否装 pandoc 无关。"""

    monkeypatch.setattr(page2md, "_prime_pandoc", lambda doc, limit=500: 0)
    monkeypatch.setattr(page2md, "_MATH_PANDOC", {})


def test_mathml_to_latex_handles_fraction_and_superscript() -> None:
    from lxml import html as LH

    doc = LH.fromstring(SECTION_HTML)
    formulas = doc.xpath("//math")
    latexes = [page2md._latex_from_math_element(node) for node in formulas]
    assert latexes[0] == "{x}^{2}=y"
    assert latexes[1] == r"\frac{1}{2}"


def test_sections_keep_headings_and_inline_math() -> None:
    markdown, _chars, counters = page2md._section_markdown(SECTION_HTML)

    assert "## 1. Introduction" in markdown
    assert "## 2. Results" in markdown
    assert "${x}^{2}=y$" in markdown
    assert counters["math_total"] >= 3


def test_block_equation_becomes_display_math() -> None:
    markdown, _chars, _counters = page2md._section_markdown(SECTION_HTML)

    assert r"$$\frac{1}{2}$$" in markdown
    assert "(4)" in markdown


def test_table_becomes_pipe_table_with_math_cells() -> None:
    markdown, _chars, counters = page2md._section_markdown(SECTION_HTML)

    assert counters["tables_rendered"] == 1
    assert "| k | value |" in markdown
    assert "| 1 | $2$ |" in markdown


def test_figure_is_placed_inline_and_copied(sample_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    markdown, _chars, _counters = page2md._section_markdown(sample_dir.read_text(encoding="utf-8"))
    localised, copied, missing = page2md._localise_images(markdown, sample_dir, out)

    assert "![Fig. 1. A caption.](files/fig1.jpg)" in markdown  # 就地出现在小节里
    assert (out / "assets" / "fig1.jpg").is_file()
    assert (copied, missing) == (1, 0)
    assert "assets/fig1.jpg" in localised


def test_warning_when_page_has_no_math() -> None:
    _markdown, _chars, counters = page2md._section_markdown(PLAIN_HTML)
    meta = {"math_total": counters.get("math_total", 0), "math_pandoc": 0}

    warnings = page2md._warnings(meta)
    assert any("公式可能是图片" in warning for warning in warnings)


def test_warning_when_pandoc_unavailable() -> None:
    warnings = page2md._warnings({"math_total": 5, "math_pandoc": 0})

    assert any("自研转换器" in warning for warning in warnings)


def test_mhtml_input_is_unpacked(tmp_path: Path) -> None:
    html_part = email.mime.text.MIMEText(SECTION_HTML, "html", "utf-8")
    outer = email.mime.multipart.MIMEMultipart("related")
    outer.attach(html_part)
    path = tmp_path / "page.mhtml"
    path.write_bytes(outer.as_bytes())

    html, form = page2md._read_html(path)

    assert form == "mhtml"
    assert "1. Introduction" in html


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc 未安装")
def test_pandoc_path_converts_math(monkeypatch: pytest.MonkeyPatch) -> None:
    from lxml import html as LH

    monkeypatch.undo()  # 恢复真实 _prime_pandoc
    doc = LH.fromstring(SECTION_HTML)
    hits = page2md._prime_pandoc(doc)

    assert hits >= 1
    latex = page2md._latex_from_math_element(doc.xpath("//math")[1])
    assert "frac" in latex or "1" in latex


def test_extract_body_works_without_trafilatura(monkeypatch: pytest.MonkeyPatch) -> None:
    """trafilatura 是可选的：少了它只该少一路来源，不该让整篇文章读不了（E2）。"""

    monkeypatch.setitem(sys.modules, "trafilatura", None)  # `import trafilatura` → ImportError

    body, info = page2md._extract_body(SECTION_HTML)

    assert body and "1. Introduction" in body
    assert info["trafilatura_missing"] is True
    assert info["engine"] == "sections"


def test_convert_writes_page_and_meta(
    sample_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 跳过 trafilatura：让它返回空，只用章节聚合
    monkeypatch.setattr(
        page2md, "_extract_body", lambda html: ("## 1. Introduction\n\nbody", {"title": "T"})
    )
    out = tmp_path / "out"

    meta = page2md.convert(sample_dir, out)

    assert (out / "page.md").is_file()
    assert (
        json.loads((out / "meta.json").read_text(encoding="utf-8"))["tool"] == page2md.TOOL_VERSION
    )
    assert meta["form"] == "html"
    assert (out / "page.html").is_file()


INTRO = "The transport resistance of a porous catalyst bed limits separation and reaction."
METHOD = "Topology optimization redistributes the porosity field to improve radial transport."
TEASER = "A publisher-only teaser sentence that the section walk never reaches sits here."


def test_cut_tail_stops_where_the_extractor_starts_replaying() -> None:
    """B：尾部不是靠字面标记认的，而是靠"开始重放已出现过的段落"认的。

    真实 Byline：ScienceDirect 正文后跟一段重复的引言/图注/小节标题，再跟声明与相关文章卡片。
    那段重复没有任何 `Recommended articles` 标题，所以旧的标记匹配全部漏网（第 4 轮实测 37%）。
    """

    markdown = "\n\n".join(
        [
            "## 1. Introduction",
            INTRO,
            "## 2. Methods",
            METHOD,
            TEASER,
            INTRO,  # 重放开始
            METHOD,
            "Fig. 3. Validation of the model with experimental results.",
            "A paragraph that belongs to another paper's abstract entirely.",
        ]
    )

    cut = page2md._cut_tail(markdown)

    assert TEASER in cut  # 重放之前的独有内容要留（出版社页才有）
    assert cut.count(INTRO) == 1
    assert "Fig. 3." not in cut
    assert "another paper" not in cut


def test_cut_tail_keeps_a_one_off_repeat() -> None:
    """窗口规则：单块重复不算重放，否则正常论文里引一句前文就会把后半篇砍掉。"""

    markdown = "\n\n".join([INTRO, METHOD, INTRO, TEASER, "A closing remark that is unique."])

    cut = page2md._cut_tail(markdown)

    assert "A closing remark that is unique." in cut
    assert cut.count(INTRO) == 2


def test_cut_tail_drops_declarations_and_recommendation_cards() -> None:
    markdown = "\n\n".join(
        [
            INTRO,
            "The authors declare that they have no known competing financial interests.",
            "United Nations, Department of Economic and Social Affairs, Population Division.",
        ]
    )

    cut = page2md._cut_tail(markdown)

    assert INTRO in cut
    assert "declare" not in cut
    assert "Population Division" not in cut


def test_numbers_capture_bare_decimals_degrees_and_scientific_notation() -> None:
    """第 5 轮丢掉 Q2/Q4/Q8 的原因：只收"带单位的数"，`0.70`/`58.86°`/`1 × 10-3` 全不可见。"""

    paragraphs = [
        "The maximum porosity is 0.70 and the angle between the block and the axis is 58.86°.",
        "The sensitivity of the objective is only about 1 × 10-3 on average.",
        "Section 2.2.2 describes the model settings.",
    ]

    values = [fact["value"] for fact in page2md._numbers(paragraphs)]

    assert "0.70" in values
    assert "58.86°" in values
    assert "1 × 10-3" in values
    assert not any(value.startswith("2.2") for value in values)  # 节号不是事实


def test_number_ignores_a_subscripted_formula() -> None:
    """`H2 molar fraction` 里没有 "2 mol" 这个事实——左侧必须是词边界。"""

    facts = page2md._numbers(["Fig. 8. Distribution of porosity and H2 molar fraction."])

    assert facts == []


def test_numbers_carry_the_sentence_they_came_from() -> None:
    """A：裸值 `"19.4%"` 谁也用不上；值 + 所在原句，读者才能把它绑到论断上。"""

    paragraphs = [
        "In the optimized case the methane conversion is relatively improved by 19.4% at 0.6.",
        "Unrelated closing text without any figure of merit in it at all.",
    ]

    facts = page2md._numbers(paragraphs)

    assert facts and facts[0]["value"] == "19.4%"
    assert "19.4%" in facts[0]["ctx"]
    assert "relatively improved" in facts[0]["ctx"]  # 值 + 谓词，够绑到论断上


def test_gist_does_not_split_a_decimal() -> None:
    """gist 曾按小数点分句："…is 0.5, which…" 被切成 "…is 0." + "5, which…"。"""

    paragraphs = [
        "The original porosity is 0.5, which is also a lower bound on the average porosity.",
        "Nothing numeric follows in this second sentence at all.",
    ]

    gist = page2md._gist(paragraphs)

    assert gist.startswith("The original porosity is 0.5, which")  # 没被切成两句
    assert " 5," not in gist


def test_key_sentences_are_capped_on_a_word_boundary() -> None:
    paragraphs = ["A sentence " + "word " * 80 + "ends here."]

    sentences = page2md._key_sentences(paragraphs, limit=1, chars=60)

    assert len(sentences) == 1
    assert len(sentences[0]) <= 63
    assert sentences[0].endswith("…")


def test_number_inside_a_table_takes_the_table_caption() -> None:
    paragraphs = [
        "Table 2. Geometric parameters of the optimized distribution.",
        "| period | high | low |\n| --- | --- | --- |\n| 17.94 mm | 11.01 mm | 6.93 mm |",
    ]

    facts = page2md._numbers(paragraphs)
    by_value = {fact["value"]: fact["ctx"] for fact in facts}

    assert "Table 2" in by_value.get("17.94 mm", "")


def test_index_drops_bookkeeping_fields(
    sample_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C：地图是给人/模型读的，"chars/level/core/paragraphs" 是给程序看的重复信息。"""

    monkeypatch.setattr(
        page2md, "_extract_body", lambda html: ("## 1. Introduction\n\nbody", {"title": "T"})
    )
    out = tmp_path / "out"

    page2md.convert(sample_dir, out)

    raw = (out / "index.json").read_text(encoding="utf-8")
    index = json.loads(raw)
    entry = index["sections"][0]
    for gone in ("chars", "level", "core", "paragraphs", "index", "keywords"):
        assert gone not in entry
    assert len(entry["key_sentences"]) <= 2
    assert '\n  "' not in raw  # indent 1，省掉纯格式字节
