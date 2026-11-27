# ADR 0030 · 动作信封带 tab / navigation 身份（第一片：只报不判）

- 状态：已接受（2026-11-26，第一片）
- 相关：ADR 0018（快照读当前标签页）、ADR 0029（浏览器状态机器级）、P5/复验报告（"tab/navigation 租约"列为架构项）

## 背景

动作与回包里没有"这是哪个标签页、哪一次导航"的身份。于是"抓到的这页是不是我刚导航的那次"只能靠事后
比对地址、标题与页面自报的 DOI。0.14.31 曾经把 ACS 的另一篇文章当成请求的那篇，0.14.32 起靠
`identity` / `capture_sha256` 补救，但那仍然是**事后**判断：

- 同一 URL 的两个标签页在回包上无法区分；
- 一次 `goto` 里扩展内部是否又发了一次导航，只能靠 `navigation_attempts` 事后统计；
- 捕获若来自另一次导航（例如超时后幽灵落地），内核没有任何字段能指出来。

## 决策（第一片，本轮实施）

回包里**报告**身份，判定逻辑一个字不改：

| 字段 | 含义 | 出现在 |
|---|---|---|
| `tab_id` | 浏览器实际导航/捕获的那个标签页 | `goto` 回包、`snapshot` 回包 |
| `navigation_id` | **这一次导航**标识（`crypto.randomUUID()`，无则时间戳+随机） | `goto` 回包 |
| `navigation_attempts` | 这一次动作真正发出的导航数（0.14.32 已加） | `goto` 回包 |

内核侧：`page_read` 回包把它们放进顶层与 `evidence`，`page2md` 与缓存不受影响。

## 为什么分两片

判定一旦改成"捕获的 navigation_id 必须等于本次导航的 id"，任何一处实现偏差都会让**正常读取**被拒；
而现在的环境里还有私有导航补丁（两次 `goto`）与旧的扩展构建。先把字段发出去、让它真实链路里跑一轮，
确认它们在**每次**读取里都存在且自洽，再让它们参与判定。

## 第二片（已实施，2026-11-27）

第一片在真实链路里被证实：四条 goto 各有非空且互不相同的 `navigation_id`，`page_read` 顶层与
`evidence` 都等于该篇最后一条 goto 的 id，`snapshot` 的 `tab_id` 与导航一致。据此改判定：

1. **捕获必须跟随本次导航**。扩展按标签页记住最近一次导航 id，`snapshot` 回包带上它；内核把
   `capture_navigation` 记为 `match` / `mismatch` / `absent`，`mismatch` ⇒
   `no_page / unverified_capture`，字节不发布（`stage: identity`）。
2. **缺失不算失败**。`absent` 只记事实不拒绝——三层（扩展、宿主、内核）是滚动升级，旧构建不会报这个
   字段，把它当失败会让"更新了内核但没重载扩展"变成所有读取都失败。
3. **导航未确认有了终态**。桥放弃一次导航（`bridge.timeout` 一类）时不再让错误冒出去当成"什么都没发生"：
   返回 `status: timeout / reason: navigation_unconfirmed / stage: navigate / unconfirmed: true`，
   并在 `next` 里要求先看 `status.browser_busy` 与标签页再决定是否重试——**标签页可能在你被告知超时之后
   才落地**，这才是"超时取消确认"缺的那块。

## 未实施（第三片，已冻结契约）

第三片补的是"调用结束 ≠ 浏览器操作结束"。方案见 `work/tasks/2026-11-27-lease-receipt/plan.md`，
可执行的契约见 `docs/protocol-lease.md` 与 `src/scholar_search/core/lease.py`（P0，尚未接线）。

已批准的三处收敛（实现方评审：`work/tasks/2026-11-27-lease-receipt/review-lead.md`）：

1. **只读追问走宿主控制通道**，不新增浏览器动词——它不是浏览器动作，进封闭动词表要同步 5 处词表，
   而本项目两次真机故障（F33-01、F34-01）都是漏层；
2. **身份字段 8 → 4**：`lease_id`+`fence`、`operation_id`、`worker_epoch`、`endpoint_epoch`；
3. **P1 拆两半**：P1a＝账本 + 迟到回包归档 + 只读追问 + `status` 摘要（全部离线可验，`observe` 模式）；
   P1b＝`features`/epoch 协商 + `context` 信封 + 安装器最小权限。

`内核指定 tab_id` 已在 0.14.45 实施（`params.tab_id`，命名标签页不可用时回退），不再属于"未实施"。

仍未做、且明确不在 P1a 范围：强制准入（`enforce`）、worker 侧每个续体的旧代隔离、
`context` 信封与 native framing 改动。

## 影响面

| 位置 | 改动 |
|---|---|
| `extension/background-*.js` | 第一片：`goto` 回报 `navigation_id`/`tab_id`；第二片：按标签页记最近一次导航，`snapshot` 回包带上它 |
| `core/service.py` | `_snapshot_locked` 保留 `tab_id`/`navigation_id`（此前在这里被丢掉，捕获永远显示 `absent`）；`page_read` 比较并与 `capture_navigation` 一起回报；导航未确认有独立终态 |
| 测试 | 跨层契约（worker 必须回报）+ `test_capture_lease.py`（match/mismatch/absent/未确认四个用例） |

## 回滚

字段是附加的。要退回"只报不判"：删掉 `page_read` 里设置 `refused = True` 的那一行即可，其余字段保留
（它们不影响任何判定）；要连字段一起退，再删 worker 三处回报与内核两处透传。
