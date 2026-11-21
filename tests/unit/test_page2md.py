"""`tools/page2md.py` 的单元测试。

夹具全部是**自造的极简 HTML**，不含任何出版商内容（AGENTS.md：fixture 必须脱敏）。
不依赖 trafilatura：`_extract_body` 内部才 import 它，测试里只调纯 lxml 的部分。
"""

from __future__ import annotations

import email.mime.multipart
import email.mime.text
import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import page2md

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
