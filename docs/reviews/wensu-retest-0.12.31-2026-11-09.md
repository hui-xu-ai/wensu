# 文溯 0.12.31 修复复验

**结论：多项修复已进入新的发行包，原报告尚不能全部关闭。A02 应继续作为发布前的严重正确性问题修复；A08 仍属部分完成；详情端的投影校验和 A09 文档仍有遗漏。**

本次对象为 HEAD `64dc8c879c8d9e79ab775025a66576b2eb10f002` 加现有未提交格式化改动，版本 0.12.31。没有将 PyPI 的 0.12.30 当成修复版本，也没有安装到现有生产 Python 环境。未修改业务代码、格式化文件、提交、打 tag 或发布。

## 已独立验证的事实

- `git status` 中 63 个已修改 Python 文件逐一与 HEAD 比较 AST（包含类型注释），**63 个均相同**。这支持“只有格式化”的交接说明。
- 完整离线测试：**218 passed in 2.51s**。
- 仓库 Ruff 0.17.1：lint 通过；格式检查 **69 files already formatted**。
- 严格类型检查：**Success: no issues found in 44 source files**。
- 五处版本一致、CHANGELOG 条目、两层计划校验通过。
- 用源码构建 **sdist → wheel** 成功；`scripts/check-assets.py` 通过，`background.js`、`content/actions.js`、`content/capture.js` 全部存在；两个渠道 manifest 均存在。
- 新 wheel 隔离安装后执行 `setup --browser edge --no-host`，导出的扩展版本为 0.12.31，`capture.js` 存在。
- 源码和新 wheel 各通过真正的 MCP stdio 客户端复验：五工具可发现；握手 `serverInfo.version=0.12.31`；page/limit 边界确实出现在实际 schema 中。
- 本轮没有访问学术站点、没有消耗真实检索额度。风控、并发及配额错误使用离线合成回放。

wheel SHA-256：`14cbefb03e8b5dbcbf514c9050dd0632d3dfffd654fdc874254a2a0d8d57cbf5`。

证据及复现程序位于：

`C:\Users\xuhui\.codex\visualizations\2026\11\09\01a1bfaf-756c-7de0-a7ea-f46f1ea4fa36\wensu-retest-0.12.31`

包含 `results.jsonl`、`retest.py`、`pytest.log`、`mypy.log`、`release-check.log`、`uv-system-build.log`、`wheel-setup.log`、`wheel-stdio.log`、`tools.json`、`dist/` 和 `clean-package/`。运行数据未写入仓库。

## 仍需处理的问题

### R01 / A02 · 同一 profile 的检索事务仍会串线

**级别**：严重 / P1。

`core/service.py:98` 的提交段和 `core/service.py:124` 的读取段仍各调用一次 `_run`；`core/planner.py:34` 的锁只覆盖各自的 plan，没有覆盖完整检索。

复用了第一轮的确定性离线交错测试：两个服务实例共享浏览器状态和真实计划锁，A 提交后暂停，B 提交，然后分别读取。当前源码仍返回：

```json
{
  "expected":{"A":["QUERY_A"],"B":["QUERY_B"]},
  "actual":{"B":["QUERY_B"],"A":["QUERY_B"]}
}
```

这个结果会进一步按 A 的请求键缓存。它不是仅影响速度的争用，也不是普通的显式失败，而是把另一检索的数据当成成功答案。

**应挑战“不值得持锁 15–20 秒”的判断。** 单请求本来就需要这些时间持有共享页面状态；无人争用时，把锁覆盖提交到读取不会凭空增加 15–20 秒。增加的是其他竞争请求的等待，而共享浏览器本来就不能同时为两个事务提供独立状态。对于已承诺串行执行的工具，这是正确性的成本。

可以选择：

1. 为完整浏览器事务持跨进程锁，覆盖提交、读取及依赖同一页面的后续步骤；所有访问共享页面的 search/detail/journal 路径都要参与，不能只锁 WoS 的两段。
2. 如不希望客户端排队，在提交前检测占用并返回明确的“浏览器忙碌”，不执行任何浏览器动作、不扣额度。
3. 更大改动才需要每请求独立标签页/会话。

不要在服务层直接持有现有的非重入 `plan.lock`，随后又让 Planner 获取同一把锁，那会死锁。应定义清晰的事务锁层次或显式的锁所有权。

CHANGELOG 声明“不支持并发”不能保证两个独立 agent 恰好不会同时调用；工具需要自行排队或拒绝，不能静默返回错误题录。

### R02 / A02 扩展 · 新增 profile_dir 是配置标签，不能证明 host 的实际浏览器身份

**级别**：严重 / P1，同属结果隔离问题。

`native-host/main.py:30–47` 的 `_profile_dir()` 读取全局 `browser.json`，不是启动该 host 的浏览器 profile。`write_endpoint` 把这个值写入每个 host 的端点。两个 profile 共享同一运行目录/注册时，新启动的 host 都会读取同一份记录。

离线模拟两个浏览器对应 host 101 和 202，配置记录 A，调用当前真实 `write_endpoint` 两次，再运行当前 `_candidates`：

```json
{
  "simulated_actual_profiles":{"101":"E:\\ProfileA","202":"E:\\ProfileB"},
  "recorded_labels":["E:\\ProfileA","E:\\ProfileA"],
  "candidate_ports_for_A":[202,101,202]
}
```

其中 202 对应模拟的 B，却被标成 A 并排在 A 前面。这里是离线身份模拟，不是声称已启动两个真实浏览器测得上述端口；确定的代码事实是端点标签来自同一份全局配置，无法区别两个实际父浏览器。

已有三个 profile 测试都手工写入了正确标签，只验证排序/过滤，没有测试标签是否真实产生。因此不能据这些测试宣称“两 profile 串线已经解决”。

建议用与实际浏览器会话绑定的身份或独立配置/注册空间建立映射；如果暂时只支持一个 profile，应检测并拒绝歧义，而不是把预期 profile 赋给任意新 host。不要以这个 advisory 字段作为已经实现隔离的依据。

### R03 / A08 · 未知参数仍被忽略，但可在自有入口解决

**级别**：一般 / P2，保持部分完成。

真正的 `tools/list` 已验证 page 范围 1–3、limit 范围 1–50；`limit=999` 在 Pydantic 校验阶段被拒绝。这部分修复有效。

但 schema 仍没有 `additionalProperties:false`，实际 `status({brief:true,breif:true})` 也正常成功，未知参数没有被报告。对于 search，同类拼写错误可能让 agent 以为某个过滤条件已生效。

现有 FastMCP 的参数模型确实默认忽略额外键；本机 SDK 的 `_setup_handlers` 还明确使用 `call_tool(validate_input=False)`。然而“没有公开配置项”并不意味着必须等待上游或改其内部。

在审查运行目录里验证了一个不改第三方内部的隔离原型：继承 FastMCP，在公开 `list_tools` 返回的 schema 中加入额外键禁令，在公开 `call_tool` 入口按工具参数集合拒绝未知键，然后才调用父类。原型输出：

```json
{"additionalProperties":false,"error":"unknown parameter(s): breif","backend_calls":0}
```

此原型仅证明当前 SDK 1.30.0 下方案可行，没有替换生产 server；正式实现还需要 stdio/HTTP 协议回归和所支持 SDK 版本的兼容性检查。关键是同时做到“schema 声明”和“执行前拒绝”，只改 schema 不够。

### R04 / A05 扩展 · detail/detail_many 的字段拼写错误仍先扣额度

**级别**：一般 / P2。

search 及 CLI search 的 `_check_fields` 前移已经有效：离线后端调用次数为 0，MCP 返回 `quota_charged=0`；新 wheel 的 CLI 退出码 2，输出单行说明。

但 `server.py:416` 的 detail 没有在访问 service 前验证 fields。它先取详情，最后才在 `server.py:477` 的 `_detail_payload` 里发现错误。detail_many 复用了此路径，而且该 ValueError 会让整个工具调用失败。

使用真实 ScholarService、Planner、PolicyEngine 和离线 fixture，对一个未缓存的合法详情 URL 传 `fields=["titel"]`：

```text
detail:      quota 300 -> 299; ToolError: unknown field(s): titel
detail_many: quota 300 -> 299; ToolError: unknown field(s): titel
```

批量用例请求两篇，第一篇就因字段拼写错误使整个调用失败。这些是隔离配额，不是线上额度。

应在 detail 和 detail_many 的入口先统一 `_check_fields`，批量入口也应在处理第一条前拒绝。CLI detail 的投影校验同样在取详情之后，应一并前移。补上验证“错误参数不调用后端、不扣额度”的回归。

### R05 / A09 · 接入文档已修正，README 和工具描述仍过期

**级别**：一般 / P2，部分完成。

`docs/integration/codex.md:85` 已正确列出五工具，也移除了实际工具必须等于描述 schema 文件的错误要求。

仍保留的原问题：

- `README.md:153` 仍写当前版本 v0.12.9。
- README 工具表仍没有 detail_many。
- `server.py:330` 的 search 描述仍无条件宣称检索后详情来自缓存；CNKI 列表不播种完整详情，首次详情仍需网络动作。

这些文字没有因五处版本一致检查通过而自动变正确；A09 不应整条关闭。

## 逐项结论

| 原编号 | 复验结论 | 证据/边界 |
|---|---|---|
| A01 | **修复通过（新发行物）** | 新 wheel 资源自检和隔离导出均包含 capture.js；没有验证全新浏览器的加载界面 |
| A02 | **未关闭** | 原同 profile 交错复现仍失败；新 host 标签不能可靠证明实际 profile，见 R01/R02 |
| A03 | **修复通过** | 合成 blocked 使批次仅访问第一条；ok_count=0、failed_count=1、attempted=1、requested=2、顶层 status=blocked、stopped_early=true |
| A04 | **修复通过** | 空 SearchPage + fields=[title] 返回 records=[]，不再报未知字段 |
| A05 | **search 原场景修复通过；详情端仍需补齐** | search 后端访问 0；detail/detail_many 各先消耗一个离线动作再失败，见 R04 |
| A06 | **原五年限制场景修复** | 真实 detail_by_doi 构造的 WoS 表达式现为 `DO=(...) AND PY=(1900-2026)`；不是完全取消时间限制，仍有 1900 至当年的显式边界；本次未在线验证旧 DOI |
| A07 | **修复通过** | 只有 page_count=9、无 begin/end 的合成题录现在 pages=null |
| A08 | **部分完成** | page/limit 边界有效；额外键仍忽略、fields 未枚举，见 R03 |
| A09 | **部分完成** | 五工具接入说明已修；README 和缓存描述仍有原问题，见 R05 |
| A10 | **修复通过** | Ruff 0.17.1 确认 69 files already formatted；63 个未提交文件 AST 与 HEAD 一致 |
| A11 | **修复通过** | 四种 MCP 文件导出的返回 bytes 与实际大小均相同：RIS 91、EndNote 36、Markdown 25、CSV 135；CLI 写文件分支也改为读取实际大小 |
| A12 | **版本问题修复；安全注解建议尚未实现** | 源码及新 wheel 握手均为 0.12.31；五工具 annotations 仍全部为 null。这项注解建议不是本轮严重阻塞项 |

## 门禁与环境记录

本次原样执行了 `python scripts/release-check.py`。在我的执行环境里，仓库旧 `.venv` Python 3.12.13 仍不能正常写入检查所用临时目录：tests/types/assets/artifacts 失败；版本、CHANGELOG、lint、format、plans 通过。当前脚本定义了九项 CHECKS；没有在此环境独立复现交接所述的“10/10 PASS”。

没有把这些权限问题归为业务逻辑失败。改用系统 Python 3.14.5 和已隔离的构建/类型依赖后，分别验证了全部测试、类型检查、sdist/wheel 构建和资源完整性：

```powershell
# 所有输出、缓存、临时文件均在上述审查运行目录
python -m pytest -q -o addopts='' -p no:cacheprovider --basetemp <隔离HOME>/pytest
python -m mypy --strict --cache-dir <隔离目录>/mypy-cache src
uv build --python D:\Python\Python314\python.exe --no-build-isolation --out-dir <隔离目录>/dist
python scripts/check-assets.py <隔离目录>/dist
python -m pip install --no-deps --target <隔离目录>/clean-package <新wheel>
```

新 wheel 使用已经隔离安装的构建依赖，不替换系统依赖。stdio 复验显式使用 `PYTHONPATH=<隔离目录>/clean-package`，已打印并确认导入路径在该隔离包中，版本为 0.12.31。

本轮是针对修复的离线与发行物复验，不替代第一轮尚未完成的实际 Codex/Claude/Cursor 界面验收、全新 native-host 注册与浏览器加载、以及论文页面逐字段人工对照。PyPI/npm 的版本状态采用交接信息，本轮没有发布，也没有重新查询远程版本。

**建议的下一步**：先修复 R01 的事务所有权与 R02 的 host 身份歧义，再补齐 R03/R04。之后将当前能复现的负向用例纳入门禁，避免“所有已有测试通过”再次掩盖同类缺陷。
