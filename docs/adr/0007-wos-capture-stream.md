# ADR 0007 · WoS 渠道拦截页面流响应取数，不导出、不重放

- 状态：accepted
- 日期：2026-11-08（rev.2，取代 rev.1 的「读渲染 DOM」）
- 关联：ADR 0002（只读）、ADR 0004（遇风控即停）、ADR 0005（配额）、`docs/wos-channel.md`

## 背景

要把 Web of Science 接成第二个渠道（`search` / `detail` / `export` 三个既有工具不变）。
用户最初提出两条取数路径：模拟点击导出 BibTeX，或读取浏览器里已加载的数据。

实测取证（用户手动保存了一份真实流式响应，522–534 KB，按时间排序后的 50 条）：

- 响应是 **NDJSON 流**，10 行：`searchInfo` ×1、`records` ×3–4 批（20+20+10）、`highlight` / `analyze` /
  `jcr` / `link` ×4；**50 条完整记录，每条含摘要**（`abstract.basic.en.abstract`，HTML 包裹）。
- 端点：`/api/wosnx/core/runQueryGetRecordsStream`（SID 在 query string 上，**不落盘**）。
- 关键字段：`titles.item.en[0].title`、`titles.source.en[0].title`、`names.author.en[].wos_standard`、
  `pub_info.{pubyear,vol,issue,begin,end,page_count}`、`doi`（42/50）、`citation_related.counts.ALLDB`、
  `address_data.address[].address_spec.organizations[].organization`、`ut`/`colluid`、
  **`item.keywords_plus`（23/50）**。
- 列表页渲染出的 DOM **不含摘要**，摘要与关键词只在流响应或 `full-record` 详情页里。

现有约束（已取证）：动词集合封闭为九个（`read_html` 无参、`read_text` 只吃 `selector`）；
扩展 `permissions` 只有 `nativeMessaging`、`tabs`；`record.json` 是公开契约且 `additionalProperties: false`。

风控判断的关键是**服务器端是否看见新的请求**，与读了多少数据无关。

## 备选

### 备选 A：点击导出 BibTeX

- 优点：schema 稳定，一次 50 条。
- 被否理由：① 唯一会新增**可见请求**并命中批量导出特征的路径（ToS 禁止 systematic downloading）；
  ② 需新增第 10 个动词 `download` 与 `downloads` 权限；③ 缺摘要与关键词，仍要回详情页。

### 备选 B：读渲染后 DOM（rev.1 的决策，现被否）

- 优点：零新增请求、零内核改动（`read_html` 已存在）。
- 被否理由：**列表 DOM 没有摘要**。要摘要就得逐条 `goto` `full-record` ⇒ 一次检索 **50 次请求**，
  这是最典型的爬虫剖面，风险比读一次响应高一个数量级。零改动的优势被 50 次请求完全抵消。
  **保留为拦截失败时的降级路径**（字段少但可用）。

### 备选 C：`chrome.debugger` + CDP `Network.getResponseBody`

- 优点：字段全、与页面实现解耦。
- 被否理由：需新增 `debugger` 权限（浏览器顶部常驻调试横幅）与第 10 个动词；
  为拿一份响应付出全局调试权限，成本与收益不对等。保留为备选 B 也失败时的最后手段。

### 备选 D：页面内包装传输层拦截流响应（选中）

- 优点：**零额外请求**（响应本就是页面自己发的，只是顺手复制一份）、
  **零新权限、零新动词**（结果写进隐藏 DOM 节点，用现有 `read_text {selector}` 读回）、
  **一次拿全 50 条含摘要与 Keywords Plus**。
- 被否理由：属轻微侵入——需 `world: "MAIN"` + `run_at: "document_start"` 改写页面传输层引用；
  依赖端点路径稳定（传输方式已由「同时包装 fetch 与 XHR」消除）。

## 决策

采用备选 D，并附四条硬规则：

1. **只拦截，不重放**：**同时包装 `window.fetch` 与 `XMLHttpRequest`**（不赌 WoS 前端用哪一种），
   只做「克隆响应、旁路读流、异步写隐藏节点」，绝不改写 URL / 请求头 / SID，
   也绝不因为拦截失败而去重发请求。
2. **白名单式匹配**：仅当 URL 含 `/api/wosnx/core/runQueryGetRecordsStream` 时捕获，
   其他请求原样透传（`return originalFetch(...)`，XHR 透明放行）。
3. **SID 与 URL 永不落盘**：审计与日志只记「捕获成功 / 字节数 / 记录数」；
   代码里的匹配用路径前缀，不拼接完整 URL。
4. **域名白名单只放直连**：`webofscience.clarivate.cn` 与 `www.webofscience.com`（后者仅防跳转链），
   `goto` 目标统一用 `webofscience.clarivate.cn`（省一次 302）。
   访问态由用户浏览器与校园网 IP 提供，不做登录 / 代理 / 验证码自动化（ADR 0004）。

配额沿用 ADR 0005：一次 `search` = `goto` + `type` + `click` 共 3 个网络动作；
`wait_for` / `read_text` / `sleep` 不占。

## 后果

- 新增 `channels/webofscience/{manifest.json,v2026_11/}`；`extension/` 加一个 MAIN-world 注入脚本
  + `host_permissions` / `content_scripts.matches` 增加 WoS 域名；**内核与动词集零改动**。
- 管道：注入脚本捕获 → 写 `#<capture-id>` 隐藏节点 → `read_text` 取回 NDJSON 文本 →
  `parse_records.py` 解析成 `Record[]` → 仍按 `limit` 截断后返回，避免把 500 KB 塞进 MCP 响应。
  注意 bridge 单帧上限 `MAX_FRAME_BYTES = 2 MB`。
- **风险**：① 页面若改用 WebSocket / EventSource 或改端点路径 ⇒ 拦截静默失效，
  必须降级到备选 B 并在审计里记 `capture.miss`；② 改写页面传输层有极低概率被前端检测；
  ③ `item.keywords_plus` 只覆盖 23/50（无作者关键词），`keywords` 按实有值填充，缺则空数组，不动契约。
- 验收三档（见 `docs/wos-channel.md` §验收）不变：契约 / fixture 回放 → 真实链路 → 风控路径回放。
- 若日后拿到 Clarivate 官方 API key，新增 ADR 并把本决策标 `superseded`。
