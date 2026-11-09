# 文溯 0.12.33 安装与第四轮审查

**结论：安装与单浏览器主流程通过；仍有 1 项 P1 和 3 项 P2，应先修复跨浏览器串线问题。223 项现有测试通过，不能据此关闭本文的新复现。**

审查日期：2026-11-09（北京时间）。工作区 HEAD：`2947a6150dd4b2edb34defd9a7c848af6bdcac2d`，开始时工作区干净。测试对象是从 GitHub Release 下载并实际安装的 **0.12.33 wheel**，不是仅测试源码目录。本轮只在仓库新增本报告，没有修改业务代码或发布版本。

## 安装及发行物核验

- GitHub 最新 Release、PyPI 和 npm `@hui-xu-ai/dsh-wensu` 的版本均为 **0.12.33**。
- GitHub 与 PyPI 的 wheel SHA-256 均为 `27e8c5eda134097b82275526342ac1abf6fdfcb1cc97d139fa5d213a545e2b05`；下载后重新计算并核验通过。sdist 的 SHA-256 为 `0112f206f375648c85e095f4d05ad0efb3cdb90cfd9c93ff1f3b37827ae9c896`。
- npm bundle 已下载并校验 registry 的 shasum；本轮未在 DSH 中安装运行。
- 先在审查目录建立全新隔离环境安装 wheel 及依赖，确认 `scholar_search.__file__` 来自该环境的 `site-packages`。
- 正式安装到 `%LOCALAPPDATA%\scholar-search\installations\0.12.33\venv`，注册 Edge/Chrome native host，保留原有 `E:\LiteratureEdgeProfile`，并添加 Codex 的 `mcp_servers.wensu` 配置，指向该安装目录。
- 正式安装使用 `setup --force --browser none` 保留既有浏览器配置；原因见问题 4。启动已配置的 Edge 后，`bridge_ready=true`，无冷却。
- 由当前源码的 sdist 重建 wheel 成功；与公开 wheel 比较，包内容在归一化 CRLF/LF 后完全一致。

远程来源：[GitHub v0.12.33](https://github.com/hui-xu-ai/wensu/releases/tag/v0.12.33)、[PyPI 0.12.33](https://pypi.org/project/wensu/0.12.33/)、[npm bundle](https://www.npmjs.com/package/@hui-xu-ai/dsh-wensu/v/0.12.33)。

## 1. [P1] 分段检索没有绑定同一个 host，选定浏览器断开后会读到另一个浏览器并污染缓存

**定位**：`src/scholar_search/core/service.py:125`、`:151`、`:452`、`:468`；`src/scholar_search/adapters/bridge/__init__.py:109`、`:126`、`:193`。

本轮新增的事务锁能防止两个服务请求交错，但不能保证整个事务使用同一个浏览器连接。每次 `_run` 都新建 adapter、重新发现 host，并在结束后关闭 adapter；`WENSU_PROFILE` 仅用于排序，找不到匹配项时仍回退到其他 profile。

**发行包离线复现**：两个实际监听 loopback TCP 的合成 host，A/B 分别标记为 `E:\FixtureA`、`E:\FixtureB`。显式设置 `WENSU_PROFILE=E:\FixtureA`。使用真实 ScholarService、BridgeAdapter、Planner、策略与缓存，A 完成提交后模拟断开：移除 A 的端点登记。tail 重新发现时只剩 B，随后成功读取 B 的旧页面。

```json
{
  "wanted_profile": "FixtureA",
  "result": ["UNRELATED_PROFILE_B"],
  "cached": ["UNRELATED_PROFILE_B"],
  "cached_hit": true,
  "host_A_actions": ["type", "click"],
  "host_B_actions": ["read_html"]
}
```

**影响**：浏览器退出或扩展断连发生在提交与读取之间时，工具可能以成功结果返回其他 profile 的题录，且后续相同查询继续命中错误缓存。显式选定 profile 也无法阻止这一行为。该问题在合成 host 中复现，没有对真实学术站点制造断连。

**建议**：将已选 endpoint 的身份与连接绑定到整个浏览器事务。host 消失时终止该请求，不重新选择另一 host；显式 profile 不存在时应明确失败。将“提交后选定 host 消失、另一 host 仍存活”加入回归，并检查没有写入错误缓存。

## 2. [P2] 已失效端点仍参与歧义判断，单个正常 host 也可能被拒绝

**定位**：`src/scholar_search/adapters/bridge/__init__.py:109`、`:114`、`:191`。

按 PID 合并 legacy 与 registry 文件的修复有效：调用发行包中原生宿主的真实 `write_endpoint` 生成两份文件，单 host 的 `probe()` 成功。

但歧义判断仍发生在存活探测之前。为这个正常监听的 host 添加一个相同 profile 标签、不同 PID、端口已经关闭的旧登记后：

```json
{"live_ping": true, "stale_ping": false}
{"error_type": "BridgeAmbiguous", "live_pings": 0}
```

报错声称“2 native hosts are running”，实际上只有一个可连接，且发现过程没有向正常 host 发出 ping。

**影响**：宿主异常退出后留下的登记可能让 `status` 和未缓存的检索失败，即使只剩一个正常浏览器。host 启动时的 `prune_registry` 无法覆盖另一个 host 随后崩溃的情况。

**建议**：先合并别名，再排除失活端点，最后对真正存活的候选判断歧义；不能根据端点文件数量宣称运行中的 host 数量。回归应覆盖一个 live + 一个 stale，而不只是两个静态文件。

## 3. [P2] WoS 已识别的文献类型在 RIS / EndNote 导出时丢失

**定位**：`src/scholar_search/core/export.py:52`、`:64`、`:171`；`src/scholar_search/channels/webofscience/v2026_11/parse_records.py:50`。

使用仓库脱敏的 WoS NDJSON fixture，经发行包中的真实渠道解析器生成记录，再调用真实导出函数。原始 Article 用例直接使用现有 fixture，其余用例只修改 fixture 的 doctypes 字段：

| 页面类型 | 解析后的 doc_type | RIS | EndNote |
|---|---|---|---|
| Article | article | `TY  - GEN` | `%0 Generic` |
| Review | review | `TY  - GEN` | `%0 Generic` |
| Proceedings Paper | proceedings | `TY  - GEN` | `%0 Generic` |
| Book Chapter | book_chapter | `TY  - GEN` | `%0 Generic` |

导出映射仅包含 CNKI 的 `journal`、`conference` 等词汇，没有覆盖 WoS 的对应值。RIS 还会写入 `document type not reported by source`，但源记录明确提供了类型。

**影响**：用户手动导入 RIS/EndNote 后，正常期刊文章、综述、会议论文和章节都变成通用记录，影响类型筛选和引用格式。

**建议**：统一跨渠道类型映射或为各格式补齐别名；已报告但不支持的类型也不应被描述为“源未报告”。添加渠道解析结果到导出的端到端 fixture 回归。

## 4. [P2] README 推荐的升级命令会替换已选定的浏览器 profile

**定位**：`src/scholar_search/cli.py:229`、`:234`；README 升级示例在 `README.md:157`、`:166`。

README 推荐升级后运行 `wensu setup --force`。同一个 `force` 不仅刷新资源，也绕过现有 profile 的保留分支，调用 `browser.create` 将 `browser.json` 改成默认 `profiles/edge`。

**发行包离线复现**：在全新隔离 HOME 预先记录一个已选定的 Edge profile，运行 `wensu setup --force --no-host`。`--no-host` 只跳过注册表操作，profile 分支与文档命令相同。

```text
exit:          0
before:        <隔离HOME>/adopted-research-profile
after:         <隔离HOME>/profiles/edge
profile_changed: true
```

原目录没有被删除，但后续 `browser start` 会启动新 profile，原窗口中已经装好的扩展和站点状态不会随配置迁移。采用 Chrome 或自定义浏览器路径的用户也可能被默认选项改回 Edge。

**建议**：资源覆盖与重建浏览器配置应使用不同选项；常规升级默认保留现有配置。修复前，升级文档应明确使用 `setup --force --browser none` 保留既有 profile，并增加已选定 profile 的升级回归。本机正式安装已采取此方式，既有 profile 未被替换。

## 通过的检查与修复复验

| 检查 | 结果 |
|---|---|
| 发行包运行完整离线套件 | **223 passed in 3.34s，exit 0** |
| Ruff lint / format | 全通过，70 files already formatted |
| mypy --strict | 44 个源文件通过 |
| 五处版本一致 | 全为 0.12.33 |
| 两层计划校验 | 两渠道全部代表计划通过 |
| sdist → wheel 构建 | 成功 |
| 扩展资源检查 | background.js、actions.js、capture.js 均存在 |
| MCP stdio | 握手版本 0.12.33，发现五工具 |
| 未知参数拒绝 | breif、year_form 被拒绝 |
| MCP detail/detail_many 错误 fields | 离线额度均 300 → 300 |
| CLI detail 错误 fields | 退出 2，后端调用 0，离线额度 300 → 300 |
| search/search、search/detail、search/journal 并发 | 后发请求等待，A 结果与缓存均为 QUERY_A，无死锁 |
| 单 host 的真实双文件布局 | 发现成功 |
| HTTP 认证 | 无 token / 错 token 为 401；外域 Host 为 403 |
| HTTP MCP | 认证后握手、五工具发现和 status 成功 |

上轮三个具体复现（双文件误判、search 与 detail/journal 交错、CLI detail 字段校验过晚）均通过。本轮问题 1 是 host 身份变化的新场景，不能以原并发回归通过代替验证。

## 真实浏览器测试

通过正式安装目录的 MCP stdio 启动服务，使用既有 Edge 扩展：

- `status`：版本 0.12.33、桥接就绪、无冷却，测试前剩余额度 **152**。
- 一次 CNKI `search(query="柔性驱动器", limit=3)`：**total=363，返回 3 条，cache_hit=false**；扣 3 次额度。
- 取首篇详情：题名与搜索结果一致，返回卷 **43**、期 **11**、页 **21-26**、DOI `10.13841/j.cnki.jxsj.2026.11.001`；扣 1 次额度。
- 同条题录 RIS 导出成功：`TY  - JOUR`，卷期页、作者和 DOI 均保留。
- 测试后桥接仍就绪、无冷却，剩余额度 **148**。没有自动重试。

本轮未在线测试 WoS，也未对论文页面全部字段逐项人工比对；WoS 导出问题来自脱敏 fixture 的确定性复现。Codex 配置已写入，独立 MCP 客户端通信已验证，当前聊天工具列表的刷新和其他客户端界面未验收。

## 门禁脚本与环境限制

原样执行了 `python scripts/release-check.py`。提升到当前用户权限后仍有 4 个门禁失败：tests、types、assets、artifacts；versions、changelog、lint、format、plans 通过。脚本优先使用仓库旧 `.venv`，其中 Python 的临时目录访问及构建环境仍有问题。因此**不声称原发布门禁全绿**。

改用全新隔离环境后，独立完成了上表的测试、类型检查、构建和资源校验。这些环境问题没有算作新的业务缺陷，也没有通过替换仓库 `.venv` 来掩盖。

## 证据与复现入口

全部运行期输出与合成配额、缓存、冷却文件均位于：

`C:\Users\xuhui\.codex\visualizations\2026\11\09\01a1c01c-2472-7ab3-9017-c2ceddfc1dd1\wensu-audit-0.12.33`

主要文件：`probes.py`、`results.jsonl`、`new-probes.log`、`regressions.log`、`upgrade-profile.log`、`pytest-final.log`、`mypy-full.log`、`release-check-full.log`、`build.log`、`stdio.log`、`http.log`、`live-results.jsonl`、`installation-verification.json`、`downloads/` 和 `built/`。

复现使用该目录 `venv/Scripts/python.exe`：`probes.py new`、`probes.py regressions`、`probes.py upgrade`、`probes.py stdio`、`probes.py http`。首次复现输出已保留；再次运行 `new` 时应使用新的审查目录，避免上一轮特意留下的 stale 登记影响前置状态。

所有合成监听端和 HTTP 测试进程均在结束后关闭。没有下载 PDF/CAJ、没有写入第三方文献库、没有记录账号或 Cookie，也没有修改正式配额与冷却文件；正式额度变化仅来自上述 4 次合法动作。
