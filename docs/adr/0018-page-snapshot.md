# 0018 · 在线文献网页快照：扩展 pageCapture + MHTML 落盘 + 本地转 Markdown

**状态**：已接受（2026-11-18）
**相关**：ADR 0003（动作动词封闭）、ADR 0004（遇阻即停）、ADR 0005（配额）、计划 `work/tasks/paper-page/plan.md`

## 背景

wensu 只能读知网/WoS 两个渠道（域名白名单由 channel manifest 声明）。用户要 agent 读**publisher 页面**（Elsevier、arXiv、PMC…）的整页正文时无路可走：`read_html` 限于两个渠道域名，`web_fetch` 只能拿无 JS 渲染的文本、且丢图片与公式上下文。

用户已实践过两条路：

1. 浏览器 **Ctrl+S** 存整页 —— 内容最全（浏览器把 CSS/图片内联进 MHTML），但每篇要人工点一次；
2. 现成扩展 `参考代码/scholarly-snapshot` —— 一键存，但**内容明显更少**。读代码确认根因：它只做 `document.documentElement.outerHTML` → `data:text/html` 下载（`background.js:36`、`content.js:45-52`），因此图片仍是远程 URL、CSS 全丢、iframe/shadow DOM 拿不到。

## 决定

1. **页面来源**：扩展对**用户当前已打开的那个标签页**调用 `chrome.pageCapture.saveAsMHTML({tabId})`，得到 MHTML Blob（[该 API 把页面与全部资源封进单文件](https://developer.chrome.google.cn/docs/extensions/mv2/reference/pageCapture)），落盘到 `SCHOLAR_SEARCH_HOME/pages/<slug>/page.mhtml`。

   **传输不走桥**：桥是「一行一个 JSON」的 TCP/native-messaging 协议，且 `read_html` 本身就有 1 MB 截断 —— 把 1–5 MB 的 MHTML base64 塞进一行会破坏这条设计（`docs/bridge-protocol.md` §Size limits 明确写了"不接受无界行"）。所以：扩展用**已有的** `downloads` 权限把 Blob 直接下载到 `wensu-pages/<slug>.mhtml`，桥上的 `snapshot` 只回报**小消息** `{ok, path, bytes, sha256}`；转换脚本按路径读取，必要时把文件移进 `pages/`。
2. **不新增任何"打开任意网址"的能力**：`snapshot` 只作用于已存在的标签页，因此域名白名单、风控模型（ADR 0004）、"动作词汇封闭"（ADR 0003）的语义都不变——只是新增一个动词。
3. **快照不计配额**：`pageCapture` 不向站点发请求，故 `snapshot` 不进 `NETWORK_VERBS`（ADR 0005 的口径不变）。
4. **转换在本地**：`tools/page2md.py` 把 MHTML/HTML 转成 `page.md`（trafilatura 抽正文；失败回退 markitdown），并移植自家的公式还原与化学式/单位后处理。
5. **对外暴露**：M2 增加第 6 个 MCP 工具 `snapshot`（`schemas/tools.json` 由生成器重建，已有闸门），配套新技能 `paper-page`。

## 被否的替代方案

- **只做"人工 Ctrl+S + 转换"**：成本最低，但仍要每篇人工点击，与"让 AI 自动阅读"的目标不符。**保留为 M1 与回退路径**（用户手存的 `.html/.mhtml` 同样走 `page2md.py`）。
- **继续用 `scholarly-snapshot` 的 DOM→outerHTML**：正是"内容更少"的根因，资源不内联。否决。
- **自建 headless 浏览器抓取（Playwright / SingleFile CLI / monolith）**：能力最强，但等于自建爬虫——撞 ToS 与站点风控（ADR 0004 的反面），且拿不到登录态内容（付费墙页面白抓）。否决为默认路径；公开 OA 页面仍由 `web_fetch` 兜底。
- **给扩展加 `<all_urls>` 的 `host_permissions` 并直接 `goto` 任意站点**：改动最小但把"只读两个渠道"的边界整个破掉，风控与合规无法评估。否决。

## 后果

- 新增动词 `snapshot` + 权限 `pageCapture` → 扩展、native host、内核三处同步（ADR 0003 要求），并新增 MCP 工具（工具面从 5 个变 6 个，`tools.json` 与契约测试同步更新）。
- 运行期产物变大（单页 MHTML 常见 1–5 MB）→ 落盘目录需上限与清理策略（默认保留 30 天），且不进 git。
- MHTML 不含请求头/Cookie，但正文可能含账号信息 → 只写本机运行期目录，`meta.json` 记录来源 URL 与抓取时间以便追溯。
