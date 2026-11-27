# ADR 0031 · 把"何时抓取"与"兜底预算"分开：观察模式与捕获回执

日期：2026-11-27。状态：**已接受**（P0 契约；P1/P2 分别实施捕获生命周期与内核触发替换）。

## 背景

一次真实抓取在 17.034 秒时超时（`docs/reviews/wensu-0.14.58-browser-flow-2026-11-27.md`），
而同一篇更早抓到过 2.87 MB。当时的实现把三件不同的事混在一起：

1. **判断页面是否加载完成** —— 实际是 `goto` 之后固定 `sleep 1200 ms`；
2. **决定何时抓取** —— 跟着那个固定睡眠走，与页面状态无关；
3. **兜底超时** —— `SNAPSHOT_TIMEOUT_MS`，却被当成"成败判据"：到期就报失败。

真正可用的就绪信号很少：出版社页面**没有** content script（`read_html`/`read_text`/`wait_for`
只注入 cnki 与 wos 两个渠道），扩展也**没有** `scripting` 权限。能拿到的是
`chrome.tabs` 的 `status`/`url`/`title` 与 `onUpdated`，它们**不保证正文完整**。

## 决定

**一、就绪判定分三层证据，只用下层修正上层，不越级。**

| 层 | 内容 | 它只能决定什么 |
|---|---|---|
| 浏览器层 | `tab.status`、`url`、`title`、`onUpdated` | **何时值得尝试抓取**（candidate），不决定成功 |
| 捕获层 | API 是否返回、字节是否收齐、身份是否一致、是否落盘 | 有没有**产物** |
| 正文层 | 正确文章的正文是否完整 | 用户看到的**成功/失败** |

**二、`snapshot` 增加 `mode`，而不是加一个布尔开关。**

- `mode: "capture"`（默认）：现有行为，`pageCapture` 生成字节；
- `mode: "observe"`：**零字节**，只轮询标签页元数据，返回 candidate / observing / risk / lost；
- `observe` 与 `token`/`offset` **互斥**（观测一次进行中的捕获是"一个请求里装两件事"）；
- 参数闭合校验在**内层 `params.py` 与宿主 `policy.py` 两处**同时生效（宿主复用同一函数）。

用两个模式而不是 `probe_only: true`：布尔字段写错一个字符，就把"观察"变成"生成一次 MHTML"。

**三、功能协商。** `features.readiness_observe=1`、`features.capture_receipts=1` 由 worker 广告；
内核只有确认两者都在时才发 `mode=observe`。未广告的旧 worker 收到该参数会把它当成捕获请求。

**四、三类预算互不推导。**

| 预算 | 起点 | 到期语义 |
|---|---|---|
| 人工验证 10 s | 观察到验证 | `terminal=timeout`、`stage=wall`、`reason=verification_timeout`、`waited=true`；页面保留 |
| 首次观测 30 s | 验证解除、身份有效 | 观测预算耗尽**仍发起第一次捕获**，证据记 `trigger=readiness_budget_exhausted`，不写 `ready=true` |
| 第二次观测 ≤10 s | 第一次正文不足 | 至多一次；不得与第一次重叠 |
| 捕获 + 传回 55 s | 物理抓取发起 | `terminal=timeout`、`stage=capture`、`reason=capture_unconfirmed`；**结果未知 ≠ 网页没有全文** |

观测预算的数值是工程取舍，不是从 17 秒样本推出的"加载时长"。捕获预算必须低于宿主单 RPC 上限
（`native-host/main.py` 拒绝 `timeout_ms > 60000`）；要更高必须改协议，不是改常量。

**五、不变式（可写成测试）。**

| 编号 | 断言 |
|---|---|
| I1 | 每个读取会话的物理 `saveAsMHTML` 次数 ∈ {0, 1, 2}；观测、状态查询、分块读取不增加次数 |
| I2 | 已知验证未解除、已知拒绝、取消、能力不符、tab 丢失、身份冲突 ⇒ **零次**捕获 |
| I3 | 安全且有效的会话，在 candidate 或观测预算耗尽后**必须**发起第一次捕获 |
| I4 | I3 保证"尝试已发起"，不保证"有产物"；API 永不返回的夹具必须允许无文件退出 |
| I5 | 第二次仅在第一次**已结束**、已有可分类字节且正文不足时发生；第一次未确认时不得并发第二次 |
| I6 | 观测与人工恢复不执行 `goto`/reload/create，不增加导航额度 |
| I7 | 任意一次捕获发现验证或拒绝 ⇒ 立即停止；事后才识别的墙可能已经尝试一次，但**发布次数恒为 0** |
| I8 | 迟到结果只能更新原 operation 的事实，不得填给新等待者、改写别的会话文件或成为下一篇结果 |
| I9 | candidate、预算耗尽、文件存在，**都不能单独**令 `full_text=true` |
| I10 | 最终发布至多一次；文件 SHA-256 与回包一致；第二次不足或失败不得覆盖已确认完整的捕获 |

**六、权限路线：不变。** 不新增 `scripting`，不加全站 host 权限。逐站授权的 DOM 观察只在
真实样本证明元数据不足之后另审；即使那时，DOM 稳定也不等于正文完整。

## 拒绝的备选

| 备选 | 拒绝理由 |
|---|---|
| 只把预算调大 | 仍早抓、仍混淆阶段；17 秒样本不能推出"需要 60 秒" |
| 加 `probe_only` 布尔字段 | 写错就把观测变成捕获；两个模式更安全 |
| 用 `scripting` + 全站权限读 DOM | 越出两渠道边界，权限提示与审计成本显著上升，且仍不保证完整 |
| 靠反复 `saveAsMHTML` 当探针 | 每次都是整页序列化，可能补取未缓存资源；既不省也不隐形 |
| 观测与捕获塞进同一个长 RPC | 又把两类预算混在一起，且撞上宿主 60 秒上限 |

## 后果

- `params.py` 的 `snapshot` 允许键增加 `mode`、`observe_ms`，并有互斥与范围校验；
- 内核 `readiness_supported(build)` 决定是否可用观测模式；旧构建继续走旧路径，且**不假装**做过观测；
- `stage` 词汇扩展为 `cache|navigate|wall|capture|identity|publish|render`，**显式 stage 优先于推导**
  （0.14.60 之前 `status=timeout` 一律被推导成 `navigate`，把抓取超时误报成"页面没到达"）；
- `retryable` 只对"确定没发出去"的捕获为真；已发出而未知的捕获必须先查询原 operation。

## 相关

`docs/reviews/wensu-0.14.58-browser-flow-2026-11-27.md`、
`docs/reviews/wensu-0.14.57-official-wall-2026-11-27.md`、
`work/tasks/2026-11-27-lease-receipt/{plan-readiness,gpt-readiness-review}.md`、ADR 0030（动作身份信封）。
