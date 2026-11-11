# Web of Science 全球站（www.webofscience.com）支持评估

**日期**：2026-11-11
**结论**：链路已通，**解析层未通**。全球站需要独立解析器，是一个独立工作项，不宜与
现有修复混在一起发布。

## 为什么要评估

用户离开机构 IP 后，镜像站 `webofscience.clarivate.cn` 无法访问（被交给
`access.clarivate.com` 登录网关）。同一时刻 `www.webofscience.com` 在用户登录后可用。
产品需要同时支持两个站点，因为用户不一定都在校园网内。

## 逐层验证结果

| 层 | 结果 | 证据 |
|---|---|---|
| 内核域名白名单 | ✅ 两个站点都允许 | `channels/webofscience/manifest.json` 的 `domains` |
| 扩展 host 权限 | ✅ `.com`、`*.webofscience.com`、`.cn` | `extension/manifest.json` |
| 内容脚本注入 | ✅ `.com` 上注入 | `<html data-wensu-capture="loaded" data-wensu-seen="…">` |
| 捕获触发 | ✅ 前缀已扩展到 `/api/esti/SearchEngine/` | 捕获节点有 2118 字节真实响应 |
| **数据解析** | ❌ **格式不同** | 见下 |

## 两个站点的接口与载荷

**镜像站（现用，可解析）** —— 换行分隔 JSON：

```
/api/wosnx/core/runQuerySearch
/api/wosnx/core/runQueryGetRecordsStream

{"key": "searchInfo", "payload": {"RecordsFound": 115}}
{"key": "records",    "payload": [{...}, ...]}
```

**全球站（已捕获，未解析）** —— 单个 JSON 文档：

```
/api/esti/SearchEngine/search

{
  "QueryResult": {"RecordsSearched": 0, "RecordsFound": 6, "RecordsAvailable": 6},
  "Data": {"Records": [
    {"author_name": "…", "pref_author_name": "…", "orcid": "…", "rid": "…",
     "claim_status": true, "dais_ng_id": "…"}
  ]}
}
```

**注意**：捕获到的这一份是**作者记录**，不是文献记录。`type` 动作向检索框写入表达式时，
全球站触发了作者名联想接口，命中了同一个 `/SearchEngine/search` 路径，把缓冲区覆盖了。
**文献检索的真实端点尚未定位**——只知道它不产生新的 `/api/` 路径（`data-wensu-seen`
里只有 6 个，没有明显的文献端点），因此可能是同一路径的另一个参数组合，或走的是被我们
的 `tracked()` 过滤掉的形式。

## 支持全球站需要做什么

1. **定位文献检索端点**：在一次成功的手动检索中记录所有请求。最省事的办法是给
   `capture.js` 加一个"记录全部 `/api/` 请求（含方法）"的临时开关，用一次人工检索取样。
2. **取样真实响应**：拿到文献记录的 JSON，确认标题、作者、来源、年份、DOI、UT、
   JCR 指标各自的字段名。
3. **写第二套解析器**：`parse_records` 现在假定 NDJSON + `key`/`payload`。需要一个
   在 `QueryResult`/`Data.Records` 形状上工作的分支，两条路都产出同一个 `Record`。
4. **脱敏取样做 fixture**：仓库规范要求 fixture 回放测试，不能只靠线上验证。
5. **`exclude_ut` 与详情链接要跟着站点走**：`UT` 是全球站还是镜像站的标识、
   `full-record` 路径是否是 `/wos/woscc/full-record/`，都要在真实响应上确认。
6. **计划里的主机常量改为可配置**（或按已登录域名自动选），否则两个站点只能二选一。

## 已落地且与上述无关的改进（0.12.52）

这些在 `.cn` 上同样有效，不依赖全球站解析：

- `sleep` 改由扩展后台执行，不再送进页面 —— 导航后那个停顿此前会排在"等内容脚本注入"
  的重试队列里，耗尽预算后报 `bridge.timeout`，而页面其实早已加载完成。
- WoS 的 `actions.js` 在 `.com` 上改为 `document_start` 注入。原先是 `document_idle`，
  高延时网络下 `window.onload` 迟迟不来，脚本永远不注入 —— 表现为
  `content_not_ready`，且几分钟后仍不复原。`.cn` 保持 `document_idle` 不动，不冒回归风险。
- 内容脚本等待预算改为按动作自己的 `timeout_ms` 推算，而不是固定 8 次（约 6.4 秒）——
  之前有 4.6 秒预算没用上就放弃了。
- `content_not_ready` 现在带回标签页 URL 和扩展自己的措辞，内核把它们拼进错误：
  `wait_for failed: content_not_ready (step 4/5, stage wait.capture)
   [reached www.webofscience.com] [Could not establish connection…]`
   —— 这条信息是分辨"没注入"和"注入了但通道断了"的唯一依据。
- 失败信息里的 `step N/M` 改成按**计划长度**计。之前用已执行动作数，一个 7 步计划
  第 2 步失败会显示 `step 2/2`，把排查引向一个不存在的两步计划。
- `capture.js` 同时跟踪两个站点的 API 前缀（`/api/wosnx/core/runQuery` 与
  `/api/esti/SearchEngine/`），并保留 `data-wensu-seen` 作为现场自述。

## 不做的事

- **不把默认主机指向 `.com`**。在解析器就绪前，那只会把"连不上"换成"读不懂"，
  同时弄坏目前能用的镜像站路径。
- **不猜测全球站的字段名**。已捕获的样本是作者记录，用它反推文献字段名会得到
  一个看起来能跑、实际错位的解析器——这轮已经因为"猜一个渠道会怎么做"付过两次代价。
