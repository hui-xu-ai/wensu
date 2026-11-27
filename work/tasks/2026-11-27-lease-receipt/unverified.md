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

## 2. ~~安装器最小 ACL（未做）~~ 已于 0.14.55 用真机读数关闭

0.14.55 起宿主的 `info` 带 `coordination_writable`：它在浏览器给它的**低完整性**下真的写一个临时文件
再删掉。真机读数 `true`（`docs/reviews/wensu-0.14.55-coordination-elsevier-2026-11-27.md` §1），
因此"宿主能不能写租约目录"不再是未知。

**仍未证明的相邻部分**（不要把它一起划掉）：这次只证明了"写/删一个文件"可以。**完整的归档、锁、去重与
恢复协议**没有真机样本；要等真实出现一次 `bridge.timeout`、再用 `navigation_status` 查到回执才算。

0.14.46 的 `navigation_status` 与 0.14.52 的 `lease_check` 都依赖这个目录可写；0.14.53 起
`lease_check` 在记录不可信时**拒绝**（`lease_protocol_unavailable`）而不是放行。

## 3. 真机样本仍然缺

- 自然出现的 `bridge.timeout` + 迟到回包（0.14.48 起的路径）；
- 人工点完验证后同一次调用续抓（0.14.41 那次是中间页自清，不是人工点击）；
- 真实 10 秒验证超时。
