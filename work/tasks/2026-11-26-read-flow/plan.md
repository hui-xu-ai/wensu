# 单任务读取流程 + 批量串行编排（方案）

日期 2026-11-26，基线 `main @ 230133a`（0.14.32）。本文件是**方案**，未改实现。

## 一、目标与非目标

**目标**

1. 一次读取有明确的状态机：每一跳都有可观测的返回值，AI 能一眼看出"成功 / 卡在哪一步 / 为什么"。
2. 验证墙有**人机协同协议**：工具明确告诉用户"去点"，用户点完后工具**知道**已经点完，然后继续；用户不点则超时跳过。
3. 批量任务有**编排规范**（skill）：按出版社分组串行抓取，组内共用一次验证；每条成功后立刻交给子代理离线转换；失败统一记账，收尾统一汇报并询问是否重试。

**非目标（明确不做）**

- 不并发访问站点（`concurrency=1` 不变，ADR 0005）。
- 不自动重试同一页、不换 IP、不延时重试、不破解验证码（AGENTS.md 1–4）。
- 不在"没有正文"时断言"机构没有订阅"（把它做成可解释的 `reason`，不猜）。
- 不放开"预热标签页"到任意域名——仍受渠道/出版社白名单。

## 二、单任务状态机（每一步的返回值）

```
S0 入队      job_id 分配（新）
S1 导航      goto(工作标签页) + halt_titles
S2 导航判定  落地 URL / 是否被墙 / 是否没跳转
S3 墙       最大化+聚焦 → 通知用户 → 受限等待 → 用户点完 or 超时
S4 等渲染    sleep(settle) → snapshot(临时区)
S5 分类      ok | abstract_only | paywall | pdf_only | blocked
S6 身份      declared | url | publisher_only | mismatch
S7 全文判定  full_text true/false + full_text_reason
S8 发布      pages/<DOI>/page.mhtml + capture_sha256（原子、一次）
S9 终态      terminal + stage + reason + evidence + quota + next
```

**S1→S2 导航是否成功**（不靠猜）

| 观测 | 判定 |
|---|---|
| `navigation.stalled`（落回 `about:blank`） | 没跳转 ⇒ 新建标签页重试**一次**（已有逻辑），仍失败 ⇒ `terminal: no_page, reason: tab_not_a_page` |
| `url` 变化且 `publisher_for_host` 命中同一出版社 | 落地成功 |
| `url` 出路到别的出版社 / 非 http | `terminal: no_page, reason: capture_mismatch`（不写缓存） |
| `halted: true` 或标题命中门规则 | 进 S3 |

**S4 加载完成**（两个信号，缺一不可）

1. 扩展的 `waitComplete` 收到 load 事件（或 13 s 上限到点）；
2. 内核 `sleep(_ARTICLE_SETTLE_MS)` 之后再抓，抓完看 `prose_words`：仍 `still_rendering` ⇒ **只做一次**二次观察（现有逻辑），不为"再等等"加长。

**S3 验证墙协议**（本方案唯一的协议新增）

1. 内核返回 `status: blocked`、`reason: challenge`，并带给人看的提示与给 AI 的 `next`。
2. **窗口动作**：`windows.update({state: "maximized", focused: true})` + `tabs.update(tabId, {active: true})`，把工作页切到前台。
3. **受限等待**：发一个新动作 `await_gate_clear`，参数 `{title_markers, timeout_ms: 10000, poll_ms: 2000}`；
   扩展内部每 2 s 读一次 `tabs.get(tabId).title`：
   - 标题不再命中门规则 ⇒ 回 `{cleared: true}`（**这就是"用户点完了"的信号**）；
   - 到点仍未清 ⇒ 回 `{cleared: false, reason: "verification_timeout"}`。
4. 内核：`cleared: true` ⇒ 回到 S4 继续抓；`false` ⇒ `terminal: timeout, reason: verification_timeout`（批量层据此跳过该出版商）。`blocked` 留给"不等就能确定的墙"（可见验证码、403/429）。
5. 该动作**不产生文档请求**（只读标签页标题），按 `policy.py` 的 `NETWORK_VERBS` 定义不计费；但它属于动作词汇表的新动词 ⇒ **需要 ADR**（AGENTS.md 6）。

> 为什么不复用 `wait_for`：内容脚本只注入知网/WoS 两个域名（`manifest.json`），出版社页没有接收端，这正是 0.14.28 那次"幽灵等待"的教训（审计 F08）。

**S5–S7 全文 / 部分的判定**（AI 只看这几个字段）

| 字段 | 取值 |
|---|---|
| `terminal` | `ok` / `partial` / `blocked` / `timeout` / `no_page` / `unsupported_site` |
| `full_text` | 仅当正文量达标（现有规则：≥5 段且 ≥1200 词）或"页面自报 DOI 相符且 ≥800 词" |
| `full_text_reason` | `abstract_only`（只有摘要/Highlights）/ `paywall`（有购买或登录提示）/ `pdf_only`（只有 PDF 入口）/ `no_body`（有页面无正文）/ `challenge` |
| `identity` | `declared` / `url` / `publisher_only` / `mismatch` |
| `prose_words`、`sections`、`headings` | 客观计数，供 AI 自己复核 |

**明确不做的推断**：正文缺失**不代表**没有机构权限——`full_text_reason` 只报"页面上看到的事实"（有付费墙提示、只有 PDF、只有摘要），不再用"no institutional access"这种归因。

**S9 终态返回的骨架**（AI 用它判断卡点）

```json
{
  "job_id": "…", "terminal": "partial", "stage": "capture",
  "status": "no_html", "full_text": false, "full_text_reason": "pdf_only",
  "identity": "declared", "doi": "…", "publisher": "acs",
  "final_url": "…", "captured_url": "…", "capture_sha256": "…",
  "mhtml_path": "…", "prose_words": 0, "navigation_attempts": 1,
  "quota_charged": 2, "quota_reason": "navigate",
  "evidence": {"title": "…", "halted": false, "declared_doi": "…"},
  "next": "只有 PDF：可以请用户给 PDF，或换一篇有 HTML 全文的版本"
}
```

`stage` 枚举：`navigate | wall | render | capture | identity | publish`——它就是"卡在哪一步"。

## 三、批量串行编排（skill 草案）

新增 `skills/scholar-batch-read/SKILL.md`（公开发行包内）。

**输入**：DOI/URL 列表（来自 `search`/`detail`），可选出版社过滤。

**步骤**

1. **预算检查**：`status` 读 `quota_remaining`；预计额度 = 条数 × 2 + 预热条数；不足则停止并告知。
2. **分组**：按 `publisher` 分组；组内按 DOI 排序。同组连续抓取，用一次用户验证覆盖整组。
3. **（可选）预热**：给默认 4 家（SpringerLink / ScienceDirect / Wiley / ACS；IEEE 目前不需要，其余用户自选）各打开**一篇**文献到**非工作标签页**，保持不关，请用户依次点击验证。
   - 成本：每家 1 次导航（1 额度、1 次站点访问），默认 4 家 ⇒ 4 额度；**执行前必须向用户确认**。
   - 这些标签页不进"可丢弃"名单，下一次 `goto` 不会清空它们（需要扩展侧"保留型标签页"改动）。
4. **串行抓取**：逐条 `page_read`。**成功一条 ⇒ 立刻把 `mhtml_path` + `capture_sha256` 交给子代理**做 `page2md` 与阅读（离线、并行，不占浏览器），主流程继续下一条。
5. **遇墙**：走 S3；`cleared` 则本组继续；`verification_timeout` ⇒ 记失败，**跳过该出版商剩余条目**，进入下一组。
6. **失败账本**：`work/reports/<run-id>/failures.json`，每条记录
   `{doi, publisher, terminal, reason, stage, evidence, quota_charged}`。
7. **收尾汇报**（等全部完成后统一告诉用户）：
   `成功 N 条 / 失败 M 条（按 reason 归类）` + 询问"是否重试失败项"。重试前重新预热。

**硬约束（写进 skill 的禁止项）**：不并发浏览器、不自动重试同一页、不破解验证、不换 IP、不加延时重试；遇 `403/429` 整批停止并冷却 24 h；`verification_timeout` 只跳过不重试。

## 四、与现有硬约束的对照

| 需求 | 是否冲突 | 处理 |
|---|---|---|
| 每 2 s 看标签页标题 | **需要新动作**（词汇封闭，AGENTS.md 6） | 写 ADR：`await_gate_clear`，非网络动作、不计费 |
| 窗口最大化 + 聚焦工作页 | 与"窗口保持最小化"相反 | 只在 S3（人类必须介入）时使用，明确记录 |
| 预热标签页常驻 | 与"启动后只留一个窗口"、`closeDisposableTabs` 冲突 | 扩展侧加"保留型标签页"，不进可丢弃名单；写 ADR 说明取舍 |
| 一次读取 1–2 次导航 | 已经是现状 | 本方案不新增导航；`view="full"` 仍是显式 opt-in |
| 组内共用一次验证、超时跳过该出版商 | 不冲突 | 属编排层，由 skill 约束 |

## 五、验收

**单任务（合成夹具）**

1. 墙 → 用户点完 → `await_gate_clear` 返回 `cleared` → 继续抓到正文 ⇒ `terminal: ok`。
2. 墙 → 用户不点 → 10 s 超时 ⇒ `terminal: blocked, reason: verification_timeout`，`stage: wall`，字节不落盘。
3. 落到 `about:blank` ⇒ 重试一次后 `no_page/tab_not_a_page`。
4. 只有 PDF 入口 ⇒ `partial / pdf_only`；有付费墙提示 ⇒ `partial / paywall`；只有摘要 ⇒ `partial / abstract_only`。
5. 同出版社另一篇 ⇒ `no_page / capture_mismatch`（已实现，回归）。
6. 每个终态都能从 `stage` 看出停在哪一步。

**批量（合成夹具 + 一次真实）**

7. 3 家 6 条，第 2 家超时 ⇒ 失败账本 2 条、其余成功、子代理并行转换、收尾询问。
8. 真实：2 家 4 条（自然出现墙才算；不制造墙）。

## 六、提交拆分

| 步 | 内容 | 需要 ADR |
|---|---|---|
| P1 | 返回值：`job_id`/`stage`/`terminal`/`evidence`（纯内核，不改协议） | 否 |
| P2 | `await_gate_clear`（扩展 + 内核 + 墙协议） | **是** |
| P3 | 保留型标签页 + 预热流程（`goto open:"new" keep:true`） | **是**（多标签页取舍） |
| P4 | `skills/scholar-batch-read/SKILL.md` + 失败账本 | 否 |
| P5 | 真实链路验收（含一次自然墙） | — |
