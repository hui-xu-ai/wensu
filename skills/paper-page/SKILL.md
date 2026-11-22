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
| `index.json` | **先读这个**：每小节的标题、`tokens` 估算、`core` 标记，以及全文 / 核心的总 token |
| `sections/NN-*.md` | 每个小节一个文件，按需只读你需要的那些 |
| `page.core.md` | `--mode core` 时生成：亮点 + 摘要 + 引言 + 结论（通常 2–3 k tokens） |
| `page.md` | 全文（已去掉参考文献及其后的所有尾部章节，重复段落已去重） |
| `meta.json` | 引擎、体积、公式/表格/图计数、`warnings`（保真度告警） |
| `page.html` / `page.mhtml` | 原始快照，供追溯与重跑 |
| `assets/` | 正文引用到的图片 |

**省 token 的读法**：先读 `index.json` 挑小节 → 读 `page.core.md`（或 `sections/` 里那几份）
→ 只有回答需要细节时才读对应小节或 `page.md`。不要一上来把 `page.md` 整篇读进上下文。

### 3. 先读 `meta.json`，再读 `page.md`

`warnings` 非空就记在心里，它决定你回答时的措辞（见下）。

## 遇到人机验证 / 登录墙

- `snapshot` 的返回里若出现 `status: "blocked"` 或 `code: "RISK_CAPTCHA"`，说明当前标签页
  正显示验证码或人机验证：**存下来的是验证页，不是论文**。此时：
  1. **不要重试**、不要刷新、不要点页面上的任何东西（ADR 0004：遇风控即停）；
  2. 告诉用户"这页要你先在浏览器里完成验证/登录"，请他做完再说一声；
  3. 用户确认后再调一次 `snapshot`。
- 这个动词**永远不会**替你过验证，也不读取会话 Cookie；页面能看到什么，完全取决于用户自己
  在浏览器里的登录状态。
- 如果同一篇反复被挡，就换一条路：请用户下载 PDF，然后用 `paper-reader`。

## 回答纪律（重要）

1. **公式、数值、表格数据一律照抄** `page.md` 里的 LaTeX/表格原文，不要自己改写或换算。
2. `warnings` 出现下列情况时，**只要用户问的细节落在受影响范围，就在回答里加一句"这部分建议对照 PDF 复核"**，并说明是哪一类：
   - `页面没有 MathML 公式；公式可能是图片` → 公式没进 Markdown，只能靠 PDF 或截图；
   - `公式由自研转换器渲染（未找到 pandoc）` → 复杂公式（积分上下限、矩阵）可能失真；
   - `N 个公式退化成线性文本` / `表格嵌在段落里未能单独成表` / `图片在本地找不到文件`。
3. 不要声称"已完整读取全文"——说清读了哪份文件、多少小节、哪些部分可能不准。
4. 需要引用页码、图版细节或关键数值定论时，主动建议用户下载 PDF；PDF 到手后用 `paper-reader`。

## 省 token 的读法（建议，不是硬约束）

工具只保证两件事：`page.md`（结构化全文，已去参考文献与重复）和 `index.json`（地图，带每节
`tokens`/`gist`/`keywords`）。**怎么读由你决定**，下面只是经验：

1. **只想知道这篇讲什么**：读 `page.brief.md`（一张地图，约 600 tokens）。
2. **要写摘要/综述**：派一个**子代理**读原文（它可以自己 `read` 任意 `sections/*.md`），只让它
   返回结构化结论 + 出处（`节号#pN`）；主上下文只收那份 JSON。子代理读完即弃，主上下文不膨胀。
   建议字段：`problem / method / key_numbers[{value,meaning,where}] / conclusions / figures /
   sections[{title,topic,tokens}] / uncertain / fidelity_warnings`。
   任何数字都要求它逐字引用并带 `where`；主代理引用前用 `--slice` 只取那一段核对。
3. **回答具体问题**：`--query "关键词"` 或 `--slice 12:20` 只导出相关段落（几百 token 起）。
4. **一次调研多篇**：每篇一个子代理，主代理只合并各篇 JSON；不要在自己的上下文里逐篇读全文。
5. 压缩（图注/公式/表格）默认**不做**；需要时显式开开关，并留意 `meta.json.compressed`。

## 硬约束

- 快照与转换产物只写 `SCHOLAR_SEARCH_HOME`（默认 `%LOCALAPPDATA%\scholar-search`），**不进 git**；
  仓库的 `.gitignore` 已排除 `pages/` 与 `work/tools/out/`。
- MHTML 体积常见 1–5 MB：**不要**通过 wensu 的桥传输文件本体（桥是「一行一个 JSON」且 `read_html` 在 1 MB 截断），
  由浏览器自己写盘、桥只回报路径。
- 转换需要 `pandoc`（公式质量最好，没装会自动回退）、`trafilatura`（正文抽取）；依赖清单见
  `tools/requirements-page2md.txt`。
- 单页转换失败时按序降级：章节聚合 → trafilatura → markitdown → 提示用户手动存或直接给 PDF。
