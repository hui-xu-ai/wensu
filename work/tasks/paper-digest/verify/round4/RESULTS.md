# 第 4 轮验收结果 · FAIL（agree 6/10）

> 协议 `QUESTIONS.md`，两臂原始答案 `ARMS.md`，判官为独立子代理（可读全文、未见两臂过程）。
> 运行环境：page2md `0.3.0-m1`，HEAD `133b5cf`，产物 `work/tools/out/map9/`。

## 1. 判定

| 题 | 判决 | 要点 |
|---|---|---|
| Q1 动机 | agree | 孔隙同时决定流路与反应强度 |
| Q2 方法 | agree | 变量/目标 Eq.(26)/约束三要素一致（M 略去 SIMP·GCMMA） |
| Q3 φ0=0.5 下界 | agree | 避免增加催化剂量 |
| Q4 拓扑形态 | **partial** | 0.31 m 有据；缺 Table 2 几何（17.94/11.01/6.93 mm）→ `M-gap` |
| Q5 提升幅度 | **partial** | 数字皆真，漏主算例 19.4%/26.4% → `M-gap` |
| Q6 验证 | agree | Tong[65]/Adris[66]，原文确无偏差数值 |
| Q7 网格 | agree | 69 840 网格、10⁻⁴ |
| Q8 Fig.4 | agree | 目标与约束趋稳 |
| Q9 α 权重 | **partial** | 只给一句空话；15.5%/2.9%/24.0% 在 index §10 → `M-gap` |
| Q10 结论 | **partial** | 仅 1 条带数；漏 30.9–59.0% → `M-gap` |

**agree 6 / partial 4 / conflict 0 / disagree 0；fabricated 0；F-err 0** → 判据 ≥9/10 未达，**FAIL**。

## 2. 三条发现

### F1 失败点不是"编造"，是"数字没被用上"（4/4 partial 均为 M-gap）

`index.json` 的 `numbers` 是**无语义的裸值字符串**（`"17.94 mm"`、`"15.5%"`），没有绑定到论断句。
地图臂拿到 39 个数字，却无法判断"15.5% 是分离提升、2.9% 是转化提升"，于是全部弃用、只答能读懂的 gist。
→ 修法：`numbers` 改 `{value, where, sentence}`（原句截断 ≤120 字），或直接由 `key_sentences` 承载。

### F2 `page.md` 尾部 37% 是污染（PAGE_DEFECT 成立）

`_cut_tail` 只认 `recommended articles / cited by / related articles / further reading` 四个字面标记，
本篇 ScienceDirect 页面里这些区块**没有这些标题**，于是：

- 191–219：重复导出的引言句、Fig.3–9 图注、§3.1/§3.3 整段重出（`3.1.2` 标题只在尾部出现过）；
- 221–223：Declaration / Funding；
- 225–253：相关文章摘要卡（含以他文口吻转述本篇 28.9%/42.8%/32.0%/92.3%，正是全文臂警告的误导源）。

量化：`page.md` 14 617 tok 中，尾部 191–257 行占 **21 401 字符 / 5 350 tok = 37%**。

### F3 该污染把"35% 预算"算漂亮了

| 基线口径 | 全文 | 地图（meta+index） | 占比 | 结论 |
|---|---|---|---|---|
| 现状（含污染尾） | 14 617 | 4 696 | **32.1%** | 看着达标 |
| 剔除尾部污染 | 9 267 | 4 696 | **50.7%** | 超预算 35% |

→ 地图侧也要瘦身：`index.json` 4 375 tok 里 `numbers`(39) + `key_sentences`(33) + `figures`(8) 占大头，
`chars/file/level/core/paragraphs` 属重复信息。目标 ≤2.5k（≤27%）。

## 3. 机器侧正向证据（`133b5cf` 的修复有效）

逐字回查 `page.md`：`numbers` 39/39、`key_sentences` 33/33、`figures` 图注 8/8 **全部命中原文**，
无伪值、无截断、无图片链接混入关键句 —— 第 3 轮那 4 处元数据缺陷确认修好。
唯一例外是 `math_total = 0`（页面无 MathML，公式为图片），`warnings` 已如实报出。

## 4. 建议的修法（待确认，改动都在 `tools/page2md.py`）

| # | 改动 | 依据 | 影响面 |
|---|---|---|---|
| A | `numbers` 带 `where` + 原句 | F1：4/4 M-gap | index schema，`--query` 不受影响 |
| B | 尾部截断改为结构性判定：**首个重复标题即截断** + 尾部重复块回扫 + 声明/致谢/相关文章块 | F2：37% 污染 | `_cut_tail`/`_dedupe_blocks`，需新单测 |
| C | 地图瘦身档（去掉重复字段、数字按节上限） | F3：50.7% | `index.json` 体积，不删信息则提供 `--map-full` |

三件都属 `tools/page2md.py` 单文件 + 单测，不动内核与扩展；做完再跑第 5 轮（同 10 问，目标 ≥9/10 且 ≤35%）。
