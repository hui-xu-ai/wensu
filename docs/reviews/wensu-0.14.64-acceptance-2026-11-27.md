# wensu 0.14.64 人工验证与零导航续读验收

日期：2026-11-27，Asia/Shanghai。依据：[0.14.64 验收清单](D:/Python/DeepSeek/DateWork/scholar-search/work/tasks/2026-11-27-lease-receipt/codex-request-0.14.64.md)。

**本篇完整正文获取成功，人工放行后的零导航续读通过。** 初始直读自然遇墙后停止，正常直读的 navigation match 分支没有覆盖；随后仅调用一次 resume_job_id，成功发布正文，未补访其他网页。

## 官方运行版本

独立安装官方 PyPI `wensu==0.14.64`，80 个带摘要的安装文件均与 RECORD 一致，未使用私有补丁。用户确认已重载扩展。

| 检查 | 实际结果 |
|---|---|
| 内核 / 扩展 / 宿主 | 均为 0.14.64 |
| worker | background-0.14.64.js |
| handshake | ok |
| coordination_writable | true |
| features | lease_control=1、operation_receipts=1、readiness_observe=1、capture_receipts=1 |

Python 位于 `C:/Users/xuhui/AppData/Local/scholar-search/installations/0.14.64/venv/`。原生宿主注册指向同版本目录，安装器已执行 coordination 权限设置。扩展部署至原加载目录。当前聊天旧 MCP 连接没有用于读取；两次调用均通过该安装启动的全新官方 MCP stdio 进程，工具 schema 包含 resume_job_id。

## 一 重页面首次读取

只调用一次：

```json
{"url":"https://www.sciencedirect.com/science/article/pii/S1385894723029534","refresh":true}
```

| 字段或证据 | 实际结果 |
|---|---|
| status / terminal / stage | blocked / timeout / wall |
| reason | verification_timeout |
| waited / wait_reason | true / verification_timeout |
| job_id | a8c26d6c0efb |
| mhtml_path | null |
| goto 审计 | 1 次，2765 ms |
| await_gate_clear 审计 | 10087 ms |
| 本次工具调用耗时 | 12.886 s |
| quota_charged / 实际差额 | 1 / 1，281→280 |

本次停在验证阶段，尚未执行加载观察或抓取；readiness 和正常直读的 capture_navigation 不适用。未自动重试。

## 二 人工放行后的零导航续读

用户明确确认原话：**“已完成验证，并进入文献网页”**。

随后仅调用一次，没有 refresh 或补传 DOI：

```json
{"resume_job_id":"a8c26d6c0efb"}
```

| 字段或证据 | 实际结果 |
|---|---|
| status / terminal / stage | ok / ok / publish |
| full_text | true |
| readiness.strategy | observe |
| readiness.state | candidate |
| readiness.elapsed_ms | 617 |
| readiness.budget_exhausted | false |
| 本次工具调用耗时 | 1.108 s，不含之后的离线转换 |
| quota_charged / 实际差额 | 0 / 0，280→280 |
| resumed_from | a8c26d6c0efb，与初始 job_id 相同 |
| 新 job_id | db98f4e1fdaf，与初始 job_id 不同 |
| 原始回包 | 保持原 timeout，留存内容未被续读改写 |
| 续读窗口 goto 行 | 0 |
| 续读动作审计 | snapshot 观察动作 618 ms |
| declared_doi | 10.1016/j.cej.2023.144222 |
| capture_navigation | absent；本次没有新导航，不据此认定正常直读的 match 已通过 |
| browser_busy / browser_lock / browser_lease.state | false / free / free |

实际运行了 observe 策略；本例在 candidate 时开始捕获，没有触发“观察预算用尽仍抓取”的分支。不将候选状态单独当作正文完整的证据。

## 正文与文件核验

正式捕获位于：

`C:/Users/xuhui/AppData/Local/scholar-search/pages/10.1016_j.cej.2023.144222/page.mhtml`

- 文件大小：**2,976,528 字节**。
- SHA-256：`a40d62a4ebce8189c94910c397a1597120053f1478ed8d2e03d3b485897316a4`，正式文件、留存副本与回包一致。
- 内容检查为 ok，正文统计 5353 词。
- 离线 Markdown 包含引言、方法、结果与结论，并与已留存的本篇完整正文参考在统一换行后**逐字一致**，不是仅摘要及少量文字。
- page2md 返回 ok、engine=sections；原始转换告警随 JSON 保存，本轮没有扩展为其他审计项目。

## 验收边界与收尾

已通过：纯官方运行版本和特性握手、自然验证后的人工放行、resume_job_id 零导航续读、实际 observe 策略、正文获取、DOI 目录、文件哈希、新旧 job 关联、真实扣费与释放锁。

未覆盖：无验证阻断时从首次导航直接发布且 capture_navigation=match，以及观察预算耗尽分支。本轮未为补齐分支重复访问或制造验证，也未重跑历史用例。

本轮共 **1 次导航、1 额度**，最后记录余额 **280**，cooldown_until=null。未使用 Computer Use，未识别机构权限，未修改产品代码。

## 留存证据

运行目录：`C:/Users/xuhui/AppData/Local/scholar-search/verification/2026-11-27/acceptance-0.14.64-5c8b970f/`。

- `acceptance.json`：前置握手、两次原始回包、前后 status、额度、用户确认、schema、核验结果。
- `actions.jsonl`：initial 与 resume 两个时间窗口的动作行。
- `resume/page.mhtml`：本次捕获副本。
- `resume/converted/page.md`、`meta.json`、`index.json`：离线正文及转换结果。
- [验收驱动](D:/Python/DeepSeek/DateWork/scholar-search/work/scratch/acceptance-0.14.64.py)：仅编排公开 MCP 工具和保存证据；同一阶段已发出后不允许重复运行。

## 补充记录 用户再次确认放行后的续读

用户另行允许一次访问后，初始调用 `c89b744975e9` 在 wall 阶段等待 10072 ms，返回 verification_timeout。之后用户明确确认：**“我点击了机器人验证，现在是文献全文已经加载完成”**。

仅调用 `page_read(resume_job_id="c89b744975e9")`，结果如下：

| 检查 | 本次实际结果 |
|---|---|
| status / terminal / stage | ok / ok / publish |
| 新 job_id / resumed_from | 4f8fec2a1055 / c89b744975e9 |
| readiness | observe / candidate，619 ms，budget_exhausted=false |
| 续读导航 / 额度 | 0 / 0 |
| 完整正文 | 获取成功；引言至结论共 54441 字符，与前轮完整正文参考一致 |
| MHTML | 2,990,236 字节，回包与文件哈希一致 |
| SHA-256 | ba6372dfe97e6adffbd6e7e0966606efeb9368a650d30b9d710aaaf8fbabac78 |
| 收尾 | browser_busy=false、browser_lock=free、browser_lease.state=free |

这次仍记录为人工确认后的独立续读，不记为首次调用内完成验证并发布。没有再打开、刷新或追加访问。本次访问与续读合计 1 导航、1 额度，余额 279。

补充证据目录：`C:/Users/xuhui/AppData/Local/scholar-search/verification/2026-11-27/same-call-0.14.64-b94080b6/`，包含 acceptance.json、actions.jsonl、resume/page.mhtml 与转换产物。目录名为发起时的测试标签，不表示同次调用分支通过。

规范的 DOI 文件路径已由这次捕获更新；复查上文首轮 SHA-256 时应使用首轮证据目录中的留存副本。
