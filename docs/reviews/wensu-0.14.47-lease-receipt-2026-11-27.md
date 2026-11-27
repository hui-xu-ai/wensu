# wensu 0.14.47 · 四项复验与超时边界

日期：2026-11-27。源码：`af9a412`。本轮不安装、不操作真实浏览器、不访问网站。

**指定四条全部通过；补充边界复现两项问题，其中一项仍会把已发送请求描述为“未发出，可以再试”。**

## 测试对象与证据范围

- 从本仓库 0.14.47 源码启动独立 MCP stdio 服务；客户端 list_tools 确认 navigation_status 存在，status.version 确认 0.14.47。
- 使用独立临时 SCHOLAR_SEARCH_HOME、SCHOLAR_SEARCH_BROWSER_STATE；不修改真实配额、冷却、租约和私有补丁。
- 迟到链路使用真实 BridgeHost、native framing、归档器和 MCP 查询，浏览器回包为构造输入。
- 第一/第二条 goto 及客户端 socket 超时使用真实适配器/Planner/service 与假 socket、fixture；没有实际网络请求。
- 相关 **57 项 pytest 测试通过**；独立验收探针执行成功。新发现的边界问题作为输出证据保留，没有因其存在把探针执行失败当成产品结论。
- 不把本次源码测试写成发布 wheel、桌面连接、真实 worker 或低完整性宿主权限的安装验收；真机自然超时仍需日后偶发样本。

探针：`work/scratch/verify-lease-receipt-0.14.47.py`。产品代码未修改。

## 1. 两个碰撞 ID 均返回未知：通过

在隔离账本中保留上一轮输入：归档 probe/collision，再分别经 MCP 查询 probe/collision 和 probe?collision。

两者均为：

```json
{
  "known": false,
  "operation": {"state": "unknown", "navigation_issued": null},
  "quota_charged": 0
}
```

非法 ID 不再通过文件名别名命中另一记录。实现为摘要文件名加记录内 ID 精确比对；合法已知 ID 的查询另有正向用例通过。

## 2. 导航后 policy.domain 归档：通过

复用报告原输入：ok=false、error=policy.domain，data 带 navigation_attempts=1、navigation_id=nav-redirect、tab_id=43。

先让真实 BridgeHost.request 超时，再通过真实 framing 交给 reader，最后经独立 MCP 查询：

```json
{
  "known": true,
  "operation": {
    "navigation_issued": true,
    "navigation_id": "nav-redirect",
    "tab_id": 43,
    "outcome": "navigated_then_refused",
    "error_code": "policy.domain"
  },
  "quota_charged": 0
}
```

F46-02 的归档错误已修复；不再将这个回包解释为未发出。

## 3. 超时边界回包只归档一次、不投递：通过

使用两线程与事件屏障，在真实 _wait 完成超时转移、request 尚未返回时送入旧请求回包；额外重复送达同一帧，并放置一个无关 pending waiter。

```json
{
  "reply": {"error": "bridge.timeout"},
  "archive_calls": 1,
  "archived": true,
  "orphan_still_registered": false,
  "unrelated_waiter_untouched": true
}
```

随后 navigation_status 查询 known=true、navigation_issued=true、outcome=landed。转移已进入同一临界区，上一轮确定性丢回包窗口未再出现；重复帧没有二次归档或污染其他 waiter。

## 4. 查不到时保持三值未知：通过

独立 MCP 查询 probe-never-existed，结果为 known=false、operation.navigation_issued=null、quota_charged=0。未将不存在的事实降为 false。

独立 MCP 状态与所有本地查询前后，隔离配额保持 300→300。

## 相邻两项修复的确认

- F46-04：active/unconfirmed 且 browser_busy=false 时，admission_blocked=false；模拟账本读取 PermissionError 得 state=unknown、readable=false、error=lease_state_unreadable、admission_blocked=false。
- F46-01 常规桥超时：两 goto 回放中第一条成功、第二条 bridge.timeout，读取顶层、evidence、last_job 均给出 second-op，不是 first-op。真实 BridgeAdapter 的匹配超时回复与客户端读超时也都会带上本次发送的 ID。

但 F46-01 的“绝不沿用前一个动作 ID”仍有下述发送前失败边界；socket 超时的用户提示也仍不诚实。

## F47-01 · P1 · 客户端读超时仍被描述为未发出、可重试

位置：`src/scholar_search/adapters/bridge/__init__.py:400`；`src/scholar_search/core/service.py:225`；stage/terminal 映射见同文件 `:146`、`:173`。

离线步骤：

1. 真实 BridgeAdapter.execute → _send；假 socket 已成功接收发送的 JSON 请求，记录其 request id。
2. 读回复时抛 TimeoutError("timed out")，得到 error="bridge.error: timed out"，operation_id 正确保留。
3. 将这一真实适配器产生的错误和 data 回放入读取服务。

实际读取结果（ID 略）：

```json
{
  "status": "error",
  "terminal": "partial",
  "stage": "render",
  "reason": "bridge.error: timed out",
  "unconfirmed": false,
  "operation_id": "the-id-that-was-sent",
  "next": "the navigation failed before it was issued: ask again."
}
```

根因：_navigation_unconfirmed 用 `"timeout" in code` 分类，但客户端异常字符串是 `timed out`；于是落入“未发出、再试”的分支。read_page 随后重新计算 stage/terminal，又把它写成 render/partial。

socket 已写出不能证明浏览器已导航，也不能证明未导航；正确答案只能是未确认。当前的 operation_id 是对的，但提示仍可能诱发第二次导航。这与用户指出的 F46-02 同属“无证据却给出安全重试答案”的问题，发生在读取回包层而非已修好的归档层。

最小修改建议：

- 由异常类型和派发阶段产生稳定错误分类，不能让 TimeoutError 混入任意 bridge.error 字符串后再猜。
- 已进入发送/等待、又没有明确未发出证明的路径，保持 navigation_unconfirmed、unconfirmed=true、stage=navigate；真正的 socket 超时返回 terminal=timeout。
- “未发出，可以重试”的提示只能由明确前置拒绝证据产生；无证据时不能把默认 else 写成这一结论。
- 保留本次 operation_id，查询与迟到归档仍走现有通路，不自动重试或清理风险状态。

验收：除 bridge.timeout 外，至少覆盖真实 TimeoutError("timed out")、发后读 EOF/连接重置，以及明确发送前失败。断言前两类不出现 before it was issued / ask again，且不会误标 render/partial。

## F47-02 · P2 · 同一适配器下一次连接失败会返回旧动作 ID

位置：`src/scholar_search/adapters/bridge/__init__.py:357`、`:400`、`:416`。

_last_request_id 只在 _send 生成新 ID 时赋值；execute 在 _connect 之前没有重置或分配本次 ID。异常分支直接取该共享成员。

离线步骤：同一适配器先执行一个成功 goto，再关闭其连接；下一次 execute 的 _connect 抛 ConnectionError("no live native host found")，没有发送第二个动作。

```json
{
  "first_id": "same-old-id",
  "second_id": "same-old-id",
  "second_error": "bridge.error: no live native host found",
  "second_action_sent": false,
  "reused_previous_id": true
}
```

此反例没有声称第二次导航真的发出了；错误在于**用第一次成功操作的查询键回答第二次失败**。查询这个键可能得到上一篇的成功事实，违反“指失败那一次动作，不是前一条成功 goto”。本例是同一适配器实例复用/重连边界，不等同于正常两 goto 的常规链路失败。

最小修改建议：每次 execute 开始就建立独立的本次身份，传入 _send，并在所有返回路径使用该局部身份；或明确发送前无对应操作时返回空身份和前置失败事实。至少不能回退到上一次成员值。

验收：同一实例 success→close→connect failure；以及新动作在 settimeout/写帧前失败。第二次返回的 ID 不得等于第一次；真正已写出的第二次读超时仍须精确等于其发送 ID。

## 复现与回归

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:TEMP='D:\Python\DeepSeek\DateWork\.tmp'
$env:TMP=$env:TEMP
$env:TMPDIR=$env:TEMP
& .\.venv\Scripts\python.exe work/scratch/verify-lease-receipt-0.14.47.py
```

该脚本会自行创建隔离 home/browser-state，断言四项验收和正向 ID 传递，并输出 F47-01/F47-02 的观测结果。退出码 0 是探针执行完毕，不表示这些附加问题也已修好。

本轮另在隔离 home/browser-state 下运行以下 8 个测试文件，共 57 项通过：test_lease_contract、test_bridge_late_reply、test_bridge、test_bridge_not_ready、test_capture_lease、test_tools_json_matches_server、test_tool_schema_contract、test_response_budget。

建议先处理 F47-01，再补 F47-02 的回归；本轮不主动修产品代码。
