# ADR 0010 · 用期刊影响因子筛选检索结果

- 状态：accepted
- 日期：2026-11-08
- 关联：ADR 0009（短清单与本地筛选）、ADR 0007（WoS 取数）

## 背景

WoS 的响应里带 `jcr` 块，字段形如：

```json
"ISSN:0021-8669": { "JournalTitle": "JOURNAL OF AIRCRAFT",
                    "ImpactFactor": 2.4, "FiveYearImpactFactor": 2.6,
                    "Year": 2025, "CategoryIFData": [{ "JifQuartile": "Q2" }] }
```

记录通过 `jcrKey`（如 `ISSN:2377-3766`）指向它。用户要的是「只要高质量期刊」，
也就是按影响因子筛掉一批，而不是把 50 条全看一遍。

## 备选

### 备选 A：只用 `sources_only`（期刊名子串）

- 优点：零改动，ADR 0009 已经实现。
- 被否理由：得先知道期刊叫什么才能筛；用户要的是「不知道具体刊名，只要够好的」，
  而且同一出版社下刊名千差万别。

### 备选 B：把 `impact_factor` 加进 `record.json`

- 优点：调用方能看到具体数值，可自行判断。
- 被否理由：`record.json` 是 `additionalProperties: false` 的公开契约，CNKI 没有这个概念，
  加了字段就意味着所有渠道都要解释"为什么这里是 null"。为筛选需求付契约代价，不对等。

### 备选 C：`SearchQuery` 加 `min_impact_factor`，渠道内部筛选（选中）

- 优点：不动 `record.json`；筛选发生在解析层，本来就能看到 `jcr`；零网络动作。
- 被否理由：`SearchQuery` 属契约，加字段是 ADR 级变更——本文即为此而写。

## 决策

1. `SearchQuery` 增加 `min_impact_factor: float | None = None`。
2. WoS 渠道的 `parse_records` 先收集所有 `jcr` 块（它**在** records 之后到达，必须单独一遍），
   再用 `jcrKey` 关联；达不到阈值或**没有指标**的记录被丢弃。
   「未知即不满足」与 `min_citations` 的「未知即保留」相反，理由不同：影响因子是按期刊走的，
   没有指标通常说明该刊不在 JCR 收录范围，正是用户想筛掉的。
3. 筛选后为空是**合法结果**，返回空页而不是抛 `ParseError`——抓取是成功的，只是没有刊达标。
4. 不支持的渠道（CNKI）静默忽略该参数。

## 后果

**实测**（2026-11-08，查询 `actuator`，近五年，一次检索 50 条）：25 个期刊带指标，
`min_impact_factor` 取 2.0 / 3.0 / 5.0 / 10.0 时分别剩 33 / 30 / 24 / 3 条；
索引到的最高是 `ISSN:0935-9648`（Advanced Materials，29.1）。端到端跑通：3 个网络动作、约 12 秒、返回 24 条。

- 影响因子**只用于筛选，不出现在返回记录里**。要看具体数值需要改 `record.json`，那是另一个 ADR。
- 筛选在解析层做，因此 `total`（站点报告的总数）与实际返回条数会不一致——这一点与年份过滤相同，
  `total` 描述的是站点结果集。
- 实测的 `jcr` 块按批下发（三批分别 15 / 11 / 0 条），所以一次性收集全部块再匹配，
  不能按批局部判断。
- CNKI 行为不变：它没有 `jcr` 块，参数是空操作。
