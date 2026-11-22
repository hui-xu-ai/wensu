# 修法计划 · A+B+C（第 4 轮验收的整改）

> 依据 `RESULTS.md` 三条发现。改动面：**只动 `tools/page2md.py` + `tests/unit/test_page2md.py`**，不碰内核/扩展/技能。
> 顺序：先写会红的测试（tdd-loop），再实现，再重生成地图与复跑验收（第 5 轮）。

## 步骤

| # | 动作 | verify（可机械判定） |
|---|---|---|
| S1 | 写 6 个新单测（B 的截断 3 条、A 的 numbers 语境 2 条、C 的字段精简 1 条） | `pytest tests/unit/test_page2md.py -q` → 6 failed（红） |
| S2 | B：`_cut_tail` 改结构性判定——块级家具标记 + "当前块重复且 4 块窗口内 ≥2 块重复 ⇒ 再导出开始" | 新测试转绿；map9 的 `page.mhtml` 重跑后尾部行数 ≤ 205 |
| S3 | A：`_numbers` 返回 `{"value","ctx"}`，ctx = 含该数字的原句（≤80 字，尽量从句首起、永不切掉数字、按词边界收尾）；表格行内的数字 ctx 取表题 | 单测断言 ctx 逐字包含 value；重生成后 33 个 value/ctx 100% 逐字命中 |
| S4 | C：每节删 `index/chars/level/core/paragraphs/keywords`；`key_sentences` 2 条（core 节 3 条，≤200 字，词边界 + 省略号）；numbers 上限 10→6，且**收裸小数/角度/科学计数**（`0.70`/`58.86°`/`1×10⁻³`），等号左侧的符号一并带上；`indent=2`→1；图注里已有的句子不再重复当关键句 | 重生成后 `index.json` **15 004 B / 3 751 tok = 38.9%**（分母 = 修好的 `page.md` 9 636 tok）；45 条 numbers 100% 逐字命中 |
| S4b | **预算改动（用户 2026-11-22 决定）**：**≤35% → ≤40%**，理由是 35% 与覆盖率互斥（34.7% 时一致率 8/10，§4/§9 事实不可见）；**发版门槛不变：仍须 ≥9/10** | 38.9% ≤ 40% ✓ |
| S5 | 回归 | `pytest tests -q`（基线 453 + 新增）、`ruff check --no-cache`、`scripts/dump-tools.py --check` |
| S6 | 第 5 轮验收 | 同 10 问重跑两臂 + 判官，目标 ≥9/10 且 ≤35% |

## 明确不做

- 不新增产物（不另造 `page.map.md`）；不删 `figures`/`gist`/`keywords`；不改 `--query`/`--slice`/`--brief` 的对外行为。
- 不动 `src/`（内核与 MCP 契约不受影响），故不需要 ADR 与版本号变更；`0.12.58` 仍待第 5 轮通过后再发。
