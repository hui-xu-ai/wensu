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

## 端点与批次（实测）

| 端点 | 触发 | 每批记录 | 含摘要 | 解压后体积 |
|---|---|---|---|---|
| `/api/wosnx/core/runQuerySearch` | 点「检索」 | **20 条** | 是 | 243 KB |
| `/api/wosnx/core/runQueryGetRecordsStream` | 排序 / 翻页 | 20+20+10 = 50 条 | 是 | 534 KB |

`capture.js` 用前缀 `/api/wosnx/core/runQuery` 同时覆盖两者，解析器对两种报文同一份代码成立。

两个必须记住的数字：

- **单次检索只拿 20 条**。`limit > 20` 时返回条数会少于请求值；要更多必须用 `page` 翻页，每页 +1 网络动作。
- **不要用 DevTools 的 Size 列估字段覆盖度**。那一列是 gzip 传输大小：`runQuerySearch` 显示 38.6 KB，
  解压后 243 KB。按 772 B/条推算"装不下摘要"是错的，实际摘要有 1000+ 字符。

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

## 验收三档

1. **契约/单测**：`pytest -q` 215 通过；最坏计划 23 动作 / 108.9 s / 7 网络动作，在内核上限内。
2. **真实链路**：重载扩展 → `wensu status` 的 `bridge_ready: true` → 一次 `search`（`limit=5`）
   → 审计里 3 个网络动作、结果数为 5、无风控信号。
3. **风控路径**：伪造 `session-expired` 跳转 → `blocked` + 24 h 冷却 → 二次调用被拒。
