---
name: paper-page
description: 把「已保存的在线论文网页」（浏览器 Ctrl+S 的 .html + `_files/` 目录，或单个 .mhtml）转成 Markdown，供 AI 通读全文并回答关于正文、公式、表格、图的问题。当用户给出论文网页链接/已存文件、要求通读、总结、逐节解释或回答细节问题时使用；PDF 用 paper-reader，纯题录检索用 scholar-search。
---

# 在线论文网页通读

网页里有 PDF 拿不到的东西：图表位置、公式的 MathML 原文、参考文献链接。这个技能把它变成
一份 agent 能读的 Markdown（公式保留为 LaTeX），并明确标出**哪些地方不可靠**。

## 何时使用

- 用户给了一个论文**网页**（publisher 页面、arXiv HTML、PMC），让你读它、总结它、回答细节；
- 用户手上有 Ctrl+S 存下来的 `.html`（连同同名 `_files/` 目录）或 `.mhtml`；
- 需要引用正文原句、公式或表格数据来做回答。

## 何时不用

| 情况 | 用什么 |
|---|---|
| 手上是 PDF | `paper-reader`（英文 PDF → 双语 Markdown 精读） |
| 只要题录（标题/作者/DOI/摘要） | `scholar-search` + `scholar-detail` |
| 要批量下载 PDF | `pdfdl-ops` / `paper-pdf-fetch` |
| 知网 / WoS 站内页面 | wensu 的 `read_html`（这两站有域名白名单） |

## 三步

### 1. 先看手上有没有文件

用户已经存过就直接用（目录名带 `_files` 的那种也可以，脚本会自己找）：

```powershell
Get-ChildItem <目录> -Filter *.html     # 或 *.mhtml
```

没有文件时用 **`mcp__wensu__snapshot`**：用户把论文页在浏览器里打开，你调一次即得 MHTML
（`pageCapture` 把图片/CSS 一起写进单文件，比手存更整齐；不发任何站点请求，**不扣额度**，
也不受渠道域名白名单限制，因为它只读用户已经打开的标签页）。返回 `{path, bytes, url, title}`，
把 `path` 交给下一步。

扩展没装或没连上时（`status.bridge_ready: false`）再退回**请用户 Ctrl+S「网页，全部」**。
不要自己去访问 publisher 站点，也不要扩大扩展的域名白名单。

### 2. 转换

```powershell
D:\Python\DeepSeek\DateWork\scholar-search\work\tools\.venv\Scripts\python.exe `
  D:\Python\DeepSeek\DateWork\scholar-search\tools\page2md.py `
  --in "<页面>.html" --out "%LOCALAPPDATA%\scholar-search\pages\<slug>"
```

输出目录里：

| 文件 | 内容 |
|---|---|
| `page.md` | **读这个**：标题、元信息、`##/###` 小节、`$…$` 公式、`|` 表格、`![图注](assets/…)` |
| `meta.json` | 引擎、体积、公式/表格/图计数、`warnings`（保真度告警） |
| `page.html` / `page.mhtml` | 原始快照，供追溯与重跑 |
| `assets/` | 正文引用到的图片 |

### 3. 先读 `meta.json`，再读 `page.md`

`warnings` 非空就记在心里，它决定你回答时的措辞（见下）。

## 回答纪律（重要）

1. **公式、数值、表格数据一律照抄** `page.md` 里的 LaTeX/表格原文，不要自己改写或换算。
2. `warnings` 出现下列情况时，**只要用户问的细节落在受影响范围，就在回答里加一句"这部分建议对照 PDF 复核"**，并说明是哪一类：
   - `页面没有 MathML 公式；公式可能是图片` → 公式没进 Markdown，只能靠 PDF 或截图；
   - `公式由自研转换器渲染（未找到 pandoc）` → 复杂公式（积分上下限、矩阵）可能失真；
   - `N 个公式退化成线性文本` / `表格嵌在段落里未能单独成表` / `图片在本地找不到文件`。
3. 不要声称"已完整读取全文"——说清读了哪份文件、多少小节、哪些部分可能不准。
4. 需要引用页码、图版细节或关键数值定论时，主动建议用户下载 PDF；PDF 到手后用 `paper-reader`。

## 硬约束

- 快照与转换产物只写 `SCHOLAR_SEARCH_HOME`（默认 `%LOCALAPPDATA%\scholar-search`），**不进 git**；
  仓库的 `.gitignore` 已排除 `pages/` 与 `work/tools/out/`。
- MHTML 体积常见 1–5 MB：**不要**通过 wensu 的桥传输文件本体（桥是「一行一个 JSON」且 `read_html` 在 1 MB 截断），
  由浏览器自己写盘、桥只回报路径。
- 转换需要 `pandoc`（公式质量最好，没装会自动回退）、`trafilatura`（正文抽取）；依赖清单见
  `tools/requirements-page2md.txt`。
- 单页转换失败时按序降级：章节聚合 → trafilatura → markitdown → 提示用户手动存或直接给 PDF。
