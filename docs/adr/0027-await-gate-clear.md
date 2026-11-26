# ADR 0027 · 为"等人清掉验证页"增加 `await_gate_clear` 动作

- 状态：已接受（2026-11-26）
- 相关：ADR 0004（遇风控即停）、ADR 0018（快照由浏览器读当前标签页）、ADR 0022 修订 1（验证/登录不冷却）、审计 F08（内容脚本只注入两个渠道）

## 背景

一次读取在 `goto` 返回时得到的标题可能是验证墙，也可能是"马上就好的中间页"。人只要在浏览器里点一下就能过，但内核拿不到"人已经点完"这个事实：

- `wait_for` 依赖内容脚本，而 `extension/manifest.json` 只把 `content/actions.js` 注入知网与 WoS 两个域名，出版社页上**没有接收端**，等待必然超时。0.14.28 曾用 `wait_for` 实现过这个等待，是一次"幽灵能力"（审计 F08）。
- 只用 `sleep` 再抓一次，抓到的可能是墙本身（一次 2–4 MB 的 MHTML），且无法区分"人点了"和"人没点"。
- 因此当前行为是：识别到门标题就返回 `blocked`，之后由人或调用方再发一次调用——**没有"点完了"的信号**。

## 决策

新增一个动作 `await_gate_clear`，由扩展在内部轮询标签页标题：

```
await_gate_clear {
  halt_titles:   [...]   // 与 goto 相同的门标记（值来自 core/risk.py）
  halt_url_markers: []   // 保留字段，当前恒为空
  timeout_ms:    10000   // 人有多久
  poll_ms:       2000    // 多久看一眼
}
→ { cleared: true, url, title } | { cleared: false, url, title, reason: "verification_timeout" }
```

行为：

1. 先把工作标签页所在的窗口 **最大化并切到前台**（人要能看见才能点）；
2. 每 `poll_ms` 读一次 `tabs.get(tabId).title`，用与 `goto` 相同的 `looksLikeGate` 规则判断；
3. 标题不再命中门标记 ⇒ `cleared: true`；到点仍命中 ⇒ `cleared: false, reason: verification_timeout`。

内核：`cleared` ⇒ 继续本页的抓取与判定；未清 ⇒ 本次读取以 `terminal: timeout`、`reason: verification_timeout` 结束，批量层据此**跳过该出版商**（`work/tasks/2026-11-26-read-flow/plan.md` §三）。

## 为什么不是放宽 `wait_for`，也不是扩大权限

- 扩 `host_permissions`/`content_scripts` 到所有出版社，会把"每个站点都能注入脚本"变成默认，风险面远大于收益；
- `pageCapture` 复用（抓一次再判断）会产生一次完整 MHTML 传输，且墙的字节仍要丢弃；
- 只读 `tabs.get().title` 用的是**已有的 `tabs` 权限**，不新增任何权限。

## 计费与风控语义

- 该动作**不是网络动作**：`policy.NETWORK_VERBS` 不变（`goto/click/select/type`），所以等待本身不扣额度；
- 它**不是"自动重试"**：不重新导航、不换 IP、不延时重试；等待的对象是人的一次点击（ADR 0022 修订 1 的"人点一下就过"）；
- 未被清掉时**停止**而不是继续，符合 AGENTS.md 3（遇风控即停）。

## 影响面

| 位置 | 改动 |
|---|---|
| `core/contracts.py` | `VERBS` 增加 `await_gate_clear`（词汇表封闭，需本 ADR） |
| `core/policy.py` | `READ_VERBS` 增加它（免费、非网络动作） |
| `core/params.py` | 参数白名单：`halt_titles` / `halt_url_markers` / `timeout_ms` / `poll_ms` |
| `core/service.py` | `_page_spec` 允许该动词；`_await_gate_clear()`；门标题分支改为"先问人，再决定" |
| `extension/background-*.js` | 新动作分支（含窗口最大化 + 标题轮询） |
| 测试 | 墙夹具由"settle + 快照"改为"一次等待"：未清 ⇒ `timeout`，已清 ⇒ 继续抓 |

## 备选与否决理由

| 备选 | 否决理由 |
|---|---|
| 继续用 `wait_for` | 出版社域没有内容脚本接收端，必然超时（F08 已实证） |
| 纯 `sleep(10s)` + 再抓一次 | 无法区分"人点了"与"人没点"，还要为墙付一次完整抓取 |
| 扩注入域到全部出版社 | 权限面过大；且与 ADR 0018 的最小权限取向冲突 |
| 让人手动重发调用 | 现状；调用方拿不到"点完了"的信号，批量编排无法判断该跳过还是继续 |

## 回滚

该动作只在 `service._read_page` 的门标题分支里使用。回滚 = 删掉调用与动作分支，恢复"识别到门标题即返回 `blocked`"；`VERBS`/`READ_VERBS`/`params` 里多出的那条不参与其它路径，留着也无副作用。
