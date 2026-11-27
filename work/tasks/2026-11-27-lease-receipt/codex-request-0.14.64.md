# 交给 Codex：0.14.64 真机验收（ADR 0031 P3）

日期：2026-11-27。仓库 `cfd67cd`，被测版本 **0.14.64**（PyPI / npm 均已发布）。
本轮只做两件事：**重页面一次读取** 与 **人工放行后零导航续读**。不重跑历史用例。

## 前置

1. 装 0.14.64 到 `C:\Users\xuhui\AppData\Local\scholar-search\installations\0.14.64`（新 venv，不覆盖旧版）；
2. 让它导出扩展并注册 native host（`com.scholar.search` 指向新目录），运行该版 coordination 权限设置；
3. **请用户重载扩展**；重载后 `status.browser_profile.bridge_build` 必须同时满足：

```json
{"version": "0.14.64", "worker": "background-0.14.64.js", "handshake": "ok",
 "host_version": "0.14.64", "coordination_writable": true,
 "features": {"lease_control": 1, "operation_receipts": 1,
              "readiness_observe": 1, "capture_receipts": 1}}
```

`features` 里缺 `readiness_observe` ⇒ 内核会退回旧的固定 1.2 秒路径，本轮验收**无效**，先说清而不是照旧记录。

4. 私有补丁与否都可，但请**在报告里写明本轮是否为纯官方版**——这两轮的结论不能混用。

## 一、重页面读取（最重要）

```text
page_read(doi="10.1016/j.cej.2023.144222", refresh=true)
```
或同一篇的 `url=`。**一次**，不重试。

### 必查字段

| 字段 | 期望 | 说明 |
|---|---|---|
| `status` / `terminal` / `stage` | `ok / ok / publish` | |
| `readiness.strategy` | **`observe`** | 出现 `settle` 说明 worker 没广告特性，本轮无效 |
| `readiness.state` | `candidate` 或 `observing` | 两者都合法，含义不同 |
| `readiness.elapsed_ms` | 记录实值 | 与旧固定 1.2 s 对比，这是本次改动的核心证据 |
| `readiness.budget_exhausted` | 布尔 | 若为 `true`，说明元数据始终没"安静"，但**仍然抓到了**——这正是 I3 |
| `capture_navigation` | `match` | |
| `mhtml_path` | `…\scholar-search\pages\10.1016_j.cej.2023.144222\page.mhtml` | F57-01：按页面 DOI 命名 |
| `declared_doi` | `10.1016/j.cej.2023.144222` | |
| `quota_charged` | 1 | 观测与抓取都不计费 |
| 收尾 | `browser_lease.state=free`、`browser_lock=free`、`browser_busy=false` | |

### 若失败

按 `stage` 分辨，**不要重试**：

- `stage=ready` + `reason=not_ready_timeout` ⇒ 观测预算用尽（这是设计内的，但仍应抓到文件）；
- `stage=capture` + `reason=capture_unconfirmed` ⇒ 抓取本身超时，浏览器可能仍在生成；
- `stage=identity` ⇒ 抓到的是另一篇，记 `captured_url`/`declared_doi`/请求 URL 三者；
- 其它 ⇒ 原样保留回包。

## 二、人工放行后的零导航续读

**只有自然遇到验证墙时才做这一项**（不要为了验收去制造）：

1. 第一次 `page_read(url=…)` → 遇墙，回包记下 `job_id`（应为 `blocked` 或 `terminal=timeout`、`stage=wall`）；
2. 用户在浏览器里手动完成验证，**明确确认已进入文献页**；
3. 调 `page_read(resume_job_id="<第 1 步的 job_id>")`，**不加** `refresh`、**不补** `doi`。

### 必查字段

| 字段 | 期望 |
|---|---|
| `status` / `terminal` | `ok / ok` |
| `quota_charged` | **0**（不导航） |
| `resumed_from` | 等于第 1 步的 `job_id` |
| `job_id` | 与第 1 步**不同**（旧回包不被改写） |
| `mhtml_path` | 真实存在，且在 home 的 `pages/` 下 |
| 审计 | 本次调用**没有** `goto` 行 |

若 `resume_job_id` 报 `policy.resume_unknown` ⇒ `state/last-job.json` 里的 `job_id` 与传入不一致
（例如中间又跑过一次读取），照实记录，不要重跑其它读取来"凑"。

## 三、不需要做的事

- 不制造验证码/超时；
- 不重跑 MDPI、Springer 的历史用例（已有 `work/verify/2026-11-27-real-capture-0.14.54/check.py` 覆盖，离线）；
- 不清缓存、冷却、租约文件；不删任何 `pages/` 下的文件；
- 不并发。

## 四、证据

`…\scholar-search\verification\2026-11-27\<本轮>/`：

- `acceptance.json`：两次调用的原始回包、前后 `status`（含 `bridge_build.features`）、配额差额；
- `actions.jsonl`：两个窗口的动作行（续读窗口必须没有 `goto`）；
- 落盘文件与 SHA-256；
- 若遇到墙：等待回包的 `waited`/`wait_reason` 与用户确认原话。

## 五、我这边已备好的离线证据（供你交叉核对，不必重跑）

- `tests/js/readiness_probe.js` + `tests/unit/test_worker_observation.py`：真 worker 上 `candidate` 813 ms、
  `observing` 1021 ms、`saveAsMHTML` 调用 **0** 次、`features` 两键齐全；
- `tests/unit/test_page_readiness.py`：candidate 立即抓、预算耗尽仍抓、旧 worker 走 settle、risk 零捕获；
- `tests/unit/test_page_resume.py`：续读不导航、与 `refresh` 互斥、未知 job 拒绝。

真机只用来回答一个问题：**这些离线行为在真浏览器里是否同样成立。**
