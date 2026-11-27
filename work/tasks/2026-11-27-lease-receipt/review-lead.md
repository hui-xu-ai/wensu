# 对 plan.md 的实现方评审（lead）

结论：**接受**。方案与我这一轮踩过的坑对得上（跨层漏项、迟到回包、把"调用返回"当"操作结束"、TTL 解锁），
它的状态机刻意不设 `TTL → free` 与"下一请求 → free"两条边，这是关键，我不改。

下面是三条**我打算在执行中做的收敛**，都属实现细节，不改变方案的安全属性。若规划方不同意，请在实施前告知。

## 调整 A：只读追问走控制通道，不新增浏览器动词

方案把 `navigation_status` 定为新动词，需要同步 5 处词表/参数/能力/计划/fixture。我建议改为**宿主控制命令**
（与已有 `lease_sync/lease_ack` 同一通道，`features.operation_receipts=1` 协商后启用）：

- 理由：它不是浏览器动作，不产生副作用；放进封闭动词表会永久扩大词汇（AGENTS.md 要求新增动词必须有 ADR，
  且这一条会让每层都要多维护一个"永远只读"的动作）；
- 保留：对外仍是独立 MCP 工具 `navigation_status(operation_id)`，回包字段与方案 §四 一致，`quota_charged: 0`；
- 代价：worker 需要一条只读控制帧 `operation.query`，白名单里写明它不调用
  `tabs.update/create/reload`、`pageCapture`、内容脚本；
- 若规划方坚持"必须是动词"，我也能实现，只是每加一层就多一个漏项风险点（F33-01/F34-01 就是漏层）。

## 调整 B：标识符收敛为 4 个

方案有 8 个身份字段。以本项目"单用户桌面、并发 1、跨 home 共享一个浏览器"的实际形态，我建议：

| 保留 | 作用 |
|---|---|
| `lease_id` + `fence` | 准入与旧代隔离（方案的核心） |
| `operation_id` | 去重、迟到回包归档、只读追问 |
| `worker_epoch` | 扩展上下文重建后识别旧续体 |

`job_id` 已有（`page_read` 回包），继续用；`resource_epoch`/`host_epoch`/`owner_instance_id` 合并为一个
`endpoint_epoch`（宿主实例身份），用于"同一资源的新实例可接续诊断"。理由：字段越少，三层同步越不容易漏；
需要区分资源与宿主时，用 `endpoint_epoch + browser_profile_id` 已足够。

## 调整 C：P1 拆成 P1a / P1b，先交付可离线验证的部分

- **P1a（先做）**：宿主持久操作账本 + 迟到原回包归档（白名单字段）+ 只读控制追问 + `status` 摘要字段。
  灰度 `observe`，不强制。验收全部离线：假 streams、真 worker VM、进程重启可读、wheel 解包跨层一致。
- **P1b（后做）**：`features`/epoch 协商、`context` 信封、安装器最小 ACL。

理由：`context` 信封要改 native framing 两侧，是"改错就全线拒动作"的那一类；把它与账本分开，可以先证明
"迟到回包不丢、追问不误导"，再动信封。

## 我认同且会照做的硬要求

1. 不设 TTL 解锁；`reconcile_after` 只触发诊断。
2. 三值 `navigation_issued`；**不能按异常字符串猜 false**；写入部分失败/断连 = `null`。
3. 迟到回包只归档该 operation 的事实，**不投递给新 waiter、不填充下一请求结果**；HTML/MHTML/正文不进共享文件。
4. 准入必须覆盖**所有**浏览器入口（`page_read`/`search`/`detail`/`detail_many`/`warm_up`/`snapshot`），
   `_page_stage` 要先把 `lease_*` 映射到 `navigate`，不能被 `status=blocked → wall` 误吃成验证码。
5. 未确认期间禁止新导航与自动重试；批量 skill 遇 `lease_*` **整批暂停**，不是换组继续撞。
6. 混合版本：未协商不发新帧；新内核 + 旧宿主 ⇒ `lease_protocol_unavailable`，不静默退回旧行为。
7. 验收矩阵里"fixture 必须提供 `info()`"这一条必须落实——本会话两次事故都是夹具不提供能力信息导致
   关键 gate 被跳过。

## 我会先做的一步（P0）

- 更新 `docs/adr/0030-action-identity-envelope.md` 第三片（写明调整 A/B/C 与未做的部分）；
- 新增 `docs/protocol-lease.md`（控制命令、账本 schema、状态机、字段白名单）；
- 写状态转移与字段类型的离线测试（纯 schema，无运行态），保证 P1a 有可执行的契约可依。

P0 不改变任何运行行为，可随时撤销。
