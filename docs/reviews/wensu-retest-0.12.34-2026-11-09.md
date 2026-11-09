# 文溯 0.12.34 重新安装与第五轮复验

**结论：重新安装及真实知网主流程通过，241 项离线测试通过。上轮提交后切换 host 的具体复现、失活端点误判、升级替换 profile 均已修复。仍有一个三宿主场景的连接歧义漏洞；导出修复不完整，并引入标准、年鉴类型回退；浏览器重复启动也会误报失败。**

审查日期：2026-11-09（北京时间）。HEAD：`311cf53eacfcc77e1cd605076ffe7f5f326ac3ae`，开始时工作区干净。测试的是重新从 GitHub Release 下载、安装的 **0.12.34 wheel**，不是旧安装或仅源码测试。本轮只在仓库新增此报告，没有修改业务代码或发布版本。

## 下载安装核验

- GitHub Release、PyPI 和 npm `@hui-xu-ai/dsh-wensu` 均为 **0.12.34**。
- 下载的 wheel SHA-256：`705e6e4815dbdbcdce6cec2b928fd8913edcacc588badd2beebce356ef18d608`，与 GitHub 公布值及 PyPI 一致。
- sdist SHA-256：`3d1ee71d32e8622064c7f1ea925fe8fc78a7b217212e94bec2c5f60faf497741`，验证通过。npm bundle 同样重新下载并核验 shasum；未在 DSH 中运行。
- 新建隔离 venv 安装发行包及测试依赖，打印确认版本与 `scholar_search.__file__`，所有复现均由该新环境运行。
- 正式安装路径：`%LOCALAPPDATA%\scholar-search\installations\0.12.34\venv`。浏览器资源与 native host 注册使用该版本的 `installations/0.12.34/browser`，Codex MCP 配置也已切换到新解释器。
- 保留原有 `E:\LiteratureEdgeProfile`。既有扩展的加载路径下资源已更新；三个脚本与本次发行包一致。本轮只重启文献插件自身的 native host，未关闭或终止浏览器。
- 正式 MCP 握手版本 **0.12.34**，`bridge_ready=true`，无冷却。由源码 sdist 重建的 wheel 与公开 wheel 在归一化换行后包内容完全一致。

来源：[GitHub v0.12.34](https://github.com/hui-xu-ai/wensu/releases/tag/v0.12.34)、[PyPI 0.12.34](https://pypi.org/project/wensu/0.12.34/)、[npm bundle](https://www.npmjs.com/package/@hui-xu-ai/dsh-wensu/v/0.12.34)。

## 1. [P1] 第三个无关宿主会使两个同名宿主的歧义检查失效

**定位**：`src/scholar_search/adapters/bridge/__init__.py:202`、`:204`、`:205`、`:214`。

新的 `pin()` 先检查存活再判断歧义，这部分有效。但它只在所有存活宿主的不同 profile 标签数量 `<=1` 时拒绝。判断的是全体候选的标签种类，没有判断**请求的同一个 profile 是否仍对应多个存活候选**。

**发行包离线复现**：三个真正监听 loopback 的合成 host。A 和 C 都报告 `E:\FixtureA`，B 报告 `E:\FixtureB`；显式设置 `WENSU_PROFILE=E:\FixtureA`。两个同名标签模拟的是项目已经确认的限制：标签来自共享配置，不能证明宿主实际属于哪个浏览器。将 C 设为较新的登记。

1. 只有 A、C 时，`pin()` 正确抛出 `BridgeAmbiguous`。
2. 加入无关的 B，A、C 的身份没有变得更明确，但 `distinct` 变为两个值，拒绝分支被跳过。
3. `pin()` 成功选中 C，真实 `BridgeAdapter.execute(read_html)` 返回 C 的页面。

```json
{
  "requested_profile": "FixtureA",
  "two_same_label_hosts": "BridgeAmbiguous",
  "after_adding_unrelated_profile": "accepted",
  "selected_actual_profile": "C",
  "ok": true,
  "html": "ACTUAL_PROFILE_C_WITH_SHARED_A_LABEL"
}
```

**影响**：多个浏览器或历史配置变更后仍可能出现不可区分的同名宿主；打开一个无关浏览器竟会解除原本正确的保护。整个事务虽然绑定到一个 endpoint，但起点仍可能选错浏览器。此处没有声称再次复现上轮的提交后换宿主或缓存污染；本轮证据证明的是**事务开始时的歧义被放行**。

**建议**：先取得存活集合，再按请求 profile 筛选，对最终合格候选本身做唯一性判断。两个同名候选不能因为存在第三个不同名候选而变得可区分。增加两个 A + 一个 B 的回归，并保证错误分支不发出页面动作。

## 2. [P2] 统一类型映射使原本正确的标准、年鉴导出回退为 Generic

**定位**：`src/scholar_search/core/export.py:184`；`src/scholar_search/core/contracts.py:151`、`:170`。

`_type_token` 改成先调用 `unify_doc_type`，但统一词表没有 `standard`、`yearbook`。二者先变为 `other`，原导出类型无法保留；`_RIS_TYPES` 即使还有 standard 入口也到达不了。

对 **0.12.33 和 0.12.34 两个独立发行包安装**运行同一组真实 Record → 导出函数用例：

| doc_type | 0.12.33 RIS | 0.12.34 RIS | 0.12.33 EndNote | 0.12.34 EndNote |
|---|---|---|---|---|
| standard | `STAND` | **GEN** | Generic | Generic |
| yearbook | `BOOK` | **GEN** | Book | **Generic** |
| journal | JOUR | JOUR | Journal Article | Journal Article |
| book | BOOK | BOOK | Book | Book |

CNKI 的 `doc_types.py` 明确把“标准”“年鉴”解析为这两个值，属于既有支持范围，不是任意未知类型。新版还给这两类记录写入“源未报告文献类型”的注释，而记录已经报告类型。

**建议**：不要让用于跨渠道筛选的统一词表缩小导出格式的支持范围。补齐合法类型或保留原始类型的可导出映射；用所有渠道已声明的类型进行回归，而不只测试 Article / Review / Proceedings。

## 3. [P2] 上轮图书章节导出问题仍未修复，缺失类型提示也未纠正

**定位**：`src/scholar_search/core/export.py:184`、`:195`；`src/scholar_search/channels/webofscience/v2026_11/parse_records.py:55`。

重复上轮的 fixture → 真实 WoS 解析器 → 导出链路，结果为：

| WoS 页面类型 | 解析 doc_type | 新版 RIS | 新版 EndNote |
|---|---|---|---|
| Article | article | **JOUR，已修复** | Journal Article |
| Review | review | **JOUR，已修复** | Journal Article |
| Proceedings Paper | proceedings | **CPAPER，已修复** | Conference Paper |
| Book Chapter | book_chapter | **GEN，仍有问题** | Generic |

Book Chapter 已经在渠道层识别为 `book_chapter`，导出仍丢失章节类型，并写入 `document type not reported by source`。CHANGELOG 的“未知类型不再误称为源未报告”也与实际代码不符：生成该注释的分支没有改变。

**建议**：补齐章节映射，区分“源没有报告类型”和“当前映射不支持已报告类型”。上轮导出问题只能标为部分修复。

## 4. [P2] 浏览器已运行时，成功退出的启动进程被误报为无法使用 profile

**定位**：`src/scholar_search/core/browser.py:289`、`:293`。

本轮正式安装后调用 `browser start`，观察到启动子进程退出码 **0**，CLI 却报：

```text
edge exited immediately with code 0; it could not use E:\LiteratureEdgeProfile.
Chromium exit code 21 means the profile directory is not writable ...
```

随后同一安装的 `status` 显示桥接就绪，实际检索、详情和导出也通过。既有浏览器已经打开，新增启动进程退出不能单独证明 profile 不可用。

离线隔离复现将 `Popen.wait` 返回值设为 0，真实 `browser.start` 同样无条件抛出上述 `RuntimeError`。函数当前把“在 1.5 秒内退出”全部当作失败，与其注释中承诺的可重复调用不符。

**建议**：区分退出码 0、实际失败码及目标 profile 已运行的情况。重复启动已有可用 profile 应明确报告已运行或已转交，而不是给出目录不可用的判断。退出码 21 的诊断只应用于相应失败情形。

## 上轮修复复验结果

| 上轮项目 | 本轮结论 | 证据 |
|---|---|---|
| 分段检索提交后宿主登记消失 | **通过** | 继续沿已绑定连接读取 A，结果与缓存为 QUERY_FOR_PROFILE_A；B 没有收到动作 |
| 提交后 A 真正断开 TCP | **通过** | 返回 ActionError；B 没有收到动作；搜索 cache_entry=null |
| 一个 live + 一个 stale | **通过** | stale ping=false；pin 成功选择 live，不再误报两个运行中的 host |
| 单宿主双文件布局 | **通过** | 调用真实 native-host writer 生成两文件，发现正常 |
| setup --force 保留选定 profile | **通过** | 隔离安装前后 adopted profile 相同；正式安装也保留 E:\LiteratureEdgeProfile |
| WoS 类型导出 | **部分通过** | Article / Review / Proceedings 已修，Book Chapter 未修，并出现问题 2 的回归 |

另外复验 search/search、search/detail、search/journal：后发请求正常等待，A 结果和缓存均正确，各线程正常结束。CLI detail、MCP detail/detail_many 的错误 fields 均未调用真实站点或消耗隔离配额。

## 测试与真实检索

| 检查 | 结果 |
|---|---|
| 新发行包运行当前仓库离线套件 | **241 passed in 5.47s，exit 0** |
| Ruff lint / format | 通过，72 files already formatted |
| mypy --strict | 44 个源文件通过 |
| 五处版本一致 | 全为 0.12.34 |
| 两层计划校验 | 两渠道代表计划均通过 |
| sdist → wheel、扩展资源 | 构建成功，三个脚本齐全 |
| MCP stdio | 握手版本 0.12.34，发现五工具 |
| 未知参数、错误字段 | 被拒绝，错误字段离线配额 300 → 300 |
| HTTP 认证 | 无 token / 错 token 为 401，外域 Host 为 403 |
| HTTP MCP | 认证后发现五工具并调用 status 成功 |
| 正式安装 MCP 知网检索 | 柔性驱动器：total=363、返回 3 条、cache_hit=false、消耗 3 次 |
| 首篇详情 | 卷 43、期 11、页 21-26、DOI 10.13841/j.cnki.jxsj.2026.11.001，消耗 1 次 |
| 同条 RIS 导出 | JOUR、作者、卷期页及 DOI 正常 |

正式额度从 **148 → 144**，总计 4 次。测试后桥接仍就绪，无冷却，没有自动重试。没有在线测试 WoS，未逐项人工比对真实论文页面；WoS 的证据来自脱敏 fixture。Codex 配置已更新并核验，独立 MCP 客户端已验证；当前聊天工具列表刷新、DSH 及其他客户端界面未验收。

## 发布门禁的环境限制

原样运行 `python scripts/release-check.py`：versions、changelog、lint、format、plans 通过；tests、types、assets、artifacts 仍失败，退出码 1。脚本使用仓库旧 `.venv`，其中临时目录访问和构建环境问题延续上轮。

全新隔离安装已独立通过上表的测试、类型、构建与资源检查，但**原发布门禁并未全绿**。本轮没有替换仓库 `.venv`，也没有把这些环境失败算作上述业务问题。

## 原始证据

审查目录：

`C:\Users\xuhui\.codex\visualizations\2026\11\09\01a1c01c-2472-7ab3-9017-c2ceddfc1dd1\wensu-audit-0.12.34`

主要文件：`probes.py`、`results.jsonl`、`ambiguity.log`、`disconnect.log`、`new-probes.log`、`upgrade-profile.log`、`export-0.12.33.jsonl`、`export-0.12.34.jsonl`、`regressions.log`、`pytest.log`、`mypy.log`、`build.log`、`release-check.log`、`stdio.log`、`http.log`、`setup-installed.log`、`installed-status.json`、`live-results.jsonl`、`installation-verification.json`、`downloads/`、`built/`。

使用审查目录的 `venv/Scripts/python.exe` 运行 `probes.py ambiguity` 可复现三宿主及零退出码判断；`new`、`disconnect`、`upgrade` 为其他主要复现入口。再次复现应选新的审查目录，避免有意保留的合成登记和缓存影响前置状态。

所有合成监听端和临时 HTTP 服务均已关闭。未下载全文，未写入第三方文献库，未记录 Cookie、账号或完整 HTML；未修改正式配额与冷却文件。实际额度变化仅来自上述 4 次合法动作。
