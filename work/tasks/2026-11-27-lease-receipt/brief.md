# 待定方案：租约与超时回执（ADR 0030 第三片）

给外部规划 agent 的问题清单。请按本文件末尾"交付要求"给出方案；本文件只陈述**我不知道答案**的部分，
以及不能违反的约束。

- 仓库：`D:\Python\DeepSeek\DateWork\scholar-search`，基线 `f5a903d`（0.14.45 已发布）
- 现状文档：`docs/adr/0030-action-identity-envelope.md`（第一片、第二片已完成；第三片未做）
- 已完成的相邻工作：`docs/adr/0029-machine-scoped-browser-lock.md`（配额/冷却/锁已机器级）

## 已经成立的事实（不要重新设计这些）

1. `page_read` 一次调用内跑完整个计划：`goto`（可能 2 条，见私有导航补丁）→ `sleep` → `snapshot`。
2. 浏览器访问由 `<浏览器状态目录>/state` + `browser.lock` 串行化，跨 home 共享；并发 1。
3. 动作词汇封闭：`goto wait_for type click select read_html read_text scroll sleep snapshot
   await_gate_clear`。新增动词需 ADR + 同步 host `VERBS` + 扩展 `CAPABILITIES`（两处都要，
   漏一处会在真机上被拒，已经发生过两次：F33-01、F34-01）。
4. 回包已带 `tab_id`、`navigation_id`（每次导航唯一）、`navigation_attempts`；`snapshot` 已能被
   内核指定 `tab_id`（0.14.45）。
5. 读取回包契约：`job_id / terminal(ok|partial|blocked|timeout|no_page|unsupported_site) /
   stage(cache|navigate|wall|capture|identity|publish) / evidence / identity / full_text`。
6. 现在导航超时的终态是 `status: timeout / reason: navigation_unconfirmed / stage: navigate /
   unconfirmed: true`，但**内核不知道标签页最终有没有落地**。
7. `status` 报 `browser_busy`（用 `browser.lock` 非阻塞试取）与 `last_job`（home 级路径）。

## 疑问一：租约由谁持有、何时算结束

- 持有者选项：(a) 扩展侧按 tab 记（内存，MV3 worker 会被回收）；(b) 宿主进程内存；(c) 内核 state 文件。
- 结束条件选项：计划返回 / 捕获发布完成 / 终态回包写出 / 人工或超时过期。
- 未确认时如何过期：固定秒数（多少？30 s？）还是"下一次读取开始即视为放弃"？
- 需求：**不得**在用户手动操作浏览器（例如自己在同一标签页点了验证）后把租约永久卡死。

## 疑问二：「租约未终结就不派新任务」的强制点在哪里

`page_read` 是同步工具调用，没有队列。可选：

- (a) 调用内阻塞等待租约释放（上限多少秒？会吃掉模型侧超时预算）；
- (b) 立即返回 `terminal: busy`（新增终态？还是 `timeout` + `reason: lease_held`？）；
- (c) 只在"上一个 job 仍未终结"时拒绝，且提供 `status.last_job.unconfirmed` 让调用方自行决定。

`terminal` 是封闭枚举，新增值会影响下游（批量 skill、验收脚本）。请明确选哪个、是否需要新枚举值。

## 疑问三：超时回执的形态

- (a) **piggyback**：扩展在超时后继续观察，下一次任意请求回包里附带 `late_navigation`（不改协议、
  无第二回执，但只有在"下一次请求发生"时才可见）；
- (b) **只读追问**：新增 `navigation_status`（或复用 `snapshot` 不带字节的参数）由内核主动问，
  0 额度，代价是一次往返；
- (c) **真·第二回执**：宿主支持异步多帧，扩展在超时后补发终态。最完整，改动最大，旧宿主需要容忍未知帧。

请评估三者对**滚动升级**（旧宿主/旧扩展/旧内核混跑）的影响，并说明 fallback 行为。

## 疑问四：超时语义的两类要分开吗

桥超时至少有两种：**动作根本没发出**（`navigation_issued=false`，可安全重试）与**发出但没回**
（可能已落地，不可重试）。现在两者都归到 `navigation_unconfirmed`。是否应拆成
`navigation_not_issued` / `navigation_unconfirmed`？若拆，下游（批量 skill 的跳过规则）如何区分。

## 疑问五：未确认时允许重试吗

若允许：如何避免两次导航交错（同一 tab 第二次导航覆盖第一次的落地）？是否强制"先只读确认当前 URL
再决定"，以及这个只读确认要不要计入额度（现在是 0）。

## 疑问六：验收口径

约束：**不制造风控样本**（不能靠反复访问制造超时/验证页）。已有：自然墙一次（0.14.41 复验，等待 6.1 s
自行清除）、两 goto 形态一次（0.14.44）、单次正常读取若干。没有"真·10 秒超时"与"人工点完续抓"样本。

请给出：这三条改动分别可用什么**离线回放**验证（仓库已有 `tests/unit/test_wall_early_exit.py` 的
JS 回放机制：真 worker + 假浏览器；以及 fixture 适配器），以及哪些必须等真实偶发样本。

## 不可违反的约束

- 只读：不实现 PDF/CAJ 下载；不写第三方文献库。
- 遇风控即停：验证码 / `/verify/home` / 403 / 登录重定向 ⇒ 停；验证与登录**不冷却**，403/429 冷却 24 h。
- 频率：最小间隔 900 ms、并发 1、单次 ≤3 页、每日 ≤300；这些只能收紧。
- 域名白名单由渠道 manifest 声明，内核与宿主双重校验。
- 运行期数据只写 `SCHOLAR_SEARCH_HOME`；浏览器级状态（配额/冷却/锁）写 `browser_state_dir()`。
- 不能假设只有一条 `goto`：私有导航补丁会发两条（首页 → 文章），`navigation_id` 取**最后一次**。
- 三层词表/能力表必须同时更新，且要有跨层契约测试（`tests/unit/test_capability_contract.py`）。

## 交付要求

1. 一份分阶段方案（每阶段：改哪个文件、验证方式、可灰度性、回滚方式）；
2. 对疑问一~六逐条给出**决策与理由**，而不是选项罗列；
3. 明确哪些阶段会改变 `terminal` / `stage` 枚举或工具回包字段，并给出下游（批量 skill、验收脚本）
   的同步要求；
4. 不允许出现"实现与声明脱节"的层（每条新增动作/字段都要指名它出现在哪几个文件里）。
