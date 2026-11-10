# wensu 0.12.36 · WoS 翻页、捕获及影响因子任务复核

**结论：第二页不是完全不能翻，本轮现场成功返回了不同的 50 条；但现有接口明确禁止第三页，无法按原方案覆盖全部 115 条。另确认结果页守卫可被缺失 URL 跳过、捕获就绪标记可能过早或陈旧，以及 JCR 年份和部分详情元数据无法可靠交付等问题。**

本轮仅测试、查阅与记录，没有修改业务代码、扩展或已安装技能，没有升级、重装、重置浏览器/配额/冷却，也没有向其他会话发送消息。此文可直接交给开发会话。

## 1. 对象与证据等级

- 日期：2026-11-10，北京时间。
- MCP status：**0.12.36**，源码 HEAD：`be9bbf9`，工作区开始时干净。
- 现场通过 Codex 已连接的 `mcp__wensu` 工具调用，使用既有 `E:\LiteratureEdgeProfile`。
- 离线复现运行正式安装目录 `installations/0.12.36/venv` 中的包；涉及的 service、server、WoS planner/parser 与仓库对应文件逐一比较，归一化换行后相同。磁盘中浏览器扩展的 background/actions/capture 脚本也与仓库一致。
- 扩展捕获回放执行原始 `capture.js`，使用 Node VM、模拟 DOM/fetch/定时器，不修改脚本逻辑，不请求网站。
- 35 项现有 WoS 契约及查询测试通过。这些测试明确把“第三页拒绝”“page=null”作为预期，不覆盖本轮的完整 115 条验收任务。

证据分为：**现场已观察**、**历史审计定位**、**离线确定性复现**、**仍待确认**。尤其是首次捕获失败，本轮第一页命中缓存，不能声称重新现场复现了首次冷捕获错误，也不能把离线路径推定成那次历史失败的唯一根因。

## 2. 同一检索式的现场结果

```text
TS=((ionic OR ionogel* OR IPMC OR "ion migration") AND actuator* AND (soft OR flexible OR polymer*)) AND PY=(2026)
```

| 调用 | 结果 | 本步扣额 |
|---|---|---|
| status | bridge_ready=true；无冷却；剩余 283 | 0 |
| page=1、limit=50 | total=115，50 条，cache_hit=true，page/page_count=null | 0 |
| page=2、limit=50 | **约 45.132 秒，现场成功返回 50 条**，cache_hit=false，page/page_count=null | **6** |
| page=3、limit=50 | **CHANNEL_ERROR，渠道明确只支持至第 2 页** | 0 |
| 已读取记录中 IF 最大者的 detail | 成功，从缓存返回，含摘要 1447 字符和单位信息 | 0 |
| 结束 status | bridge_ready=true；无冷却；剩余 277 | 0 |

**本轮正式额度 283 → 277，仅消耗 6 次，无自动重试。**

两批各含 50 个唯一 WoS ID，交集为 **0**，合计 **100 个唯一 ID**。其中 4 条 `impact_factor=null`，96 条有指标。115 条中仍有 15 条未覆盖，不能把 100 条中的最大值当作全部结果最大值。

已读取的 100 条中，最大返回影响因子是 **29.1，且有两篇并列**：

1. A Multifunctional Ionograsper Enabling Ion-Redistribution Proximity Sensing and Structural-Reconfiguration-Driven Bidirectional Actuation — DOI `10.1002/adma.74981`，WoS ID `WOS:001874427500001`。
2. Directional Confinement Governed Ion Transport for Efficient Actuation — DOI `10.1002/adma.75384`，WoS ID `WOS:001903275600001`。

两篇均返回 ADVANCED MATERIALS、29.1。该数值来自当前工具返回，**JCR 年份未提供，未进行外部 JCR 校验**；此处只作测试结果比较，不将其解释为 2026 JIF 或全部 115 条中的最终最高值。

尝试只读核对浏览器界面页码时，app 读取授权等待超时，没有取得页码/范围画面。因此本轮**没有人工确认当前 UI 显示的是 51–100**；能确认的是工具返回了与第一页不同的 50 个 ID。未操作浏览器按钮或绕过 MCP 读取剩余 15 条。

## 3. 原反馈逐条复核

| 原反馈 | 复核结论 |
|---|---|
| 第二页疑似不执行翻页 | **需修正表述**：代码确实有下一页点击，本轮也成功返回不同的 50 条；但每次目标页调用先重新提交检索，用户看到返回检索式页有代码依据 |
| 在检索式页刷新、重复刷新 | 存在可确定性复现的守卫缺口，见 W02；但本轮现场成功调用没有记录每次刷新 URL，不能把历史每次刷新对象都认定已核验 |
| 首次捕获无记录 | 本轮第一页命中缓存，未现场重现；离线确认“只有元数据也标为 ready”和误导性的 ParseError 文案，见 W03/W05 |
| 超时缺乏定位 | **确认**。已从审计和固定计划定位历史两次超时，公开错误却无法区分这些阶段，见 W05 |
| retryable 与技能冲突 | **确认**。工具 ActionError 超时为 false，技能仍写重试一次，见 W06；本轮未照技能重试 |
| 无可靠页码与记录范围 | **确认**。成功返回仍只有 null；也没有结果集 ID、范围或重复校验结果，见 W04 |
| 已关闭浏览器被提示扩展未连 | 合成残留 LOCK 文件可复现同类误判，见 W09；本轮未关闭用户浏览器，不能认定用户那次必由该文件导致 |

### 历史两次超时已能定位到哪个阶段

读取的是项目自己的结构化审计日志，不包含查询、页面内容或凭证。时间转换为北京时间：

- **17:13:42–17:13:51**：`goto → sleep → wait_for(timeout≈8014ms)`。结合固定计划，等待的是 `textarea#advancedSearchInputArea`，即检索式编辑框。只有 goto 一个计费动作，对应 `quota_charged=1`。
- **17:14:02–17:14:27**：`goto → sleep → wait_for → type → sleep → click → sleep → goto → sleep → wait_for(timeout≈10077ms)`。第二个 goto 是首次刷新，失败点是第一次等待 `#wensu-wos-capture[data-ready='1']`。已有 4 个计费动作，对应 `quota_charged=4`。
- **两次都没有到达下一页按钮的点击**。因此不能把这两次错误直接定位为“下一页按钮失效”。
- 本轮成功的第二页审计顺序是 `goto,type,submit click,reload,next-page click,reload,read_text`，夹有 sleep/wait_for，计费动作共 6 个。

审计本身不记录 selector、URL、request ID 或 page。本次定位依赖固定计划、动作顺序和时长，不能将其当成一般情况下足够完整的诊断机制。

## 4. 主要问题与开发定位

### W01 · [P1，任务阻塞] WoS 禁止第三页，完整 115 条验收在现有接口下不可完成

**证据：现场及代码。**

实际调用 `search(query=<原式>, channel="webofscience", limit=50, page=3)`：

```json
{
  "status": "error",
  "code": "CHANNEL_ERROR",
  "message": "the webofscience channel supports at most 2 pages per call: every page needs a scroll round to refill 50 records, and a third would exceed the kernel's 120 s plan budget",
  "retryable": false,
  "quota_charged": 0
}
```

定位：`channels/webofscience/v2026_11/plan_search.py:218`、`:250`。工具 schema、通用验证和技能说 page 1–3；WoS 渠道另行硬拒绝 3。它并非“每次调用只能前进两页、下一次还能继续第三页”，而是目标参数 page=3 被直接拒绝。当前每次调用又会重新从 advanced-search 提交，不存在另一个可继续结果集的公开接口。

**建议验收要求**：为固定查询提供能到达第三页的分段计划/结果集续取，保持既有并发、频率和计划预算限制；不要为本任务直接放宽硬限制。错误消息还残留“scroll round”说法，而当前路径已用刷新代替滚动，应同步解释。

### W02 · [P1] 提交点击缺失 URL 时，结果页守卫被跳过，确实可刷新检索式页

**证据：扩展代码 + 真实服务/计划的离线状态回放。**

1. `extension/background.js:219` 对 click 的 `sendToTab()` 设置 **2 秒 Promise.race**。内容脚本里 WoS 的 `wait_until=enabled` 本来可能等待更久。
2. 超过 2 秒就从 `:234` 返回 `ok=true, data={navigation_expected:true}`，没有 url、settled。Promise.race 并不会取消仍在执行的 click/等待。
3. `core/service.py:678` 的 `_click_landing` 只看 click 的 `data.url`；之后 sleep 已返回的真实 URL也不参与落地判断。
4. `core/service.py:175` 仅在 `landed` 非空时拒绝非结果页。**没有 URL 反而跳过检查**，随后执行 tail 的当前页刷新。

离线令点击返回上述真实协议形状，页面始终保持 advanced-search；真实 ScholarService、WoS split plans、Planner 继续执行，动作记录明确出现 `reload=true` 且 URL 为 advanced-search，最终产生与反馈同文案的 PARSE_ERROR。page=2 场景还会继续尝试下一页路径。

这证明刷新检索式页是**可达路径**，不是仅凭截图推测；但没有把它断言为历史那次首次失败的唯一原因。

**建议**：缺失 URL/状态应等待并重新确认结果路由，不能当作已满足结果页前置条件。对第一次刷新和每次下一页后的刷新分别核验目标状态；也应处理未完成内容脚本动作与后续导航的竞争。

### W03 · [P1] 捕获节点的 ready 标记不代表本页数据已完整、已更新

**证据：未改动的 capture.js 在 Node VM 中的确定性 fetch/定时器回放。**

- `capture.js:149` 的 begin 只对 primary query 清空 ready。**secondary stream 开始后仍保留 ready=1 和上一批正文**。
- 一批有效 JSON 到达、响应尚未关闭时，触发 idle timer 也会标记 ready。
- 只有 `searchInfo/RecordsFound=115`、完全没有 records 的捕获，仍能标记 ready=1。

实际输出摘要：

```json
[
  {"case":"secondary-start-keeps-ready","before":"1","during_pending_stream":"1","payload_still_previous":true},
  {"case":"ready-with-open-response","ready":"1","response_closed":false,"payload_contains_B":true},
  {"case":"metadata-only-marked-ready","ready":"1"}
]
```

定位：`capture.js:102`、`:125`、`:149`；当前闲置窗口为 2000ms，完成检查只检查尾行是否是可解析 JSON。计划只等待 ready 标记，不验证期望记录数或 generation，因此两批间隔较长、尾批晚到时，可能提前读取旧/不完整数据。

**边界**：长连接不关闭本身不一定是故障，不能简单改成“必须等 HTTP 响应结束”。真正需要的是本次结果页/请求代次、预期记录范围与已收记录的一致性。本轮现场第二页没有发生短页，故这里是离线确认的机制缺口，不是宣称这次成功页面缺记录。

### W04 · [P2] 结果范围和完整性未校验；limit 也不控制站点每页量

**证据：现场、代码及 fixture 回放。**

- 返回没有 requested_page、actual_page、起止记录号、实际站点 page_size、结果集标识、是否重复等字段。`page=null` 比伪造请求页码诚实，但仍不足以完成全量比较验收。
- parser 对不同 records 块没有按 WoS ID 去重。向 fixture 加入一个重复块后，返回 **5 条、4 个唯一 ID**，没有重复标志。
- 在 fixture 中间插入损坏 JSON 行，parser 仍成功返回题录，响应不带 malformed/partial 警告；因此客户端无法区分短页与丢行。当前 capture 的尾行检查也不能证明中间每一行有效。
- 固定随机数后，同一 page=2 的 limit=20 与 limit=50 **生成完全相同的动作计划**。没有设置 WoS 每页条数，服务只在解析后截断 `records[:limit]`。如果站点为 50 条/页，不能据 `limit=20` 假定第二次会得到第 21–40 条；本轮未额外上线验证这个变体。

定位：`parse_records.py:329`、`:376`、`:399`；`core/service.py:256`；WoS plan 未使用 limit 设置站点控件。

**建议**：将响应截断上限与站点每页量分开表达；从 UI 或流元数据取得能核验的实际页/范围，暴露稳定 WoS ID、结果集标识与完整性诊断。对重复及损坏行明确报错或返回 partial 标志，不能让“成功”被理解为本页完整。

### W05 · [P2] 不同失败阶段得到同一超时；ParseError 也混淆“未截获”和“截获但没有记录”

**证据：历史日志 + 真实 MCP 服务层的离线错误回放。**

三个离线失败点均返回：`ACTION_TIMEOUT / wait_for failed: timeout / retryable=false`：

| 失败点 | 实际等待 | quota_charged |
|---|---|---|
| 编辑框阶段 | textarea#advancedSearchInputArea | 1 |
| 首次刷新后 | capture ready | 4 |
| 下一页并刷新后 | capture ready | 6 |

公开响应都不带 selector、步骤编号、当前 route、requested_page 或捕获计数。AuditLog 只记 verb、耗时、错误码，两个 wait_for 也无法直接区分。

只含合法 searchInfo 的数据已经被截获，却仍报 `capture holds no records; the stream was not intercepted (0 unparseable line(s) dropped)`。应区分未安装/未命中捕获器、只收到元数据、仍在接收、收到不完整/损坏记录和真正无法解析。

**建议**：返回阶段和结构化计数；URL若用于诊断，应去掉 session/query 等敏感材料，保留路由类别或脱敏结果集标识即可，不需记录完整 HTML。

### W06 · [P2] 重试规则与随包技能确有冲突，且技能中存在其他过期承诺

**证据：正式工具代码、已安装技能与离线回放。**

- `server.py` 的 `_retryable` 仅对 BridgeTimeout 返回 true，ActionError 的 wait_for timeout 返回 false。
- `skills/scholar-search/SKILL.md:318` 仍写此类 ActionError “重试一次”。下一段还写超时响应“不报告扣了多少”，而实际明确返回 quota_charged。
- 同一技能将 page 描述为 1–3，未说明 WoS 只支持到 2；将 IF 称为“JCR 当年值”，但公共记录未带年份；详情技能还仅说明 CNKI，和实际工具双渠道能力不一致。

**建议**：先定义哪些失败允许重试、是否可能重复提交、消耗如何计算，再让工具字段、技能与文档保持一致。风控 blocked 始终禁止重试。**本轮遵循返回值和全局规则，没有按技能自动重试。**

### W07 · [P2] JCR 年份在 parser 中被丢弃，无法证明影响因子比较基准一致

**证据：fixture 含明确 Year，真实 parser 输出对照。**

`_impact_factors` 只取 ImpactFactor，Record 只保存浮点 impact_factor，没有 JCR 年份、版本或五年 IF 字段。fixture 的 JCR entry 自带 `Year=2025`；将其改为 2020、保持 IF 不变后，公共 Record 除抓取时间外**完全相同**。

定位：`parse_records.py:240`、`:296`、`core/contracts.py` 的 Record 字段。

**影响**：论文出版年 2026 不等于指标年份 2026；当前无法满足“报告缺失数和 JCR 年份”的验收要求。本轮只能统计已读 100 条中的 4 条缺失，不能补造未读 15 条的缺失数或指标年份。

### W08 · [P2，新边界] WoS 记录没有摘要时，搜索成功后 detail 反而不可用

**证据：真实服务、真实 WoS parser 的离线 fixture 回放。**

`core/service.py:235` 只有 `record.url and record.abstract` 才播种详情缓存。如果 WoS 文献没有摘要，连已经取得的作者、DOI、卷期页等元数据也不播种；下一次 detail 缓存未命中后调用 WoS 的 plan_detail，而该方法未实现。

离线搜索正常返回已知 DOI、卷期页和 URL 的题录，随后的 detail 返回：

```json
{"status":"error","code":"CHANNEL_ERROR","message":"webofscience channel does not implement detail yet","retryable":false,"quota_charged":0}
```

**建议**：缓存可用的 WoS 全记录与“是否有摘要”应分开，摘要缺失不能让已经取得的其余详情无法取用。应说明缓存缺失/过期时的支持边界。用户所述带摘要记录的缓存 detail 正常，本轮也确认正常，不与该结果矛盾。

### W09 · [P2] 浏览器运行判断只看 LOCK 文件存在，残留文件会误导恢复操作

**证据：不启动任何浏览器的合成残留文件回放。**

在隔离 profile 中只创建 `Default/LOCK`，不启动进程：`profile_is_running=true`；status 的诊断仍为“browser is using the profile, but the extension is not connected”，next_action=reload_extension、command=null。

定位：`core/browser.py:245` 直接调用 `.exists()`；`bootstrap.py` 据此选择恢复建议。

这能复现与用户所述相同的错误方向，但不能证明用户那次正常关闭后留下的状态必然如此。本轮没有关闭、重启、结束用户浏览器，也没有清理正式 profile 的 LOCK。

**建议**：利用可验证的进程/profile 存活信息或锁占用状态，而不是文件是否存在；无法确认时输出 unknown，提供明确的专用 profile 启动建议，避免要求用户对不存在的窗口重新加载扩展。

## 5. 推荐交给开发会话的验收重点

1. **先解决第 3 页的能力/契约缺口**，再要求固定查询的 115 条完整性测试。不能通过重复调用 page=2 代替第三页。
2. 对提交后的路由状态作独立确认，覆盖 click 超过 2 秒、缺失 URL、延迟 SPA 路由、页面仍在检索式页等时序。
3. 捕获回放至少包含：只含 searchInfo、批次间隔超过 2 秒、旧 ready 未清理、末批延迟、重复记录块、中间损坏行。
4. 连续读取 50/50/15 后，比较 115 个稳定 WoS ID 的唯一性与记录范围，而不是只比返回数量。
5. 保留 JCR Year，报告实际覆盖数、有效/缺失指标数和并列最大者；另外覆盖无摘要 WoS 文献的 detail。
6. 将各阶段超时与恢复/重试规则纳入公开 MCP 返回测试，安装技能也用同一规则验收。

## 6. 证据位置与复现方式

证据根目录：

`C:\Users\xuhui\.codex\visualizations\2026\11\09\01a1c01c-2472-7ab3-9017-c2ceddfc1dd1\wos-review-0.12.36-2026-11-10`

- `initial-status.json`、`page1.json`、`page2.json`、`page3.json`、`best-detail.json`、`final-status.json`：真实 MCP 返回。
- `comparison.json`：两批 ID 的唯一性、交集、缺失 IF、并列最大值。
- `today-wos-audit.json`：本机当日 WoS 结构化审计，含用户前序失败及本轮成功调用。
- `offline.py`、`offline-results.jsonl`、`*-actions.json`：隔离服务/计划/parser/LOCK 回放。
- `capture-probe.js`、`capture-probe.json`：原始扩展捕获逻辑的模拟时序证据。
- `pytest-wos.log`：35 项现有 WoS 测试通过。

离线复现：使用正式 0.12.36 解释器运行 `offline.py`，再执行 `node capture-probe.js`。重复 Python 回放应使用新的证据目录，防止既有 fixture 缓存改变前置状态。除报告之外没有修改仓库文件；全部模拟状态、缓存和额度均在审查目录内，与正式配额和浏览器分离。
