# 0.14.5 修复计划：新会话验收测试（2026-11-25）发现的缺陷

来源：`D:\Python\DeepSeek\Test\wensu-test-report.md`（P1–P9）。本文只写方案，未动代码。

## 0. 根因（已读源码确认，不是推测）

| 缺陷 | 根因（代码位置） |
|---|---|
| P1 零命中报成 `query.rejected` + 抽到帮助图例 | `parse_records.py:39 EMPTY_MARKERS` 只有英文 `your search found no results`；本次会话站点是**中文 UI**，零命中提示是中文 → 空标记不命中 → 落到 `QUERY_ERROR_MARKERS`（`:54`）里的**通用帮助词** `布尔运算符`（检索页帮助面板就写着「布尔运算符 : AND, OR, NOT」）→ `query_error()`（`:68`）返回图例并被当成拒绝 |
| P3 拒绝要等 14.8 s 才知道 | `plan_export.py:75` 第一条是 `wait_for(RESULT_READY, 15s)`；探针 `_site_diagnosis` 只在**超时之后**由 `service.py:1422 _run_tail` 调用。站点 0.2 s 就给横幅，我们睡满 15 s 才看 |
| P5 `blocked` 的 `next` 让别再调 `page_read` | 三处文案未跟 ADR 0022 修订 1 一起改：`service.py:111`、`errors.py:112`、`server.py:839` |
| P6 无效 DOI 判成 `abstract_only`、仍扣 2、仍落盘 | `pageprobe.py:176` 没有「DOI 解析失败」这一类，is-not-article → `abstract_only`；`service.py` 见 `:85` 就把 `abstract_only` 当"付费墙/需登录" |
| P2 skill 与工具脱节 | `skills/scholar-search/SKILL.md:10`「七个工具」（缺 `page2md`）；`:22` 写「WoS 20–22 秒」（实测 10.5 s）；`:51/:407` 撞墙要报 `cooldown_until`（实际不冷却，ADR 0022 修订 1） |
| P7 额度账差 1 | 明细无逐笔账（`quota.json` 只有当日总数），无法对账 |
| P9 page2md 产物 | 公式 160 字符截断；图片外链未本地化；归档目录名截断到 ~80 字符 |
| P4 撞墙判定 12.12 s | `goto` 全程走完才做风控判定；要早期判定必须让扩展在导航过程中回报标题 → **动扩展 + 原生宿主** |

## 1. 批次 A（建议本轮做：纯 Python + 文档，全部可单测验证）

- **A1 P1 判定重写** — 改动面：`channels/webofscience/v2026_11/parse_records.py`（`EMPTY_MARKERS` 补中文；`QUERY_ERROR_MARKERS` 收紧为**拒绝专属**短语，删掉帮助面板也有的通用词；多处命中时取**位置最靠前**的那句）、`tests/unit/test_wos_query_error.py`。verify：`pytest tests/unit/test_wos_query_error.py`，新增三例——中文零命中 → `None`（no_match）；帮助图例+零命中 → `None`；真拒绝 → 原句。
- **A2 P3 早探针** — 改动面：`plan_export.py`（首等待 3 s）＋ `service.py:_run_tail`（探针判定后若既非拒绝也非空，**继续剩余 12 s 等待**，总预算仍是 15 s）。verify：新单测——拒绝在第 3 s 就抛；happy path 不多跑任何动作。
- **A3 P5 文案** — 改动面：`service.py:111`、`errors.py:112`、`server.py:839` 改为「过验证后重调 `page_read`（open-tab，0 额度）或 `snapshot`」。verify：`grep "Do NOT call page_read"` 为空。
- **A4 P6 无效 DOI** — 改动面：`pageprobe.py`（标题/H1 命中 `DOI Not Found`/`Article not found` → `reason: doi_not_found`）、`service.py`（该 reason 不落盘、不计费、`next` 改为「DOI 可能不存在」）。verify：fixture 单测 + 一次真实坏 DOI。
- **A5 P2 skill 同步** — 改动面：`skills/scholar-search/SKILL.md`（8 工具表补 `page2md`；新增「在线阅读」一节：`page_read`→`page2md` 不碰 shell；撞墙改为「过墙后重调 `page_read` 走 open-tab 复用，或 `snapshot`」；耗时基线改 10–15 s / 知网 ~5 s）。

## 2. 批次 B（本轮可选，P4 需真机验证）

- **B1 P4** 撞墙早期判定（扩展在导航中回报标题 → 12.1 s 降到 ~1 s）。动 `extension/` + native host + 新 ADR，blast radius 大。
- **B2 P7** 额度逐笔账（tool/amount/ts 追加进 `quota.json`）。
- **B3 P9** `page2md` 归档目录名加短哈希；图片本地化（8 MB 级别，需评估）。

## 3. 明确不做

- **P8**（`D:\Python\DeepSeek\Test` ACL 缺"更改权限"）：环境问题，不属 wensu。
- **"零命中改收 8 额度"**：实测 3 = 真实发生的 3 个计费动作，改成 8 反而不诚实。改为在 skill 里写清「零命中只收实际动作费（3）」。
- WoS 单次 1000 条（ADR 0024 已记录理由，不重提）。

## 4. 收尾

版本 0.14.5（五处版本号 + CHANGELOG）→ `release-check` 十门全绿 → G4 证据 + G5 评审。发布动作需用户另行确认。
