# ADR 0028 · 预热标签页：为"人清验证"保留若干标签页

- 状态：已接受（2026-11-26）
- 相关：ADR 0018（快照读当前标签页）、ADR 0022 修订 1（验证不冷却）、ADR 0027（`await_gate_clear`）、ADR 0017（启动后只留一个窗口）

## 背景

验证页属于**站点**并且有时间窗：同一出版商的连续读取，往往只需清一次。但内核默认只有一个工作标签页，且 `closeDisposableTabs()` 会在**每次导航前**把临时标签页清成 `about:blank` —— 任何"提前打开、留给人点"的页面都会在下一篇文献开始前被清掉，等于白做。

批量场景（`skills/scholar-batch-read`）需要在开工前把若干出版商的验证页一次性摆出来让人点，之后再串行抓取。

## 决策

1. `goto` 增加一个参数 **`keep: true`**（与 `open: "new"` 同时使用）：该标签页被记入**保留名单**（`chrome.storage.local["wensuKeptTabs"]`），`closeDisposableTabs()` 永不触碰它。
2. 新增 MCP 工具 **`warm_up(targets: [doi|url])`**：为每个目标出版商的**一篇**文献各开一个保留标签页，返回 `opened[]`（含 `publisher`/`ok`/`quota_charged`）与总 `quota_charged`。
3. 保留标签页**由用户自行关闭**（本轮不提供自动关闭动作：关闭动作要么新增动词，要么让 `goto` 带一个"不导航只关闭"的分支，两者都会把词汇表/参数表推向语义重载）。超过 8 个按最早淘汰（`slice(-8)`）。
4. 保留标签页**不是工作标签页**：后续读取仍在工作标签页进行，不会被这些页面干扰（`boundTabId`/`workTab` 逻辑不变）。

## 成本与告知

- 每个目标 = **1 次导航 = 1 额度 + 1 次站点访问**；默认 4 家 = 4 额度。
- 因此 `warm_up` 的工具说明与 skill 都要求**先告诉用户成本再调用**，并在调用后请用户去点。
- 保留标签页不会自动刷新；时间久了验证可能再次出现，此时由用户自己刷新/重点。

## 影响面

| 位置 | 改动 |
|---|---|
| `extension/background-*.js` | `KEPT_KEY` 名单、`rememberKept()`；`open:"new"` 分支按 `keep` 分流；`closeDisposableTabs()` 不触碰保留名单 |
| `core/params.py` | `goto` 参数白名单加 `keep`；校验：必须是 boolean，且只在 `open:"new"` 时允许 |
| `core/service.py` | `warm_up(targets)`：逐个目标解析出版社、一个事务内连续 `goto`，按实际动作计费 |
| `server.py` | 新工具 `warm_up`（第九个工具） |
| `tests` | 工具清单由八个改为九个；`warm_up` 计费与 `unsupported_site` 用例 |

## 备选与否决理由

| 备选 | 否决理由 |
|---|---|
| 让用户自己开浏览器标签页 | 无法保证标签页落在允许域内，也无法在之后的抓取里复用"已清"的状态 |
| 用 `open:"new"` 但不加 `keep` | 下一次导航就被 `closeDisposableTabs()` 清空，预热失效 |
| 自动定时刷新保留标签页 | 等于在用户不知情时反复访问站点，与"遇风控即停/不重复访问"的取向冲突 |
| 新增 `close_kept` 动词 | 扩词汇表只为关闭标签页，收益不抵语义重载（可后续按需再加 ADR） |

## 回滚

`keep` 是可选参数：去掉 `rememberKept()` 的分流即可回到"全部按临时标签页处理"；`warm_up` 工具可单独下线（不影响其它工具）。保留名单存在 `chrome.storage.local`，残留只是几个标签页，用户关掉即可。
