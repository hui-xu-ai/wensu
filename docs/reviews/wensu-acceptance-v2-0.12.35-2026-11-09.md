# wensu 0.12.35 · v2 矩阵验收报告

**一句话总评：单浏览器的安装、连接、检索与导出主流程可以走通，上轮四项具体复现已修复；混合无标签旧宿主时仍会放行两个同名宿主的歧义，连接不可用的可重试提示也需要修正。**

依据：`D:\Python\DeepSeek\DateWork\wensu-acceptance-plan-v2.md`。日期：2026-11-09，北京时间。源码 HEAD：`e4bc7a8944f467a61bb240a1716aecc1c204cb98`，开始时工作区干净。实际测试对象为重新下载、安装的 GitHub **0.12.35 wheel**；未修改业务代码，没有提交或发布版本。

## 1. 环境、安装与证据约定

GitHub、PyPI、npm 的当前发行版均为 0.12.35。下载并校验：

- wheel SHA-256：`2058a058234210e1a31591ce64d7393f586ee0304376d2d57c3fae8a1fdc4270`。
- sdist SHA-256：`f25f66f695d0dc010392b3f74376c71a90488a586e2e07e1e862b6fbb5ddc08f`。
- npm `@hui-xu-ai/dsh-wensu` 的 bundle 重新下载并核验 shasum；本轮未在 DSH 中运行。

先新建隔离 venv 安装 wheel 和测试依赖，再将同一个 wheel 正式安装到：

`%LOCALAPPDATA%\scholar-search\installations\0.12.35\venv`

Python 为 **3.14.5**。解释器、实际包导入位置、包元数据、Codex MCP 配置保存在 `environment.json`。公开 wheel 与由本地源码 sdist 重建的 wheel，包内容归一化 CRLF/LF 后完全一致。

正式安装命令的关键部分为：

```text
wensu setup --target <HOME>/installations/0.12.35/browser --force --browser edge --skills-dir C:\Users\xuhui\.codex\skills
```

使用版本目录注册 native host，避免覆盖旧宿主正在使用的可执行文件；既有扩展加载路径中的资源同步更新。原 `E:\LiteratureEdgeProfile` 保留，没有换成默认新 profile。随包技能已通过安装命令更新，Codex MCP 指向正式 0.12.35 解释器。安装后的 `browser.json`、`host/` 树及完整 setup 输出分别保存在 `browser-installed.json`、`host-tree.json`、`setup-installed.log`。

安装后第一次状态检查显示扩展未连接。随后执行正式 profile 的 `browser start`，返回 0、显示 `started`，约 **2.016 秒**后 `bridge_ready=true`。之后重复启动均返回 0，提示已在运行并转交。

来源：[GitHub v0.12.35](https://github.com/hui-xu-ai/wensu/releases/tag/v0.12.35)、[PyPI 0.12.35](https://pypi.org/project/wensu/0.12.35/)、[npm bundle](https://www.npmjs.com/package/@hui-xu-ai/dsh-wensu/v/0.12.35)。

### 构造方式与覆盖范围

- A：**手写端点 JSON + 真正存活/关闭的本机 TCP 监听端**。每格实际启动发行包的 MCP stdio，调用 `status`、`search`、`status`，走真实服务、桥接、计划、策略与 CNKI 解析器。监听端仅返回脱敏页面 fixture。这里的 search 是真实 MCP 调用，**不是向学术站点发送请求**。
- B：真实渠道 parser 生成记录，经实际 `export` 工具导出四种格式。已知词表全部覆盖；WoS 的未知类型直通另加边界用例。
- C：实际 Edge 启动、转交和缺扩展状态；C5 实际限权执行未观察到权限错误，另用受控退出码 21 验证报错方向，明确区分两种证据。
- D1/D2：**两个独立 Python 进程**，真实 WoS 分段计划、parser、文件锁和缓存；共享 fixture 适配器及虚拟时钟。D4–D6 使用真实 BridgeAdapter 与本机 TCP，合成分段渠道。
- E：实际 MCP/CLI 参数入口，fixture 后端及隔离额度；E5 另外执行真实知网 DOI / URL / 外域 URL 对照。

规定的 A、C、D、E 共 **31 格**，均有记录；D3 因发行渠道不支持 journal 标为不适用，其余 30 格实际执行。B 为 **21 个渠道类型用例 × 4 格式 = 84 次导出**，加缺失、未知类型两个边界后共 **92 次**。另有 A14–A16 三个补充组合。

完整机器可读覆盖表为审查目录下 `coverage.csv`、`coverage-summary.json`；逐次原始返回在 `matrix.jsonl`，不是只保存 PASS/FAIL。

## 2. 矩阵 A · host 选择

本表“就绪”是 `status.bridge_ready` 的实际值；“未指定”同时不设置 WENSU_PROFILE、也不提供 browser.json 的默认 profile。“无标签”用于模拟兼容旧端点。

| 项 | 存活/标签 | 请求 | status 就绪 | 实际 search | 选择/动作 | 隔离扣额 |
|---|---|---|---|---|---|---|
| A1 | 1：A | 未指定 | true | 成功 | H1 | 3 |
| A2 | 1：A | A | true | 成功 | H1 | 3 |
| A3 | 1：A | B | true | BRIDGE_ERROR，无 B | 无页面动作 | 0 |
| A4 | 1：无标签 | A | true | 成功，兼容旧端点 | H1 | 3 |
| A5 | 2：A、B | 未指定 | true | 成功 | H2 | 3 |
| A6 | 2：A、B | A | true | 成功 | H1 | 3 |
| A7 | 2：A、B | B | true | 成功 | H2 | 3 |
| A8 | 2：A、A | A | true | BridgeAmbiguous | 无页面动作 | 0 |
| **A9** | **3：A、A、B** | **A** | **true** | **BridgeAmbiguous，原问题修复** | **无页面动作** | **0** |
| A10 | 3：A、B、C | A | true | 成功 | H1 | 3 |
| A11 | 1 活 A + 1 死 A | A | true | 成功 | 仅活 H1 | 3 |
| A12 | 死 A、死 B | A | false | BRIDGE_ERROR | 无页面动作 | 0 |
| **A13** | **1 活 A，含 legacy 别名 + 1 stale A** | **A** | **true** | **成功，原问题修复** | **仅活 H1** | **3** |

A1–A13 共消耗 **27 次合成额度**，不影响正式配额。拒绝的四格均返回 `retryable:true`，见问题 V2-02。

补充覆盖：

| 项 | 标签与请求 | 实际结果 | 说明 |
|---|---|---|---|
| A14-extra | A、A、无标签；请求 A | **成功并发出页面动作，扣 3** | 两个 A 的歧义被放行，见 V2-01 |
| A15-extra | 无标签、无标签；请求 A | BridgeAmbiguous，扣 0 | 未放行 |
| A16-extra | A、无标签；请求 A | 选择有标签的 A，扣 3 | 记录兼容策略，不单独计为缺陷 |

本轮没有把“标签不能证明真实 profile”这一已知限制本身列为缺陷。V2-01 针对的是：仍有两个不可区分的 A，却因另一个无标签候选而不再拒绝。

## 3. 矩阵 B · 两渠道全部已知类型与四种导出

CNKI 已知类型 **9 种**：achievement、book、conference、journal、newspaper、patent、standard、thesis、yearbook。

WoS 已知输出类型 **12 种**：article、book、book_chapter、correction、data_paper、early_access、editorial、letter、meeting_abstract、proceedings、retraction、review。它还会保留未知类型的小写原文，不能把有限词表当作全部可能输入。

原生词汇重叠仅 **book**；journal/article、conference/proceedings 等通过统一词汇关联。两份 manifest 没有枚举 doc_type，清单来自 parser 的 CANONICAL / DOC_TYPES。

| 渠道 | doc_type | RIS TY | EndNote %0 | RIS N1 原文（无则 —） |
|---|---|---|---|---|
| CNKI | achievement | GEN | Generic | achievement; no RIS equivalent mapped |
| CNKI | book | BOOK | Book | — |
| CNKI | conference | CPAPER | Conference Paper | — |
| CNKI | journal | JOUR | Journal Article | — |
| CNKI | newspaper | NEWS | Newspaper Article | — |
| CNKI | patent | PAT | Patent | — |
| CNKI | standard | **STAND** | Generic | — |
| CNKI | thesis | THES | Thesis | — |
| CNKI | yearbook | **BOOK** | **Book** | — |
| WoS | article | JOUR | Journal Article | — |
| WoS | book | BOOK | Book | — |
| WoS | book_chapter | **CHAP** | **Book Section** | — |
| WoS | correction | GEN | Generic | correction; no RIS equivalent mapped |
| WoS | data_paper | GEN | Generic | data_paper; no RIS equivalent mapped |
| WoS | early_access | GEN | Generic | early_access; no RIS equivalent mapped |
| WoS | editorial | GEN | Generic | editorial; no RIS equivalent mapped |
| WoS | letter | GEN | Generic | letter; no RIS equivalent mapped |
| WoS | meeting_abstract | GEN | Generic | meeting_abstract; no RIS equivalent mapped |
| WoS | proceedings | CPAPER | Conference Paper | — |
| WoS | retraction | GEN | Generic | retraction; no RIS equivalent mapped |
| WoS | review | JOUR | Journal Article | — |
| 边界 | 未报告 | GEN | Generic | document type not reported by source |
| 边界 | something_new | GEN | Generic | something_new; no RIS equivalent mapped |

每行都实际导出了 RIS、EndNote、Markdown、CSV，共 92 个结果文件，保存于 `matrix-B/`。CSV 的 doc_type 均与输入相同；Markdown 成功生成，但本来不呈现专门的文献类型字段，未把它当作类型映射错误。EndNote 没有 RIS 的 N1 字段。

标准、年鉴回归与章节映射已修复。当前未映射的已知类型仍为 Generic，但注释准确说明映射缺口，不再错误指责来源没有提供类型；本轮将其作为能力范围记录，没有将诚实降级单独列为新缺陷。

## 4. 矩阵 C · 启动与连接

| 项 | 实际构造及命令 | 结果 |
|---|---|---|
| C1 | 全新隔离 Edge profile，无已运行实例，`browser start` | 退出 0，约 1.523 秒返回 started；进程确实存活。未加载扩展，status 不就绪，需要文档所述人工加载 |
| C1 补充 | 正式既有 profile 从未连接状态执行 `browser start` | 退出 0，started，约 **2.016 秒**后桥接就绪 |
| C2 | 正式浏览器已运行，再 `browser start` | 退出 0，明确提示 already running / handed over |
| C3 | 隔离 Edge 真实进程运行，无扩展连接，`status --brief` | bridge_ready=false；next_action=reload_extension；human_step_required=true；command=null |
| C4 | 隔离 HOME 无任何 host，MCP search | BRIDGE_ERROR、quota_charged=0，但 **retryable=true**；额度 300 → 300 |
| C5 | 通过实际受限执行环境，在一次性 profile 执行 `browser start` | 退出 0，started，未观察到实际权限拒绝；另用受控退出码 21 检查诊断，正确提到目录不可写 |
| C6 | 正式 profile 连续两次 `browser start` | 两次均退出 0、均提示已运行并转交，桥接仍就绪 |

C2、C6 原“正常退出码 0 被误报为 profile 不可写”的问题已修复。C5 **没有真实制造目录 ACL 拒绝**，所以不声称已验证全部真实权限失败路径；退出码 21 的文案证据属于受控模拟。

只清理了本轮新建隔离 profile 时持有的进程句柄，没有按浏览器进程名终止用户浏览器。C5 后续身份核对时其启动 PID 已不存在或身份不再匹配，因此没有据旧 PID 停止任何进程。

## 5. 矩阵 D · 事务、进程时序与缓存

| 项 | 实际构造 | 观察与缓存复查 |
|---|---|---|
| D1 | 真实 WoS 分段计划；A 提交后暂停，另一进程发 CNKI detail | B 未在 A 恢复前完成；动作在 A 读取后才发生。A 返回 QUERY_A，同 query 命中 QUERY_A 缓存 |
| D2 | 同上，B 发另一次 WoS search | B 排队；A 返回/缓存 QUERY_A，B 返回/缓存 QUERY_B |
| D3 | 检查两渠道 manifest 的 journal capability | **不适用**：两个发行渠道都未声明 journal；未据此报错或算缺陷 |
| D4 | 真实本机 TCP，提交后删选定 host 的登记文件 | 已建立连接继续读取 A，B 无动作；同 query 命中缓存，内容仍为 A，非错误缓存 |
| D5 | 提交后真正关闭 A 的 TCP 与登记 | read_html 返回 ActionError；B 无动作；缓存不存在。同 query 再查得到 BridgeError，没有 cache_hit 的错误成功结果 |
| D6 | 提交后才登记另一个不同 profile 的真实监听 host | 原事务仍由 A 完成；B 无动作；同 query 命中正确 A 缓存 |

D1/D2 使用实际跨进程锁，不是仅靠两个线程模拟。辅助回放第一版遗漏了 WoS 计划实际使用的 `read_text` 载荷，产生 ParseError；补齐 fixture 输出后使用新的 `matrix-D-final/` 目录重跑。上述结论只使用最后一轮完整结果，早期辅助程序错误保留在原始日志中，没有计为产品缺陷。

## 6. 矩阵 E · 参数与边界

| 项 | 实际调用 | 观察 |
|---|---|---|
| E1 | CLI search/detail `--field titel`；MCP search/detail 错误 fields | CLI 退出 2、列可用字段，后端动作 0；MCP status=error，隔离额度 300 → 300 |
| E2 | fixture 零结果，fields=[title] | 正常返回 records=[]、total=0，无未知字段错误；扣 3；empty_reason=null，按原样记录 |
| E3 | CLI/MCP limit=999、page=9 | 均在取数前拒绝，CLI 退出 2；MCP isError=true；无页面动作、不扣额 |
| E4 | 五个实际工具各传未知参数 | 五个都拒绝，未静默忽略；isError=true、不扣额 |
| E5 | fixture URL、DOI、外域 URL；另补真实知网对照 | 冷 URL 扣 1、暖 URL 扣 0；DOI 搜索+详情扣 4；外域自动推断 UNKNOWN_CHANNEL，指定 cnki 则 POLICY_URL_DOMAIN，均扣 0 |
| E6 | fixture 页面只含 2026 年记录，要求 1900–1901 | records=[]；total 保留 595；dropped_year=2；empty_reason=all_dropped_by_year；扣 3，明确 year_scope=page |

真实 E5 对照：从真实详情得到 DOI `10.13841/j.cnki.jxsj.2026.11.001`，分别传原 URL 与该 DOI。两者返回的**题名和 DOI 一致**；暖 URL 扣 0，DOI 扣 4，外域 URL 在本地拒绝、扣 0。未把离线 fixture 的合成 DOI 语义当作线上正确性的证据。

## 7. 问题清单（按方案模板）

### V2-01 · 两个同名宿主旁边出现无标签旧宿主时，歧义再次被放行

**级别**：严重 / P1。

**矩阵项**：A8、A9 的对照，补充组合 A14-extra；A15/A16 为兼容状态对照。

**构造方式**：手写合法端点 JSON，三个真实本机 TCP 监听端；发行包的 MCP search、真实 BridgeAdapter / Planner / parser。没有访问真实学术站点。

**现象**：A、A 时拒绝，A、A、B 且请求 A 时也拒绝；改成 A、A、无标签后，请求 A 却成功，向 H1 发出 goto/type/click/read_html，并返回其题录。

**复现命令原文**（审查目录中）：

```text
venv\Scripts\python.exe matrix.py A-extra
```

**实际输出**（仅摘关键字段，完整输出见 matrix-A-extra.log）：

```json
{
  "case": "A14-extra",
  "labels": ["A", "A", null],
  "live": [true, true, true],
  "wanted": "A",
  "selected_hosts": ["A14-extra-H1"],
  "search": {
    "isError": false,
    "payload": {
      "records": [{"title": "Synthetic host A14-extra-H1"}],
      "cache_hit": false,
      "quota_charged": 3,
      "quota_remaining": 297
    }
  }
}
```

**预期**：依据方案第 7 节及项目自己的约束，两个声称同一 profile 的 host 不能区分，应拒绝。第三个无标签兼容端点没有提供区分两个 A 的新证据。这里不是要求 host 自证身份，而是要求身份不明时保留既有拒绝行为。

**影响**：混合旧/新端点时可能选到无法确认归属的浏览器。当前证据直接证明歧义被放行和页面动作发生，**没有声称本次读取的 fixture 结果已造成真实用户数据串线**。

**定位/原因**：`adapters/bridge/__init__.py:213` 把无标签候选加入 eligible；`:217–219` 又要求 eligible 的标签种类 `<=1` 才拒绝。A、A、None 的标签集合大小为 2，所以跳过拒绝。

**建议**：明确区分匹配标签集合与旧无标签集合。多个匹配 A 本身就应拒绝，不能被 None 的存在解除保护；旧端点兼容策略另行处理。将 A、A、None 加入正式回归。

### V2-02 · 无 host、请求 profile 不在场或存在歧义时仍标记 retryable=true

**级别**：一般 / P2。

**矩阵项**：C4、A3、A8、A9、A12、A15-extra。

**构造方式**：隔离 HOME；无端点，或实际监听但不符合请求的端点。通过真实 MCP search 观察，不只直接调用内部 `_ensure_bridge`。

**复现命令原文**：

```text
venv\Scripts\python.exe matrix.py E
venv\Scripts\python.exe matrix.py A
```

**实际输出**（C4）：

```json
{
  "status": "error",
  "code": "BRIDGE_ERROR",
  "message": "no live native host found",
  "kind": "BridgeError",
  "channel": "cnki",
  "retryable": true,
  "quota_charged": 0
}
```

额度 300 → 300，错误本身正确，没有偷扣额度。

**预期**：在浏览器启动、扩展重连、关闭冲突 host 或调整 profile 前，重复相同调用不能改变结果。项目 `server.py` 中桥接故障的现有说明同样要求外部状态改变、避免重试循环。

**影响**：客户端容易按机器可读标志无效重试；这些路径也缺少 ActionError 桥接路径原有的 `requires=external_state_change` 和 remediation。

**定位/原因**：事务入口的 `pin()` 先抛 BridgeError / BridgeAmbiguous，未经过 `_ensure_bridge` 的 ActionError 包装；`server.py:219` 把所有 BridgeError 视为可重试，`:256` 的特殊修正只覆盖 ActionError。

**建议**：区分瞬时通信超时与无连接/无匹配/歧义等确定状态；后几种返回 retryable=false，并给出所需外部动作。回归应走公开 search，而不只测试内部 guard。

### 诊断建议（不计为新增业务缺陷）

- **A3/A8/A9**：`bridge_ready=true` 仅证明有宿主回应，并不保证请求 profile 可用或唯一。文档如此定义时不是逻辑错误，但可增加 profile 可用性/歧义字段，避免客户端把“有连接”读成“可检索”。
- **C3**：全新 profile 尚未加载扩展也被建议 reload_extension。诊断可区分“首次加载”与“已加载但断连”，附扩展目录；当前仅 command=null、human_step_required=true，单看 status 无法完成首次加载。

## 8. 实际文献任务与额度账目

任务：检索 2022–2026 年与“柔性驱动器”相关的 3 条 CNKI 题录，读取首篇摘要，导出 RIS / EndNote / Markdown / CSV，并对照 DOI 与 URL。

结果：站点 total=**363**，返回 3 条；首篇为《柔性可穿戴腕关节康复手套构型设计与控制策略研究》，DOI `10.13841/j.cnki.jxsj.2026.11.001`，读取到摘要 **198 字符**。年份过滤仍为本页过滤，total 不是过滤后的总数。本轮未逐字段人工比对网页，也未在线验收 WoS。

| 正式操作 | 剩余额度 | 本步扣额 |
|---|---|---|
| 开始；安装、状态检查、重复启动 | 144 | 0 |
| 一次关键词检索 | 141 | 3 |
| 首篇 URL 详情与摘要 | 140 | 1 |
| 四种文本导出 | 140 | 0 |
| 同一暖 URL 详情 | 140 | 0 |
| 同一 DOI 解析与详情 | 136 | 4 |
| 外域 URL 本地拒绝、结束 status | **136** | 0 |

**正式额度 144 → 136，共 8 次**，无冷却、无验证码、无自动重试。A/B/D/E 使用隔离配额，未计入正式账目。

导出文件位于 `%LOCALAPPDATA%\scholar-search\exports\acceptance-0.12.35\`：

| 格式 | 文件名 | 返回 bytes / 实际 bytes |
|---|---|---|
| RIS | 柔性驱动器-2022-2026.ris | 1951 / 1951 |
| EndNote | 柔性驱动器-2022-2026.enw | 1852 / 1852 |
| Markdown | 柔性驱动器-2022-2026.md | 1786 / 1786 |
| CSV | 柔性驱动器-2022-2026.csv | 1856 / 1856 |

**能否照着走通**：本机既有扩展环境下可以。setup 保留原 profile，启动后连接恢复，检索、摘要与导出完成。首次使用全新 profile 仍需人工加载扩展；本轮没有替用户操作开发者模式或加载扩展。

## 9. 常规检查与限制

| 检查 | 结果 |
|---|---|
| 新发行包运行仓库完整离线套件 | **248 passed in 3.61s**，退出 0 |
| Ruff lint / format | 通过，72 files already formatted |
| mypy --strict | 44 个源文件通过 |
| 五处版本、CHANGELOG、两层计划校验 | 通过 |
| sdist → wheel、扩展资源、两渠道打包 | 独立构建及资源检查通过，包内容与公开 wheel 一致 |
| 原样 release-check.py | **仍未全绿**：tests/types/assets/artifacts 4 项失败，其余 5 项通过 |

原门禁继续使用仓库旧 `.venv`，受临时目录访问和构建环境问题影响；新隔离环境中的测试、类型、构建已分别通过。没有替换仓库 `.venv`，也没有把环境失败算成上述两个业务问题。当前聊天的工具列表刷新、DSH 实际运行及其他 MCP 客户端界面不在本轮已完成范围内。

## 10. 原始证据与复现

审查根目录：

`C:\Users\xuhui\.codex\visualizations\2026\11\09\01a1c01c-2472-7ab3-9017-c2ceddfc1dd1\wensu-acceptance-0.12.35`

主要材料：

- `coverage.csv`、`coverage-summary.json`、`matrix.jsonl`：每格是否执行、返回值、动作与额度。
- `matrix.py`、`previous_probes.py`、`startup.py`、`research.py`：复现辅助程序。
- `matrix-A.log`、`matrix-A-extra.log`、`matrix-B/`、`matrix-D-final.log`、`matrix-D-final/`、`matrix-E.log`、`matrix-C-*.log`：分组证据。
- `live-research.jsonl`、`live-identifiers.log`、`environment.json`、`setup-installed.log`、`browser-installed.json`、`host-tree.json`：正式安装与真实任务。
- `pytest.log`、`lint.log`、`format.log`、`mypy.log`、`build.log`、`plans.log`、`release-check.log`、`downloads/`、`built/`：常规检查及发行物。

复现时使用此目录的 `venv/Scripts/python.exe`。矩阵命令为 `matrix.py A`、`matrix.py B`、`matrix.py D`、`matrix.py E`、`matrix.py A-extra`；启动测试为 `startup.py cold/formal/restricted`。再次运行应换新证据目录，避免已保存的缓存、同步标志、故意保留的 stale 登记改变前置状态。

所有本机合成监听端与 D 组子进程均在测试结束后关闭。未下载全文、未写第三方文献库、未读取或记录浏览器账号/Cookie、未保存真实完整 HTML，未修改正式配额或冷却文件；正式额度变化仅来自账目中的合法动作。
