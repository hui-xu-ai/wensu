# Web of Science channel — 设计与待确认

状态：**待需求确认**（本文件是接手用的入口，不是最终设计）。
负责人接手前先读 `AGENTS.md` 的硬约束与 `docs/channel-contract.md`。

## 目标（一句话）

新增一个 `webofscience` 渠道，让 `search` / `detail` / `export` 三个既有工具能在
Web of Science 上返回合法的题录 `Record`，与 `cnki` 渠道并列、可切换。

## 非目标

- 不下载 PDF/全文（ADR 0002 只读）。
- 不写入 Zotero/EndNote 等第三方库（ADR 0006）。
- 不处理登录、验证码、机构代理跳转的自动化（ADR 0004：遇风控即停）。
- 不新增动作动词（`verb` 集合是封闭的九个）。

## 现状（可直接复用）

- 微内核 + 渠道包：`src/scholar_search/channels/<site>/manifest.json` + `<site>/<site_version>/`。
- 参考实现：`channels/cnki/v2026_10/`（`selectors` / `plan_search` / `parse_search` /
  `plan_detail` / `parse_detail` / `doc_types`）。
- 内核已具备：配额与冷却（ADR 0005：最小间隔 3000ms、并发 1、单页、每日 300）、风控拦截、
  审计、RIS/EndNote 渲染（`export`）、浏览器桥（`docs/bridge-protocol.md`）。
- 契约与测试：`tests/contract/`（manifest 校验、动词白名单、域名白名单、解析器错误类型）。

## 待确认（开工前必须回答）

1. **访问方式**：走用户自己浏览器里的已登录会话（同 CNKI）？还是需要机构 IP / 代理域名？
   入口是 `www.webofscience.com`（新版）还是 `webofscience.com` / `clarivate.com` 旧版？
2. **域名白名单**：机构代理（如 `*.edu.cn` 反代）要不要进 `domains`？这决定 manifest。
3. **检索页形态**：结果列表走 `summary` 页面还是 API（`/api/wos/...`）？分页是 `page=N` 还是游标？
4. **字段映射**：WoS 的 `Source Title` / `Document Type` / `Affiliations` 如何映射到
   `schemas/record.json`（`source` / `doc_type` / `institution` / `keywords` / `citations` / `downloads`）？
   注意 `record.json` 的字段是公开契约，不能自行加字段。
5. **配额折算**：一次检索在 WoS 上等于几个网络动作（CNKI 是 3）？是否沿用 300/日？
6. **许可边界**：WoS 为订阅服务，抓取题录是否在用户机构许可范围内 —— 需要用户明确确认，
   否则默认不做（与 ADR 0002/0004 一致）。

## 落点（文件清单，待确认后细化）

```
src/scholar_search/channels/webofscience/
├── manifest.json                      # channel/site_version/domains/detail_url_prefixes/capabilities
└── v2026_11/
    ├── __init__.py                    # 导出 Channel 实现
    ├── selectors.py                   # 选择器集中在此，便于站点改版时替换
    ├── plan_search.py                 # SearchQuery -> Plan（仅九个动词）
    ├── parse_search.py                # html -> SearchPage
    ├── plan_detail.py                 # url -> Plan
    └── parse_detail.py                # html -> Record
tests/fixtures/webofscience/           # 脱敏 HTML 回放（禁止线上验证代替 fixture）
tests/contract/test_channel_webofscience.py
```

## 验收（三档，缺一不可）

1. **契约/单测**：`pytest tests/contract -q` 通过；解析器对畸形 HTML 抛 `ParseError` 而非 `KeyError`；
   fixture 回放得到预期 `SearchPage` / `Record`。
2. **真实链路**：`wensu status` → `bridge_ready: true`；一次 `search`（单页 ≤3 条）+ 一次 `detail` +
   一次 `export`；审计里能看到动作数、耗时、结果数。
3. **风控路径**：故意触发（或回放）一次验证码/重定向，确认返回 `blocked` 且 24h 冷却生效。

## 风险

- WoS 对自动化访问敏感，验证码/限流概率高于 CNKI ⇒ 先做“能解析”再谈“能翻页”。
- DOM 与 URL 形态变动频繁 ⇒ `site_version` 目录化，旧版本保留可回滚。
- 若走机构代理，域名白名单与 Host 检查需同步评审，避免把白名单放宽到任意子域。
