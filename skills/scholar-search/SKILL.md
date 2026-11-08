---
name: scholar-search
description: 通过 wensu MCP 检索文献题录。双渠道：cnki（中文文献，中文检索式）与 webofscience（英文文献，WoS 检索式，自带期刊影响因子）。只返回题录，不下载全文。
---

# 文献检索

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
3. **量**：`page` 取值 1–3，`limit` 1–50；每次调用只返回一个目标页。日上限 300 次由内核强制。
4. **串行调用**：不要并行发多个检索。虽然内核有跨进程锁会串行化，但排队期间每个调用都占着超时预算，实测两个并行各自要等约 20 秒，比顺序发更慢也更容易撞上超时。
5. **不猜结果**：只转述工具返回的字段，不补全、不虚构作者或年份。

## 最重要的陷阱：年份过滤是「当前页过滤」

`year_from` / `year_to` **只在刚抓到的那一页上过滤**，不会让站点重新检索。

后果：`records: []` 加 `total: 65` 意味着「**这一页没有符合年份的**」，**不是**「这个主题没有该年份的文献」。

**判断方法**——看 `dropped_year`：

| 返回 | 含义 | 该怎么办 |
|---|---|---|
| `records: []`，`dropped_year: 0`，`total: 0` | 真的没有匹配 | 可以下「无文献」结论 |
| `records: []`，`dropped_year: 30` | 这一页 30 条全被年份筛掉了 | **换检索式或翻页**，不要说无文献 |
| `records: [9 条]`，`total: 401` | 只有 9 条落在今年 | 引用时说明「共 401 条，本页 9 条符合年份」|

**空结果不等于没有文献。** 交付前至少用同义词再交叉验证一次，别凭单次空结果下结论。

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

**年份有两个入口，效果不同**：

- 写进检索式 `PY=(2026)` —— **站点侧过滤**，`total` 就是该年的真实命中数（更准，需要一次完整检索）；
- 用参数 `year_from=2026` —— **当前页过滤**，`total` 仍是全量（快，但看 `dropped_year`）。

要结论可靠时，把年份写进检索式。

### 影响因子（仅 WoS）

WoS 记录自带 `impact_factor`（JCR 当年值，可能为 `null`——该刊无指标）。

- `min_impact_factor: 5` —— **本地筛选**，**无指标即丢弃**（会降低召回，这是设计而非 bug）；
- `sort_by: "citations"` 或 `"year"` —— 本地排序，不发额外请求。

**注意 `sort` 与 `sort_by` 是两套**：`sort` 让站点重排（多 2 个请求、走配额），`sort_by` 在本地重排（免费）。
想按被引排序又要省配额，用 `sort_by: "citations"`；想要站点的全局排序用 `sort`。

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
- 两个渠道的 `doc_type` 词表不同：CNKI 是 `journal`/`thesis`/`conference`，WoS 是 `article`/`review`/`proceedings`。

## 详情与导出

```
detail(url)                  → 完整记录（含摘要）。search 之后从缓存取，零网络动作
export(records, format="ris" | "endnote")   → 纯文本题录，不写文件
```

`detail` 只需要 URL，**不用传 channel**。

## 异常

| 返回 | 含义 | 处理 |
|---|---|---|
| `status: blocked` | 风控或验证页 | 停止，原样报告 `signal` 与 `cooldown_until` |
| `PolicyError`（`page` > 3 / `limit` > 50）| 参数越界 | 改参数 |
| `PolicyError`（host not allowed）| URL 不属于任何渠道 | 检查 URL 是否被拼接过 |
| `ActionError`（`wait_for` 超时）| 页面没在预期时间内给出数据 | **重试一次**，仍失败则报告；不要连续重试 |
| `ParseError` | 页面结构变化 | 报告并停止，不要重试同一请求 |

**超时会消耗额度**（请求已经真实发出去了），响应里目前不报告扣了多少。用 `status` 的
`quota_remaining` 前后对比。

## 不要做的

- 不要因为一次空结果就断言「没有文献」——先看 `dropped_year`；
- 不要用循环把同一关键词翻很多页；
- 不要为了「多拿点数据」把 `limit` 拉到 50 再本地截断；
- 不要把 `blocked` 解释成「稍后再试」；
- 不要把中文 query 发去 WoS（或反之）然后报告「无结果」。
