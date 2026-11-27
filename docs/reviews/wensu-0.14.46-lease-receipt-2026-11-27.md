# wensu 0.14.46 · 租约与迟到回执复验

日期：2026-11-27。源码基线：`0cdaa6b`。范围：用户指定的三项观测，不访问文献网站。

## 验收结论

| 用户要求 | 结果 | 证据边界 |
|---|---|---|
| 不存在 operation_id 时诚实返回未知 | **普通不存在 ID 通过；ID 别名碰撞不通过** | 0.14.46 独立 MCP stdio 进程真实工具调用 |
| 锁空闲、租约非 free，observe 模式不声称强制准入 | **正常路径通过；异常分支有缺陷** | active/unconfirmed、brief/full 已验证；读取异常时仍返回 admission_blocked=true |
| 超时后查询迟到回执 | **离线基本路径通过；不能宣布真机验收完成** | 真实 BridgeHost framing + 假扩展回包 + MCP 查询；发现身份缺失、错误归因和丢回包竞态 |

现有相关回归 **27 项通过**。额外探针发现的问题见后文；不能把既有测试全绿当成本轮没有问题。

## 版本与测试方法

- 当前聊天连接的旧 MCP `status.version=0.14.44`，没有 navigation_status 工具；本机全局 Python 安装也仍是 0.14.44。
- **本报告的新功能证据来自 0.14.46 仓库源码启动的独立 MCP stdio 服务**。客户端先 list_tools 确认 navigation_status 存在，再调用 status 确认 version=0.14.46。
- 这不是已发布 wheel 的安装验收，也不是桌面旧会话已重连的证明。未安装升级、未重启或重载浏览器。
- SCHOLAR_SEARCH_HOME 和 SCHOLAR_SEARCH_BROWSER_STATE 均指向独立临时目录；未改动真实配额、冷却、租约或浏览器配置。
- 导航全部为 fixture 或假 streams，不启动浏览器，不访问文章、首页、登录或验证页面。真实站点访问次数为 0。
- 只按本版 P1a/observe 契约验收；不将未实现的 enforce、worker 续体隔离或实时 tab 查询误算为本版遗漏。

离线探针：`work/scratch/verify-lease-receipt-0.14.46.py`。运行时数据在临时 home，源码中不包含私有补丁。

## 1. navigation_status 的诚实性

通过独立 MCP 客户端查询 `probe-never-existed`：

```json
{
  "ok": true,
  "known": false,
  "target_operation_id": "probe-never-existed",
  "source": "ledger",
  "operation": {"state": "unknown", "navigation_issued": null},
  "quota_charged": 0
}
```

回包 next 也明确说明不能将缺少账本解释为未发出。查询前后隔离配额均为 300。普通不存在 ID 的路径通过。

但补查 ID 身份后发现反例：只归档 `probe/collision`，查询从未存在的 `probe?collision`，竟返回 known=true、navigation_issued=true。两者被转换成同一个文件名，读取时又未核对记录中的 operation_id。此项不能整体判定通过，见 F46-05。两个示例 ID 都是本地探针构造，没有真实网站请求。

代码：`core/service.py:1914`。有效的非空不存在 ID 与非法空参数是两种情况；本项不以空参数错误替代未知 ID 验收。

## 2. status 的锁与租约字段

在隔离目录写入 active 租约和 executing 操作，保持 browser.lock 可取；真实 MCP 返回：

```json
{
  "version": "0.14.46",
  "browser_busy": false,
  "browser_lock_held": false,
  "browser_lease": {
    "state": "active",
    "operations": 1,
    "unresolved": ["probe-unresolved"],
    "admission_blocked": false
  }
}
```

brief 与完整 status 均确认上述意义。将该隔离租约转为 unconfirmed 后，admission_blocked 仍为 false。**这符合本版不强制的刻意设计，不是主路径 bug**。但该字段也不证明旧导航已经停止。

额外边界：模拟 LeaseStore.read 抛 PermissionError，`bootstrap._lease_summary()` 返回：

```json
{"state": "unknown", "admission_blocked": true}
```

这时并未启用 enforce，却声称 admission_blocked=true，字段含义与正常分支不一致。列为 F46-04，不能据此称“所有异常分支也通过”。

## 3. 迟到回包归档与查询

### 已通过的离线通路

1. 调用真实 BridgeHost.request(goto)，假扩展不及时回复，得到 bridge.timeout。
2. 使用真实 native framing 注入该 request id 对应的迟到 action_result。
3. 由真实 reader 和 archive_late_reply 写入隔离账本。
4. 从独立 MCP 进程调用 navigation_status 查询同一 ID。

结果：

```json
{
  "known": true,
  "operation": {
    "action": "goto",
    "state": "settled",
    "navigation_issued": true,
    "navigation_id": "nav-late",
    "tab_id": 41,
    "quiescent": true,
    "outcome": "landed"
  },
  "quota_charged": 0
}
```

未知 ID、丢失回执时的查询仍返回 known=false、navigation_issued=null，没有自动变成 false。

### 尚未获得的现场证据

本轮没有读取网页，自然也没有真机偶发 bridge.timeout。因此没有证明：真实扩展的迟到回包、浏览器低完整性宿主的实际归档权限、或现场宿主退出后的查询行为。

应等待以后一次正常授权读取中自然出现超时，按其实际 operation_id 查询，不为补样本重复导航。这一条仍标为“待自然现场样本”，不能用假回包代替。

## 发现的问题及下一轮最小修改

### F46-01 · P1 · 读取超时回包没有交出可查询的 operation_id

位置：`src/scholar_search/adapters/bridge/__init__.py:345`、`core/service.py:202`、`core/service.py:1984`；工具说明见 `server.py:923`。

工具说明让调用者从 read.evidence 或 status.last_job 取得 operation_id，但实际链路未提供：

- BridgeAdapter._send 生成 transport request id；收到匹配回复后，只把 reply.data 放入 ActionOutcome，丢弃顶层 id。
- socket 超时的 execute 异常返回同样不保留该 ID。
- _page_evidence 和 _note_job 的白名单均无 operation_id。
- 假 socket 回放真实 _send 得到 error=bridge.timeout、data={}；fixture 读取进一步返回 timeout/navigation_unconfirmed，但顶层、evidence 与 last_job 均无 operation_id。

影响：归档文件按 request id 可被正确查询，但正常调用者拿不到这个键，无法执行用户要求的“查该 operation_id”。job_id 不能代替 action 的 ID，两条 goto 尤其不能混为一个。

最小修改建议：发送前建立并保留该动作 ID，匹配回复和客户端读超时都返回同一 ID；通过 ActionOutcome/ActionError、读取 evidence、last_job 逐层传递。暴露的是**失败或未确认的那一次动作**，不是前一条成功 goto 的 ID。无需为了补这个键提前实现整套 P1b context 信封。

验收：在假 socket 中记录发出的 id，令该动作超时；断言读取回包和 last_job 提供的 operation_id 与它完全相同，再用该 ID 归档/查询迟到帧。覆盖第一条与第二条 goto 超时、宿主回包超时和客户端 socket 超时。

### F46-02 · P1 · policy.domain 不能证明导航未发出

位置：`src/scholar_search/core/lease.py:423`、`extension/background-0.14.46.js:1030`。

archive_late_reply 将所有 policy.* 错误统一归为未发出：

```python
refused = error.startswith("policy.") or error in {"no_active_tab", "policy.params"}
```

但真实 worker 在 goto 已调用、已取得落地页后，仍可能因越域返回 policy.domain；该分支的数据明确带 navigation_attempts=1、tab_id 和 navigation_id。

向真实归档链输入这种 worker 已有的回包形态，再从 MCP 查询，实际得到：

```json
{
  "known": true,
  "operation": {
    "navigation_issued": false,
    "navigation_id": "nav-redirect",
    "tab_id": 43,
    "outcome": "refused",
    "error_code": "policy.domain"
  }
}
```

**这是错误的已知 false，比 known=false 更危险。** 错误发生于导航之后，不能被解释为可安全重复发起。这里没有实际访问越域网站；使用的是源码既有分支对应的假回包。

最小修改建议：按导航阶段与结构化证据判断；不能按错误前缀猜 false。明确的发出证据优先，无法证明前置拒绝时保留 null。outcome 应保留“已发出但越域被拒”的事实，不混同“根本未发出”；不新增 page_read terminal/stage。

验收：至少覆盖导航前 policy 拒绝、发出后 policy.domain、HTTP 403/429、未知 bridge 错误。断言后两类不能被错误地写成未发出，且仍保留既有风控停止规则。

### F46-03 · P2 · pending 移除与 orphan 登记之间仍会丢回包

位置：`src/scholar_search/adapters/bridge/host.py:126`、`:253`、`:96`。

当前 _wait 在锁内 pop pending，然后 request 退出该函数，再重新取锁登记 orphan。两个临界区之间存在空档。

探针使用两个真实 Python 线程和事件，确定性安排以下时序：

1. waiter 超时，pending 已移除；暂停在 _wait 返回之前。
2. reader 收到有效的迟到 action_result；此时既无 pending，也无 orphan，回包被丢弃。
3. 恢复 request，登记 orphan，向调用者返回 bridge.timeout。

实际结果：

```json
{
  "reply": {"error": "bridge.timeout"},
  "archived": false,
  "orphan_still_registered": true,
  "query": {"known": false, "operation": {"navigation_issued": null}}
}
```

查询的未知语义仍诚实，符合用户要求的 fallback；但已经到达的事实被丢掉，迟到路径的完整性不足。现有测试是“登记 orphan 后再送帧”，没有覆盖这个交接空档。

最小修改建议：在同一个 Condition 临界区完成 pending→orphan 转移；提前记录该业务 request 的动作元数据。区分 hello/control 与业务操作，不能把握手超时误归档成导航。

验收：保留上述事件屏障用例，禁止使用随机 sleep 碰运气；断言 reader 在交接边界到达也只归档一次，且绝不交给下一 waiter。

### F46-04 · P2 · observe 的读取异常分支声称已阻断准入

位置：`src/scholar_search/bootstrap.py:239`。

正常 active/unconfirmed 回包正确；PermissionError 分支却固定 admission_blocked=true。该字段描述本版实际准入行为，不能同时用来表达“状态不可信，建议别读”。

最小修改建议：observe 继续诚实表示未强制；使用独立错误/健康字段报告账本无法读取。将来 enforce 模式按实际拦截结果返回，不混用两种含义。

验收：参数化 free、active、unconfirmed、quarantined、损坏记录与读取异常；分别断言 lease 事实、错误事实和 admission_blocked 的实际行为。

### F46-05 · P2 · 不存在的 ID 可误命中另一操作的账本

位置：`src/scholar_search/core/lease.py::operation`、`_safe_name`；对外查询见 `core/service.py:1914`。

_safe_name 把不同特殊字符都替换成下划线，并截断到 80 字符。operation() 根据该文件名加载记录后，不验证 payload.operation_id 是否等于请求 ID；service 还把请求 ID 回显为 target_operation_id，使调用者看不出结果来自另一操作。

离线实测仅归档 `probe/collision`，MCP 查询 `probe?collision` 返回：

```json
{
  "known": true,
  "target_operation_id": "probe?collision",
  "operation": {"navigation_issued": true, "outcome": "landed"},
  "quota_charged": 0
}
```

此时不存在所查 operation_id，正确结果应为未知或明确参数错误。运行时自动生成的短十六进制 ID 不属于本例的碰撞输入；问题在于公共工具接受任意字符串，既没有拒绝这类输入，也没有保证精确身份匹配。

最小修改建议：读取后强制校验实际 operation_id；文件键采用不发生这种别名的编码或摘要，或以明确格式拒绝非法/过长 ID。兼容旧文件的读取也必须做身份核对，不能继续静默返回别人的事实。

验收：字符替换碰撞、80 字符截断碰撞、普通未知 ID、已知 ID 精确查询；未知输入不能得到其他记录的 known=true。

## 复现与回归命令

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:TEMP='D:\Python\DeepSeek\DateWork\.tmp'
$env:TMP=$env:TEMP
$env:TMPDIR=$env:TEMP

& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider `
  tests/unit/test_lease_contract.py `
  tests/unit/test_bridge_late_reply.py `
  tests/unit/test_tools_json_matches_server.py `
  tests/unit/test_tool_schema_contract.py

& .\.venv\Scripts\python.exe work/scratch/verify-lease-receipt-0.14.46.py
```

前者本轮 27 项通过。后者退出码 0 表示探针执行完毕、正向断言成立；其输出还包含上文已复现的缺陷，**不是所有负向场景均已通过**。

优先处理 F46-01/F46-02，再补 F46-03/F46-04/F46-05 的边界回归。此次只新增复验报告与离线探针，未修产品代码，未触碰私有补丁。
