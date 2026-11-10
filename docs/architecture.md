# 架构说明

本文说明 wensu（文溯）的分层、一次调用的完整路径、内核各组件的职责，以及可以往外扩的点。
面向要改代码或加渠道的人；只想知道怎么用的读者看 [README](../README.md) 即可。

## 1. 定位与边界

一句话：**内核不懂知网，渠道不懂 IO。**

- 内核（`core/`）负责契约、注册表、策略、风控、计划调度、审计、缓存、导出。它不知道任何
  CSS 选择器、URL 或页面结构。
- 渠道（`channels/`）只描述"在这个站点上怎么检索、怎么解析"，不碰网络、不认识 MCP。
- 适配器与浏览器侧只做管道：把九个通用动作送到页面，把结果搬回来。

这条边界不是洁癖，是维护成本：站点改版时只动一个目录，内核与工具 schema 不动。

## 2. 分层

```
transports/            stdio | http（回环 + 令牌）
server.py              MCP 工具面：search / detail / export / status
core/                  contracts registry policy risk planner audit cache locking export params
channels/cnki/         manifest.json（渠道级）+ v2026_10/（站点版本）
adapters/              bridge（生产） | fixture（测试） | cdp（预留）
native-host/           TCP 回环 + 令牌；动作校验第二道闸；拉起浏览器侧
extension/             九个动作；零站点知识
```

依赖方向严格向下：渠道不 import 传输层，传输层不 import 渠道实现，内核不 import 浏览器侧。
`tests/contract/test_channel_contract.py` 会把新渠道按契约过一遍。

| 层 | 文件 | 职责 |
|---|---|---|
| 传输 | `transports/stdio.py`、`transports/http.py` | 把 MCP 协议接进 `server.build_server()` |
| 工具面 | `server.py` | 四个 tool 的参数与返回；把异常转成 `{status, error}` |
| 内核 | `core/service.py` | 编排：解析渠道、查缓存、跑计划、调 `sort_fix`、解析、年份过滤、写缓存 |
| | `core/planner.py` | 逐动作执行；动作之间检查风控；持跨进程锁 |
| | `core/policy.py` | 动词/域名白名单、间隔与抖动、每日配额、计划体积与时长 |
| | `core/risk.py` | 识别风控信号、写 24h 冷却、`ensure_ready()` 拦截 |
| | `core/registry.py` | 发现渠道与站点版本、按 `min_core` 选可用的 |
| | `core/audit.py` | JSONL 动作与风控记录 |
| | `core/cache.py` | SQLite 响应缓存（默认 7 天） |
| | `core/export.py` | RIS / EndNote 文本渲染，含类型映射与字段清洗 |
| | `core/params.py` | 九个动词的封闭参数 schema（内核与宿主共用） |
| 渠道 | `channels/cnki/v2026_10/` | 计划（`plan_*`）、解析（`parse_*`）、选择器、类型归一化 |
| 适配器 | `adapters/bridge/` | 发现活的宿主、帧协议、超时与错误映射 |
| 浏览器 | `native-host/`、`extension/` | 原生消息宿主；标签页管理与九个动作 |

## 3. 一次 `search` 的完整时序

```
client ──search(query)──▶ server.search
                            │ ① query.validate()（页码、条数、排序、年份组合）
                            │ ② risk.ensure_ready()（冷却中就 blocked，不进浏览器）
                            │ ③ registry.select("cnki") → 最高可用站点版本
                            │ ④ cache.get(key)           命中则直接返回
                            ▼
                       channel.plan_search(query)      产出 Plan（动作元组）
                            ▼
                       planner.run(plan, manifest)
                            ├─ 跨进程锁 state/plan.lock（超时 90s）
                            ├─ policy.validate_plan：动词、域名、≤40 动作、≤200s
                            └─ 逐个动作：
                                 ├─ risk.ensure_ready()（别的进程可能刚触发冷却）
                                 ├─ 网络动作 → policy.wait_turn()（3s 下限 + 抖动）
                                 │             → 配额原子预留（interval + 计数 + 落盘）
                                 ├─ adapter.execute(action, timeout_ms)
                                 ├─ audit.action(...)
                                 ├─ risk.inspect(outcome) → 命中即 trip 冷却并抛 Blocked
                                 └─ 失败即停，后续动作不再执行（依赖已被破坏）
                            ▼
                       取出 read_html 的 HTML
                            ▼
                       channel.sort_fix(query, html)  排序落成 ASC 时返回纠正计划
                            └─ 最多重跑 2 轮
                            ▼
                       channel.parse_search(html, query) → SearchPage
                            ▼
                       年份过滤（客户端）→ 截断到 limit → 写缓存 → 返回
```

`detail` 的路径更短：校验 URL 域名与路径前缀（`detail_url_prefixes`）→ 计划 → 解析 → 缓存。

## 4. 计划（Plan）与动作词汇

计划是**纯数据**：一串 `(verb, params, timeout_ms)`。词汇封闭为九个：

| 动作 | 参数 | 计数网络配额 |
|---|---|---|
| `goto` | `url` | 是 |
| `type` | `selector` `text` `clear` | 是 |
| `click` | `selector` | 是 |
| `select` | `selector` `value` | 是 |
| `read_html` | — | 否 |
| `read_text` | `selector` | 否 |
| `wait_for` | `selector` `timeout_ms` `state` | 否 |
| `scroll` | `to` | 否 |
| `sleep` | `ms` | 否 |

几个容易踩的点：

- **读类动作不占配额**，但占计划时长预算（总和 ≤200s）。所以"多等一下"不是免费的。
- **`sleep` 的 `timeout_ms` 必须大于 `ms`**。浏览器在窗口非前台时会把定时器按整秒分桶，
  暂停最多晚到近 1 秒；0.3.15 起统一用 `plan_search.settle(ms)`（自带 2s 余量），
  不要手写 `Action("sleep", ...)`。
- **`wait_for` 的 `timeout_ms` 是宿主侧的等待上限**，比参数里的 `timeout_ms`（页面内轮询上限）
  大 `WAIT_REPLY_MARGIN_MS`，两者不是一回事。
- 一旦某个动作失败，计划就地停止；解析阶段拿不到完整 HTML 会直接报错，不会返回半页数据。

## 5. 渠道与站点版本

渠道目录结构：

```
channels/cnki/
  manifest.json          渠道级：名称、域名白名单、动作集、能力、min_core
  v2026_10/              站点版本：包名即版本号，vYYYY_MM
    __init__.py          get_channel() 工厂 + CnkiChannel 实现
    selectors.py         所有 CSS 选择器与入口 URL
    plan_search.py       检索计划
    plan_detail.py       详情计划
    parse_search.py      结果表解析
    parse_detail.py      详情页解析
    doc_types.py         文献类型归一化（两个解析器共用）
```

注册表扫描 `channels/*/manifest.json`，再枚举该渠道下所有 `v*` 目录，
得到 `(channel, site_version)` 列表，按版本号取最高的、且满足 `min_core` 的那个。
旧版本目录会保留并仍然可加载（可以通过 `site_version` 参数显式选择），
这样站点改版期间可以新旧并存，回滚只是换个目录。

新增站点版本 = 复制目录 + 改选择器与解析 + 补 fixture 测试，**不改内核**。
详见 [知网改版应对](cnki-maintenance.md)。

## 6. 桥接与信任边界

```
server ──TCP 127.0.0.1:<port>──▶ native-host ──stdio──▶ extension ──▶ tab
          带 token，帧 = 4 字节长度 + JSON，单帧 ≤2 MiB
```

- 宿主只监听回环，端口与令牌写在 `%LOCALAPPDATA%\scholar-search\host\bridge.json`，
  多个宿主可并存，适配器逐个 ping，选应答的那个。
- **校验是双层的**：内核用渠道 manifest 校验动词/域名/参数；宿主用自己的可信域名白名单
  再校验一次，请求只能收窄范围，不能替换。即使扩展被替换，也拿不到任意 JS 执行能力。
- 扩展侧：`background.js` 负责标签页绑定、域名复核、导航完成等待、消息重试；
  `content/actions.js` 只实现九个动作，不写任何站点逻辑。
- 浏览器以低完整性启动宿主，所以 `host/` 目录会被 `install.ps1` 标记为低完整性可写，
  否则宿主写不了端点文件。

## 7. 状态与数据

运行期数据全部落在 `SCHOLAR_SEARCH_HOME`（默认 `%LOCALAPPDATA%\scholar-search`），仓库里不写：

| 路径 | 内容 |
|---|---|
| `state/quota.json` | 当日已用网络动作数、上次时间戳（跨进程唯一真源） |
| `state/cooldown.json` | 风控冷却到期时间与信号 |
| `state/plan.lock` | 计划级跨进程互斥 |
| `audit/audit.jsonl` | 每个动作的渠道/动作/耗时/结果/错误码；风控单独一条 |
| `cache/cache.sqlite3` | 响应缓存（默认 7 天） |
| `host/bridge.json` | 宿主端点与令牌 |
| `host/logs/host.log` | 宿主生命周期日志 |
| `installations/<版本>/` | 部署树（venv + browser 资源） |

审计只记元数据，不记 HTML、不记 Cookie、不记账号。

## 8. 错误模型

| 异常 | 触发 | 客户端看到 |
|---|---|---|
| `PolicyError` | 参数越界、域名不合法、计划超限、配额/冷却 | `status: error`，`error` 里带规则名 |
| `Blocked` | 风控信号 | `status: blocked` + `signal` + `cooldown_until` |
| `ActionError` | 某动作失败（含超时） | `status: error`，带动词与错误码 |
| `ParseError` | 页面结构与解析器期望不符 | `status: error` |
| `ChannelNotFound` / `ChannelError` | 渠道或版本不存在、manifest 不合法 | `status: error` |

风控优先于一切：冷却期内任何工具调用都在进入浏览器之前被拒。

## 9. 可扩展点

| 想加什么 | 动哪里 | 不用动什么 |
|---|---|---|
| 新站点（万方、维普） | `channels/<name>/manifest.json` + `v<版本>/` | 内核、宿主、扩展 |
| 站点改版 | 新增 `vYYYY_MM/`、补 fixture | 同上 |
| 新传输 | `transports/` + `cli.py` 的 `serve` | 渠道 |
| 另一种浏览器 | `adapters/` 新适配器（如 CDP），实现 `BrowserAdapter` | 内核与渠道 |
| 新导出格式 | `core/export.py` | 其余全部 |
| 新动作 | 需 ADR：`core/params.py`、`core/contracts.py`、宿主、扩展四处同步 | — |

**不能加的**：下载全文、任意 JS 执行、把题录写进第三方文献库（[ADR 0006](adr/0006-no-third-party-ingest.md)）。

## 10. 不变量

1. 动作词汇封闭，没有 `eval`、没有下载动作。
2. 内核的限额是硬边界，渠道只能收紧。
3. 解析全部在服务端完成，必须有 fixture 回放测试，禁止"只靠线上看一眼"。
4. 一个计划一份锁，并发恒为 1；配额是跨进程的单一真源。
5. 任何风控信号都终止计划、写审计、冷却 24h，不自动重试。
6. 扩展不含站点知识；选择器只随计划下发。

## 11. 决策记录

| ADR | 主题 |
|---|---|
| [0001](adr/0001-microkernel.md) | 微内核 + 渠道插件 |
| [0002](adr/0002-read-only.md) | 只读，不碰全文 |
| [0003](adr/0003-native-bridge.md) | 用原生消息宿主而不是调试端口 |
| [0004](adr/0004-risk-stop.md) | 遇风控即停、冷却 24h |
| [0005](adr/0005-quota-300.md) | 每日 300 次与频率下限 |
| [0006](adr/0006-no-third-party-ingest.md) | 不做第三方题录入库 |
| [0012](adr/0012-bridge-threat-model.md) | 桥的威胁模型与宿主任信边界 |
