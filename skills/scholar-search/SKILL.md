---
name: scholar-search
description: 通过 wensu MCP 检索文献题录。双渠道：cnki（中文文献，中文检索式）与 webofscience（英文文献，WoS 检索式，自带期刊影响因子）。只返回题录，不下载全文。
---

# 文献检索

## 场景 → 工具速查

五个工具，按「要做什么」选，不要按名字猜：

| 你要做的事 | 用 | 关键参数 | 花费 |
|---|---|---|---|
| **找文献**（主题/篇名/作者/刊名） | `search` | `query`, `channel`, `limit` | 3（知网）/ 4（WoS）|
| **只要命中数**，先试检索式对不对 | `search` | `limit: 1`, `fields: ["title"]` | 同上，但响应极小 |
| **看某一篇的完整信息**（含摘要） | `detail` | `url`，或直接给 `doi` | 缓存 0 / 现场 1 |
| **一次看多篇完整信息** | `detail_many` | `urls: [...]` | 每篇同 `detail` |
| **存成文件**交给 Zotero/EndNote | `export` | `records`, `out_path` | **0** |
| **查额度、查桥接通不通** | `status` | — | **0** |

**三条容易被忽略的省法**：

1. **`fields` 投影** —— 只要标题年份就写 `fields: ["title","year"]`，别把整页拉进上下文；
2. **`local_sort` 免费** —— 重排手上这一页不要钱，`site_sort` 才扣额度；
3. **`export(out_path)`** —— 143 条落盘是 0 额度 0 token，逐条读进上下文是最贵的做法。

## 何时使用

- 用户要按主题、篇名、作者、刊名找文献；
- 需要一页题录（标题、作者、刊名、年份、被引、影响因子、链接）；
- 需要把检索结果交给后续的详情或导出技能。

## 先选渠道

| 查询语言 | `channel` | 检索式风格 |
|---|---|---|
| 中文 | `cnki`（默认） | 关键词，或 `SU=`/`TI=` 等字段式 |
| 英文 | `webofscience` | 关键词，或 `TS=`/`PY=` 等 WoS 表达式 |

**不要跨语言自动翻译**。中文 query 送进 WoS 通常命中 0 条，英文 query 送进 CNKI 同理——
命中 0 条时先怀疑渠道选错了。

## 硬约束

1. **只读**：不请求、不调用任何 PDF/CAJ 下载。
2. **遇阻即停**：返回 `status: blocked` 时立即停止，把 `signal` 和 `cooldown_until` 原样告诉用户，禁止重试、禁止换关键词绕开。
3. **要更多结果，先看渠道**：
   - **WoS → 用 `exclude_ut`**。把这一轮每条记录的 `url` 最后一段（`WOS:...`）都传回去，
     同一个检索式就会返回没见过的那些。每轮是独立请求，结果集可预期地缩小
     （实测 115 → 65，两轮间零重复）。一次最多 500 个。
   - **CNKI → 用 `page`**（1–3），它没有排除字段。
   - `page` 只在"差几条、检索式已经很窄"时用。**它不是走完大结果集的手段**：每翻一页都要
     重新提交检索、保持一个结果列表打开，还容易被站点看成脚本行为。
   - 排除是**按已读记录**排除的，不是按名次。所以两次调用之间站点重排也不会重复，
     只会改变剩下哪些。返回里的 `total` 每次应减少等于排除数的量，可用来核对。
4. **串行调用**：不要并行发多个检索。虽然内核有跨进程锁会串行化，但排队期间每个调用都占着超时预算，实测两个并行各自要等约 20 秒，比顺序发更慢也更容易撞上超时。
5. **不猜结果**：只转述工具返回的字段，不补全、不虚构作者或年份。
6. **不碰用户的浏览器**：桥接没就绪时，唯一允许的动作是请用户点一下扩展图标。禁止启动、关闭、
   重启、结束任何浏览器进程；禁止改 profile、注册表、扩展目录；禁止删 `%LOCALAPPDATA%\scholar-search\`
   下的文件来「重置状态」。理由见下一节——这条是 2026-11-09 一次真实事故换来的。

## 红线：桥接没就绪时不要动浏览器

扩展通常只装在某一个浏览器 profile 里。**按进程名批量重启会拉起默认 profile**，那里没有扩展，
桥接不但没恢复，还会把用户正在用的浏览器一起关掉。

真实事故：调用方看到 `bridge_ready: false`，读 `host.log` 里的 `msedge` 记录，推断「浏览器卡在
后台」，执行 `Stop-Process -Name msedge -Force` 再重启。结果关掉了用户正在用的浏览器，重启的又是
没有扩展的那个 profile，桥接只活了 5 秒。

**正确做法**：先把 `status.browser_profile` 读出来，那里记录了 wensu 自己管的那个 profile。

```
status → browser_profile = null
       → 还没初始化，让用户跑一次 `wensu setup --browser edge`
status → browser_profile.start_with = "wensu browser start"
       → 让用户跑这条命令（或用你自己的终端跑），它会用 --user-data-dir 启动那个特定 profile
status → bridge.ready = false，但 browser_profile 有值
       → 让用户跑 `wensu browser start`，然后点一下扩展图标
```

**这是唯一允许的启动方式**：`wensu browser start` 只对**它自己记录的那个 `--user-data-dir`** 生效。
**不要**用 `Start-Process msedge`、**不要**按进程名批量操作、**不要**改 profile 或注册表。

## 最重要的陷阱：年份过滤是两层，不是一层

`year_from` / `year_to` 的行为**按渠道不同**，而且同一渠道上两层都有：

| 渠道 | 这两个参数做了什么 |
|---|---|
| **WoS** | **写进站点检索式**（`… AND PY=(2026)`，`query_effective` 能看到），**并且**再对抓到的那一页做一次本地过滤 |
| **CNKI** | 只做本地过滤，不改变检索式 |

所以 WoS 上 `total` 已经是年份限定的数量，而 `dropped_year` 通常很小；CNKI 上
`total` 是全量，`dropped_year` 可能吞掉整页。

后果：`records: []` 加 `total: 65` 意味着「**这一页没有符合年份的**」，**不是**「这个主题没有该年份的文献」。

**判断方法**——看 `dropped_year` 和 `dropped_filter`：

| 返回 | 含义 | 该怎么办 |
|---|---|---|
| `records: []`，`total: 0`，`empty_reason: no_match` | 真的没有匹配 | 可以下「无文献」结论 |
| `records: []`，`dropped_year: 30`，`empty_reason: all_dropped_by_year` | 这一页 30 条全被年份筛掉了 | **换检索式或翻页**，不要说无文献 |
| `records: []`，`dropped_filter: 30`，`empty_reason: all_dropped_by_filter` | 全被影响因子/被引阈值筛掉 | 放宽阈值，不要说无文献 |
| `records: [9 条]`，`total: 401` | 只有 9 条落在今年 | 引用时说明「共 401 条，本页 9 条符合年份」|

**空结果不等于没有文献。** 交付前至少用同义词再交叉验证一次，别凭单次空结果下结论。

## 查询语义：两个通道差别很大

### 知网：不支持整句短语，空格即 AND

这是实测出来的行为，不是文档写的：

| 输入 | 结果 |
|---|---|
| `离子柔性驱动器`（整串） | **0 条** |
| `离子驱动器` | 4 条 |
| `离子 柔性 驱动器`（空格分词） | **128 条** |

**整串会被当成一个不可分割的词**。中文短语查不到时，第一反应应该是**拆成空格分隔的关键词**，
而不是换同义词或翻页。想精确匹配短语，用检索式加引号：`SU='"离子柔性驱动器"'`。

### 各通道各给一个已验证的示例

```
知网  SU='柔性驱动器'                            → 主题检索
知网  TI='生态' and KY='生态文明'                 → 布尔组合
知网  离子 柔性 驱动器                            → 空格分词（无字段时自动包成 SU=）

WoS   TS=(ionogel AND actuator)                   → 主题（题名+摘要+关键词）
WoS   TS=(ionic) AND PY=(2026)                   → 加年份
WoS   TS=(ionic) AND PY=(2025-2026)              → 年份区间
```

**`PY=(2026-2026)` 会被自动改成 `PY=(2026)`**——站点不接受两端相同的区间。

**只给一端年份时的规则**（自动生成的表达式可见 `query_effective`）：

| 你给的 | WoS 生成的 | 说明 |
|---|---|---|
| `year_from=2024`，无 `year_to` | `PY=(2024-2026)` | 到今年为止 |
| `year_from=2027`，无 `year_to` | `PY=(2027)` | 未来年份收敛成单年，不会倒序 |
| 无 `year_from`，`year_to=2020` | `PY=(2016-2020)` | 默认五年窗口 |

### 想要的年份不在这一页时

WoS 上这两个参数会进检索式，所以首页就已经是年份限定的；CNKI 上只做本地过滤，
首页可能整页被筛掉。不管哪种，首页没有目标年份时：

1. **首选**：`site_sort=date`（站点按时间倒序重排）——**多花 2 个额度**（3 → 5），但一页就能拿到最新的；
2. 或者：把年份写进检索式。**WoS 已验证**：`PY=(2026)`、`PY=(2025-2026)` 都有效。
   **知网未验证**：`年='2026'` 实测 0 命中（2026-11-09），不要照抄；知网请用 `site_sort=date`
   或 `year_from`。
3. **不要**：连续翻页扫库，那是最贵的做法。

## 动作价目（每次调用前先算一笔）

| 动作 | 知网 | WoS | 说明 |
|---|---|---|---|
| 一次检索（默认相关度） | 3 | 4 | 基本成本 |
| 加 `site_sort`（站点重排） | +2 | +2 | 排序要走两次点击 |
| `local_sort`（本地重排） | **0** | **0** | 纯本地，免费 |
| 翻一页 | 3–4 | 4 | 每页都是完整一轮 |
| `detail` 命中缓存 | **0** | **0** | 只有 WoS 的检索行会预热详情缓存 |
| `detail` 未命中 | **1** | **1** | **知网 detail 基本恒为 1**——检索不预热，见下 |
| `detail` 未命中（知网） | 1 | — | 真去访问详情页 |
| 空结果（`no_match`） | 3 | 4 | 探测也要真实检索 |

**预算建议**：一轮「检索 + 看详情」按 4 个额度估，`sort=date` 按 6 个估。

`status` 会返回精确的 `quota_remaining`，每个 `search` / `detail` 响应也会带，不用单独查。

### 零结果长什么样

命中 0 条时站点**不会跳转**，页面停在检索式填写页。工具会探测这一点并返回：

```json
{"records": [], "total": 0, "empty_reason": "no_match"}
```

`empty_reason: "no_match"` 是**渠道确认过页面之后**给出的结论，可以直接采信；它和
`records: []` 但 `empty_reason: null` 是两回事——后者通常意味着抓取失败或过滤掉了。

代价是空结果需要约 20 秒（要等超时再探测）。**这是正常的，不要因此重试**。

## 调用

```json
{"query": "IPMC", "channel": "cnki", "limit": 20, "page": 1}
{"query": "TS=(ionic AND (soft OR flexible) AND actuator)", "channel": "webofscience", "limit": 20, "year_from": 2026}
```

### CNKI 专业检索式

`query` 里出现 `字段=` 或 `字段%` 时自动切到专业检索页。可检索字段：

| 字段 | 含义 | 字段 | 含义 |
|---|---|---|---|
| `SU` | 主题 | `TI` | 篇名 |
| `TKA` | 篇关摘 | `KY` | 关键词 |
| `FT` | 全文 | `AB` | 摘要 |
| `AU` | 作者 | `FI` | 第一作者 |
| `RP` | 通讯作者 | `AF` | 作者单位 |
| `FU` | 基金 | `CO` | 小标题 |
| `RF` | 参考文献 | `CLC` | 分类号 |
| `LY` | 文献来源 | `DOI` | DOI |
| `CF` | 被引频次 | | |

运算符：`and`/`*`、`or`/`+`、`not`/`-`；`%` 表示作者模糊匹配；支持括号分组。

```
TI='生态' and KY='生态文明' and (AU % '陈' + '王')
```

### Web of Science 检索式

| 记号 | 含义 | 例 |
|---|---|---|
| `TS=` | 主题（标题+摘要+关键词） | `TS=(ionogel AND actuator)` |
| `TI=` | 篇名 | `TI=(soft robot*)` |
| `AU=` | 作者 | `AU=(Kim, J*)` |
| `PY=` | 出版年 | `PY=(2021-2026)` |
| `SO=` | 期刊名 | `SO=(Advanced Materials)` |
| `ALL=` | 全字段 | `ALL=(ionic polymer)` |

布尔：`AND` / `OR` / `NOT`，括号分组，`*` 通配。

**年份有两个入口，效果按渠道不同**：

- 写进检索式 `PY=(2026)` —— **站点侧过滤**，`total` 是站点在该年命中的数量；
- 用参数 `year_from=2026` —— **WoS 上同样写进检索式**（`query_effective` 能看到），
  **CNKI 上只过滤当前页**，`total` 仍是全量，要配合 `dropped_year` 读。

**`total` 不等于「该年有那么多篇」**：一条记录匹配 `PY=(2026)` 却可能带 `year=2027`
（在线首发，或次年卷期的会议录）。按 `year` 分组显示是对的，看到一两条落在区间外
不是错误；`dropped_year` 就是按 `year` 再筛掉的条数。

覆盖率（要拿全一年的文献）只能靠 `exclude_ut` 多轮取，`total` 本身不给这个保证。

### 影响因子（仅 WoS）

WoS 记录自带 `impact_factor`（JCR 影响因子，可能为 `null`——该刊无指标）和
`impact_factor_year`（该指标出自哪一年的 JCR 版本，**可能为 `null`**）。

**比较影响因子前先看 `impact_factor_year`**：2024 版和 2025 版的数值不是同一件事。
两者不同时不要直接比大小；`impact_factor_year` 为 `null` 时说明来源没给年份，也不要声称
"这是 2026 年的影响因子"。

- `min_impact_factor: 5` —— **本地筛选**，**无指标即丢弃**（会降低召回，这是设计而非 bug）；
- `local_sort: "citations"` 或 `"year"` —— 本地排序，不发额外请求。

**`site_sort` 与 `local_sort` 是两套**：前者让站点重排（多 2 个请求、走配额），后者在本地重排（免费）。旧名 `sort` / `sort_by` 仍能用，但不再推荐——四个名字并存只会让人犹豫。
想按被引排序又要省配额，用 `local_sort: "citations"`；想要站点的全局排序用 `site_sort`。

## 返回

```json
{
  "total": 63025,
  "page": null,
  "page_count": null,
  "dropped_year": 0,
  "records": [
    {
      "title": "…",
      "authors": ["…"],
      "source": "SMART MATERIALS AND STRUCTURES",
      "year": 2022,
      "citations": 9,
      "downloads": null,
      "impact_factor": 4.2,
      "abstract": null,
      "url": "https://webofscience.clarivate.cn/wos/woscc/full-record/WOS:…"
    }
  ]
}
```

- `page` 为 `null` 表示该渠道这一页没有可靠的页码（WoS 记录流里不带页码），**不要当成第 0 页**。
- 默认不含摘要。需要时把 `url` 交给 `detail`，它**自动从域名判断渠道**。

### 跨渠道比较用 `doc_type_unified`
`doc_type` 是各站点自己的词表：CNKI 说 `journal`，WoS 说 `article`、`proceedings`。直接比较等于比较
措辞而不是概念。**要跨渠道筛选用 `doc_type_unified`**：

| 值 | 含义 |
|---|---|
| `article` | 期刊论文（CNKI 的 `journal` 归到这里）|
| `review` | 综述 |
| `conference` | 会议论文（WoS 的 `proceedings` 归到这里）|
| `thesis` | 学位论文 |
| `book` / `newspaper` / `patent` | 图书 / 报纸 / 专利 |
| `other` | 渠道给了类型但不在词表里 |

**但只能「输出」，不能「输入」**：没有文献类型筛选参数。

- `source_types=["review"]` 在 WoS 上会报 `CHANNEL_ERROR`（那是刊名方向，不是类型）；
- `DT=(Review)` 会被本地拒绝为未知字段码（`DT` 不在 WoS 的可用字段表里）。

**要「只要综述」，就在拿到的 `records` 上按 `doc_type_unified == "review"` 自己筛**，
并说明这只覆盖已取回的那些，不是站点全集。想缩小召回，用检索式收窄主题。

### `filters`：这次到底筛掉了什么

请求里带了任何本地过滤器时，响应会多一个 `filters`：

```json
{
  "filters": {
    "year_from": 2026, "year_to": null, "year_scope": "page",
    "min_impact_factor": 5.0, "impact_factor_drops_unrated": true,
    "local_sort": "citations",
    "dropped": { "year": 49 }
  }
}
```

- **没出现的键 = 该过滤器没生效**，而不是「生效了但没有丢弃任何记录」；
- `dropped.year` 是被年份筛掉的条数，和 `dropped_year` 同义；
- `dropped.filter` 是被阈值/刊名筛掉的条数，和 `dropped_filter` 同义；
- `impact_factor_drops_unrated: true` 提醒：没有 JCR 指标的期刊会被**丢弃**，
  召回因此降低。`min_citations` 同理：**被引数未知的记录会被丢弃**，
  不再当作「未知所以保留」——「至少被引 1000 次」的调用方不应收到一条查不到被引数的论文。

`total` 永远是**站点侧**命中数，`records` 是过滤后的结果。两者不一致是正常的。

**这些过滤器都不要钱**：它们作用在已经抓到的那一页上。改 `sort_by` / `limit` /
`min_citations` / `min_impact_factor` / `include_abstract` 不会重新访问站点，
会直接命中缓存（`cache_hit: true`，`quota_charged: 0`）。

**会重新检索的**是真正改变抓取动作的东西：`text`、`channel`、`sort`（站点排序）、
`page`、`exclude_ut`，以及**渠道相关的年份参数**——WoS 把年份写进检索式，所以改年份
是一次新检索；CNKI 只做本地过滤，改年份命中缓存。

**同一条检索式重复调用是免费的**（`cache_hit: true`）。如果你发现相同请求又扣了额度，
那是缺陷，不是设计。

## 详情与导出

```
detail(url, include_abstract=false, fields=[...])   → 完整记录，摘要默认不返回
detail_many(urls, include_abstract=false)           → 批量，逐条失败隔离
export(records, format="ris"|"endnote"|"markdown"|"csv", out_path=…) → 可落盘
```

**导出前看清楚手里是什么记录**：

- `ris` / `endnote` 是**引文格式**，只带题录字段，**不带影响因子**；
- `markdown` / `csv` 是**展示导出**，带影响因子**和它的 JCR 年份**（`impact_factor_year`
  列 / `（JCR 2025）` 后缀），但不是完整元数据备份——例如 CSV 不含单位；
- **用 `fields` 投影过的结果不要直接导出**：缺作者/期刊会得到 `TY  - GEN`，
  而且看起来像「来源没提供」。要完整题录，先用记录的 `url` 调 `detail` 取回完整缓存再导出。
- `out_path` 指向已存在文件时会被覆盖，响应里 `overwritten: true` 会告诉你。

**关于缓存，实测结论（2026-11-09）**：

| 渠道 | 检索后 `detail` 是否免费 |
|---|---|
| **WoS** | **是**。检索行自带摘要和 DOI，详情缓存已被预热，`quota_charged: 0` |
| **知网** | **否**。检索行没有摘要，缓存不会被预热，**第一次 detail 扣 1，同一 URL 再取扣 0** |

所以「search 之后 detail 免费」这句话**只对 WoS 成立**。知网按 1/篇预算，但重复取同一篇不再扣。

**摘要很贵**：知网约 1200 字，WoS 约 1000 字，占单篇详情响应的 60–80%。
只要卷期页/DOI 就**不要**传 `include_abstract`；`detail_many` 一次取十二篇带摘要约 14 KB。

```
detail("10.13841/j.cnki.jxsj.2026.11.001")                          → 无摘要
detail("10.13841/j.cnki.jxsj.2026.11.001", include_abstract=true)   → 带摘要
detail(url, fields=["title","doi","pages"])                         → 只要三个字段
```

`detail` 只需要 URL，**不用传 channel**。

## 异常

| 返回 | 含义 | 处理 |
|---|---|---|
| `status: blocked` | 风控或验证页 | 停止，原样报告 `signal` 与 `cooldown_until` |
| `PolicyError`（`page` > 3 / `limit` > 50）| 参数越界 | 改参数 |
| `PolicyError`（host not allowed）| URL 不属于任何渠道 | 检查 URL 是否被拼接过 |
| `ActionError`（`wait_for` 超时）| 页面没在预期时间内给出数据 | **不要重试**：返回体里 `retryable` 为 `false`。重试会重新提交检索、再次消耗额度，且同一页大概率仍超时。报告给用户 |
| `BridgeTimeout` | 传输层超时 | 这是**唯一** `retryable: true` 的情况，可以重试一次 |
| `ParseError` | 页面结构变化 | 报告并停止，不要重试同一请求 |

**超时会消耗额度**（请求已经真实发出去了），错误响应里会带 `quota_charged`，
不用自己去比对 `status`。

`message` 里带 `stage`，用它可以判断停在哪一步：

| `stage` | 含义 |
|---|---|
| `wait.query-input` | 检索输入框没出现（页面没开或没加载完） |
| `wait.result-list` | 点了检索，结果列表没出现 |
| `wait.capture` | 结果列表有了，但数据流没截到 |
| `input.fill` / `click.submit` | 填检索式 / 点提交时没回应 |
| `navigate.*` | 打开或刷新页面时没回应 |

`stage` 只说明**哪一层没回应**，不说明原因。`bridge_ready` 为 true 而 `stage` 是
`input.fill` 时，连接是好的，多半是那个标签页没响应：把窗口切到前台、或点一下
wensu 图标再试。**不要重启一个已经在工作的浏览器。**

`wait.capture` 失败时还会带 `diagnostics`，说明页面当时到底有什么：

```json
"diagnostics": {"verdict": "metadata_only", "bytes": 58, "lines": 1,
                "declared_records": 115, "has_search_info": true,
                "has_records_block": false}
```

| `verdict` | 含义 | 该怎么办 |
|---|---|---|
| `no_stream` | 一个字节都没截到 | 数据流没开始 |
| `metadata_only` | 只有元数据，`declared_records` 却说有 N 条 | 流没跑完 |
| `stream_started_no_records` | 有内容但没有记录块 | 格式变了或流被截断 |
| `records_present_not_ready` | **记录到了，就绪标记没抬** | 判定逻辑的问题，不是站点 |

有 `declared_records` 就说明站点确实有这个结果集，**不要说「没有文献」**。

## 不要做的

- 不要因为一次空结果就断言「没有文献」——先看 `dropped_year`；
- 不要用循环把同一关键词翻很多页；
- 不要为了「多拿点数据」把 `limit` 拉到 50 再本地截断；
- 不要把 `blocked` 解释成「稍后再试」；
- 不要把中文 query 发去 WoS（或反之）然后报告「无结果」。
