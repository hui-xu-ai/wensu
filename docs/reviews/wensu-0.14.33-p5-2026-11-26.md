# wensu 0.14.33 · P5 真实链路验收

**P5 按授权流程已跑完，整体验收不通过。** 新 worker、单篇发布和文件哈希通过；四家预热及人工确认后，6 篇分组串行读取得到 **4 篇 ok、2 篇失败/部分结果**。4 篇成功捕获全部交子代理转换，其中 **1 篇 Markdown 正文被误截断**。墙协议在真实自然墙上失败，另有预热费用与错误回包问题。本报告确认 **3 项 P1、1 项 P2**，未修复产品实现。

日期：2026-11-26，北京时间。仓库 `05d10e7`，测试对象为官方安装版 0.14.33。仅安装、测试和记录结果，没有修复产品代码、发布版本或公开私有补丁。本轮遵循用户指定范围，超时取消确认、tab/navigation 租约、跨 home 队列继续列为后续 ADR，不在本轮实现。

## 0 · 安装与运行身份

- 官方 PyPI 与 npm 0.14.33 已核对；独立 venv、全局 CLI、Edge 扩展文件、native host 注册及 DSH desktop bundle 已更新。
- 用户确认重载扩展。正式 MCP stdio 新会话返回 worker=`background-0.14.33.js`、handshake=`ok`、version/host_version 均为 `0.14.33`。
- 不使用当前聊天残留的旧 MCP 常驻工具做新版验收。测试入口启动指定版本的正式 MCP 服务，通过 MCP SDK 调用原始工具；适配器仅增加被动结果记录。
- 安装版 53 个 Python 源文件与仓库一致，排除用户授权的私有 `core/page_nav.py` 覆盖点；扩展磁盘 worker 与审阅源码一致（均归一化换行）。
- 原 profile `E:\LiteratureEdgeProfile`、额度和冷却保留；安装备份为新版目录 `upgrade-backups/20261126-224712`。私有补丁独立安装并自检通过，不收录其实现及首页表。

运行中握手能力为：

```json
{
  "worker": "background-0.14.33.js",
  "handshake": "ok",
  "capabilities": ["goto", "snapshot", "sleep"]
}
```

**注意缺少新增的 `await_gate_clear`，见 F33-01。** 首次预检因此在任何页面动作前被验收脚本拦下，真实额度未变；保留该记录为 preflight 证据，不计成一次文章访问。随后仅调整验收脚本，将缺项单独记账，以测试仍受支持的正常读取；没有修改或绕过产品能力门。

## 1 · 单任务正常路径

样本：`10.3390/s26041303`。

| 观测 | 结果 |
|---|---|
| terminal / stage | **ok / publish** |
| identity / full_text | declared / true |
| job_id | `57b78ce3fbe4` |
| prose_words | 3961 |
| MHTML 字节数 | 672192 |
| capture_sha256 | `8b3fdab1cf1db6cce03f502fd43c274fb0331db122525f76baba86ab387a0cd7` |
| 独立读取落盘文件算 SHA256 | **一致** |
| 真实额度 | **265 → 263** |

为了验收 `publish` 而非旧缓存，单篇调用显式指定一次 `refresh=true`；没有重复该真实读取。MCP 回包含 `pdf_url` 只作为页面元数据保存，未请求或下载 PDF。

该成功捕获立即交给子代理 `convert_normal`，仅通过 0.14.33 正式 MCP `page2md` 做本地转换：

- 额度 263 → 263；交接哈希、转换 meta 的 `capture_sha256` 与输入均一致，`input_changed=false`。
- engine=`sections`，coverage=**0.602**（6903 → 4156 个粗略空白词）。
- 16 个分节文件存在，索引总计与分节求和均为 7421 token；39 个长段落块抽查均可在 `page.md` 找到。
- 保留 19 个 MathJax 图形公式缺少对应 LaTeX 的告警；未将该结果描述为公式完整。

## 2 · 自然验证与墙协议

四家预热中，ScienceDirect、Wiley、ACS 的实际导航回包自然出现“请稍候”标题。没有反复访问制造验证，也没有自动点击、识别或破解验证。

这仅证明出现了标题信号，**不能证明已经出现可见验证码、HTTP 403/429，也不能证明 `await_gate_clear` 的 10 秒等待和前台窗口行为通过**。

墙协议在真实批量中也复现失败：Wiley `10.1002/pi.2828` 自然落到 `scijournals.onlinelibrary.wiley.com` 的“请稍候”页，第二条 goto 回 `halted=true`；正式 MCP `page_read` 总耗时仅 **3.297 s**，含原先两次导航，便返回 `terminal=timeout/reason=verification_timeout/stage=wall`，`mhtml_path=null`。动作日志**没有任何 `await_gate_clear`**，因而不是人等了十秒仍未点完。

根因与离线交叉验证一致：真实握手未声明等待动作，能力门返回 `action.unsupported`；用这份能力表做安装版回放，约 **0.0078 s** 就得到相同超时终态。详见 F33-01/02。没有重试这篇文章，没有通过直接调用扩展绕开能力门。

验收观察器准备在真实等待动作期间被动记录 Windows 前台进程、窗口状态和门标题信号，不主动改变窗口或点击验证。由于该动作根本没有发出，不把“窗口最大化、切前台、人工点击后续抓取”或“实等 10 秒”标为通过。修复后还需实际确认前台效果；当前扩展分支只明确设置 `state: maximized`，不能仅凭这段代码推断已经聚焦。

## 3 · 四家预热与分组批量

调用前告知成本并核对预算。按 SpringerLink、ScienceDirect、Wiley、ACS 顺序预热，每家使用单独的 `warm_up([doi])`，每家完成后检查状态与冷却；不把四个目标一次交给会捕获异常并继续循环的工具。

| 出版社 | 预热 DOI | 返回 | 额度 | 标题门信号 |
|---|---|---|---:|---|
| Springer | `10.1007/s11468-024-02246-z` | opened.ok=true | 1 | 无 |
| Elsevier | `10.1016/j.sna.2024.116038` | opened.ok=true | 1 | 请稍候 |
| Wiley | `10.1002/pen.23634` | opened.ok=true | 1 | 请稍候 |
| ACS | `10.1021/acs.inorgchem.1c03019` | opened.ok=true | 1 | 请稍候 |

预热 **263 → 259**，无已上报的 403/429 或真实冷却。上述导航回包的 HTTP status/captcha_visible 均缺失，因此“未上报”不能当作站点未拒绝的保证。

用户明确回复“验证已处理，可以开始批量”后才开始以下 6 篇，全部按出版社分组串行，各调用一次：

| 出版社 / DOI | terminal / stage | 结果 | 额度 |
|---|---|---|---:|
| Springer `10.1007/s11468-024-02246-z` | ok / publish | 捕获哈希通过；转换发现正文误截断 | 2 |
| Elsevier `10.1016/j.sna.2024.116038` | ok / publish | 捕获、转换及结构核对通过 | 2 |
| Wiley `10.1002/pen.23634` | ok / publish | 捕获、转换及结构核对通过 | 2 |
| Wiley `10.1002/pi.2828` | timeout / wall | 自然验证墙；等待动作未执行，误报 verification_timeout | 2 |
| ACS `10.1021/acs.inorgchem.1c03019` | partial / capture | 实际捕获 ACS 首页，192 prose_words；返回 abstract_only，未得到本篇正文 | 2 |
| ACS `10.1021/jacs.6c13448` | ok / publish | 捕获及转换结构核对通过，但全文仅 1 个分节且已告警 | 2 |

样本 DOI 经 Crossref 官方题录核实。本轮不是文献检索结论，未将样本视作主题综述的证据集。Wiley 超时位于本组最后一篇；没有需要再跳过的本组条目，随后进入 ACS。没有重试失败项。ACS 第一篇 partial 不当作全文交给子代理，也不把“落到首页”解释成用户没有订阅。

预热 Wiley 的实际子域为 `4spepublications.onlinelibrary.wiley.com`，第二篇则是 `scijournals.onlinelibrary.wiley.com`。这证明“同出版社预热且用户确认后，另一文献仍可能出现验证”，不能保证预热一次覆盖整组；未读取 Cookie，未推断具体会话原因。

成功项即时交子代理，主流程不等转换而继续下一次串行网络任务。转换均核对输入、复制件/meta 与交接哈希，`input_changed=false`：

| 转换样本 | engine | coverage | 索引 | 独立结构核验 |
|---|---|---:|---|---|
| Springer | sections | 0.365 | 6 节 / 5006 token | **失败**：两个末尾章节在 chunks 中，却不在 page.md |
| Elsevier | sections | 0.493 | 8 节 / 6328 token | 36 个长分节块均在 page.md |
| Wiley 第一篇 | sections | 0.575 | 18 节 / 9761 token | 46 个长段落块均在 page.md |
| ACS 第二篇 | sections | 0.738 | 1 节 / 24576 token | 173 个长分节块均在 page.md；保留章节不足与公式告警 |

这些是结构一致性核验，并非逐句语义完整度证明。正常单篇的 MDPI 另外完成一次子代理转换，不计入批量 4 篇。

运行账本按新版 `terminal` 判定分流。验收脚本曾将 Wiley 的兼容字段 `status=blocked` 误记成整批停止；核对其 `terminal=timeout`、仅标题门信号且真实冷却为空后，修正验收判断，旧标记改名保留为 `legacy-status-harness-stop.json`，再进入下一组。**没有清理产品风控或配额状态。**

## F33-01 · P1 · 新等待动作未加入握手能力表

位置：`extension/background-0.14.33.js:14`、`:742`；`src/scholar_search/core/service.py:1922`。

worker 已实现新分支，但 CAPABILITIES 仍只有 goto/snapshot/sleep。出版社计划的能力门只允许 universal 能力，因此等待动作在发给扩展前就被拒绝。重载无法解决：本轮实际 worker、宿主及源码已一致为 0.14.33。

建议：同步已批准动作的能力声明，补“真实握手能力表 → 计划校验 → 可执行动作”的契约测试。现有不提供 info 的 fixture 可以绕过这一检查，不能替代完整协议验收。先修复并发布新 worker，再复验自然墙，无需增加站点访问来证明当前缺陷。

## F33-02 · P1 · 等待执行失败被伪装成用户 10 秒未完成验证

位置：`src/scholar_search/core/service.py:1076`、`:1456`。

`_await_gate_clear` 捕获 ActionError 等异常后返回 `reason=action_failed`；上层不保留该原因，统一回 `verification_timeout`，并提示“十秒未清”。本轮证据为真实 `page_read` **共 3.297 s（含导航）、等待动作执行数 0**，以及安装版离线回放 **约 8 ms**。

影响：编排会把能力或桥接故障误认成用户没有及时操作，跳过整个出版社；新 terminal/stage 字段看似清晰，但根因仍被吞掉。

建议：区分“等待已执行且预算耗尽”与“等待根本未执行/执行失败”，保留实际错误码、等待耗时和证据。只有扩展明确返回 verification_timeout 时，才使用该终态原因。

## F33-03 · P2 · 预热 403 后回包仍是 ok，且少报额度

位置：`src/scholar_search/core/service.py:1194`。

隔离回放第一家 goto=403、第二家待预热：

- 实际只执行第一条 goto，临时额度 **1**，临时冷却已写入。
- 第二家由策略层冷却阻止，**没有第二次真实或合成导航执行**。
- 工具却回 `status=ok/quota_charged=0`，两项都只记 `action_failed`，继续提示用户完成验证。

因此这里不是证明冷却可被绕过；问题是工具吞掉阻断原因和已用额度，且控制流继续遍历后续目标。只根据工具外层 ok/费用做编排会误判。本轮的单家预热与逐次检查没有修改产品风控，真实配额和冷却也未被合成测试触碰。

建议：RiskBlocked 立即结束预热批次；回传具体信号、cooldown、已执行费用及未执行目标。补首家 403/429 的工具级测试，断言停止位置和费用。

## F33-04 · P1 · 普通正文 excited by 触发截尾，结论整节丢失

位置：`src/scholar_search/page2md.py:736`，裸子串查找在 `:744`，旧 sections 消费在 `:1762`。

Springer 真实捕获与输入哈希均正确，问题出在本地提取。`_cut_tail_markers` 找不到 `## cited by` 标题后，退回对全文裸查 `cited by`；普通科学正文 **`excited by`** 包含这个子串，导致把后面全部当作尾部切掉。

安装版的最小纯合成复现：

```python
_cut_tail_markers("The mode is excited by light.\n\n## Conclusion\n\nImportant result.")
# 实际："The mode is ex\n"
```

该真实输入聚合分节去重后 **20,225 字符**，截尾后 **16,933 字符**；`page.md` 缺少 Fabrication Steps…、Conclusion 两节及 Result Analysis 尾段，而 `index.json/sections` 仍保留它们。coverage=0.365，超过 0.3，并未触发大量缺失告警。

影响：即使 `terminal=ok/stage=publish`、哈希一致、转换成功、覆盖率也不低，AI 仍可能读不到结论。另一路消费者读分节时又拿到更多内容，输出来源不一致。

建议：尾部识别限定在实际标题/语义容器，禁止对科学正文做裸子串截断；裁剪完成后从统一正文结构生成 page、index、chunks、brief/core。加入 excited by、普通句中的 cited by、真正 Cited By 标题三种回放，并检查结论同时存在于各输出。

## 下一轮建议

1. 先修 F33-01/02，保证能力门允许已批准等待动作，真实等待预算与实际错误原因分开。当前自然墙已足以证明问题，修复前不要继续访问补样本。
2. 同时修 F33-04，先通过最小合成回放及已保存 Springer 捕获，不需要再请求原网页。
3. 修 F33-03 的停止/错误/费用回包；以合成 403/429 检查，不在网站上制造拒绝。
4. 发布新 worker 并重载后，再在自然发生的验证上验最大化、聚焦、人工清墙续读和真实 10 秒超时。不能把本轮预热时用户点击与 `await_gate_clear` 续读当成同一通过项。

## 已知范围和材料

本轮真实额度合计 **18**：正常样本 2，预热 4，批量读取 12；**265 → 247**，回包费用总和与实际账本一致。没有收到明确 403/429 信号，真实冷却为空；没有重试失败项或清理风险状态。没有以缺失 HTTP 元数据证明站点安全，合成 403 回放也不计作真实 403 验收。

脚本位于 `work/verify/2026-11-26-codex-01433/`：

- `setup_review_install.py`：复用已审阅的安装迁移。
- `p5_check.py`：版本钉住的正式 MCP、单篇、单家预热检查、哈希核验和纯本地转换；相同真实 label 已有证据时拒绝重跑。
- `protocol_regressions.py`：用实际能力表回放等待入口与预热 403，零真实浏览器动作，状态存于运行目录的 synthetic 子目录。
- `summarize_p5.py`：仅读本地证据，按六篇计划生成抓取汇总、抓取失败及转换质量失败账本，并核对额度总账。

私有原始证据在 `%LOCALAPPDATA%\scholar-search\verification\2026-11-26-codex-0.14.33-p5\`，包括正式 MCP events/summary、被动 actions 日志、子代理 conversion/inspection、protocol-regressions、installation-checks、batch-plan 与 batch-summary。

- `failures.json`：2 条真实读取未得到全文的结果（Wiley timeout、ACS partial）。
- `conversion_failures.json`：1 条捕获成功后的正文截断质量失败（Springer）。
- `preflight-findings.json`：首次零动作预检的能力缺项，单独记录，不计文章访问失败。
- `failures-before-final-summary.json`：保留汇总前账本，不丢弃验收过程记录。

全文、账号、Cookie、桥接 token 和私有补丁未写入本轮公共材料。子代理只在各自输出目录处理本地文件，未调用网络读取工具或操作浏览器。
