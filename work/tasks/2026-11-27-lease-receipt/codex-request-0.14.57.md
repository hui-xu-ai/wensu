# 交给 Codex：0.14.57 安装 + 一次真实读取（F55-01 收尾）

日期：2026-11-27。目标：把 0.14.57 真正装进浏览器链路，用**一次**真实读取确认 F55-01 已修。
本轮只做这一件事，不重跑其它历史用例。

## 当前事实（我已核实，别重复确认）

| 项 | 值 |
|---|---|
| native host 注册 | `HKCU\…\Edge\NativeMessagingHosts\com.scholar.search` → `…\installations\0.14.55\browser\native-host\com.scholar.search.json` |
| Edge 加载的扩展 | `…\installations\0.14.55\browser\extension\manifest.json`，版本 **0.14.55**，worker `background-0.14.55.js` |
| 共享配额 | `quota_remaining = 288`（机器级，ADR 0029） |
| `coordination_writable` | `true`（0.14.55 真机读数） |
| 已发布版本 | PyPI / npm `0.14.57` |

## 你要做的步骤

1. **安装到新目录**：按仓库 `docs/publishing.md`/`install` 的既有做法，把 0.14.57 装到
   `C:\Users\xuhui\AppData\Local\scholar-search\installations\0.14.57`（新 venv，不覆盖 0.14.55）。
2. **导出扩展与注册 host**：让 0.14.57 写出 `…\installations\0.14.57\browser\extension\`，并把
   `com.scholar.search` 指向新 host 的 manifest；同时运行该版本安装器的 coordination 权限设置。
3. **请用户重载扩展**（只有用户能做）：重载后 `status.browser_profile.bridge_build.worker`
   必须是 `background-0.14.57.js`、`version` 与 `host_version` 必须是 `0.14.57`。
4. 私有补丁照旧只装进该独立安装，**不要**进公开仓库。

## 一次真实读取（唯一一次）

```text
page_read(url="https://www.sciencedirect.com/science/article/pii/S1385894723029534", refresh=true)
```

**不要**补传 `doi`，**不要**重试，**不要**换网址。

### 必须成立的断言

| 断言 | 依据 |
|---|---|
| `status == "ok"`、`terminal == "ok"`、`stage == "publish"` | F55-01 修复后，URL-only 请求不再因"和空 DOI 比较"被拒 |
| `identity == "url"` | 没有 DOI 约束时以地址的文章身份（PII）为准 |
| `capture_navigation == "match"` | 捕获跟随本次导航 |
| `captured_url` 与请求 URL 相同（query 可不同） | 同一 PII |
| `declared_doi == "10.1016/j.cej.2023.144222"` | 页面自报值原样回传（F53-03） |
| `mhtml_path` 存在且在 `…\scholar-search\pages\10.1016_j.cej.2023.144222\page.mhtml`（或 DOI 检出后对应的目录），**不在** `browser-state\pages` | F41-01 归属分离 |
| 文件 SHA-256 与回包 `capture_sha256` 一致 | 捕获契约 |
| 结束后 `status.browser_lease.state == "free"`、`browser_lock == "free"`、`browser_busy == false` | 租约收尾 |
| 配额差额 = 实际导航数（本形态应为 2） | 计费口径 |

### 如果仍然失败

保留原始回包与动作日志即可，**不要**重试。按 `next` 里的事实陈述逐项核对：

- 若 `reason == "unverified_capture"` ⇒ 看 `capture_navigation` 与 `navigation_id` 是否一致；
- 若 `reason == "capture_mismatch"` ⇒ 记下 `captured_url`、`declared_doi`、请求 URL 三者，这是身份判断的新证据；
- 若 `reason` 是 `lease_*` ⇒ 看 `status.browser_lease.state` 与 `browser_lock`。

另外：0.14.56 之前那次误拒绝把 `capture_mismatch` 写进了页面缓存，TTL 300 s；如果立刻重试仍被挡，
等 5 分钟后再说，不要删缓存、不要改风控状态。

## 顺带确认（不需要访问站点）

- `status.browser_lock` 必须是 `free | held | denied` 三态之一（0.14.57 新增；`denied` 表示当前进程无权写状态目录，不是"有读取在跑"）；
- 若用**未获授权写 state 目录**的解释器跑 `status`（例如仓库 `.venv` 或临时 venv），应得 `browser_lock: "denied"`、`browser_busy: false`——这正是 F56-01 的判定。

## 本轮不要做的事

- 不为制造验证墙/超时反复访问；
- 不重跑历史 MDPI / Springer 用例（它们的结论已由 0.14.54 的离线脚本覆盖：
  `work/verify/2026-11-27-real-capture-0.14.54/check.py`）；
- 不清缓存、不改冷却、不重置租约文件。

## 证据要留

`…\scholar-search\verification\2026-11-27\<本轮>/`：`acceptance.json`（回包原样）、动作审计行、
落盘文件与 SHA-256、`status` 前后各一次（含 `browser_lease` / `browser_lock`）。
