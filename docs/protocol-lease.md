# 租约与操作回执：协议契约（P0）

- 状态：**契约已冻结，未接线**（2026-11-27；实现见 `work/tasks/2026-11-27-lease-receipt/plan.md`）
- 代码：`src/scholar_search/core/lease.py`（当前没有任何运行时调用点）
- 测试：`tests/unit/test_lease_contract.py`
- 相关：ADR 0030（动作身份）、ADR 0029（浏览器级状态）

## 1 · 为什么需要它

`page_read` 一次调用跑完整个计划，调用返回后浏览器里可能仍有在飞的导航。此时"调用结束了"不等于
"浏览器操作结束了"：一次已发出的导航可能在超时**之后**才落地。没有这东西，第二次读取会在第一次的
落地页上再导航一次，两次结果混在一起，而回包看起来完全正常。

## 2 · 词汇表（封闭）

| 集合 | 值 | 含义 |
|---|---|---|
| 租约状态 | `free` `active` `releasing` `unconfirmed` `recovering` `quarantined` | 资源持有者的生命周期 |
| 操作状态 | `prepared` `executing` `settled` `unknown` | 单个动作的副作用是否已交代 |
| `navigation_issued` | `true` / `false` / `null` | **三值**：`null` = 不知道，绝不能当 `false` |
| 准入/导航原因 | `lease_held` `lease_unconfirmed` `lease_protocol_unavailable` `navigation_not_issued` `navigation_unconfirmed` | 回包里的 `reason` |

`navigation_issued = false` 只允许出现在两种情况：内核根本没到派发；或 worker 在调用浏览器导航 API
**之前**就拒绝/被隔离。TCP 写成功、socket 超时、worker 崩溃、无回执 —— 一律 `null`，理由：按异常字符串
猜 `false` 会让一次已落地的导航被重放。

## 3 · 状态机（两条边被明确禁止）

```
free → active                       (原子 acquire)
active → releasing | unconfirmed
unconfirmed → recovering | quarantined
recovering → unconfirmed | releasing | quarantined
quarantined → recovering
releasing → free
```

**不存在** `unconfirmed → free`，也**不存在** `任意 → active`。即：

- 没有"超过 TTL 就自动解锁"；
- 没有"下一次请求到来就视为放弃"；
- 没有"进程退出/PID 消失就视为已收尾"。

`reconcile_after = 动作 deadline + 30 s` 只是**进入诊断**的提示，不是解锁条件。

## 4 · 释放条件（三者同时满足）

1. 调用方声明本次计划结束（`owner_finished`），或已核实原调用进程确实终止；
2. 收尾证据属于**操作**而非时钟，且是下列之一：
   - `refused_before_navigation`：worker 在导航 API 之前拒绝；
   - `settled_with_receipt`：该操作的终结回执证明其续体全部结束；
   - `quarantined_old_epoch`：旧 worker 代已被隔离且其输出被丢弃；
   - `target_closed`：原工具标签页已关闭且无在飞 fallback；
   - `resource_gone`：持有它的浏览器实例已核实退出。
3. 没有未终结操作（`settled` 且 `quiescent`）。

**不算证据**（写进代码当作反例清单）：`url_changed` `title_changed` `tab_complete` `deadline_passed`
`revoke_ack` `process_exit`。

## 5 · 身份字段（4 个，2026-11-27 收敛）

| 字段 | 作用 |
|---|---|
| `lease_id` + `fence` | 准入与旧代隔离；`fence` 在同一资源内单调递增，不用时间戳 |
| `operation_id` | 去重、迟到回包归档、只读追问 |
| `worker_epoch` | 扩展上下文重建后识别旧续体 |
| `endpoint_epoch` | 宿主实例身份（合并了原方案的 resource/host/owner 三个） |

`job_id` 沿用 `page_read` 回包里的那个，不再新增。`navigation_id` 仍是"这一次导航"，不是 `job_id`。

## 6 · 持久化白名单

只有 `RECEIPT_KEYS` 里的键可以进共享回执文件（身份、状态、发出与否、导航 id、tab id、时间、错误码）。
**永不入库**：HTML/MHTML、base64 分块、正文、检索结果、带签名 URL、Cookie、token。
完整文献结果仍按 home 返回（`pages/`、`page-read.json` 都在 home 级）。

## 7 · 只读追问（调整 A）

新增 MCP 工具 `navigation_status(operation_id)`，**不新增浏览器动词**：它走宿主控制通道
（与后续 `lease_sync/lease_ack` 同一通道，`features.operation_receipts=1` 协商后启用），
只读、不导航、不抓取、不扣额度。已释放的租约仍可查历史回执。

回包只描述事实：`known` / `state` / `navigation_issued` / `quiescent` / `outcome` / `tab_id` /
`navigation_id`；查不到就是 `known=false, state=unknown, issued=null`，**不是"未发出"**。

## 8 · 混合版本的 fallback

| 组合 | 行为 |
|---|---|
| 全链新版本且 `features` 齐全 | 可进入 `enforce` |
| 新内核 + 旧宿主 | `blocked / lease_protocol_unavailable`，不静默退回旧行为 |
| 新宿主 + 旧扩展 | 不发未知控制帧；`enforce` 拒绝，`observe` 可保留旧功能但无租约保证 |
| 旧内核 + `enforce` 新宿主 | 缺 `lease/context` 的动作在宿主被拒；`ping`/`info` 可用 |
| 任一层版本/代不明 | 只保留诊断，记录停在 `recovering`/`quarantined` |

**发布前提**：`enforce` 只有在"同一受控资源上没有旧宿主链路在服务"时才成立——需要用户重载扩展/确认
宿主切换。在此之前只能标 `observe`，CHANGELOG 与 `status` 措辞都必须这么说。

## 9 · P1a 的接线清单（下一步）

1. 宿主侧 `LeaseStore`/`ReceiptStore` 写 `browser_state_dir()/coordination/`（短锁、锁内重读、
   临时文件原子发布；复用 F41-02 的教训）；
2. `BridgeHost` 超时只取消 waiter，**迟到回包按 `operation_id` 归档**，不投递、不丢；
3. `status` 增加 `browser_lease`（摘要）与 `browser_lock_held`（原始锁事实）；
4. `navigation_status` 工具 + 控制命令；
5. 全部为 `observe`，不强制准入；验收靠假 streams、真 worker VM、进程重启与 wheel 解包。
