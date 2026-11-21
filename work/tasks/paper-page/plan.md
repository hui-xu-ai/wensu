# 计划（草案）· 在线文献网页「自动阅读」能力

> 状态：**M1 已完成**（2026-11-18）；M2（扩展 pageCapture + snapshot 动词）待开工。G0 需求 → 本文件；G1 ADR 待选型确定后写 `docs/adr/0018-*`。

## 1. 需求（G0）

- **问题**：wensu 现在只能取知网/WoS 的题录与详情页字段；用户拿到一篇在线论文（publisher 页面、arXiv、PMC…）时，agent 无法"读整页"——正文、图表、公式、参考文献都在页面里，`read_html` 只在两个渠道域名内有效。
- **用户已试过的两条路**：
  1. 浏览器 **Ctrl+S 存整页**：内容最全（含图片、CSS），但要人工点，且存下来的是 `.html/.mhtml`，agent 直接读会灌满噪声；
  2. 现有扩展 [`scholarly-snapshot`](../../../参考代码/scholarly-snapshot)：一键存，但**内容明显更少**。
- **根因（读代码确认）**：该扩展只做 `document.documentElement.outerHTML` → `data:text/html` 下载（`background.js:36`、`content.js:45-52`）。所以：图片仍是远程 URL（没内联）、CSS 一个字节没有、iframe/shadow DOM 全丢。Ctrl+S/MHTML 才是把**资源内联进单文件**的那条路。
- **目标**：任取一个在线文献页面 → 得到一个**结构良好的 Markdown**（标题/章节/表格/公式/图片引用/参考文献），agent 直接读它做总结、提问、对比。
- **非目标**：不做全文 PDF 批量下载（已有 `pdfdl-ops` / `paper-reader`）；不绕过付费墙/登录墙；不对站点做爬取式批量遍历。

## 2. 三个候选架构

| | A. 人工存 + 本地转换 | B. 扩展内快照（pageCapture）→ 宿主落盘 | C. 独立 headless 抓取（Playwright/SingleFile CLI） |
|---|---|---|---|
| 页面怎么来 | 用户 Ctrl+S / SingleFile 存好 | 对**用户已打开的那个标签页**做 `chrome.pageCapture.saveAsMHTML()` | 自建浏览器访问 URL |
| 内容保真 | ★★★（浏览器原生，资源内联） | ★★★（MHTML 内联 CSS/图片，同 Ctrl+S） | ★★（无登录态 → 付费墙内容拿不到） |
| 自动化程度 | 每篇一次人工点击 | 一键/一句命令 | 全自动（含批量） |
| 改动面 | 0（新增脚本 + skill） | 扩展 `pageCapture` 权限 + 新动词 `snapshot` + host 落盘 + **ADR** | 新依赖（CDP/Chromium）+ 新进程 |
| 合规风险 | 无 | 低（不新增"访问任意站点"的能力，只快照当前标签页） | **高**（等于自建爬虫，撞 ToS/风控，违反 ADR 0004 精神） |
| 结论 | **先做**（M1） | **第二阶段**（M2） | **排除**（仅保留"OA 页面用 `web_fetch` 兜底"） |

**关键设计点**：B 不新增任何"打开任意网址"的能力，只读当前标签页 —— 这样既不碰域名白名单（ADR：域名由渠道 manifest 声明），也不改变风控模型。

## 3. HTML/MHTML → Markdown 选型

| 方案 | 优点 | 缺点 |
|---|---|---|
| **trafilatura（主）+ markitdown（兜底）** ← 推荐 | trafilatura 专治 boilerplate，`-f markdown` 直接出正文（标题层级/表格/图片链接/元数据），学术页表现好；markitdown 覆盖 HTML/PDF/DOCX 等异形输入 | 依赖两个库；trafilatura 对复杂公式页需要后处理 |
| 只用 markitdown | 一个库覆盖所有格式，微软维护 | 无正文裁剪，导航/侧栏/相关阅读会混进 MD |
| 继续用自家 `参考代码\html-20260826` | 已有 ScienceDirect 适配器、`math_handler`、化学式/单位修正 | 自研 150 KB、无基准与回归集、"不成熟"；维护成本落到我们身上 |

**吸收其中真正有价值的部分**（不整套搬）：`restoreFormulas`（MathJax `script[type^=math/tex]` → 源码；KaTeX `data-latex`）、公式四类来源的保留策略、`correction.fix_units/fix_chem` 的化学式与单位上标修正 —— 作为**后处理插件**加在 trafilatura 之后。

## 4. 落盘布局（新增约定）

```
%LOCALAPPDATA%\scholar-search\pages\<yyyy-mm-dd>-<slug>\
  page.mhtml      原始快照（可追溯、可重跑）
  page.html       从 mhtml 解出的主文档（阶段 A 直接用用户存的 .html）
  page.md         agent 读这一份
  assets/         可选：抽出的图片
  meta.json       url / title / 抓取时间 / 工具与版本 / sha256 / 转换告警
```

## 5. Skill 设计

新增 **`paper-page`**（与现有 `paper-reader` 分工：前者=在线网页，后者=英文 PDF 双语精读）：

- `description` 写触发场景："用户给一个论文/文献**网页链接**、或让你读某篇在线文章时用；不适用于 PDF（用 paper-reader）、不适用于纯题录检索（用 scholar-search）"。
- 正文写：输入三选一（已存 .html/.mhtml / 目录 / URL）→ 调 `tools/page2md.py` → 先读 `meta.json` 的告警，再读 `page.md`；失败时分级回退（trafilatura → markitdown → 提示用户 Ctrl+S）。

## 6. 里程碑与验收（每步都有 verify）

| 里程碑 | 内容 | verify |
|---|---|---|
| **M0** ✅ | 依赖装好（trafilatura、markitdown）+ `tools/page2md.py` 骨架 | 三个样本（arXiv abs 页 / 中文期刊页 / ScienceDirect 页）各跑一次，产出 md |
| **M1** ✅ | 正文抽取调优 + `meta.json` 告警 + 目录布局 + skill `paper-page` + 单测 | `pytest tests/unit/test_page2md.py -q`；断言：`^# ` 标题存在、`$$` 公式块 >0、表格行 >0（有表页）、黑名单词（Cookie/Subscribe/Related）命中 0、正文长度在区间内 |
| **M2**（下一里程碑） | 扩展加 `pageCapture` + 动词 `snapshot` + host 落盘 + ADR 0018 | 真机：在 Edge 打开一篇 → 点扩展/调工具 → `pages/<slug>/page.mhtml` 与 `page.md` 都生成；`wensu status` 配额不变（快照不发站点请求） |
| M3（可选，暂不做） | 多标签批量、公式图 OCR（pix2tex） | — |

## 7. 决策（2026-11-18 已定，讨论结论）

| 问题 | 决定 |
|---|---|
| 本期范围 | **M1 + M2**（既做转换，也做"当前标签页一键快照"，省掉人工 Ctrl+S） |
| 转换引擎 | **trafilatura（抽正文）+ markitdown（兜底）**，并移植自家 `restoreFormulas` / `fix_units` / `fix_chem` 作为后处理 |
| 快照来源 | **允许**扩展对"当前已打开的标签页"做 `pageCapture` MHTML；**不新增**访问任意站点的能力 |

对应决策记录：[ADR 0018](../../docs/adr/0018-page-snapshot.md)。

## 7b. 交付文件清单（按里程碑）

**M1**

|---|---|
| `tools/page2md.py` | 转换入口：`--in <file|dir> --out <dir>`；MHTML/HTML → `page.md` + `meta.json` + `page.html` |
| `tools/requirements-page2md.txt` | `trafilatura`、`markitdown[all]` 固定版本 |
| `tools/page2md_post.py` | 移植：公式还原（MathJax/KaTeX）、`fix_units`、`fix_chem` |
| `skills/paper-page/SKILL.md` | 新技能（与 `paper-reader` 分工：网页 vs PDF） |
| `tests/unit/test_page2md.py` | 3 个样本页的断言集（见 §6） |
| `.gitignore` | `pages/`（运行期快照不进 git） |

**M2**

| 文件 | 改动 |
|---|---|
| `extension/manifest.json` | 加 `pageCapture` 权限（`downloads` 已有） |
| `extension/background.js` | 新增 `snapshot`：`pageCapture.saveAsMHTML({tabId})` → `downloads.download({filename:"wensu-pages/<slug>.mhtml"})` → 用 `downloads.search` 取最终绝对路径回报 |
| `native-host/main.py` | `snapshot` 动词：转发给扩展并**只**透传小消息 `{ok, path, bytes, sha256}`（不承载文件本体） |
| `src/scholar_search/core/contracts.py` / `policy.py` | 动词白名单加 `snapshot`；**不计配额**（不发站点请求） |
| `src/scholar_search/server.py` | 新增 MCP 工具 `snapshot`（第 6 个工具） |
| `schemas/tools.json` | 由 `scripts/dump-tools.py` 重新生成（已有闸门） |
| `tests/unit/test_snapshot_verb.py` | 动词合法性 + 不扣配额 + 回报路径校验 |

**为什么大文件不走桥**：`docs/bridge-protocol.md` §Size limits 明说「一行一个 JSON、不接受无界行」，`read_html` 也在 1 MB 处截断。5 MB 的 MHTML 只能由浏览器自己写盘（`downloads`），桥只回报路径。

## 7c. 运行环境

- 依赖装在**独立 venv**（`work/tools/.venv`），不污染全局 Python314；`page2md.py` 在 `meta.json` 里记录自身版本与依赖版本。
- `markitdown` 需要的 Python ≥3.10（本机 3.12/3.14 都满足）。

## 8. 风险与合规

- MHTML 会把页面资源内联进来 → 单文件可能几 MB；需设上限与清理策略（默认保留 30 天）。
- MHTML **不含请求头/Cookie**，但正文可能含账号信息 → 落盘只在本机、不进 git（`.gitignore` 加 `pages/`）。
- M2 只快照当前标签页，不改变"不访问任意站点"的边界；`snapshot` 是新动词 → 必须写 ADR 并同步扩展/host/内核三处（ADR 0003 的动词封闭规则）。
