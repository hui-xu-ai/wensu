# 验收报告 · wensu 0.12.56（真实链路，2026-11-17）

> 运行 ID：`2026-11-17-accept-0.12.56`
> 档位：**真实链路**（双渠道检索 / 详情 / 批量 / 导出全部真跑，走 DSH 正在连接的 `mcp__wensu__*`）
> 未覆盖：`--force` 资源刷新手感的 UI 观感、扩展在 `edge://extensions` 里的显示（需人眼确认）

## 1. 结论摘要

| # | 结论 | 档位 |
|---|---|---|
| 1 | 五个工具在册、schema 与契约测试一致；`status/detail/export/detail_many` 行为全部符合文档 | 真实链路 |
| 2 | 双渠道检索可用：CNKI `total 2141`、WoS `total 50`，记录真实可复核（卷期页/DOI/JCR 年份齐全） | 真实链路 |
| 3 | 缓存与免费视图的三条承诺成立：重复检索 0、`local_sort` 0、同 URL 二次 detail 0 | 真实链路 |
| 4 | **配额计量单位与文档不符**：WoS 检索实际扣 **8**（文档 4）；裸 DOI 扣 **4**（文档暗示 1） | 真实链路 |
| 5 | **`query_effective` 没反映真正执行的表达式**：WoS 追加的 `AND PY=` 在执行式里有、在返回字段里没有 | 真实链路 + 源码 |
| 6 | `dropped_*` 的分母是抓到的整页（20 行），不是返回值（`limit`） | 真实链路 |
| 7 | 扩展副本仍是 **0.12.53**，而包/状态报 0.12.56；`status` 无字段能暴露它 | 真实链路 |
| 8 | `schemas/tools.json` 已腐化（缺 3 个参数 + `status.brief`），且无任何闸门读取它 | 源码 |

## 2. 环境

- 包：`D:\Python\Python314\Scripts\wensu.exe`，`wensu --version` → `0.12.56`
- 桥：`bridge_ready true`，`bridge_protocol 1`，profile `E:\LiteratureEdgeProfile`，extension_id `gmaimbocfjkolcpljeekjcomakipoaph`
- 扩展副本：`%LOCALAPPDATA%\scholar-search\browser\extension\manifest.json` → **0.12.53**
- 起始状态：`2026-11-17 21:39` 触发 `verify_redirect` 冷却，用户人工验证后由 `wensu reset --confirm` 清除（输出 `risk cooldown cleared`，随后 `cooldown_until: null`）

## 3. 配额台账（1 单位 = 1 个网络动词）

| 时间 | 调用 | 扣 | 余 |
|---|---|---|---|
| 21:39 | `search(cnki 柔性驱动器)` → `blocked verify_redirect` | 1 | 299 |
| 21:48 | `search(cnki 柔性 驱动器 limit5)` | 3 | 296 |
| 21:49 | 同一检索式 + `local_sort` + `fields`（缓存） | 0 | 296 |
| 21:50 | 同一检索式 + `year_from/to=2025`（缓存，本地过滤） | 0 | 296 |
| 21:48 | `detail(cnki url)` 首次 | 1 | 295 |
| 21:49 | `detail(cnki url)` 第二次 | 0 | 295 |
| 21:52 | `search(wos TS=(ionic AND actuator) year_from=2024)` | **8** | 287 |
| 21:53 | `detail(wos url)`（检索播种） | 0 | 287 |
| 21:54 | `detail(裸 DOI 10.13841/…)` | **4** | 283 |
| 21:57 | `detail_many(2×wos + 1×doi)`（全缓存） | 0 | 283 |
| 21:58 | `search(cnki count_only=true)`（缓存） | 0 | 283 |
| 21:59 | `export(ris, out_path)` | 0 | 283 |

合计消耗 **17 / 300**。

## 4. 验收矩阵

| 断言（出处） | 实测 | 判定 |
|---|---|---|
| `status` 报包版本、渠道、能力表（`docs/integration/dsh.md`） | 0.12.56 / cnki+webofscience / 能力表与列表行实际字段一致（CNKI 行 doi、abstract、keywords 均 null，与 `channel_capabilities` 相同） | 通过 |
| 检索返回题录（`scholar-search` L14） | CNKI 5 条、`total 2141`、`query_effective SU='柔性 驱动器'` | 通过 |
| 同检索式重复调用免费（L337） | `cache_hit true`、`quota_charged 0` | 通过 |
| `local_sort` 免费（L164） | `quota_charged 0`（但见 F5） | 通过 |
| CNKI 年份只做本地过滤且命中缓存（L92） | `year_scope page`、`cache_hit true`、`records []` + `all_dropped_by_year` | 通过 |
| 空结果不是「没有文献」（L97–108） | `total 2141` 保留、`dropped_year 20` | 通过（但见 F4） |
| 知网 detail 首次 1、重复 0（L362） | 1 → 0 | 通过 |
| WoS 检索播种详情，detail 免费（L361） | `quota_charged 0` | 通过 |
| `detail_many` 逐条隔离、失败不连坐（tools.json） | 3/3 ok，`ok_count 3`、`failed_count 0` | 通过 |
| `export(ris, out_path)` 落盘且不带影响因子（L348–355） | 884 字节、`TY JOUR/AU×4/T2/PY/VL/IS/SP-EP/DO/KW/UR`，无 IF | 通过 |
| `page>3` 被 schema 拦（L382） | MCP 层 `less_than_equal` 校验失败，未花配额 | 通过 |
| WoS 检索扣 4（status.action_cost + SKILL L162） | **8** | **不通过 → F1** |
| `query_effective` 显示 `AND PY=(…)`（L91/L231） | 返回里没有 PY，执行式里有 | **不通过 → F2** |
| detail 花费「缓存 0 / 现场 1」（L16） | 裸 DOI = **4** | **不通过 → F3** |

## 5. 发现清单（含复现方法与修复落点）

### F1 WoS 检索实际扣 8，文档与 `action_cost` 都写 4　【高】

- **证据**：`raw/06-wos-search.json`（`quota_charged: 8`）、`raw/07-plan-cost.txt`（WoS 计划 21 个动作、其中 `click` 6 次）、`raw/08-quota-model.json` 与 `audit.jsonl` 逐条对账（`goto 1 + type 1 + click 6 = 8`）。
- **复现**：
  1. `mcp__wensu__search {query:"TS=(ionic AND actuator)", channel:"webofscience", limit:3, year_from:2024}` → 看 `quota_charged`；
  2. `D:\Python\Python314\python.exe work\verify\2026-11-17-accept-0.12.56\probe-plan-cost.py`（不花配额）；
  3. `Select-String audit.jsonl -Pattern '"event": "action"' | …` 数 `goto/type/click` 条数。
- **根因**：1 配额 = 1 个 `NETWORK_VERBS`（`core/planner.py:74` → `policy.wait_turn()` → `state.used += 1`）。WoS 走 BibTeX 导出路径后计划里多了 6 次 `click`，而 `status.action_cost` 是**手写常量**，没跟着改。
- **落点**：`service.status()` 的 `action_cost` 表；`skills/scholar-search/SKILL.md` 价目表与「一轮按 4 个额度估」；`tools.json` 里 `site_sort` 的 "costs quota (about 5)" 同样待核。
- **别改错**：不要动 `wait_turn` 的计量逻辑（审计可自证），也不要为了对上 4 去裁 WoS 计划的 click——那会改变抓取行为。

### F2 `query_effective` 报的是调用方原文，不是执行的表达式　【中高】

- **证据**：响应 `query_effective: "TS=(ionic AND actuator)"`；同一 query 的 `channel.effective_query()` 打出 `(TS=(ionic AND actuator)) AND PY=(2024-2026)`（`raw/07-plan-cost.txt` 第 8 行）；`year_scope` 却已是 `site_and_page`。
- **根因**：`channels/webofscience/*/parse_bibtex.py:207` 写了 `query_effective=query.text`，而 `core/service.py:282` 的「用 channel.effective_query 覆写」只在字段为 `None` 时触发 ⇒ 覆写永远不执行。
- **复现**：上面的 search 调用 + `probe-plan-cost.py`；或 `grep -n "query_effective" channels/webofscience/*/parse_bibtex.py`。
- **落点**：`parse_bibtex.py:207` 改为不填该字段（让 service 覆写），或直接填 `expression.build(query)`。**顺带**：`year_scope` 的取值 `site_and_page` 在 `tools.json`/SKILL 里从未出现（SKILL 只写 `page`），要一起补。
- **别改错**：`_writes_year_into_query()`（`server.py`）是按渠道写死的，不要改成查 manifest，注释里写着「错的 manifest 不能让响应失败」。

### F3 裸 DOI 在知网扣 4（检索 3 + 详情 1），文档暗示 1　【中】

- **证据**：`detail(10.13841/j.cnki.jxsj.2026.11.001)` → `quota_charged: 4`，且返回的 `url` 与缓存里那条 CNKI 详情 URL **不同**（新的 `v=` 令牌）；audit 显示该次 `search` 3 个网络动词 + `detail` 1 个。
- **复现**：先 `detail(cnki url)`（1），再 `detail(同一篇的 DOI)`（4）。
- **落点**：`skills/scholar-search/SKILL.md` L16 的花费列、`tools.json` 里 `detail.url` 的描述（"A DOI costs one extra search"→ 应写成"含一次检索，知网实测 4"）。
- **已澄清**：同一 DOI 第二次是 0（`detail_many` 里那一条 `quota_charged: 0`），所以这是「首解析贵」，不是「DOI 永远贵」。

### F4 `dropped_*` 的分母是抓到的整页，不是 `limit`　【中】

- **证据**：`limit=5` 却得到 `dropped_year: 20`、`page_count: 108`（`raw/03-cnki-year-filter.json`）。`2141/20 ≈ 107` 印证站点每页 20 行，`limit` 只在返回前截断。
- **复现**：`search(cnki, "柔性 驱动器", limit 5, year_from 2025, year_to 2025)` → 看 `dropped_year`。
- **落点**：SKILL「最重要的陷阱」一节（补一句分母定义）、`tools.json` search 描述。
- **别改错**：不要把 `dropped_year` 改成"按返回值统计"——那会让 `all_dropped_by_year` 变成"这 5 条都超年份"，语义更差。

### F5 `local_sort` 的回显用了旧键名，且在知网上无声无效　【低】

- **证据**：传 `local_sort: "citations"`，`filters` 回显 `{"sort_by": "citations"}`（`raw/02-cnki-cache-local-sort.json`）；同页 5 条 `citations` 全为 `null`（CNKI 列表行没有被引数），排序结果与不排序完全一致。
- **落点**：`server.py:_filters_payload` 的回显键名；SKILL L252「想按被引排序用 `local_sort`」应注明在 CNKI 上无数据可用。

### F6 扩展副本版本说谎，且 `status` 无字段可见　【高，上一轮已定位，本轮真机复现】

- **证据**：`wensu status` 全量 payload 的 `browser_profile` 只有 `extension_dir`/`extension_id`，**没有版本**；磁盘副本 `manifest.json` 是 `0.12.53`，包是 `0.12.56`；`extension_telemetry_file_data` 里 Edge 记录的也是 0.12.53。
- **复现**：
  1. `(Get-Content "$env:LOCALAPPDATA\scholar-search\browser\extension\manifest.json" -Raw | ConvertFrom-Json).version` → 0.12.53
  2. `wensu --version` → 0.12.56
  3. `wensu setup --no-host --browser none; $LASTEXITCODE` → **0**（而 assets 一个字没刷新，`stderr` 只有一行 "already exists; pass --force"）
- **根因**：`assets.py:89` 抛 `FileExistsError` → `browser_setup.py:48-51` 吞掉 → `cli.py:280-286` 返回 0。刷新资源只有 `--force` 一条路，且这个开关同时 `rmtree` 用户技能目录。
- **落点**：`assets.py::copy_assets`（改成按版本比对自动刷新）、`browser_setup.py`（跳过刷新时给非 0）、`cli.py`（`--force` 拆成 `--force-assets`/`--force-skills`）、`service.status()`（加 `extension_version` + `version_mismatch`）。

### F7 `schemas/tools.json` 与真实工具面不一致，且无人校验　【中】

- **证据**：真实 `search` 有 18 个参数（含 `exclude_ut`/`sort`/`sort_by`），`tools.json` 只有 15；`status` 真实有 `brief`，文件里是 `properties: {}`。
- **复现**：`D:\Python\Python314\python.exe -c "import asyncio,json;from scholar_search.bootstrap import build_service;from scholar_search.server import build_server;print(json.dumps({t.name:sorted(t.inputSchema.get('properties',{})) for t in asyncio.run(build_server(build_service()).list_tools())}))"`，与 `schemas/tools.json` 对比。
- **根因**：`tests/unit/test_tool_schema_contract.py:7` 明确「不解析 schemas/tools.json」；`scripts/release-check.py` 也不读它 ⇒ 文件是纯装饰。
- **落点**：要么删掉该文件并改成从服务端生成（`tools/list` dump），要么在 `release-check.py` 加一条「dump 结果与文件一致」。

### F8 技能四份 / 三副本分叉（上一轮结论，未变）

- 仓库 `skills/`（源）→ `~/.codex/skills/` → `D:\DSH\.dsh\skills/`：12 个文件里 8 个哈希不同。
- `docs/integration/codex.md:159` 仍写「三份 SKILL.md」，漏第四份 `scholar-install`。
- **复现**：`Get-FileHash` 三处同名 `SKILL.md` 对比。

### F9 升级流程三套并存的残留

- 机器上同时存在 `installations\0.12.48\browser\extension`（0.12.48）、`browser\extension`（0.12.53）、`installations\0.12.48\venv\...\assets\extension`（0.12.56）；`extension.bak-0.4.2` 残留；`%LOCALAPPDATA%\scholar-search\profiles\edge` 与真实 profile `E:\LiteratureEdgeProfile` 并存。
- `installations\0.12.48` 目录里装的是 0.12.56 —— **目录名不能当版本证据**。

## 6. 建议修复顺序

1. **F1 + F3（纯文档/常量，零风险）**：改价格表与 `action_cost`，先让"预算"是真的。
2. **F6 第 1 步（只加字段）**：`status` 加 `extension_version`/`version_mismatch` —— 以后再出这类问题，agent 能自己发现。
3. **F2（一行）**：`parse_bibtex.py:207` 不填 `query_effective`；补 `year_scope` 词汇表。
4. **F6 第 2 步（行为变更，需回归）**：`setup` 按版本比对自动刷新 + `--force` 拆分；必须先加测试再改。
5. **F7、F8、F4、F5（收尾）**：契约文件收敛、技能副本同步闸门、文档补分母与渠道限制。

## 7. 证据文件索引

| 文件 | 内容 |
|---|---|
| `raw/01-cnki-search.json` | CNKI 首次检索原始响应（含 `query_effective`） |
| `raw/02-cnki-cache-local-sort.json` | 缓存命中的同检索式调用 |
| `raw/03-cnki-year-filter.json` | 年份本地过滤 + `dropped_year` 分母问题 |
| `raw/04-cnki-detail.json` | CNKI 详情首次（扣 1） |
| `raw/05-cnki-detail-repeat.json` | 同 URL 二次（扣 0） |
| `raw/06-wos-search.json` | WoS 检索（扣 8）与 `query_effective` 缺失 PY |
| `raw/07-plan-cost.txt` | 两个渠道的计划动作清单（不花配额） |
| `raw/08-quota-model.json` | 计量单位推导 + audit 逐条对账 |
| `export-ris.ris` | RIS 导出成品（2 条） |
| `probe-plan-cost.py` | 计划动作探针（复现 F1/F2 用） |

## 8. 修复记录（按本报告的发现顺序落地）

| 发现 | 提交 | 改了什么 | 怎么验的 |
|---|---|---|---|
| 基线 | `0c9a5f6` | 本报告的 raw/ 证据入库 | — |
| F1 + F6① | `a4ff43c` | `ACTION_COST` 抽为模块常量并改成实测值（WoS 检索 8、`site_sort` 分渠道 5/10、`page_turn` WoS=None）；`status.browser_profile` 增加 `extension_version` 与 `extension_version_mismatch` | 新增 10 例；修复前红在 `assert 4 == 8`；真机读到 `extension_version=0.12.53 / mismatch=true` |
| F2 | `04cdb36` | `parse_bibtex` 不再把 `query.text` 写进 `query_effective`，交给 `service` 用 `effective_query()` 覆写 | 新增 2 例；修复前红在 `query_effective='TS=(ionogel)'` |
| F1/F3 文档 | `dfb0ee8` | SKILL 价目表/速查表、`year_scope` 取值、`dropped_*` 分母；`tools.json` 的 `site_sort` 与 `detail.url` 描述 | 数字与 `raw/09-action-cost-scenarios.txt` 逐项对应 |
| F6② | `ccc5e2b` | `copy_assets` 改为按 sha256 树比对：相同跳过、不同自动刷新；`--force` 拆成 `--force-assets` / `--force-skills`；`setup` 不再吞异常 | 新增 5 例；真机 `wensu assets` 把扩展从 0.12.53 刷到 **0.12.56**，第二次运行无输出 |
| F5 | `9fd981c` | `filters` 回显 `local_sort`（旧键名 `sort_by` 只剩输入别名） | 新增 2 例 |
| F7 | `efa91f7` | `schemas/tools.json` 由 `scripts/dump-tools.py` 从服务端生成（422 行，补回 `exclude_ut`/`sort`/`sort_by`/`status.brief`）；接入 pytest、`release-check.py`、CI 三道闸门 | 故意改一个字节后 `--check` 报 stale |
| F8 | `9d9f247` | `assets.stale_skills` + `setup` 报出与本版本不同的已装技能；`codex.md` 三份→四份 | 真机报出 `D:\DSH\.dsh\skills` 4 个、`~/.codex/skills` 2 个 |

**回归证据**：`pytest tests` 409 passed；`ruff check` / `ruff format --check` 全绿；
`python scripts/release-check.py` 9/11 PASS（`versions` / `tool-schema` / `changelog` / `tests` /
`lint` / `format` / `types` / `plans` 全过；`assets` 与 `artifacts` 这两个需要 `uv build` 的
检查在本机沙箱里跑不起来 —— `uv` 无法写 `D:\uv-cache` 与临时目录，`os error 5`，与本次改动无关）。

## 9. 仍未处理（需要人拍板，属运行时目录，未擅自改动）

1. `D:\DSH\.dsh\skills` 下 4 份、`~/.codex/skills` 下 2 份 `SKILL.md` 与仓库不同
   —— 可能是你的批注，也可能是滞后。要覆盖请说一声（`wensu setup --skills-dir <目录> --force-skills`）。
2. `%LOCALAPPDATA%\scholar-search` 里的残留：`browser\extension.bak-0.4.2`、
   `installations\0.12.48`（里面装的其实是 0.12.56）、`profiles\edge`（真实 profile 在 `E:\LiteratureEdgeProfile`）。
3. 扩展文件已刷到 0.12.56，但浏览器里加载的那份要**重载一次**（`edge://extensions` → 重新加载）才会显示新版本号。
