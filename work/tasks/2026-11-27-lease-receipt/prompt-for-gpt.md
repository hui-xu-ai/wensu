# 交给 GPT 的提示词：设计"就绪判定与抓取"方案

复制下面整段给 ChatGPT。它**不需要**访问这台机器，所有它需要的事实都在里面。

---

你是 wensu（Python 包 + Edge MV3 扩展 + 原生消息宿主）的设计评审者。请为"**何时抓取网页**"这一环出一份可实施方案。
不要写代码，输出：结论、备选方案对比、推荐方案的步骤与验收、风险登记、以及你认为需要我确认的决策点。

## 背景与硬约束（不可协商）

- 目标：把论文网页**正文**存成 MHTML，供离线转 Markdown。只读，不下载 PDF，不做第三方题录自动入库。
- 动作词汇封闭：`goto wait_for type click select read_html read_text scroll sleep snapshot await_gate_clear`。新增动词必须先有 ADR。
- 遇风控即停：验证码 / 403 / 429 / 登录页 → 立即 `blocked`，禁止自动重试、禁止换 IP、禁止破解验证码。验证码/登录不冷却；403/429 冷却 24 h。
- 频率：最小间隔 900 ms、并发 1、单次 ≤3 页、每日 ≤300。计费只数 `goto/click/select/type`（每次导航 1 单位）；`snapshot`、`sleep`、`wait_for` 不计费。
- 用户要求：**判断"页面是否加载完成"、决定"何时开始抓取"、以及"兜底超时预算"是三件事，必须分开计算**；兜底预算只为防止程序卡死，不得用来判定页面不存在或抓取失败。

## 当前实现（已验证的事实）

```json
// extension/manifest.json
host_permissions: cnki.net, webofscience.com, webofscience.clarivate.cn   // 只有这两个渠道
permissions     : nativeMessaging, storage, tabs, downloads, pageCapture    // 没有 scripting、没有 debugger
```

```js
// background-*.js
const CAPABILITIES = ["goto", "snapshot", "sleep", "await_gate_clear"];      // 所有站点可用
const CHANNEL_CAPABILITIES = ["read_html","read_text","scroll","click","type","select","wait_for"];
// 上面这组依赖 content script，只注入两个渠道 ⇒ 在出版社页面（ScienceDirect/MDPI/ACS…）不可用
```

- `goto`：`chrome.tabs.update(tabId, {url})` → `waitComplete(tabId, 5000)`，每 250 ms 查 `chrome.tabs.get().status === "complete"`，**5 秒到点不等也返回**。
- `snapshot`：`chrome.pageCapture.saveAsMHTML({tabId})` → base64 分块经原生消息传回内核落盘。实测：3 MB 页面曾耗时 >17 s，当时预算 15 s ⇒ 超时。
- 内核现状：`goto` 之后固定 `sleep 1200 ms`，然后抓一次；抓完才分类（无正文且无登录/拦截标记 ⇒ 判定"仍在渲染"），再 `sleep` 一次、抓第二次（一次为限）。

## 真机观测（真实发生过的）

1. 自然出现机器人验证墙：`goto` 1476 ms，`await_gate_clear` 真等 10127 ms 超时，回包 `blocked/timeout/verification_timeout/wall/waited=true`，未发布，配额差额 1。✅ 正确。
2. 用户手动过验证后，调 `snapshot()` 抓当前页：17.034 s 后 `bridge.error: timed out`，`stage: snapshot`，`retryable: false`，无文件。页面本身可抓（同篇 2.87 MB 抓到过）。
3. 另一次 URL-only 读取：成功，`identity: url`，2.87 MB，SHA 与回包一致。

## 需要你解决的问题

1. **就绪判定**：在"出版社页面没有 content script、没有 scripting 权限"的前提下，只用 `chrome.tabs.get().status`、`chrome.tabs.onUpdated`、`tab.title`、`tab.url` 这些**零网络**信号，如何构造一个"足够可信"的就绪判据？明确指出它会在什么情况下误判，以及每种误判的兜底。
2. **不变式**：如何保证"无论如何至少抓一次、最多抓两次"，从而既不早抓也不至于等到超时还没有文件？请给出可写成测试的不变式。
3. **预算分层**：人类过验证等待、页面就绪等待、抓取本身，三个预算各自的取值理由、到期后的**回包语义**（stage / reason / retryable），以及为什么它们之间不能互相推导。
4. **要不要扩权限**：为拿到真 DOM 就绪判定，加 `scripting` + 出版者 host 权限（`https://*/*`）。请对比"扩权限"与"不扩权限"的收益/代价（含扩展权限提示、与现有两渠道边界的冲突、审计解释成本），并给出你的建议。
5. **`goto` 与用户点书签的区别**：从服务器视角，`chrome.tabs.update` 触发的导航与用户点击书签打开同一 URL，差异可能在哪里（例如 `Sec-Fetch-User`、Referer、user activation）？在不使用 `debugger`/CDP 的前提下，扩展能否让前者更接近后者？如果不能，说明为什么，并给出"把这类差异验证清楚"的最小实验（例如本地回显服务器对比两种导航的请求头，零外部请求）。
6. **额外风险**：列出你认为当前抓取链路里尚未被处理的风险（不含已明令禁止的手段）。

## 输出要求

- 结论先写；每个方案给"成本 / 收益 / 会在什么情况下失效"。
- 步骤要能落地到文件与函数级别（可以引用上面的名字），每步给一条验证命令或测试断言。
- 明确写出"不做的事"，以及需要我决策的点（用编号列表，最多 5 条）。
- 不要提出：CDP/`debugger` 注入、验证码识别或代点、换 IP/代理、并发抓取、以 `sleep` 时长作为就绪依据。
