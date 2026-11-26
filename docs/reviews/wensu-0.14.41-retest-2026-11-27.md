# wensu 0.14.41 · 等待协议与共享状态复验

**上一轮等待动作与窗口聚焦修复已在真实链路通过；整体验收仍有 2 项 P1、1 项 P2。** 新增共享配额后，页面缓存和捕获目录意外串到共享目录；首次迁移并发时可以覆盖已经建立的额度文件；status 的 last_job 读写路径也不一致。

日期：2026-11-27，北京时间。仓库基线 `c39f606`（产品发布提交 `a27d7ac`），官方发行版本 0.14.41。仅安装、测试和记录结果，没有修改产品实现、提交发布或公开私有补丁。

## 安装、版本与测试范围

- 官方 PyPI 和 npm 均提供 0.14.41，已安装独立 venv、全局 CLI、扩展文件、native host 与 DSH desktop bundle；上轮本地 tarball 依赖已切回官方 npm 版本。
- doctor 返回三方版本一致；用户确认重载扩展。新建正式 MCP stdio 会话实证 worker=`background-0.14.41.js`、handshake=`ok`、host_version=`0.14.41`，capabilities 包含 `await_gate_clear`。
- 安装版 53 个 Python 文件与审阅源码一致，排除用户授权的私有 `core/page_nav.py` 覆盖点。私有补丁在两个安装环境自检通过，未进入公开审计材料。
- 保留原 profile `E:\LiteratureEdgeProfile`。配置与扩展备份在新版目录 `upgrade-backups/20261127-004352`；预先记录旧文件和共享状态文件的哈希，旧 quota/cooldown 文件检查后仍保留且哈希不变。
- 本聊天旧常驻 MCP 没有用于新版验收。入口以指定版本 Python 启动原始 MCP 服务，通过 SDK 调用原始工具，仅给适配器附加被动结果与窗口观察。

真实访问只有两篇各一次：MDPI 正常样本、上一轮自然遇墙的 Wiley 样本。浏览器串行，本地转换可与读取并行；没有反复访问制造墙。真实账本 **300 → 296**，总费用 4；300 是新日期的自然日额度，未人为重置。未收到明确 403/429，真实冷却为空；未下载 PDF/CAJ 或写入第三方文献库。

## 1 · 正常读取、哈希与任务观测

MDPI `10.3390/s26041303` 一次显式刷新读取：

| 项目 | 实际结果 |
|---|---|
| terminal / stage | **ok / publish** |
| identity / full_text | declared / true |
| job_id | `33693dc83387` |
| capture_sha256 与落盘文件 | **一致** |
| MHTML 大小 | 671836 B |
| 费用 | 2 |
| 结束后的 browser_busy | false |
| 结束后的 status.last_job | **null，异常，见 F41-03** |

本地正式 `page2md` 转换：engine=sections，coverage=0.607，16 节、7421 token；检查的 46 个长 Markdown 块全部存在于 page.md。输入、meta 哈希一致，input_changed=false。保留 19 个 MathJax 图形公式缺少对应 LaTeX 的告警。

捕获实际保存到了 `...\scholar-search\browser-state\pages\10.3390_s26041303\page.mhtml`，这是 F41-01 在真实默认环境中的直接证据；不能只因为读取成功就忽略存储归属变化。

## 2 · 自然验证、前台最大化与继续捕获

Wiley `10.1002/pi.2828` 一次读取，自然出现“请稍候”标题。实际动作记录：

1. 两条本机导航，分别生成各自 navigation_id；没有重试该 DOI。
2. **await_gate_clear 被宿主放行，ok=true，实际运行约 6.1 s，cleared=true。**
3. 随后继续 snapshot；最多两次本地观察，未额外导航。

原先 `policy.verb` 阻断未再出现。Windows 被动观察记录：动作前前台为 ChatGPT.exe；等待期间 **23 个样本**记录前台为 msedge.exe、窗口 show_cmd=3（最大化）。另只读核对该前台 PID 的命令行，确认属于 `E:\LiteratureEdgeProfile`。因此本轮确实观察到了文溯 Edge **切前台且最大化**。

用户明确确认：**“没有手动操作，页面自行变化”。** 本例证明“自然中间页自清 → 同一次调用继续捕获”，不能记成“人工点击清墙”。本轮未自然遇到持续满 10 秒的墙，因此真实十秒超时仍没有样本；没有再次访问来补齐它。

### 无网页全文是本例的预期结果

捕获后返回 `terminal=partial/stage=capture/full_text=false`，工具原因为 `abstract_only`。用户随后说明：**“刚才这篇文献本身没有网页全文”。** 因此本项归为**预期 partial**，不计作全文抓取缺陷，也不推断用户没有订阅。

原始回包仍完整保存；验收脚本最初自动收集的非 ok 条目保留到 `non-ok-outcomes-original.json`，另写 `expected-partial-outcomes.json` 记录用户确认；本轮 `failures.json` 不再把它列为非预期在线失败。新发现的离线回归在 `review-summary.json` 与下文单独记录。

## 3 · tab/navigation 标识与已有正文修复

两次真实读取的四条 goto 都有非空且互不相同的 navigation_id。每篇顶层及 evidence 的 navigation_id 都等于该篇最后一条 goto 的 id；所有实际 snapshot 的 tab_id 与该篇导航、顶层 tab_id 一致。

这是 ADR 0030 第一片“报告身份”的正面实证。snapshot 尚不带 navigation_id、内核不指定 tab 租约属于 ADR 明示的后续片，本轮不将其误报为本版回归；也不因两例一致就宣称租约或超时取消确认已经实现。

已保存 Springer `10.1007/s11468-024-02246-z` 仅离线重转，未重新访问网站：

- 输入与 meta SHA256 为 `ec603b6b210bb7a20d2cd120a5f591e82f61dc84265fe0bffd115921cd0c7f70`，input_changed=false。
- coverage=0.442，6 节、5006 token；Fabrication Steps 与 Conclusion 同时存在于 page.md、index 及分节。
- 检查的 39 个长 Markdown 块全部匹配，上一轮正文误截断未复现。

两份转换的覆盖率和分节匹配都是结构检查，不等同逐句语义完整度。并行本地转换期间全局共享余额可能因主流程导航变化，不能用某个转换进程的 before/after 差额归因转换收费；本轮总账与四条真实 goto 的 4 额度一致。

## 4 · 新共享状态的正向检查

所有合成测试都使用私有验收目录下的两个新 home 和独立 `SCHOLAR_SEARCH_BROWSER_STATE`，不复制真实 host 端点、不连接浏览器。

| 场景 | 结果 |
|---|---|
| 两个 home 构造服务后的 quota 路径 | 相同 |
| 两边各预留一次合成动作额度 | 两边均看到 used=2 |
| A 的合成 403 冷却 | B 的 risk.ensure_ready 正确拒绝 |
| 两边 browser.lock | 同一路径 |
| 两线程竞争该锁 | 临界区最大同时进入数 1 |
| 合成检查前后真实 quota/cooldown 文件哈希 | **不变** |

这些确认共享锁与常规计数/冷却在该配置下生效，不覆盖下述首次迁移竞争，也不是对真实站点并发施压。

## F41-01 · P1 · 页面缓存和捕获目录意外串 home

位置：`src/scholar_search/core/service.py:965`、`:1856`、`:1883`。

`bootstrap.build_service()` 把 PolicyEngine.state_path 移到共享浏览器目录后，页面读取仍用 `policy.state_dir` 推导页面缓存位置，用其 parent 推导页面文件位置。这把 **page-read.json、pages/.probe 与 pages/<DOI>** 一起搬到了 browser-state。

ADR 0029 及 bootstrap 注释明确说“文档、缓存和审计仍按 home 计”；本轮实际违背了页面文件与页面缓存的归属。

隔离复现（两个真实安装版 build_service、同一共享策略目录、纯合成内容）：

- A/B 的 `_page_cache_path()` 完全相同；B 能命中 A 写入的页面缓存。
- 两边发布同 DOI 返回同一路径，路径不在 A 或 B home 内，而在共享 browser-state。
- B 发布第二份合成字节后，A 持有的原路径读取到 B 的新内容。

真实正常样本也已经落入 browser-state/pages，因此不是仅靠辅助函数构造的假设。影响是同一 OS 用户下不同 home 的文档/验收数据互读和覆盖；不把它扩大描述为跨 OS 用户的泄露。

**建议：** 显式分开 home 的文档/页面缓存根与 browser 的 quota/cooldown/lock 根；页面存储不能从配额路径反推。补两个 home 共用 browser state 的测试，断言策略共享、文档与页面缓存保持各自归属；刷新 B 不改变 A 已发布输入。已有共享目录中的捕获如何迁回需保留哈希和回滚证据，不直接删除或批量覆盖。

## F41-02 · P1 · 首次迁移的检查与写入不原子

位置：`src/scholar_search/core/config.py:113`，调用在 `src/scholar_search/bootstrap.py:233` 附近。

`adopt_legacy_state` 先 `target.exists()`，再 `target.write_bytes()`，没有把“检查缺失、复制、发布”放在同一跨进程初始化保护内。该迁移在 build_service 阶段，早于业务浏览器锁。

用未修改的生产函数做确定调度回放：两个调用都先观察到 target 不存在；第一来源 used=77 先写，第二来源 used=11 后写。结果：

```json
{
  "both_reported_adoption": [true, true],
  "first_written_used": 77,
  "final_used": 11,
  "legacy_sources_retained": true
}
```

调度器仅控制真实 exists/write 的交错，文件读写发生在隔离目录。顺序再调用同一函数会正确拒绝覆盖，说明现有幂等性只覆盖顺序场景。

影响条件是共享文件尚未建立、两个 home/进程同时首次启动；已经建立的共享额度可能被后来完成的旧来源复制覆盖，从而少计。相同迁移函数也用于 cooldown，存在覆盖更严格拒绝状态的同类风险。**本轮没有证明用户真实账本遭到这种覆盖，也没有改动真实计数。**

**建议：** 迁移使用与共享策略初始化/写入协调的跨进程锁，重新检查目标存在性后原子发布，确保已经建立的共享状态不被旧副本覆盖。补两个独立进程同时首次迁移、迁移期间正常预留额度以及冷却版本交错的测试。来源选择策略若要调整，应在迁移契约里明确，不能仅凭测试中较大的数字假定所有场景都应无条件取 max。

## F41-03 · P2 · last_job 写共享目录、status 仍读 home

位置：`src/scholar_search/core/service.py:1821` 与 `src/scholar_search/bootstrap.py:216`。

service 的 `_last_job_path()` 随 policy.state_dir 指到共享目录，`_note_job()` 在那里写文件；status 的 `_last_job()` 仍固定读取 `app_home()/state/last-job.json`。

真实 MDPI 成功后，同一 MCP 会话紧接调用 status：browser_busy=false，但 **last_job=null**。共享目录中的 job marker 实际存在。

隔离回放也确认：A 写 synthetic-job-a，B 的 service.last_job 读到 A；B 写 synthetic-job-b 后，同一共享文件被更新，而 A/B 的 bootstrap status reader 都返回 null。

影响：新增“上个任务已终结”的观测口在正常路径就失效；若旧 home 留有旧 marker，还可能显示过期任务。它也说明仅移动 PolicyEngine 路径会改变依赖该路径的其他状态。

**建议：** 先决定 last_job 是 home 级还是浏览器级，再由同一个明确路径接口供写入者和 status 使用，原子发布 marker，并核对 job_id 与刚结束的读取一致。补正式 MCP `page_read → status.last_job` 回归，而不只单测 service.last_job。

## 自动化检查与下一轮顺序

`scripts/release-check.py` **11 道门全通过**：版本、schema、CHANGELOG、测试、lint、格式、类型、计划、资源、committed、发行物。143 文件格式检查通过、53 源文件类型检查通过，wheel 76 文件且包含两个渠道。测试输出双 quiet，未据省略的进度推算通过数。

首轮检查因测试解释器不能写所选 C 盘临时目录而使部分门未执行；切换到已验证的 D 盘临时目录，并隔离应用 home 与浏览器状态后重跑全绿。两份日志保留；临时目录权限问题不计产品缺陷。自动化全绿没有覆盖这次复现的状态归属和初始化交错。

建议下一轮先处理 F41-01/02，再修 F41-03。三项都能先用本轮合成复现和已保存捕获验证，无须增加在线访问。自然墙的十秒超时与人工完成后续抓尚未现场命中，继续保持“不制造样本、不重试补墙”的边界。

## 证据与文件

脚本：`work/verify/2026-11-27-codex-01441/`。

- `setup_review_install.py`：迁移基线记录、版本化安装和回滚备份。
- `p5_check.py`：正式 MCP 被动观察，按新 browser_state_paths 读实际配额/冷却，记录 goto/snapshot 身份；已有真实 label 的用例拒绝重跑。
- `offline_scope_review.py`：两个隔离 home 的策略、文件、缓存、last_job 与首次迁移交错。
- `summarize_review.py`：本地证据核对、用户更正归类及最终汇总。

原始证据仅在 `%LOCALAPPDATA%\scholar-search\verification\2026-11-27-codex-0.14.41-p5\`：normal-mdpi / natural-wiley events、summary、actions；foreground-profile-check；offline-scope-review；user-observations；expected-partial-outcomes；review-summary；转换输出及发布检查日志。纯合成迁移/冷却状态保存在其 synthetic 子目录，与真实浏览器策略状态分开。

文章全文、Cookie、账号、桥接 token 和私有补丁没有写入公开审计材料；本轮真实额度 **4**，余额 **296**，没有修改产品代码。
