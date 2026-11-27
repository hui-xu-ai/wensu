# 未验证清单（租约 / 回执）

记录"已发布但没有行为验证"的东西，避免下一轮把它当成已验证。

## 1. worker 侧的旧代围栏（0.14.52）

- 代码：`extension/background-*.js` 的 `lease_sync` 处理、`policy.fence` 拒绝、`WORKER_EPOCH`。
- 现状：只有**静态契约测试**（`tests/unit/test_capability_contract.py::test_the_worker_implements_the_lease_fence`）断言这几处存在且接进了消息分派。
- 缺什么：一次真行为的回放——`lease_sync` 后，旧 fence 的动作必须被拒、当前 fence 与无信封的动作必须放行。

### 我试过的两次（都失败，都删掉了）

1. **两条管道 + 脚本化 worker**：宿主侧握手 OK，但探针要驱动的是 worker 而不是宿主，方向错了。
2. **VM + 假 `chrome` + 端口**：加载成功，但 `onConnect`/`onMessage` 的回调没有收到任何消息，四条全 `null`。
3. **VM + `context.onHostMessage(message, channel)`**（照 `gate_watch_probe.js` 的既有模式）：进程不退出，
   没有任何输出——最可能是 worker 顶层的 `connect()`/定时器让 VM 一直活着，而 `console.log` 在
   异步链之前就被挡住了。

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

## 2. 安装器最小 ACL（未做）

`coordination/` 需要低完整性可写（浏览器启动的宿主是低完整性进程）。目前没有任何证据说明真机上
宿主能写进去；0.14.46 的 `navigation_status` 与 0.14.52 的 `lease_check` 都依赖这个目录可写。

**更正（0.14.53）**：本文件早先写的是"`lease_check` 读不到记录时按 `free` 处理 ⇒ 会拒绝一切带租约的帧"。
**这句话是错的，方向正好相反。** 按 0.14.52 的实际代码，记录不可读时 `LeaseStore.read()` 返回
`quarantined`，而 `lease_check` 里"记录没有 `lease_id`"那条短路让它返回 `None` ⇒ **帧照发**。
也就是说权限失败的后果不是"全部拒绝"，而是**静默不设防**：谁也不知道旧导航是否还在落地，宿主替它放行。

0.14.53 改了两处：

1. `lease_check` 对 `quarantined`/`unknown`/读取异常一律返回 `lease_protocol_unavailable`（拒绝，且原因
   指向可修的东西），不再因为"记录里没有 `lease_id`"而放行；
2. `install.ps1` 创建并给 `browser-state/coordination` 打低完整性标签（尊重
   `SCHOLAR_SEARCH_BROWSER_STATE` 覆盖）。

**仍未验证**：真机上这次 ACL 是否足够。它只能在真实读取自然出现一次 `bridge.timeout`、再用
`navigation_status(<operation_id>)` 查到回执时才能确认；在那之前，"宿主能写进 coordination/" 只是
安装器的意图，不是观测到的事实。

## 3. 真机样本仍然缺

- 自然出现的 `bridge.timeout` + 迟到回包（0.14.48 起的路径）；
- 人工点完验证后同一次调用续抓（0.14.41 那次是中间页自清，不是人工点击）；
- 真实 10 秒验证超时。
