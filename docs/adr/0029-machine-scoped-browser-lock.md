# ADR 0029 · 浏览器锁改为机器级（跨 home）

- 状态：已接受（2026-11-26，只实施第一片）
- 相关：ADR 0005（每日额度/并发 1）、ADR 0022（冷却）、P5 验收 2026-11-26（"跨 home 共享同一浏览器"列为架构风险）

## 背景

浏览器是**一个**资源，但 `SCHOLAR_SEARCH_HOME` 可以有多个：验收用隔离 home、CI 用临时 home、桌面用默认 home。
这些 home 都能驱动同一个浏览器（native host 是系统级注册的），却各自持有一把
`<home>/state/browser.lock`。结果：

- 两个进程都以为自己独占浏览器，实际交错导航；
- 配额（每日 300）与冷却（24 h）也是每 home 一份 —— 一个 home 撞墙冷却，另一个照打。

## 决策（第一片，本轮实施）

新增 `browser_state_dir()`（`SCHOLAR_SEARCH_BROWSER_STATE` 可覆盖，默认
`%LOCALAPPDATA%\scholar-search\browser-state`），并把 **`browser.lock` 移到那里**：

- `ScholarService._browser_lock_path()` → `browser_state_dir()/browser.lock`；
- `status.browser_busy` 探同一把锁；
- 测试通过 `tests/conftest.py` 把该目录指向临时目录，不写用户真实目录。

这样"两个 home 驱动同一浏览器"至少**不会交错导航**，而且不改任何计数语义。

## 决策（第二片，已实施）

`browser_state_paths()` 把三个文件一起交出来：

```
<浏览器状态目录>/state/quota.json
<浏览器状态目录>/state/cooldown.json
<浏览器状态目录>/browser.lock
```

`bootstrap.build_service()` 用它们构造 `PolicyEngine` / `RiskGuard`，并先做一次**迁移**：
`adopt_legacy_state(旧 home 的 quota.json → 共享位置)`，冷却同理。

迁移规则：**读旧文件、写新文件、永不删除**。理由：用户可能回滚到旧版本，旧文件还得在；共享位置已存在时
不再读旧文件（避免两个来源来回覆盖），所以迁移是幂等的一次性动作。文档、缓存、审计日志仍按 home 计。

## 暂不实施（需要自己的迁移）

**配额与冷却仍按 home 计**。把它们移进 `browser_state_dir()` 会改变既有行为（用户可能正用自定义 home
做隔离实验），并需要一次迁移：首次运行从 home 的旧 `quota.json`/`cooldown.json` 读取一次、写入共享位置、
**不删除**旧文件。这一步要单独一个 ADR 与回滚方案，本轮不做。

## 影响面

| 位置 | 改动 |
|---|---|
| `core/config.py` | `ENV_BROWSER_STATE` + `browser_state_dir()` |
| `core/service.py` | `_browser_lock_path()` 指向机器级路径 |
| `bootstrap.py` | `_browser_busy()` 探同一路径 |
| `tests/conftest.py` | 会话级把该目录指向临时目录 |
| 测试 | 新增"两个 home 共享一把锁"用例；修一处自己拼锁路径的用例 |

## 备选与否决理由

| 备选 | 否决理由 |
|---|---|
| 在 `app_home()` 下再开 `shared/` | 仍是 per-home，解决不了同一浏览器两把锁 |
| 按浏览器 profile 哈希分目录 | 更正确，但需要从 host 端点/`browser.json` 推导 profile 身份，属后续细化 |
| 一并把配额/冷却搬过去 | 语义变更 + 迁移，风险不该和"锁"混在一次 |

## 回滚

把 `_browser_lock_path()` 改回 `<state_dir>/browser.lock` 即可；`browser_state_dir()` 里只会留一个空的
`browser.lock` 文件，删掉即可。
