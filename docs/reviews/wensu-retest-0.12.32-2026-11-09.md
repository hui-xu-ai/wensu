# 文溯 0.12.32 第三轮审查

**结论：仍不建议发布。新 host 歧义检查会阻断正常单 host 连接；检索事务锁没有覆盖详情调用，仍可串线并污染缓存。未知参数拒绝和 MCP 详情字段校验已修复，CLI 详情入口仍有遗漏。**

审查对象：HEAD `9a43eb3957233ee0fca646543aa28614d795dec7`，版本 **0.12.32**。开始时工作区干净。本轮只新增本报告，没有修改业务代码、提交、打 tag、替换现有安装或访问学术站点。

## 1. [P1] 同一个 host 的两个端点文件被误计为两个 host

**定位**：`src/scholar_search/adapters/bridge/__init__.py:99–111`；端点生成逻辑在 `native-host/main.py:69–73`。

正常的 `write_endpoint` 会同时写入：

```text
host/bridge.json
host/hosts/bridge-<同一PID>.json
```

两份文件描述的是同一个 host。新的 `_candidates` 把二者都加入 `ordered`，未按实际端点身份去重，也未先确认存活，就把相同 profile 标签的多个文件视作多个运行中的 host。

**复现**：

1. 创建隔离 HOME，写入合法的单 profile 配置。
2. 启动一个仅响应 ping 的本机合成 TCP host。
3. 调用当前原生宿主的真实 `write_endpoint`，生成正常的两份端点文件。
4. 通过隔离安装的新 **0.12.32 wheel** 启动标准 MCP stdio 服务，调用 `status(brief=true)` 和 `search(query="synthetic",limit=1)`。

**实际输出**（省略 profile 绝对路径）：

```json
{
  "endpoint_files":2,
  "unique_pids":1,
  "status_isError":true,
  "search_isError":true,
  "message":"2 native hosts are running and all of them report the same profile ...",
  "ping_count":0
}
```

合成 host 只有一个，且监听正常；服务在发起任何 ping 前就拒绝。此复现没有启动真实浏览器，也没有请求学术站点。

**影响**：正常单浏览器在拥有 browser.json 和新版端点字段时即可进入错误路径，连接状态与检索都不可用。“关闭多余浏览器”无法解决同一 host 的重复文件问题。

**建议**：先按实际进程/端点身份合并 legacy 与 registry 别名，再排除失活端点，最后对无法确认归属的多个真实存活 host 判断歧义。现有 `test_one_host_is_never_ambiguous` 只创建一份 registry 文件，没有复现真实 writer 的两份文件布局；应添加 writer → discovery 的回归。

## 2. [P1] 事务锁只约束 search，detail 仍能插入检索的提交与读取之间

**定位**：`src/scholar_search/core/service.py:116`、`:314–328`；`journal` 的同类路径为 `:332` 起。

`search` 确实持有新 `browser.lock`，search/search 的原始串线场景已通过。`detail` 和 `journal` 仍直接执行 `_run`，只持有另一把 `plan.lock`，没有参与浏览器事务锁。

**复现**：两个真实服务实例共享策略目录、浏览器状态和真实锁实现；使用合成渠道及虚拟时钟，不访问站点。A 完成分段检索的提交后暂停，保留 browser.lock；B 尝试 search、detail 或 journal；再恢复 A 的读取。

| B 的调用 | A 恢复读取前 B 是否完成 | A 返回题名 | A 的缓存题名 |
|---|---|---|---|
| search QUERY_B | 否，正常等待 | QUERY_A | QUERY_A |
| detail B | 是 | **DETAIL_B** | **DETAIL_B** |
| journal B | 是 | **JOURNAL_B** | **JOURNAL_B** |

检索与详情交错的实际动作顺序：

```text
A type QUERY_A
A click submit
B goto detail/B
B read_html -> DETAIL_B
A read_html -> DETAIL_B
```

随后检查 A 的实际 SQLite 缓存，已经保存了 DETAIL_B；合成 journal 用例也保存了 JOURNAL_B。journal 用例是服务层合成能力测试；**detail 本身是已公开的 MCP 工具，足以触发主要风险**。

**影响**：两个客户端分别检索和取详情时仍可能得到错误的成功结果，且后续命中缓存会重复该错误。

**建议**：所有依赖或改变共享浏览器页面的现场操作使用同一个事务边界。至少覆盖 search、detail 和现有 journal 路径；已缓存的数据可以继续在锁外返回。不要在 detail_by_doi 的外层简单增加相同非重入锁，再调用会自行持锁的 search/detail，以免死锁。添加 search/detail 交错回归，不能只测两次 search。

## 3. [P2] CLI detail 仍在取详情之后才验证 fields

**定位**：`src/scholar_search/cli.py:343`；`:389` 的 `_check_fields` 位于 detail 分支返回之后，仅覆盖 search。

**已修复的部分**：MCP detail/detail_many 在字段拼写错误时均未消耗离线配额，300 → 300，返回 quota_charged=0。

**仍可复现的部分**：CLI detail 用真实 ScholarService、Planner、PolicyEngine 和离线 fixture，执行：

```text
detail https://example.org/article/1 --channel fake --field titel
```

**实际输出**：

```json
{
  "exit":2,
  "quota_before":300,
  "quota_after":299,
  "stderr":"wensu: unknown field(s): titel. available: ..."
}
```

这是隔离回放配额，非线上消费。CLI 已有简短报错，但错误仍在访问后端后发现。

**建议**：将 `_check_fields` 移到 search/detail 的公共入口，在分支取数之前执行，并测试两个入口的错误字段均不会调用后端。

## 4. 文档剩余问题

上一轮 R05 的三个具体文字问题已修复：README 不再硬编码 0.12.9，工具表补齐 detail_many，search 描述按渠道解释详情费用。

不过 README 的“并发”部分（142–144 行）仍写“分段检索在提交与读取之间会释放锁”，与新 search 事务锁不符；还把 WENSU_PROFILE 描述成可选中不同 profile，而当前宿主标签仍来自共享配置，歧义检测也有第 1 项问题。应在并发修复完成后，按实际排队/拒绝和 profile 支持范围统一更新。

## 5. 通过的检查与修复

| 项目 | 本次结果 |
|---|---|
| 完整离线测试 | **220 passed in 2.54s** |
| Ruff lint | **All checks passed!** |
| Ruff 格式 | **69 files already formatted** |
| 严格类型 | **Success: no issues found in 44 source files** |
| 版本一致 | 五处均为 **0.12.32** |
| CHANGELOG / 两层计划校验 | 通过 |
| sdist → wheel | 构建成功 |
| wheel 扩展资源 | background.js、actions.js、capture.js 均存在，check-assets.py 通过 |
| 新 wheel 隔离安装 | 成功，实际导入路径和版本已确认 |
| MCP stdio | 握手版本 0.12.32，发现五工具 |
| 未知参数（原 R03） | 五工具 schema 均有 additionalProperties=false；`breif`、`year_form` 实际返回 isError=true，未调学术站点 |
| MCP 详情字段（原 R04 的 MCP 部分） | detail/detail_many 错误字段均不扣离线额度 |
| search/search 并发 | 等待后各自得到正确结果，线程均正常结束，无死锁 |
| HTTP | 正确认证后发现五工具并调用 status；无 token/错误 token 为 401，外域 Host 为 403 |

这些通过项不覆盖第 1–3 项的新复现。现有测试没有覆盖真实端点双文件布局、检索与详情交错、CLI 详情字段错误的零费用要求。

原样运行 `python scripts/release-check.py` 仍受本执行环境中旧 `.venv` Python 3.12.13 的临时目录写入问题影响：tests/types/assets/artifacts 失败，其他项通过。改用系统 Python 3.14.5 和隔离工具后，独立完成了上表测试、类型、构建与资源检查；没有声称原脚本已全绿。

构建使用：

```powershell
uv build --python D:\Python\Python314\python.exe --no-build-isolation --out-dir <隔离目录>/dist
python scripts/check-assets.py <隔离目录>/dist
```

新 wheel SHA-256：`86a37f40303a3bb4b518058e925e82b5e3202c288cff0bd8a8ed70bbe48742ce`。

原始证据、隔离包与复现程序保存于：

`C:\Users\xuhui\.codex\visualizations\2026\11\09\01a1bfaf-756c-7de0-a7ea-f46f1ea4fa36\wensu-retest-0.12.32`

主要文件：`check.py`、`results.jsonl`、`pytest.log`、`release-check.log`、`mypy.log`、`build.log`、`tools.json`、`wheel-stdio.log`、`dist/`、`clean-package/`。合成监听端在复现结束后已关闭；未下载全文、未写第三方文献库、未改变线上配额或冷却。
