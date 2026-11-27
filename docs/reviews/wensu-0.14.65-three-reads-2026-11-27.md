# wensu 0.14.65 三次读取验收

日期：2026-11-27，Asia/Shanghai。依据：[three-reads-0.14.65.md](D:/Python/DeepSeek/DateWork/scholar-search/work/tasks/2026-11-27-lease-receipt/three-reads-0.14.65.md)。

**① 正常直读导航匹配通过；② 观察预算耗尽仍捕获通过；③ 本轮未触发抓取超时，迟到回执分支未覆盖。** 三次普通读取均未遇到机器人验证，均取得完整正文文本。没有重复访问补样本。

## 官方版本与测试设置

独立安装官方 PyPI `wensu==0.14.65`，80 个带摘要的发行文件均与 RECORD 一致，未使用私有补丁。用户已重载扩展；实际运行内核、宿主及扩展均为 0.14.65，worker=`background-0.14.65.js`，handshake=`ok`，coordination_writable=`true`，readiness_observe/capture_receipts 等四个特性位均为 1。

每项通过该安装启动独立 MCP 进程，公开调用 page_read 一次，refresh=true。诊断环境变量只传给对应子进程；开始下一项前不继承上一项的诊断变量。没有改变网站、浏览器配置、缓存、配额、冷却或租约文件。

| 项目 | 实际加载观察预算 | 实际抓取请求预算 |
|---|---|---|
| ① 正常直读 | 30000 ms | 55000 ms |
| ② 观察预算耗尽 | 50 ms | 55000 ms |
| ③ 抓取超时诊断 | 30000 ms | 200 ms |

有效配置由同环境下的新 Python 进程读取并保存，均已核对。

## 一 无验证阻断的正常直读

请求：`page_read(doi="10.1016/j.sna.2024.116038", refresh=true)`。

论文：**Piezo-Ionic Actuator for Haptic Feedback**。该 DOI 来自本机既有成功读取记录，属于同一出版社；本次重新正常导航读取，没有使用缓存回包。

| 检查 | 实际结果 |
|---|---|
| status / terminal / stage | ok / ok / publish |
| full_text | true |
| capture_navigation | **match** |
| navigation_id | d2a1e8fd-f6a0-4b51-b668-102270460591 |
| readiness.strategy / state | observe / candidate |
| readiness.elapsed_ms / budget_exhausted | 623 / false |
| declared_doi | 10.1016/j.sna.2024.116038 |
| 目录 | pages/10.1016_j.sna.2024.116038/page.mhtml |
| 文件大小 | 1,676,978 字节 |
| SHA-256 | 45e79b7e860aad35a3e7fd43fbc24d2b499ad133a2cecf29bff0d68cac88cc13 |
| 调用耗时 | 5.180 s |
| goto / 额度差额 | 1 / 1，279→278 |

主文包含引言、实验/表征、结果与讨论、结论，且从引言至结论与本机留存完整正文参考逐字一致。文件、回包及留存副本哈希一致。**本项通过。**

## 二 观察预算耗尽后仍然捕获

仅此项子进程设置 `SCHOLAR_SEARCH_READINESS_BUDGET_MS=50`。

请求：`page_read(doi="10.1016/j.cej.2023.144222", refresh=true)`。

| 检查 | 实际结果 |
|---|---|
| status / terminal / stage | ok / ok / publish |
| full_text | true |
| readiness.strategy | **observe** |
| readiness.state | **observing** |
| readiness.budget_exhausted | **true** |
| readiness.elapsed_ms | 215，记录实际用时，不将 50 ms 配置值当成实际耗时 |
| capture_navigation | match |
| navigation_id | 76a99bb8-2a59-4c08-9004-6b44baa3fef1 |
| 目录 | pages/10.1016_j.cej.2023.144222/page.mhtml |
| 文件大小 | 1,270,355 字节 |
| SHA-256 | 5c28bb3928bf47832c80f48e7d5b2b2152406d216ee2f68929ecfee647cb609f |
| 调用耗时 | 3.603 s |
| goto / 额度差额 | 1 / 1，278→277 |

预算用尽没有令调用放弃：实际生成了可读 MHTML，并完成发布。主文各章节齐全；规范化 Markdown 图片标记后，正文文字与已留存完整参考一致。图片标记有差异，不将这一比较写成图片/公式的无损验收。**I3 的本次真机分支通过。**

## 三 200 ms 抓取预算未触发超时

仅此项子进程设置 `SCHOLAR_SEARCH_SNAPSHOT_TIMEOUT_MS=200`，加载观察恢复默认 30000 ms。

请求：`page_read(doi="10.1016/j.cej.2023.144222", refresh=true)`。

| 关注字段 | 清单希望命中 | 本次实际结果 |
|---|---|---|
| stage | capture | **publish** |
| reason | capture_unconfirmed | **空字符串** |
| terminal | timeout | **ok** |
| mhtml_path | null | **实际文件存在** |
| quota_charged | 1 | 1 |
| operation_id | 超时操作 id | 成功回包未提供该超时操作 id |
| known | 查询迟到回执 | **未查询，本次没有 capture_unconfirmed 操作** |

补充实际字段：readiness=observe/candidate，elapsed_ms=616，budget_exhausted=false；capture_navigation=match；full_text=true；调用总耗时 2.921 s；文件 2,899,428 字节，SHA-256=`bd11204376dcda7d97968319cee788ce72d68c42f7e66f15aee9c1b069bc7459`。主文从引言到结论与完整参考逐字一致。额度 277→276。

本地核对确认预算入口已接入首捕获和分块请求：[service.py](D:/Python/DeepSeek/DateWork/scholar-search/src/scholar_search/core/service.py:2510)、[分块请求](D:/Python/DeepSeek/DateWork/scholar-search/src/scholar_search/core/service.py:2061)。该预算是请求预算，不能由整次调用总耗时推断是否应超时，也不能保证 200 ms 必然触发目标分支。

**本项记为未覆盖，不计通过，也不判为迟到回执缺陷。** 没有重复访问、进一步缩短至非法预算或制造故障；没有拿其他操作的 id 代替捕获超时 id。由于没有发生该次超时，清单中的“查不到则等 30 秒再查”步骤不适用。

## 环境恢复与收尾

两个诊断变量均只存在于测试子进程中，未写入全局或持久环境。测试结束后，父进程中的两个变量均为空，有效默认预算为加载观察 30000 ms、抓取请求 55000 ms。

三项各一次读取，共 **3 次 goto、3 额度，279→276**。每项收尾 browser_busy=false、browser_lock=free、browser_lease.state=free，cooldown_until=null。未使用 Computer Use，未测试机构权限，未修改产品代码。

本轮只需将本报告与对应原始证据交回。此前 0.14.64 的人工验证续读结果仍为历史已通过证据；本轮补齐了无验证直读 match 与观察预算耗尽分支，捕获超时/迟到回执仍待受控样本。

## 留存证据

运行目录：`C:/Users/xuhui/AppData/Local/scholar-search/verification/2026-11-27/three-reads-0.14.65-1713a202/`。

- `acceptance.json`：三个场景的请求、有效配置、完整回包、前后 status、检查结果、正文比对与环境清理。
- `actions.jsonl`：三个窗口的原始动作及场景标记。
- `direct/`、`readiness_exhausted/`、`capture_timeout/`：各自捕获副本和转换产物。
- `reference/`：仅用于离线正文比对的既有捕获副本。
- [验收驱动](D:/Python/DeepSeek/DateWork/scholar-search/work/scratch/three-reads-0.14.65.py)：每场景只能发出一次读取，环境预算只对子进程生效。

哈希复查应使用各场景留存副本：第二、三项为同一 DOI，第三项正常更新了规范 DOI 路径中的文件。
