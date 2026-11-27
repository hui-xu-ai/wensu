# 三次读取关掉剩余未验证项（0.14.65）

日期：2026-11-27。被测版本 **0.14.65**（PyPI / npm 已发布）。
三条都走**普通读取**：不额外访问、不制造验证墙、不改站点行为、不用降级网站。用完删掉环境变量即恢复默认。

前置：装 0.14.65 → 重载扩展 → `status.browser_profile.bridge_build.worker` 应为
`background-0.14.65.js`、`features` 含 `readiness_observe: 1`。

---

## ① 无验证阻断的直读：`capture_navigation` 应为 `match`

**目的**：证明"这次捕获确实跟着本次读取发出的那次导航"。最近几轮都停在墙或走续读，这条一直没机会出现。

**操作**：在浏览器里手动通过一次验证后，**短时间内**读同一出版商的**另一篇**文献（不需要特殊条件）：

```text
page_read(doi="<另一篇的 DOI>", refresh=true)
```

| 字段 | 期望 | 若不符 |
|---|---|---|
| `status` / `terminal` / `stage` | `ok / ok / publish` | — |
| `capture_navigation` | **`match`** | `absent` ⇒ 捕获没带上 navigation_id；`mismatch` ⇒ 抓到的是另一次导航的页面，需查 `navigation_id` |
| `readiness.strategy` | `observe` | `settle` ⇒ worker 没换，本轮无效 |
| `quota_charged` | 1（官方基线一次导航） | 2 ⇒ 有第二次导航，记下审计两条 `goto` |
| 落盘 | `pages/<DOI>/page.mhtml` | 标题目录 ⇒ F57-01 复发 |

---

## ② 观测预算耗尽：`budget_exhausted: true`，**仍然抓一次**

**目的**：不变式 I3——预算到期不是放弃，是"照抓并如实标注"。两条真机都在 617 ms 就一致了，从没走到这里。

**操作**：

```powershell
$env:SCHOLAR_SEARCH_READINESS_BUDGET_MS = "50"
```

然后读任意一篇（有墙也照常，遇墙就停下来另开一轮）：

```text
page_read(doi="<任意一篇>", refresh=true)
```

| 字段 | 期望 | 说明 |
|---|---|---|
| `readiness.strategy` | `observe` | |
| `readiness.budget_exhausted` | **`true`** | 50 ms 内元数据不可能"安静" |
| `readiness.state` | `observing` | 不是 `candidate`——这两者的区别就是本条要验的 |
| `mhtml_path` | **非空且文件存在** | 抓取照常发生 |
| `status` | `ok`（若页面本身正常） | |

读完删掉变量：`Remove-Item Env:SCHOLAR_SEARCH_READINESS_BUDGET_MS`。

---

## ③ 抓取超时 + 迟到回执：`capture_unconfirmed` 后能查到

**目的**：一条动作超时返回、浏览器之后自己完成时，调用方仍能按 `operation_id` 查到事实。

**操作**：

```powershell
$env:SCHOLAR_SEARCH_SNAPSHOT_TIMEOUT_MS = "200"
```

读任意一篇（上面 ② 那篇也行，但请**重新发起**一次读取，不要复用 ② 的回包）：

```text
page_read(doi="<同上>", refresh=true)
```

| 字段 | 期望 |
|---|---|
| `stage` | **`capture`**（不是 `navigate`——这正是 0.14.60 修的那处） |
| `reason` | `capture_unconfirmed` |
| `terminal` | `timeout` |
| `quota_charged` | 1（导航照常计费；抓取不计费） |
| `mhtml_path` | `null` |
| `operation_id`（在 `evidence` 或 `last_job` 里） | 有值，记下来 |

紧接着（**只读、免费、不碰浏览器**）：

```text
navigation_status(operation_id="<上一步的 operation_id>")
```

| 字段 | 期望 | 若不符 |
|---|---|---|
| `known` | **`true`** | `false` ⇒ 迟到回执没被归档，这是真缺陷，请把两个回包都留给我 |
| `operation.action` | `snapshot` | 说明账本按操作记录，与动词无关 |
| `operation.state` | `settled`（若回执已到）或 `unknown`（若还没到） | 都不是"页面不存在" |
| `quota_charged` | **0** | 这个查询不花额度 |

读完删掉变量。若 `known: false`，请**等 30 秒再查一次**（迟到回执可能要一会儿才落地），仍为 `false` 就是缺陷。

---

## 不要做的事

- 不为了制造超时去反复访问；上面三条各自只读**一次**；
- 不并发；不清缓存/冷却/租约文件；
- 不为 ① 特意换出版商（同一出版商可用即可，验证不会立刻失效）；
- 若遇到**新的**验证墙：停下、告诉用户手动过，然后按 `resume_job_id` 续读即可（这是已验收的路径）。

## 交回什么

每一轮：完整回包（或 `acceptance.json`）+ 审计窗口 + `status` 一次（含 `browser_lease`/`browser_lock`）。
我关心的不是"能不能读"，而是这六个字段：`capture_navigation`、`readiness.strategy`、
`readiness.budget_exhausted`、`stage`、`reason`、`known`。
