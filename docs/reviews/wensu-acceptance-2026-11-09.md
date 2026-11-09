# 文溯 MCP 独立测试审查 · 2026-11-09

**一句话总评：现有浏览器环境下，单客户端的知网、WoS 题录检索可以完成实际任务；0.12.30 尚不适合按当前说明交付新用户，须先修复扩展打包缺失、分段检索结果串线和批量风控误报成功。**

本次依据 `D:\Python\DeepSeek\DateWork\wensu-acceptance-plan.md` 执行，并审查仓库 AGENTS.md、渠道、内核、native host、扩展、MCP 服务和发行配置。仅测试题录；未下载全文、未向第三方文献库入库、未制造线上验证码、未重置配额或冷却。生产代码未修改。

## 1. 范围与证据可信度

| 项目 | 本次范围 |
|---|---|
| 源码 | `9c78abf407b629a076421b55df2ea01ef9ddc7c1`，开始审查时工作区干净 |
| 已安装包 | wensu **0.12.30**，系统 Python **3.14.5** |
| 独立发行包 | 从 PyPI 下载固定版本 0.12.30，`pip install --no-deps --target <隔离目录>`，复用本机已安装的依赖；不是全新 Windows/全依赖重装 |
| 本地构建 | 用 Hatchling 从本次源码构建 wheel，核对扩展文件与两个渠道 |
| 线上链路 | 现有专用 Edge → 现有扩展/native host → CLI 和真正的 MCP stdio 客户端 |
| HTTP | 独立运行目录、本机回环端口，实际初始化、列工具、调用 status；未通过 HTTP 访问学术站点 |
| 并发/风控异常 | 合成数据、离线适配器和真实服务/计划执行层；不在真实站点并发或触发风控 |
| Codex 等客户端 | 验证标准 MCP SDK 客户端的 stdio/HTTP 协议；未修改 Codex、Claude、Cursor 的实际配置，未分别验证这些产品的界面与审批行为 |
| UI 对照 | 浏览器窗口可以枚举，但控制工具因不能可靠确认当前网址而停止；未完成文章页面逐字段人工对照 |

原始调用、检查日志、隔离安装及复现程序保存在以下审查运行目录，未写进仓库：

`C:\Users\xuhui\.codex\visualizations\2026\11\09\01a1bfaf-756c-7de0-a7ea-f46f1ea4fa36\wensu-audit-runtime`

主要证据文件：`observations.jsonl`、`mcp-tools.json`、`pytest-elevated.log`、`mypy.log`、`format.log`、`downloads/`、`built/`、`clean-package/`、`clean-home/`。原始检索输出含站点返回的长链接；本报告不复制链接签名、令牌或会话材料。

## 2. 问题清单（按级别排序）

### A01 · 发行 wheel 遗漏扩展清单必需的 capture.js

**级别**：阻塞（首次安装链路）

**现象**：PyPI 0.12.30 与本地构建的 wheel 均没有 `scholar_search/assets/extension/content/capture.js`，但打包的扩展 manifest 引用了该文件。隔离导出后仍缺失。本机长期使用的扩展目录恰好有该文件，已有环境的线上成功无法证明发行包完整。

**复现**：
1. `python -m pip download --no-deps wensu==0.12.30 --dest <临时目录>`。
2. 解压或隔离安装 wheel。
3. 执行 `wensu setup --browser edge --no-host`。
4. 遍历 `extension/manifest.json` 的 `content_scripts[].js`，检查对应文件是否存在。

**实际输出**：
```json
{"expected":["content/actions.js","content/actions.js","content/capture.js"],"missing":["content/capture.js"]}
```

**预期**：首次安装导出的扩展包含 manifest 引用的全部资源。来自验收方案第 2 节、README 快速开始及 WoS 渠道的捕获设计。

**影响**：干净安装得到不完整的扩展，无法通过首次加载验收；WoS 的流捕获资源确定缺失。浏览器具体加载错误文本未采集，不把旧环境测试通过计为首次安装通过。

**定位/建议**：`pyproject.toml:67` 附近只列出 `actions.js`。补齐 `capture.js`，并让发行检查遍历 manifest 中所有资源，而不仅检查两个渠道 manifest 是否在 wheel 中。

发行包 SHA-256：`b2077d26061b83283022e5b94c334fae2bde3a451cc588ac86ca7708d814b244`。

### A02 · 分段检索之间释放浏览器锁，两个请求会收到同一份结果

**级别**：严重

**现象**：服务把 WoS 检索拆成提交和读取两段，每段各自持锁；段与段之间没有整个检索的所有权。离线受控交错中，A 提交后暂停，B 完成提交，随后 A 读取到了 B 的结果，并按 A 的缓存键保存。

**复现**：
1. 使用两个服务实例，配额与计划锁目录相同，模拟共享同一个浏览器页面。
2. 使用真实 `ScholarService.search` 和 `Planner.run`，合成渠道实现与 WoS 相同的 `plan_search_split` 接口。
3. 在 A 的提交段完成并释放锁后暂停 A，让 B 完成提交段。
4. 继续两个请求的读取段。没有访问真实站点，也没有关闭实际限速逻辑；测试时钟为虚拟时钟。

**实际输出**：
```json
{"expected":{"A":["QUERY_A"],"B":["QUERY_B"]},"actual":{"B":["QUERY_B"],"A":["QUERY_B"]}}
```

**预期**：每个请求读取与自身检索式对应的结果。依据项目宣称的跨进程串行化，以及多个 agent 客户端可能共享同一浏览器的正常使用方式。

**影响**：可能把另一主题的题录当成本次结果，污染检索缓存；这是静默的数据正确性问题。单个 skill 建议串行调用，不能约束另一客户端同时工作。

**定位/建议**：`core/service.py:98`、`core/service.py:124`，`core/planner.py:34`。锁的范围应覆盖整个依赖浏览器状态的检索事务，或为请求提供真正隔离的标签页与结果身份验证。此项为离线确定性复现，未宣称已在线上制造串线。

### A03 · detail_many 把 blocked 计为成功并继续遍历

**级别**：严重

**现象**：`detail` 将 `RiskBlocked` 转成 `status: blocked` 后，批量接口仅判断 `status == error`，因此把风控对象放入成功的 `record`，并继续下一条。

**复现**：以离线合成服务令每次 `detail` 抛出 `RiskBlocked`，经真实 FastMCP 工具调用 `detail_many(urls=[合成URL1, 合成URL2])`。

**实际输出**（省略重复字段）：
```json
{
  "results":[
    {"ok":true,"record":{"status":"blocked","code":"RISK_BLOCKED","retryable":false}},
    {"ok":true,"record":{"status":"blocked","code":"RISK_BLOCKED","retryable":false}}
  ],
  "ok_count":2,
  "failed_count":0
}
```

**预期**：风控应终止当前批次，明确返回 blocked，不能增加成功计数。依据 AGENTS.md 遇风控即停规则。

**影响**：agent 或自动流程可能把整批判为成功，未向用户报告需停止。真实服务下层仍有冷却检查，本复现没有证明后续网络动作绕过了冷却；缺陷是批量返回值和控制流错误。

**定位/建议**：`server.py:446`。先处理 blocked 并终止批次，再分别处理普通失败与成功；补充批量接口级的风控回放测试。

### A04 · 合法字段投影遇到零结果会报“未知字段”

**级别**：一般

**现象**：字段集合取自第一条记录；没有记录时，任何合法字段也被视为未知。

**复现**：
```powershell
wensu search "文溯验收零命中zqvkjx20261109" --channel cnki --limit 1
wensu search "文溯验收零命中zqvkjx20261109" --channel cnki --limit 1 --field title
```
第一条实测为正常零结果；第二条命中其缓存，没有额外网络消耗。

**实际输出**：第一条 `total: 0`、`empty_reason: no_match`；第二条退出码 1，并显示 traceback，末行为：
```text
ValueError: unknown field(s): title. available:
```

**预期**：仍返回 `records: []`、零结果诊断及额度信息。依据字段精简与零结果均为正常功能。

**影响**：agent 最常用的“小响应探测”会把无文献误判成工具故障；同样影响年份过滤后为空的页面。

**定位/建议**：`server.py:86`。从固定 Record/schema 获取合法字段，而不是从结果实例推导。

### A05 · 拼错字段在检索之后才验证，冷请求会先扣额度；CLI 还泄露 traceback

**级别**：一般

**现象**：`fields=["titel"]` 的拼写错误直到检索执行、解析及缓存完成后才发现。CLI 的 `_page_payload` 在处理 ValueError 的 try 块外，输出 traceback。

**复现**：
1. 线上对已缓存的 `柔性驱动器` 查询使用 `--field titel`：退出码 1，输出 traceback；本次由于缓存，消耗 0。
2. 离线使用真实服务与 fixture 进行一个未缓存查询，再经真实 MCP 工具传 `fields=["titel"]`：比较配额前后。

**实际输出**（离线）：
```json
{"error_type":"ToolError","quota_before":300,"quota_after":299}
```
错误原文以 `unknown field(s): titel. available: abstract, authors, ...` 结尾。线上 traceback 位于 `cli.py:425` → `server.py:_project`，完整堆栈保存在运行目录。

**预期**：本地可判定的参数错误在任何浏览器动作之前拒绝，消耗 0；CLI 返回简短可操作信息。依据验收方案第 5 节。

**影响**：agent 的一次拼写错误可能花掉整次真实查询的额度与等待时间；参数错误和程序错误表现不一致。

**定位/建议**：`server.py:342`、`cli.py:425`。进入 service 前验证投影字段，统一 CLI/MCP 参数错误返回。

### A06 · WoS DOI 解析附带默认五年限制，旧论文无法按 DOI 解析

**级别**：一般

**现象**：`detail_by_doi` 构造 `DO=(...)` 查询时不传年份；WoS 查询构造器随即增加最近五年的限制。`detail` 接口没有用于取消该范围的参数。

**复现**：离线执行与 DOI 解析相同的查询构造：
```python
build(SearchQuery(text='DO=("10.0000/synthetic.2010")', channel='webofscience'))
```

**实际输出**：
```text
(DO=("10.0000/synthetic.2010")) AND PY=(2022-2026)
```

**预期**：已知 DOI 是唯一定位，不应附加未请求的时间窗。依据 `detail` 工具说明支持裸 DOI。

**影响**：实际出版年份在默认范围之外的论文会被额外条件排除，返回“找不到记录”。未为证明此问题额外在线查询旧 DOI；排除行为由生成表达式直接确定。

**定位/建议**：`core/service.py:263`、WoS `query.py:125`。DOI 精确解析应显式禁用默认时间窗，且应核对返回 DOI 与目标 DOI。

### A07 · WoS 将 page_count 当成题录页码导出

**级别**：一般

**现象**：当 `pub_info.begin/end` 缺失时，`_pages` 返回 `page_count`。真实结果已有两条 `pages: "9"`；离线合成输入进一步确认页数被映射进了页码字段。

**复现**：用 WoS parser 回放合成题录，`pub_info` 包含 `page_count: 9`，不提供 begin/end。

**实际输出**：
```json
{"input":{"pubyear":"2020","page_count":9,"article_number":"116038"},"output":{"pages":"9"}}
```

**预期**：总页数不能冒充起止页码；没有页码证据时返回 null，电子文章编号按独立语义处理。

**影响**：RIS/EndNote 可得到错误的页码定位。未完成浏览器逐字段对照，因此不据此断言所有返回 `9` 的真实论文应是什么页码；确定的是 parser 的字段语义错误。

**定位/建议**：WoS `parse_records.py:130–138`。去掉页数到页码的回退，必要时增加独立的页数/电子定位字段。

### A08 · 实际 tools/list 没有采用维护中的约束 schema

**级别**：一般

**现象**：`schemas/tools.json` 有 page/limit 上下界、投影字段枚举与 `additionalProperties: false`，实际 FastMCP 自动生成的 schema 没有这些约束，输出 schema 仅为泛型 object。

**复现**：实际 stdio `initialize` → `tools/list`，对比 schema 文件；调用 `status({brief:true,unexpected_flag:true})`。

**实际输出**：实际 `page` 为 `{"default":1,"title":"Page","type":"integer"}`；`limit` 无 minimum/maximum；未知参数被静默忽略，status 正常返回。`limit:999`、`page:4` 仍会在函数内部被拒绝，没有发生站点访问。

**预期**：agent 发现的 schema 应直接包含有效边界，实际行为应与维护的契约一致。

**影响**：仅安装 MCP、没有额外 skill 的客户端无法从字段 schema 获得关键约束；拼错参数可能被静默忽略，也更容易生成不必要的失败调用。

**定位/建议**：`server.py:243` 及工具签名，`schemas/tools.json`。使用带范围与字段枚举的参数模型，并添加针对真实 `tools/list` 的契约测试。

### A09 · 接入文档会把正常的五工具安装判为错误

**级别**：一般

**现象**：`docs/integration/codex.md:85` 写“可用工具只有四个”，还要求多出工具按安装错误处理；实际有五个。README 工具表也少了 `detail_many`，当前版本写为 0.12.9。`search` 工具说明还泛称检索后详情来自缓存，实测 CNKI 列表后的首篇详情需要额外 1 次网络动作。

**复现**：比较 `tools/list`、上述文档、`wensu --version` 与本报告额度账目。

**实际输出**：
```text
search, detail, detail_many, export, status
wensu 0.12.30
CNKI first detail: quota_charged=1
```

**预期**：接入说明、工具自描述与实际行为一致。来自验收方案第 6 节。

**影响**：照文档接入的 agent 可能主动停止一个正常安装，或错误估计 CNKI 详情的配额；README 的版本核对也失效。

**建议**：文档从真实工具定义生成；按渠道说明详情缓存能力。默认 setup 不会自动修改所有 agent 的技能目录；显式 `--skills-dir` 安装四份 skill 已验证，应在接入流程中明确说明。

### A10 · 格式检查不通过，而 release-check 没有覆盖格式检查

**级别**：一般（开发验收）

**现象**：仓库所用 Ruff 0.17.1 的只读格式检查退出码为 1；普通 lint 通过。发布脚本只运行 `ruff check`。

**复现**：
```powershell
.venv/Scripts/ruff.exe check --no-cache src tests scripts
.venv/Scripts/ruff.exe format --check --no-cache src tests scripts
```

**实际输出**：
```text
All checks passed!
15 files would be reformatted, 51 files already formatted
```

**预期**：满足 AGENTS.md 的 Ruff 格式要求；“发布检查全绿”至少不能遗漏这一要求。

**影响**：当前源码不能通过规定的格式检查。没有为了审查自动格式化或改动生产代码。

**建议**：格式化后在 release-check/CI 纳入 `ruff format --check`。pre-commit 带自动修复，本次未运行会修改源码的钩子，也没有提交。

### A11 · Windows 导出报告的 bytes 小于实际文件大小

**级别**：一般（返回值准确性）

**现象**：工具返回 UTF-8 字符串的字节数，但 Windows 写文件会把换行转换为 CRLF。

**复现**：导出本次五条 CNKI 结果，比较响应 `bytes` 与输出文件的 `stat().st_size`。

**实际输出**：

| 格式 | 返回 bytes | 实际文件字节 |
|---|---:|---:|
| RIS | 2004 | 2054 |
| EndNote | 1892 | 1937 |
| Markdown | 1794 | 1818 |
| CSV | 1890 | 1896 |

**预期**：`written: true` 响应的 bytes 应为实际落盘大小。

**影响**：依赖该字段核对文件大小的调用方得到错误信息；本次文件均存在且可以读取，未发现由换行造成的题录内容损坏。

**定位/建议**：`server.py` 与 CLI 的 export 写文件分支。写入后读取实际大小，或显式固定换行编码。

### A12 · MCP 握手版本显示 SDK 版本，且没有工具安全注解

**级别**：建议

**现象**：实际初始化的 `serverInfo.version` 为 **1.30.0**，与安装的 MCP SDK 版本一致；`status.version` 才是 **0.12.30**。五个工具的 annotations 均为 null。

**复现**：标准 MCP 客户端执行 `initialize`、`tools/list`、`status`。

**实际输出**：
```json
{"serverInfo":{"name":"wensu","version":"1.30.0"}}
```

**预期**：客户端显示文溯实际版本，并能区分只读站点检索与可能写本地文件的 export。

**影响**：客户端诊断和用户排障可能混淆组件版本；缺少 readOnlyHint 等提示。具体客户端如何审批取决于其实现，本次未验证，不能据此声称出现了越权调用。

**建议**：显式设置服务器发行版本；按实际能力添加工具注解，含 out_path 的 export 不宜笼统标为只读文件系统。

## 3. 验收方案逐项记录

| 方案项 | 观察与结论 |
|---|---|
| 1 环境 | Windows 10 19045，Python 3.14.5，Edge 156.0.4314.50；此前已安装 0.12.30 |
| 2 安装 | 固定版 PyPI wheel 可下载、可隔离安装；pip 提示原环境存在无效分发 `~ensu`、`~v`，不是隔离包安装失败 |
| 2.1 setup | 隔离 HOME 下 `setup --browser edge --no-host --skills-dir <隔离目录>` 成功，退出 0，生成 browser.json，安装四份 skill；未覆盖现有 HKCU 原生宿主注册 |
| 2.2 扩展 | ID 固定为 `gmaimbocfjkolcpljeekjcomakipoaph`；实际线上复用旧扩展；全新导出发现 A01，未完成首次浏览器加载 |
| 3 连接 | 初始 bridge_ready=false。受限启动返回 exit 21 的明确目录不可写提示；允许访问专用 profile 后 `browser start` 在约 2.38 秒内完成且 bridge_ready=true |
| 3 诊断 | 初始无浏览器可见窗口时 status 因残留 Default/LOCK 判断“profile 正在使用，需 reload_extension”；启动后恢复。这个提示不够可靠，未把它当成真正有窗口运行的证据 |
| 4.1 状态 | 线上连接后的 brief 输出 178 UTF-8 字节；full 有渠道、能力、费用、配额状态路径、桥接修复提示。初始 full 含更长的未连接诊断，不能与连接后的 brief 做同状态压缩率比较 |
| 4.2 中文 | `柔性驱动器`，limit 5：5 条，total 363，page 1，page_count 19，约 11.307 秒，输出 4380 字节 |
| 4.3 WoS | `TS=(ionic AND actuator)`，limit 5：5 条，total 791，约 19.656 秒；实际式为 `(TS=(ionic AND actuator)) AND PY=(2022-2026)`；page/page_count 均为 null |
| 4.4 字段精简 | CNKI 实际仅保留 title/year/url；输出从 4380 降到 2010 字节，减少约 54%；本次缓存命中，扣 0，不代表首次投影查询免费 |
| 4.5 详情 | CNKI 首条的摘要开关正确；无摘要 1122 字节，有摘要 1678 字节。首次 URL 详情扣 1，随后缓存详情扣 0。返回 DOI、43(11)、21–26、单位及关键词；未完成页面人工对照 |
| 4.5 DOI | 同篇裸 DOI 调用成功，约 1.305 秒、扣 0；此环境已有相关缓存，不能证明冷 DOI 解析免费。CNKI URL 230 字符，WoS URL 75 字符 |
| 4.6 批量 | WoS 三条详情 0.019 秒、全部命中缓存、扣 0；CNKI 三条批量 6.282 秒，1 条缓存 + 2 条现场，扣 2；随后逐条共约 0.05 秒、扣 0。缓存冷热不同，不能据此比较批量与逐条性能优劣 |
| 4.7 导出 | CLI 的 RIS/EndNote/Markdown/CSV 均生成文件；MCP 内联 RIS 和 out_path Markdown 也成功；未执行向 Zotero/EndNote 的自动导入 |
| 5 桥接不可用 | 隔离 HOME 无 host，search 返回“no live native host found”，额度仍 300；没有关闭用户浏览器来制造断连 |
| 5 零结果 | 随机合成词：total 0、empty_reason=no_match，23.198 秒、扣 3；加字段投影时发生 A04 |
| 5 年份过滤 | CNKI 限定 1900：records=[]、total=363、dropped_year=20、year_scope=page、empty_reason=all_dropped_by_year；扣 3。20 是抓取页面的条数，不是 limit 5 |
| 5 参数错误 | CLI limit999 退出 2，单行说明范围；MCP limit999/page4 为 isError=true，均不耗网络额度；拼错字段见 A05 |
| 5 受限写入 | browser start 可明确指出 profile 目录不可写；本机旧虚拟环境的测试工具也受写权限干扰，详见静态检查记录 |
| 6 自描述 | 实际五工具；search 描述 2438 字符，输入 schema 序列化约 1834 字节；detail 990 字符，detail_many 660，export 469，status 387。search 描述混有旧名字/兼容历史、价格、长篇解释；建议将参数规则移入字段 schema，并修正 A08/A09 |

检索记录的全部键（两渠道相同，19 个）：

`channel, title, authors, institution, source, year, volume, issue, pages, doi, abstract, keywords, citations, downloads, impact_factor, url, fetched_at, doc_type, doc_type_unified`。

CNKI 五条列表记录的 institution/volume/issue/pages/doi/abstract/citations/impact_factor/fetched_at 均为 null；1 条 downloads 为 null；1 条学位论文 authors 为空列表。列表到详情后可补全多项，不能把列表缺省值等同站点无数据。WoS 五条均有 DOI、单位和卷；2 条 issue、1 条 citations、1 条 impact_factor 为 null；abstract 因默认关闭而为 null。

## 4. 额度账目

真实环境：**168 → 152，共 16 个网络动作**。isolated/fixture 的 300→299 等计数仅用于离线复现，不计入实际消费。未调整现有配额和冷却文件。

| 调用 | 耗时（秒） | 消耗 | 余额 |
|---|---:|---:|---:|
| 初始 status / browser start / status | — | 0 | 168 |
| CNKI search 柔性驱动器 limit5 | 11.307 | 3 | 165 |
| 同查询 title/year 投影 | 1.238 | 0 | 165 |
| CNKI 首条 URL detail | 2.979 | 1 | 164 |
| 同条 detail --abstract | 1.238 | 0 | 164 |
| CLI 四种 export | 每次约 0.2 | 0 | 164 |
| CNKI 同主题 year=1900 | 10.324 | 3 | 161 |
| CLI limit999 / 拼错字段的缓存查询 | 0.225 / 1.344 | 0 | 161 |
| CNKI 合成零结果查询 | 23.198 | 3 | 158 |
| MCP 初始化、列工具、状态、参数及外域 URL 拒绝 | — | 0 | 158 |
| MCP WoS search limit5 | 19.656 | 4 | 154 |
| WoS detail_many 三篇（缓存） | 0.019 | 0 | 154 |
| CNKI 同篇 DOI detail（现有缓存） | 1.305 | 0 | 154 |
| CNKI 零结果缓存 + title 投影（报错） | 1.304 | 0 | 154 |
| CNKI detail_many 三篇（两篇未缓存） | 6.282 | 2 | 152 |
| 同三篇逐条 detail（缓存） | 0.010 / 0.030 / 0.010 | 0 | 152 |
| MCP 两种 export / 最终 status | — | 0 | 152 |

线上未触发验证码、登录拦截、403 或冷却。上述线上失败调用没有新增额度消耗；离线证明“冷查询字段错误”有先扣额度的缺陷，不能把这一费用混入真实账目。

## 5. 静态检查、构建与安全审查

| 检查 | 结果 |
|---|---|
| 仓库完整 pytest | **210 项通过**；系统 Python 3.14.5、禁用第三方插件自动加载、关闭 pytest cache、临时文件放隔离 HOME |
| Ruff check | **通过**（仓库 Ruff 0.17.1；系统 Ruff 0.16.8 也通过） |
| Ruff format --check | **失败**，15 文件需格式化，详见 A10 |
| mypy --strict src | **通过**，44 个源文件；隔离安装的 mypy 2.4.1 |
| check-versions.py | **通过**，五个版本位置均为 0.12.30 |
| CHANGELOG | 包含 0.12.30 条目 |
| check-plan.py | **通过**，两渠道各四种计划均通过内核与 host 校验 |
| 本地 wheel 构建 | **成功**，两个渠道都存在；扩展文件完整性失败 A01 |
| 项目 release-check.py 原样执行 | **未全绿**：版本/CHANGELOG/计划通过；允许权限后的 lint 通过；旧 .venv 的 Python 3.12.13 无法正常使用临时目录，tests/types/build 失败。上述三类工作改用系统 Python/隔离工具独立完成；没有将环境故障当成源码测试失败，也没有声称原始发布检查已通过 |

已执行的主要命令：

```powershell
python scripts/release-check.py
python -m pytest -q -p no:cacheprovider --basetemp <SCHOLAR_SEARCH_HOME>/pytest314
.venv/Scripts/ruff.exe check --no-cache src tests scripts
.venv/Scripts/ruff.exe format --check --no-cache src tests scripts
python -m mypy --strict --cache-dir <隔离目录>/mypy-cache src
python scripts/check-versions.py
python scripts/check-plan.py
python -m hatchling build -t wheel -d <隔离目录>/built
```

pytest/mypy/Hatchling 使用源码路径，未用已安装包冒充源码测试。MCP 线上调用使用实际安装的 0.12.30。只审查和运行现有代码，没有发版、提交或推送。

安全边界方面：

- 检索/详情未发现全文下载或第三方参考文献库写入接口；扩展权限为 nativeMessaging/tabs，无 downloads/debugger。
- 内核和 host 均校验九个动作与域名，离线契约/风险/策略测试通过；外域详情实际返回 UNKNOWN_CHANNEL，消耗 0。
- 本机 HTTP 实测：无 token **401**、错误 token **401**、非回环 Host **403**；正确认证后初始化、发现五工具和 status 成功。
- 审查时间范围内真实 audit 日志仅含 ts/event/channel/purpose/verb/ok/duration_ms/error 等结构字段，未发现完整 HTML、Cookie 或账号字段；未把凭证/令牌复制到本报告。
- native host 的本机同用户信任边界及宿主不独立限速已在 ADR 0012 登记，本次没有重复将该接受风险列作新严重漏洞。
- 并发隔离与批量 blocked 处理仍有 A02/A03，不能用底层策略测试通过来替代请求级验证。

## 6. 自由探索：能否支持一次真实选题准备

任务：为柔性/离子驱动器研究准备一个可追踪的中英文候选清单，并从英文结果中选择三篇不同方向的论文读取摘要。

实际路径：查状态 → 知网检索五条 → 首篇详情/摘要 → WoS 检索五条 → 三篇批量摘要 → 文本导出。英文候选中选取了：

| 方向 | 论文（题名缩写） | DOI |
|---|---|---|
| 透明低电压凝胶 | High-performance transparent hybrid (ionic and dielectric) gel actuator system… | 10.1039/d4ma00143e |
| 纤维素离子软驱动器 | High-performance nano-biocomposite ionic soft actuators… | 10.1002/pc.27146 |
| 前馈控制提速 | Accelerating electro-ionic soft actuators by feedforward control… | 10.1117/12.3010552 |

这三篇是本次返回页面中的方向覆盖选择，**不是全库最相关三篇或系统综述结论**。工具确实支持检索后按需补摘要，WoS 三篇摘要均从缓存取得。题录页码存在 A07，正式引用前需要核实。

起初连接不可用，按工具命令启动专用 profile 后恢复；协议和 CLI 正常路径没有长期卡住。未发生线上风险信号，没有为同一失败请求反复访问站点。若优先重设计一个环节，应把浏览器所有权提升到完整请求级，避免正确的检索式收到另一请求的数据；首次安装则应先保证包内资源自检通过。

## 7. 实际有帮助的设计

1. **默认不拉摘要、按需从缓存补全文摘**：WoS 三篇详情耗时约 0.019 秒且零网络动作；CNKI 详情也保留完整缓存，再切换摘要开关不需要重访。
2. **字段投影保留 url 与额度诊断**：本次列表体积减少约 54%，仍能继续详情流程；空结果处理需修复 A04。
3. **total / dropped_year / empty_reason / query_effective**：实测能分辨真正无结果与页面筛选为空，也能看见 WoS 自动加了五年范围。
4. **桥接预检查不乱扣额度**：隔离环境缺少 host 时余额保持 300；status 给出专用 profile 和后续命令，受限启动也有明确错误说明。
5. **HTTP 鉴权与域名拒绝有实际效果**：验证失败的请求被拒绝，测试不需要动学术网站。
6. **文本导出可用**：四种格式可直接保存，用户可自行手动导入参考文献软件，符合项目边界。

## 8. 环境与输出附录

时间范围约为 **2026-11-09 17:40–17:59（Asia/Shanghai）**。本附录对长输出仅保留与验收有关的部分，截断均作说明。

```text
python --version
Python 3.14.5

pip show wensu
WARNING: Ignoring invalid distribution ~ensu (D:\Python\Python314\Lib\site-packages)
WARNING: Ignoring invalid distribution ~v (D:\Python\Python314\Lib\site-packages)
Name: wensu
Version: 0.12.30
Location: D:\Python\Python314\Lib\site-packages
Requires: beautifulsoup4, lxml, mcp, packaging, uvicorn
[截断：许可正文及空字段；终端中的中文包简介出现编码乱码]

wensu --version
wensu 0.12.30
```

现有 `browser.json`：

```json
{
  "browser": "edge",
  "executable": "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "profile_dir": "E:\\LiteratureEdgeProfile",
  "extension_dir": "C:\\Users\\xuhui\\AppData\\Local\\scholar-search\\browser\\extension",
  "extension_id": "gmaimbocfjkolcpljeekjcomakipoaph"
}
```

受限运行与正常启动输出：

```text
wensu browser start
wensu: edge exited immediately with code 21; it could not use E:\LiteratureEdgeProfile.
Chromium exit code 21 means the profile directory is not writable — check permissions or sandbox mounts for that path.
exit: 1

[允许访问现有专用 profile 后]
started edge (pid 18684) with profile E:\LiteratureEdgeProfile
if the toolbar icon is missing, load the unpacked extension once:
  chrome://extensions -> Load unpacked -> C:\Users\xuhui\AppData\Local\scholar-search\browser\extension
exit: 0
```

最终 brief status：

```json
{
  "version":"0.12.30",
  "bridge_ready":true,
  "bridge_last_seen":"2026-11-09 17:43:29",
  "bridge_next_action":null,
  "quota_remaining":152,
  "cooldown_until":null
}
```

完整 status 的静态部分：渠道为 cnki/webofscience；bridge_protocol=1；搜索估价 cnki=3、WoS=4；detail_cached=0、cnki detail_live=1。配额路径为 `%LOCALAPPDATA%\scholar-search\state\quota.json`，桥接路径为 `%LOCALAPPDATA%\scholar-search\host\bridge.json`。原始 full 输出未原样重复，详见前述终端观察与服务源码。

原运行目录深度 1 清单（以 `%LOCALAPPDATA%\scholar-search` 为根，已省略重复根路径）：

```text
audit/
  audit.jsonl
browser/
  extension/
  extension.bak-0.4.2/
  native-host/
  schemas/
cache/
  cache.sqlite3
host/
  hosts/
  logs/
logs/
profiles/
  edge/
state/
  plan.lock
  quota.json
  quota.lock
tmp/
browser.json
```

初始 host.log 尾部摘录（20 行中的最后 4 行，其余为同类历史启动/断开事件；未包含端点令牌）：

```text
2026-11-09 17:28:23 extension channel closed; shutting down
2026-11-09 17:28:34 start pid=21244 cwd=C:\Users\xuhui\AppData\Local\scholar-search\browser\native-host
2026-11-09 17:28:34 ready port=4778 endpoint=C:\Users\xuhui\AppData\Local\scholar-search\host\bridge.json
2026-11-09 17:40:29 extension channel closed; shutting down
```

未完成项应保留在后续验收：修复 wheel 后在干净浏览器加载扩展、完整 native-host 注册安装、实际 Codex/Claude/Cursor 客户端发现与审批、浏览器页面题录逐字段对照，以及修复 A02/A03 后的请求级回归。
