# 未验证清单（租约 / 回执 / 就绪）

记录"已发布但没有行为验证"的东西，避免下一轮把它当成已验证。

## 0. ADR 0031（就绪观测）—— 已真机验收，两条分支仍未覆盖

真机验收：`docs/reviews/wensu-0.14.64-acceptance-2026-11-27.md`（纯官方 0.14.64，无私有补丁）。

| 项 | 结果 | 我离线核过 |
|---|---|---|
| `features` 四项 | 全在 | ✅ `acceptance.json` 的 `preflight_status` |
| 首次直读 | 自然遇墙：`blocked/timeout/wall`、`wait 10087 ms`、`quota 1` | ✅ |
| **零导航续读** | `ok/ok/publish`、`readiness.strategy=observe`、`state=candidate`、`617 ms`、`budget_exhausted=false`、`quota_charged=0`、`resumed_from` 指回、**审计窗口 0 行 `goto`** | ✅ `calls.resume.reply` 与 `actions.jsonl` |
| 正文与文件 | DOI 目录、2,976,528 B、SHA 与报告一致；Markdown 与既有完整正文参考**逐字一致** | ✅ 重算 SHA 通过 |
| 补充轮 | 同一路径再验一次（619 ms、quota 0） | ✅ 目录与哈希在 |

**仍未覆盖（报告已明确，我照抄认领）**：

1. **无验证阻断时从首次导航直接发布**（`capture_navigation: match` 分支）——本轮首读停在墙；
2. **观察预算耗尽分支**（`budget_exhausted: true` 仍抓一次，I3）——两轮都在 `candidate` 就抓了。

这两条只有等自然样本，**不要为它们制造访问**。

## 1. ~~worker 侧的旧代围栏（0.14.52）~~ 已于离线补通（0.14.64 测试集）

`tests/js/lease_fence_probe.js` + `tests/unit/test_lease_fence_worker.py` 现在**驱动真 worker**：

| 输入 | 实测 |
|---|---|
| `lease_sync {lease_id: L1, fence: 5}` | `lease_ack {ok: true, fence: 5, lease_id: L1, worker_epoch}` |
| `snapshot`，信封 `fence: 4`（被取代） | `ok: false`、`error: "policy.fence"`、`data.fence: 5` |
| `sleep`，**无信封**（旧内核） | `ok: true` —— 围栏不是墙 |
| `sleep`，信封 `fence: 5` | `ok: true`，且回包 `context` 原样带回 |

静态契约测试（`test_capability_contract.py`）保留：它抓"这行被删了"，行为探针抓"消息绕过检查"。

### 我前三次为什么失败（留作教训）

1. 两条管道 + 脚本化 worker：宿主侧握手 OK，但方向错了——探针要驱动的是 worker；
2. VM + 端口：加载成功，`onConnect`/`onMessage` 收不到任何消息；
3. VM + `onHostMessage` 但没显式退出：进程挂住、无输出。

**可用的模式**（`gate_watch_probe.js` 起就有的三条）：假 `chrome` 满足加载期所有监听器；
直接 `await context.onHostMessage(msg, {postMessage})`；末尾 `process.exit(0)`。

### 建议的补法

以 `tests/js/gate_watch_probe.js` 为模板（它是能跑通的、且有 pytest 包装），只加三处：

- `makeBrowser()` 用模板里的那份（它已经满足 worker 在加载期注册的所有监听器）；
- 探针主体照模板的 `drive()`：`await sleep(25)` → `context.workTab(DOMAINS)` → 逐条
  `await context.onHostMessage({...}, channel)`；
- 进程退出用 `process.exit(0)` 显式结束，不要等事件循环自然清空。

断言（放在 pytest 包装里，不放在 JS 里）：

| 动作 | 期望 |
|---|---|
| `lease_sync{fence:5, lease_id:L1}` | `lease_ack{ok:true, fence:5, lease_id:"L1", worker_epoch:<hello_ack 的同一个>}` |
| `action{fence:4}` | `ok:false, error:"policy.fence"`，且没有发生导航 |
| `action`（无 `context`） | 照常执行 |
| `action{fence:5}` | 照常执行 |

## 2. ~~安装器最小 ACL（未做）~~ 已于 0.14.55 用真机读数关闭

0.14.55 起宿主的 `info` 带 `coordination_writable`：它在浏览器给它的**低完整性**下真的写一个临时文件
再删掉。真机读数 `true`（`docs/reviews/wensu-0.14.55-coordination-elsevier-2026-11-27.md` §1），
因此"宿主能不能写租约目录"不再是未知。

**仍未证明的相邻部分**（不要把它一起划掉）：这次只证明了"写/删一个文件"可以。**完整的归档、锁、去重与
恢复协议**没有真机样本；要等真实出现一次 `bridge.timeout`、再用 `navigation_status` 查到回执才算。

0.14.46 的 `navigation_status` 与 0.14.52 的 `lease_check` 都依赖这个目录可写；0.14.53 起
`lease_check` 在记录不可信时**拒绝**（`lease_protocol_unavailable`）而不是放行。

## 3. 真机样本：四类已补，三类仍缺

### ✅ F55-01 端到端通过（0.14.57 单次真实读取）

`docs/reviews/wensu-0.14.57-single-read-2026-11-27.md`：URL-only 请求 → `ok / ok / publish`、
`identity: url`、`full_text: true`、`capture_navigation: match`、`declared_doi=10.1016/j.cej.2023.144222`、
捕获 2,874,736 B（SHA 与回包一致）、配额 288→286、收尾 `browser_lease: free`、`browser_lock: free`。

**该轮有一项未满足，已修（0.14.58）**：文件落在 `pages/A-chemotactic-…-ae7b52ea/` 而不是 DOI 目录，
因为发布时用的是请求的 identifier（URL-only 为空）。现在用"答案能证明的 DOI"作存储键（F57-01）。

### ✅ F56-01 权限分支（同一轮）

仓库 `.venv` 解释器 → `browser_lock: denied`、`browser_busy: false`；安装版读取前后均为 `free`。
两种真实环境已分开。

### ✅ 真实 10 秒验证超时（0.14.57 纯官方版）

`docs/reviews/wensu-0.14.57-official-wall-2026-11-27.md`：自然出现 Are-you-a-robot 墙，`goto` 1476 ms，
`await_gate_clear` 真等 **10127 ms**，回包 `blocked / timeout / verification_timeout / wall / waited: true`，
未发布、未重试、未代点；配额差额 1。我离线核过 `acceptance.json` 与 `actions.jsonl`。

### ⚠️ 人工放行后的"唤醒→等待→抓取"（**只到 transaction 层**）

`docs/reviews/wensu-0.14.57-manual-verification-2026-11-27.md`：同一 `_browser_transaction()` 内
`_await_gate_clear()`（`cleared=true`，10076 ms）→ `sleep 1200` → `_snapshot_locked` → `_publish_page`，
未重新导航、额外配额 0、身份与 DOI 匹配。留存副本 SHA 与 `page.md` 字节数我都离线核过；
该捕获 **0 个 `<table>`**，`table_rows=0` 正确。

### ❌ 仍然缺

- **单个公开 `page_read` 调用内**人工放行后直接续抓（上面那次是本地驱动复用官方原语）；
- 页面**自然自清**（无人工点击）；
- 自然出现的 `bridge.timeout` + 迟到回包（0.14.48 起的归档路径），以及依赖它的归档/锁/去重/恢复协议；
- `SCHOLAR_SEARCH_LEASE_MODE=enforce` 的真机行为，与 worker 旧代续体围栏（§1）。

### ✅ 真实 10 秒验证超时（0.14.57 纯官方版，已验收）

`docs/reviews/wensu-0.14.57-official-wall-2026-11-27.md`：ScienceDirect 自然出现 Are-you-a-robot 墙，
一次直达 `goto`（1476 ms）后 `await_gate_clear` 真等 **10127 ms**，回包
`status: blocked / terminal: timeout / reason: verification_timeout / stage: wall / waited: true`，
未发布文献、未重试、未代点；配额 286→285（差额=实际导航数 1），冷却未设，收尾
`browser_lock: free`、`browser_lease.state: free`。

我离线核过证据目录：`acceptance.json` 的五个字段与报告一致，`actions.jsonl` 两行 verb 齐全。

### ⚠️ 人工放行后的"唤醒→等待→抓取"（**只到 transactions 层，不是公开 `page_read`**）

`docs/reviews/wensu-0.14.57-manual-verification-2026-11-27.md`：同一 `_browser_transaction()` 内依次调用
官方 `_await_gate_clear()`（返回 `ran=true / cleared=true`，耗时 10076 ms）→ `sleep 1200` →
`_snapshot_locked(tab="work")` → `_publish_page()`，**没有重新导航**，额外配额 0；文章标题/URL/PII/
`declared_doi=10.1016/j.cej.2023.144222` 均匹配，MHTML 2,915,487 B，`page2md` ok（coverage 0.643）。

我离线核过：留存副本 SHA-256 = `a31507…ce6`（与报告相同），`converted/page.md` = 55,178 B（与报告相同），
该捕获 **0 个 `<table>`**，所以 `table_rows=0` 是正确结果、不是 F53-01 的复发。

**但这不是"单次公开 `page_read` 内人工放行后续抓"**：那次公开调用自己已经 `timeout` 并停在 `last_job` 里，
唤醒走的是本地驱动直接调用官方原语。所以下面这条**仍然缺**。

### ❌ 仍然缺

- **单个公开 `page_read` 调用内**人工放行后直接续抓（当前样本是本地驱动复用官方原语）；
- 页面**自然自清**（无人工点击）；
- 自然出现的 `bridge.timeout` + 迟到回包（0.14.48 起的归档路径），以及随之才能证明的
  归档/锁/去重/恢复协议；
- `SCHOLAR_SEARCH_LEASE_MODE=enforce` 的真机行为，与 worker 旧代续体围栏（§1）。
