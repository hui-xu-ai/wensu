# Web of Science channel — 决策记录

状态：**已决策并实现**（2026-11-08）。取数方式见 `ADR 0007`，所需内核改动见 `ADR 0008`。
本文原先是「待确认」清单，现在每条都有了答案。

## 目标

`search` / `export` 两个既有工具通过 `channel: "webofscience"` 切换即可用，返回与 CNKI 同构的
`Record`。渠道包自包含，**不改内核分派逻辑**，CNKI 一个字节不动。

## 原「待确认」六条的答案

| 问题 | 答案 |
|---|---|
| 访问方式 | 用户自己的浏览器 + 校园网 IP，直连 `webofscience.clarivate.cn`（Clarivate 中国镜像）；不做登录/代理/验证码自动化 |
| 域名白名单 | `webofscience.clarivate.cn`、`www.webofscience.com`（后者只防跳转链）；`goto` 一律用前者，省一次 302 |
| 检索页形态 | **不走 API 重放**：拦截页面自己的 `/api/wosnx/core/runQueryGetRecordsStream` 流，读渲染 DOM 拿不到摘要 |
| 字段映射 | 见下表，`record.json` 17 个字段中 15 个有来源 |
| 配额折算 | 一次检索 = `goto` + `type` + `click` = **3 个网络动作**，沿用 ADR 0005（300/日、间隔 3000ms + 抖动、并发 1） |
| 许可边界 | 用户以个人研究用途访问其机构订阅下的公开题录；项目只读、不导出文件、不分发 |

## 字段映射（实测 50 条覆盖）

| `record.json` | WoS 路径 | 覆盖 |
|---|---|---|
| title / authors | `titles.item.en[0].title` / `names.author.en[].wos_standard` | 50/50 |
| source / doc_type | `titles.source.en[0].title` / `doctypes[0]` | 50/50 |
| year / volume / issue | `pub_info.pubyear` / `vol` / `issue` | 50/50 |
| pages | `pub_info.begin`–`end`，缺则 `page_count` | 50/50 |
| doi | `doi` | 42–50/50，随批次 |
| abstract | `abstract.basic.en.abstract`（剥 HTML） | 49–50/50 |
| keywords | `item.keywords_plus` | **23/50** |
| citations | `citation_related.counts.ALLDB` | **随视图变化**：相关性排序时 50/50；按时间排序时 `counts` 是空字典 ⇒ 全部为 `null` |
| institution | `…address_spec.organizations[]`（取 `pref:"Y"`） | 50/50 |
| url | `…/wos/woscc/full-record/WOS:<ut>` 构造 | 50/50 |
| downloads | WoS 无此概念 | — |

## 端点与批次（实测 2026-11-08）

| 端点 | 触发 | 每批 | 累计 |
|---|---|---|---|
| `runQuerySearch` | 点「检索」 | 20 条 | 20 |
| `runQueryGetRecordsStream` | 第一次 `scroll` 到底 | 20 条 | 40 |
| 同上 | 第二次 `scroll` 到底 | 10 条 | **50** |

`capture.js` 用前缀 `/api/wosnx/core/runQuery` 覆盖两者；解析器对两种报文同一份代码成立。
批次**串行**到达，所以节点只在 `runQuerySearch`（首屏查询）时清空，后续批次累加——
早先版本按「有没有未完成请求」判断，串行批次会被误当成新一轮而互相清空，只剩最后一批。

**一次检索的真实成本**（实测 2026-11-08，刷新方案）：

| 指标 | 值 |
|---|---|
| 内核配额 | **4 个网络动作**（`goto` / `type` / `click` / `goto reload`）|
| 耗时 | **约 23 秒** |
| 返回 | 50 条短清单（默认不含摘要）|
| 捕获批次 | `runQueryGetRecordsStream` × 3，**没有 `runQuerySearch`** |

**关键：刷新才是全量加载的正路。** 点检索按钮后是页内跳转，结果分批懒加载，要滚动两次才满 50 条
（19 个动作、86 秒）。而**刷新（F5）**走的是另一条路径：页面直接把整页结果按流推下来，三个批次
一次到齐，**完全不发 `runQuerySearch`**。所以计划在提交后做一次 `goto {reload: true}`，不再滚动。

**取摘要零请求**：`search` 会把每条**自带摘要**的记录播种进 `detail:<url>` 缓存，
所以 `detail(url)` 以**零网络动作**返回完整记录。这是本渠道与 CNKI 的关键差异——
CNKI 的摘要在详情页，`detail` 必须真去访问一次（列表行没有摘要，也就不会被播种）。

**两个坑**：

- DevTools 的 Size 列是 **gzip 后**大小（`runQuerySearch` 显示 38.6 KB，解压后 243 KB），
  不能用它估算字段覆盖度或记录条数。
- 一个懒加载批次是 **~100 KB 的单行长 JSON**，分多个 chunk 传输。用「多久没新数据」判断传输结束
  会在 chunk 之间误判，拿到半截行——必须**检查最后一行能否 JSON 解析**再宣告完成。

## 落点（已实现）

```
src/scholar_search/channels/webofscience/
├── manifest.json                 # domains / verbs / capabilities: search, export
└── v2026_11/
    ├── __init__.py               # get_channel()
    ├── selectors.py              # data-ta 优先；禁止锚定 cdk-overlay-N / mat-menu-panel-N
    ├── query.py                  # 检索式构造：字段白名单、日期默认五年、残留覆盖
    ├── plan_search.py            # 九动词内，默认路径 3 个网络动作
    └── parse_records.py          # NDJSON -> Record[]
extension/content/capture.js      # MAIN world，document_start，拦截 fetch + XHR
tests/fixtures/webofscience/records.ndjson   # 脱敏，3 条（含缺 keywords / 缺 doi 的形态）
tests/contract/test_channel_webofscience.py
tests/unit/test_wos_query.py
```

## 交互纪律（写进代码，不靠自觉）

- 一次检索**只发 3 个请求**；翻页每页 +1，显式排序 +2，默认都不加。
- 所有暂停都是随机区间（`jitter()`），没有固定节拍。
- 检索式框每次先清空（`type` 的 `clear: True`），多次检索不会互相污染。
- 日期写进检索式 `PY=(…)`，**不点任何筛选控件**，默认近五年。
- 需要组合历史检索时用完整检索式表达（`ALL=(a) AND ALL=(b)`），不走页面的「检索历史」面板。

## 未做（明确记录）

- `detail`：作者关键词（Author Keywords）只在 `full-record` 页，本版不取；`capabilities` 已声明不含它。
- `journal`：WoS 无对应入口。
- `#N` 检索历史引用：会让内核去读页面面板，交互不划算；调用方传完整表达式即可，效果等价。
- 配额与冷却仍为**全局单例**（理由见 ADR 0008「明确不做」）。

## 交互与风控审计（2026-11-08）

一次检索的动作与真实请求：

| 动作 | 计入配额 | 真实请求 | 与上一动作的间隔 |
|---|---|---|---|
| `goto` advanced-search | ✅ | 1（整页加载）| — |
| `type` 检索式 | ✅ | 0 | — |
| `click` 检索 | ✅ | 1（表单提交 → 结果页）| type 后 1.2–2.2 s |
| `scroll` ×2 | ✗ | 0（但各触发 1 个懒加载）| 1.6–2.4 s + 等载荷 |

**配额与真实请求不一致，这是本渠道最需要注意的一点**：一次检索记 **3** 个网络动作，
实际发出 **4–5** 个 HTTP 请求。`scroll` 是读动词，按 ADR 0005 不计量；它触发的懒加载是**页面
自己的行为**，与「我们构造请求」性质不同，但流量确实发生了。
后果：每日 300 配额对应的实际上限是**约 60–100 次检索**，不是 300 次。要保守就按 60 次算。

**拟人化核对**（2026-11-08 调整后）：

| 动作 | 模拟内容 |
|---|---|
| 点击 | 滚入视口 → **随机落点**（元素内留 20% 边距，非正中心）→ hover 六连发（pointerover/enter、mouseover/enter、pointermove、mousemove）→ pointerdown+mousedown → 停 50–120 ms → pointerup+mouseup → 停 40–100 ms → click，**每个事件带真实坐标** |
| 输入 | 聚焦 → 停 60–150 ms → **逐字符** keydown/input/keyup，每字停 20–70 ms → change |
| 滚动 | `scrollBy` 平滑滚动，距离与停顿随机 |
| 刷新 | 真 `reload`（`navigation.type === "reload"`，与 F5 相同）+ `bypassCache`（否则纯 reload 走缓存、零请求）|
| 节拍 | 任意两个网络动作之间由内核强制 ≥ 3 s + 0–1.2 s 抖动 + 10% 概率再加 2–4 s |

**做不到的一件事**：合成事件永远是 `isTrusted: false`，这是浏览器安全边界。要伪造只能上
`chrome.debugger`（CDP 原始输入），但它会在页面顶部常驻「正在调试此浏览器」横幅——比合成事件
本身显眼得多，所以没做。**刷新的按下/松起同理**：`chrome.tabs.reload` 是内核 API，不经过 DOM，
产生不了 F5 的按键事件；页面能读到的只是导航类型 `reload`。

**不存在**这些典型自动化特征：固定节拍、瞬移点击、同一坐标连点、一次性填表、无间隔翻页、
请求重放、构造新请求、后台隐藏请求。`capture.js` 只**镜像**页面自己发出的请求，从不构造新请求——
这是本设计最重要的安全属性，也是它相对「导出 bib / 重放 fetch」两条路的根本优势。

**风控信号覆盖**（`core/risk.py`）：

| 信号 | 判据 |
|---|---|
| 403 / 429 | `outcome.data.status` 或错误文案 |
| 登录跳转 | URL 含 `/login`、`sso`、`shibboleth`、`carsi`、`session-expired` |
| 验证码 | URL 含 `captcha`/`recaptcha`/`hcaptcha`；页面 `captcha_visible` |
| 门页标题 | `session expired`、`sign in`、`access denied`（大小写不敏感）|

任一命中即 `blocked` + 24 小时冷却，需人工 `wensu reset --confirm` 才能恢复。

**已知缺口**：WoS 的软封锁（HTTP 200 但正文是 "Access Denied"）只靠 `<title>` 匹配，
如果站点把提示放在正文而非标题，会漏判。遇到时人工确认，不要重试。

**结论**：交互面与人工检索同构，没有可识别的自动化特征；主要风险来自**频率**而非行为形态，
而频率由内核的每日配额与最小间隔兜着。配额的失真（scroll 不计量）已如实记录在上面。

## 验收三档

1. **契约/单测**：`pytest -q` 215 通过；最坏计划 23 动作 / 108.9 s / 7 网络动作，在内核上限内。
2. **真实链路**：重载扩展 → `wensu status` 的 `bridge_ready: true` → 一次 `search`（`limit=5`）
   → 审计里 3 个网络动作、结果数为 5、无风控信号。
3. **风控路径**：伪造 `session-expired` 跳转 → `blocked` + 24 h 冷却 → 二次调用被拒。
