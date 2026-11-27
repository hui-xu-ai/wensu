# 方案：把"何时抓取"与"兜底预算"分开（0.14.60）

作者：lead。日期：2026-11-27。状态：**待确认**（未动代码）。

## 0. 先说一个我上一轮说错的事实

我上一条说"用 `read_html`/`read_text`/`wait_for` 轮询 DOM 判断加载完成"——**对出版社页面做不到**。
刚查了 `extension/manifest.json` 与 `background-*.js`：

```json
host_permissions: cnki.net, webofscience.com, webofscience.clarivate.cn     // 只有两个渠道
content_scripts : 同上                                                       // content/actions.js 只注入这两处
permissions     : nativeMessaging, storage, tabs, downloads, pageCapture      // 没有 scripting
```

```js
const CHANNEL_CAPABILITIES = ["read_html","read_text","scroll","click","type","select","wait_for"];
const CAPABILITIES = ["goto","snapshot","sleep","await_gate_clear"];
```

`read_html` / `read_text` / `wait_for` 依赖 content script，**ScienceDirect / MDPI / ACS 上没有**。
所以"用 DOM 探针判断就绪"在当前权限下对真实出版社页面是**空话**，这也是我对方案一直说得很虚的原因。

## 1. 现状（有代码位置，不是印象）

| 环节 | 现在怎么做的 | 问题 |
|---|---|---|
| 导航后等加载 | worker `waitComplete(tabId, 5000)`：每 250 ms 查 `tab.status === "complete"`，**5 秒到点不等也返回** | 慢页面在"仍在加载"时就返回 |
| 等正文渲染 | 内核固定 `sleep 1200 ms`（`_ARTICLE_SETTLE_MS`） | 拿时间当依据；与网速无关 |
| 抓取 | `saveAsMHTML` 一次 | — |
| 判断是否真的抓到 | 抓完分类（`_still_rendering`：没有正文但也没有登录/拦截标记） | **事后**才知道；等价于"拿抓取当探针" |
| 补救 | 再 `sleep` 一次 → 再抓一次（一次为限） | 第二次抓取 |
| 兜底 | `SNAPSHOT_TIMEOUT_MS`（我上一轮 15s→60s） | 被当成"成败判据"，17 s 就把可抓页面判死 |

## 2. 核心难点：没有任何单一信号能证明"加载完成"

| 候选信号 | 出版社页面可用？ | 会怎么骗人 |
|---|---|---|
| `tab.status === "complete"` | ✅（`tabs` 权限） | SPA 正文在 complete 之后才渲染 ⇒ 假"就绪" |
| `chrome.tabs.onUpdated` 静默（一段时间无 status 变化） | ✅ | 长连接/轮询站点的 complete 之后仍在变 ⇒ 假"未就绪" |
| `tab.title` / `tab.url` | ✅ | 标题在正文出来前就已定稿 ⇒ 假"就绪" |
| `document.readyState` / DOM 文本量 / 章节标记 | ❌ 需要 `scripting` + 出版者 host 权限 | 精确，但要扩权限 |
| **抓下来的 MHTML 内容本身** | ✅ | 最权威，但代价是一次整页抓取 |

结论：**能拿到的最强证据是"抓下来的内容"**，而它同时也是我们要的产物。所以设计目标不是"找一个完美的就绪信号"，
而是：**用最便宜的信号决定何时敢抓第一次，用内容本身做最终裁决，并且保证无论如何都会抓、且最多抓两次。**

## 3. 方案 A（推荐，不扩权限）

**把就绪判定搬进 worker**——只有它在能看到 `tabs` 与 `onUpdated`。

1. **`goto` 收紧语义**（不加新动词）：等到 `status === "complete"` **且** 连续两次检查间隔 ≥500 ms 无
   `onUpdated(status)` 变化（"安静"），上限 45 s；回包带上
   `page_state: {status, quiet, waited_ms, capped}`，让内核知道"是真的安静了"还是"到顶了"。
2. **内核去掉固定 1.2 s 睡眠**：不再用时间当依据。`page_state.quiet === false` 时按 `sleep`（免费）做
   **至多若干次**的有界等待，每次之后重读 `page_state`（通过一次 `snapshot` 前的最小 `goto`? 否——
   见 3.3，只读 `page_state` 需要一次便宜调用，这里用 `snapshot` 的 `probe_only` 变体，见下）。
3. **`snapshot` 增加 `wait_ready_ms` 参数**（同一动词，扩展语义）：worker 先等 `complete`+安静（最多
   `wait_ready_ms`），再 `saveAsMHTML`；回包里同样带 `page_state`。**这一步让公开 `snapshot()` 也有就绪判定。**
4. **抓取次数硬约束**：一次读取里 `saveAsMHTML` **至少 1 次、至多 2 次**。第一次在"就绪或就绪兜底到期"时发生；
   第二次只在第一次抓下来的内容被判定为"没正文也没拦截"时发生（就是现有的 second look）。
5. **兜底只是兜底**：
   | 预算 | 值 | 到期后果 |
   |---|---|---|
   | 人类过验证 | 10 s（不动） | `stage: wall`、`verification_timeout`、`waited: true` |
   | 就绪等待 | 120 s（网速容差） | **仍然抓一次**，回包 `stage: ready`、`reason: not_ready_timeout` |
   | 抓取本身 | 120 s | `stage: capture`、`reason: capture_timeout`，无文件 |
6. **回包永远不撒谎**：`stage` ∈ `wall | ready | capture | identity | publish`，`reason` 只陈述已发生的事实；
   绝不把"预算到了"说成"页面不存在"或"抓取失败"。

### 为什么这不会"到超时都没抓"

因为就绪等待到期时的动作是**无条件抓一次**（第 5 条），不是"再等一会儿"。这个不变式有专门的测试。

### 为什么这不会"抓早了"

因为抓完立即分类，判定为"没正文"时还有一次（且仅一次）补救；同时 `goto` 的"安静"判定已经排除了
最常见的一种早抓（主文档还在跳转/加载）。仍然可能早抓的只剩"SPA 在 complete 之后才画正文"这类，
由第二次抓取兜住。

## 4. 方案 B（可选，需要你决策）：扩权限换取真正的 DOM 就绪判定

加 `scripting` 权限 + 出版者 host 权限（`https://*/*` 或逐站），就能在出版社页面上读
`document.readyState`、正文长段落数、DOM 静默。收益：早抓风险接近零、可在抓之前就发现"页面是验证页"。
代价：

- 权限扩张会出现在扩展的权限提示里，且与当前"只对两个渠道注入 content script"的既定边界冲突（需新 ADR）；
- 需要用户重新授权/重装扩展；
- 权限越宽，扩展被审计时越难解释。

我的建议：**先做 A**；B 只有在 A 的真机样本里仍然出现"早抓/晚抓"时才提。

## 5. 验证计划

单测（fixture 回放，不需要真机）：

| 用例 | 断言 |
|---|---|
| 页面立刻安静 | 只抓一次，`page_state.quiet: true`，`stage: publish` |
| 一直不安静 | 到就绪兜底后**仍然抓一次**，回包 `stage: ready`、`reason: not_ready_timeout`，且有文件 |
| 抓下来没正文 | 发生**第二次且仅第二次**抓取；总抓取次数 = 2 |
| 抓取超时 | `stage: capture`、`reason: capture_timeout`、无文件、`retryable: true` |
| 验证页 | 一次都不抓，`stage: wall`、`blocked` |
| 抓取次数 | 任何路径下 `saveAsMHTML` 调用次数 ∈ {1, 2} |

真机（由你/Codex 执行，我不制造样本）：
- 一篇重页面（就是 ScienceDirect 那篇）在**人工过验证后**读一次，看 `page_state.quiet`、`waited_ms`、抓取次数；
- 一次自然验证墙（若遇到），确认 `stage: wall` 与 0 次抓取。

## 6. 影响面与风险

- worker 改动集中在 `waitComplete`、`goto`、`snapshot` 三处；`CAPABILITIES` 不变（不新增动词），
  但 `snapshot` 接受新参数 ⇒ 旧内核调用不受影响（参数缺省）；
- 内核改动：去掉 `_ARTICLE_SETTLE_MS` 作为触发条件、新增 `page_state` 处理、`stage/reason` 词汇扩展；
- **测试夹具会大面积更新**：现有回放按"goto → sleep → snapshot"的序列断言，插入 `page_state` 后要改；
  这是本方案最大的工作量与回归风险，我会优先跑完整套件而不是只跑新用例。

## 7. 不做的事

- 不新增动作动词（AGENTS.md §6 要 ADR）；
- 不靠"把预算调大"当修复；
- 不在就绪循环里反复整页抓取；
- 不扩权限（除非你选方案 B）。
