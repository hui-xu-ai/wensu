# WoS BibTeX 导出 + 本地影响因子库

## 0. 需求（intake）

- **问题**：`www.webofscience.com` 上抓不到检索响应（顶层窗口从未发起 `runQueryGetRecordsStream`，
  该请求由我们无法拦截的上下文发出）。同时 BibTeX 导出在该站点可用，且题录最全。
- **目标**：`.com` 的检索结果通过**站点自带的 BibTeX 导出**获得，不再依赖接口抓取；
  影响因子由用户提供的 JCR 表在本地建库查询。
- **用户约束**：BibTeX 下载功能**只在 `.com` 提供**，镜像站不提供 —— 正好避免违规下载。
- **非目标**：不做全文/PDF 下载；不把 JCR 数据打进发行包（授权 + 体积）。
- **验收**：`wensu search --channel=webofscience` 在 `.com` 上返回带 DOI 与影响因子的题录；
  解析器与 IF 查询有离线回放测试；真实链路在用户浏览器上跑通一次。

## 1. 现有方案盘点（避免重复造）

| 已有 | 位置 | 复用方式 |
|---|---|---|
| `Record.impact_factor` / `impact_factor_year` | `core/contracts.py:233-239` | **直接复用**，不新增字段 |
| WoS 解析器从流里的 `jcr` 块取 IF | `parse_records.py:241` | BibTeX 路径改由本地库填充 |
| 九动词封闭集 | `core/contracts.py` | **不新增动词**：下载路径随 `click` 的 `data` 返回 |
| `wensu export` / `assets` / `setup` | `cli.py` | 新命令挂同级 |

**结论**：不新建渠道、不新增动词、不新增 Record 字段。

## 2. 关键事实（已验证）

### .bib 真实结构（来自用户样本，2 条记录）

```
@article{ WOS:001218812900001,
Author = {Lo, Li-Yu and Lin, Pei-Ting and ...},     ← "Last, First and ..." 格式
Title = {Miniaturized ionogel-based ...},
Journal = {SENSORS AND ACTUATORS A-PHYSICAL},
Year = {2024}, Volume = {370}, DOI = {10.1016/j.sna.2024.115220},
Abstract = {...}, Keywords = {..; ..}, Cited-References = {...},
Unique-ID = {WOS:001218812900001}, DA = {2026-11-11},
}
```

要点：
- **条目键就是 UT**（`WOS:…`），与现有 `Record.ut` 同一标识；
- 值用 `{...}` 包裹，**续行以 3 空格缩进**；`{[}…{]}` 是转义的花括号；
- 条目类型至少 `@article`、`@inproceedings`（后者用 `Booktitle`、`Pages`）；
- **没有**影响因子 —— 这正是需要本地库的原因；
- 「完整记录」选项不含 `Cited-References`，体积小得多（用户建议）。

### JCR 工作簿（用户提供 `JCR分区.xlsx`，4.2 MB）

| sheet | 表头 | 行数 |
|---|---|---|
| `2025JCRIF-分区` | 期刊名称 / 2024JIF / Quartile / JIF rank / 2023分区 / Total citation / Category / ISSN / eISSN | 22249 |
| `2025中科学院分区表` | （表名行）/ 期刊名称 / 2025分区 / Top / Open Access | 21771 |

注意：sheet 名是 **2025**JCRIF，列头是 **2024**JIF —— 发布年 vs 数据年。库里按列头解析并存两列，
不猜。

### 用户已有扩展 `WoS-BibTeX-Assistant`（可参考，不复用）

- 弹窗定位：`.window` 内 `h1` 含 "BibTeX" + `app-export-out-details form` + `#exportButton`
- 范围：`input[name="outputMethodType"][value="fromRange"]` + `markFrom` / `markTo`
- 记录内容下拉：`wos-select button[role="combobox"]`，选项 `option-fullRecord`（完整记录）等
- 下载识别：`/^savedrecs(?: \(\d+\))?\.bib$/i` + `chrome.downloads.onChanged`
- **它只负责"填表辅助"，不负责打开导出弹窗** ⇒ 入口选择器仍需实测发现

## 3. 设计

### 3.1 影响因子本地库

```
wensu jcr import <path-to-xlsx>     # 生成 %LOCALAPPDATA%\scholar-search\data\jcr.sqlite
wensu jcr status                    # 行数 / edition / 源文件名 / 导入时间
```

- **不随包分发** JCR 数据：授权归 Clarivate，且 4.2 MB 不该进 wheel。
- 表结构：`jcr(issn, eissn, name, name_key, jif, quartile, jif_rank, prev_quartile,
  total_citations, category, edition)` + `cas(name, name_key, quartile, is_top, is_oa, edition)`
  + `meta(edition, source_file, imported_at, rows)`。
- 查询：**ISSN/eISSN 精确匹配优先**，退化到刊名归一化（大写、去标点、`&`→`AND`、折叠空白）。
- 填充：BibTeX 路径拿到 `ISSN`/`EISSN`/`Journal` 后查库，写入
  `Record.impact_factor` / `impact_factor_year`（edition 取自列头年份）。

### 3.2 BibTeX 导出计划（仅 `.com`）

```
goto advanced-search → type 表达式 → click 检索 → wait_for 结果列表
→ click Export → click BibTeX → wait_for #exportButton
→ [click 记录内容 → click 完整记录]        ← 可选，默认完整记录
→ click #exportButton                      ← 触发下载
```

- 扩展 `click` 在触发下载时把 `data.download = {path, filename, size}` 一并返回
  ⇒ **不新增动词**。
- 需要新权限 `downloads`（重载时用户需确认）。
- 内核读该文件 → `parse_bibtex` → `Record`；`detail` 走 `Unique-ID` 拼 URL，不变。

### 3.3 路径选择

| 站点 | 取数方式 |
|---|---|
| `www.webofscience.com` | BibTeX 导出（新） |
| `webofscience.clarivate.cn` | 现有 capture（不动） |

由 `selectors.ADVANCED_SEARCH` 的 host 决定，无新用户参数。

## 4. 改动面清单

| 文件 | 为什么必须改 |
|---|---|
| `channels/webofscience/v2026_11/parse_bibtex.py` | 新：BibTeX → Record |
| `channels/webofscience/v2026_11/plan_export.py` | 新：导出点击链 |
| `channels/webofscience/v2026_11/selectors.py` | 导出按钮 / 格式项 / 弹窗锚点 |
| `channels/webofscience/v2026_11/__init__.py` | 按 host 选取数路径 |
| `extension/manifest.json` + `background.js` | `downloads` 权限 + 下载回报 |
| `core/jcr.py`（新）+ `core/config.py` | 库路径与查询 |
| `cli.py` | `jcr import` / `jcr status` |
| `tests/fixtures/webofscience/records.bib` | 真实样本做回放 |
| `tests/` | 解析器、IF 查询、计划结构 |

## 5. 待用户确认

1. 记录里**是否一起给分区**（JCR Quartile + 中科院分区）？表里有，几乎免费；但会给 `Record` 加字段。
2. 导出内容用「**完整记录**」（不含参考文献，快）—— 按你建议默认这个，确认即可。
3. 下载的 `.bib` **保留**在你的下载目录，还是读完就删？

## 6. 步骤与验证

| # | 步骤 | verify |
|---|---|---|
| 1 | BibTeX 解析器 + fixture | `pytest tests/unit/test_parse_bibtex.py` 绿 |
| 2 | JCR 导入 + 查询 | `wensu jcr import` 后 `wensu jcr status` 行数 22249/21771 |
| 3 | IF 填充接入 | 单测：给定 ISSN 断言 IF 与 edition |
| 4 | 扩展 downloads + 下载回报 | 重载后 `click` 返回 `data.download` |
| 5 | 发现导出入口选择器 | 在用户浏览器上跑通一次导出，落选择器 |
| 6 | 端到端 | `wensu search --channel=webofscience --limit=3` 返回带 IF 的题录 |
