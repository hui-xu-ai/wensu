# wensu 0.14.34 · P5 复验

**结论：仍不能整体通过。** worker 与能力声明通过；“等待未运行”终态区分通过；Springer 原捕获的正文截断修复通过。真实自然验证页仍无法启动等待，原因已从缺少能力声明变为 **原生宿主动作白名单漏项 `policy.verb`**。这是本轮剩余的一个确定 P1。

日期：2026-11-26，北京时间。仓库基线 `628a264`。使用新安装的 0.14.34 正式 MCP，会话握手及实际 worker 均核对后才访问网站。只安装和审计，没有修改产品实现、发布包或公开私有补丁。超时取消确认、tab/navigation 租约和跨 home 队列保持后续 ADR 范围，本轮未实施。

## 0 · 版本、运行身份与安装来源

正式 MCP status 回包：

```json
{
  "version": "0.14.34",
  "worker": "background-0.14.34.js",
  "handshake": "ok",
  "host_version": "0.14.34",
  "capabilities": ["goto", "snapshot", "sleep", "await_gate_clear"]
}
```

- 独立 venv、全局 CLI、扩展文件、native host 注册和 DSH bundle 均已更新为 0.14.34，doctor 返回 ok。用户确认重载扩展后验证上述实际握手。
- 本聊天暴露的旧常驻 MCP 未用于新版测试。验收入口启动指定 0.14.34 的正式 stdio 服务，通过官方 MCP SDK 调用工具；适配器只被动记录结果及等待期间的窗口状态。
- 安装版 53 个 Python 文件与仓库一致，排除用户授权的私有 `core/page_nav.py` 覆盖点；扩展磁盘 worker 与审阅源码一致（归一化换行）。不是在测旧宿主或旧代码。
- 私有补丁独立恢复并自检通过，原 profile `E:\LiteratureEdgeProfile`、配额和冷却保留。安装迁移备份为新版目录 `upgrade-backups/20261126-233213`。

**DSH 来源需要单独说明：** 本轮查询官方 npm 版本接口及带缓存戳的包元数据，索引均未提供 0.14.34，latest 为 0.14.33；PyPI 0.14.34 可正常安装。因此从当前发布源码 `628a264` 本地 pack 桌面 bundle，逐项确认归档只包含 `package.json/README.md/cordis.patch.yml` 三个公开文件，再安装到原 desktop profile。未发布任何包，没有把私有补丁打包进去。

DSH 依赖当前指向私有安装目录中的本地 tarball，版本为 0.14.34；其 SHA256 为 `e977ea722065a7e87dbf62e269cd1f9922467b61f067cb232e640db2ee2835e7`。打包前备份原 package/lock/workspace 文件；包管理器自动新增的 release-age 例外经精确比较后恢复。后续官方 npm 可用时，可切回官方 registry 版本；本次本地安装不能作为“npm 已发布”的证明。

## 1 · 自然验证、窗口与真实等待

仅读取一次上一轮自然遇墙的真实 DOI **`10.1002/pi.2828`**，没有重复访问制造验证。实际又自然落到 `scijournals.onlinelibrary.wiley.com` 的“请稍候”页。

正式 MCP `page_read` 耗时 **3.733 s**，返回：

```json
{
  "terminal": "blocked",
  "reason": "gate_wait_unavailable",
  "stage": "wall",
  "waited": false,
  "wait_reason": "policy.verb",
  "mhtml_path": null,
  "quota_charged": 2,
  "job_id": "8a654f3d40e2"
}
```

这次等待调用已通过内核能力门，到达原生宿主；适配器记录 `await_gate_clear` 返回 **ok=false/error=policy.verb**。宿主在向扩展写动作帧之前拒绝，因此 worker 的窗口和轮询分支没有执行。

被动窗口观测在调用前记录前台进程为 ChatGPT.exe；等待立即被拒，没有进入 250 ms 的持续观察周期。不能把该记录解释为成功最大化 Edge 或切到前台。

**此项仍未通过的部分：** 窗口最大化且聚焦、人工处理后在同一调用续抓正文、实际等待约 10 s 后返回 timeout/waited=true，都被宿主白名单阻断。没有通过直接调用扩展或放宽校验绕过该层来补“通过”记录。

收到 blocked 后停止全部在线测试，没有再次读取该 DOI、清理冷却、重置风险状态或操作验证码。真实额度 **247 → 245**，无冷却；两条 goto 是本机私有导航形态的正常费用，不是两次重试。

## 2 · 等待未运行与真实超时的终态区分

**等待未运行分支通过真实链路复验。** 上述 `blocked/gate_wait_unavailable/waited=false/stage=wall` 保留了实际原因 `policy.verb`，不再把构建/协议问题说成用户十秒未点击。

对比上一轮同 DOI 的 0.14.33 回包：`timeout/verification_timeout`，虽然等待当时根本未执行。0.14.34 已纠正这处归因。

本轮**没有**真实运行成功后的十秒预算耗尽样本，也没有人工完成后同一调用续抓成功的样本；这两个分支不能因为“等待未运行”分支正确就推定通过。修复宿主前不再用真实访问补样本。

## 3 · 同一 Springer 捕获的离线正文复验

输入为上轮已保存并复制冻结的 Springer MHTML，DOI `10.1007/s11468-024-02246-z`，**没有重新访问原网页**。

输入、转换 meta 及复制件的 SHA256 均为：

`ec603b6b210bb7a20d2cd120a5f591e82f61dc84265fe0bffd115921cd0c7f70`

通过 0.14.34 正式 MCP `page2md` 转换，`input_changed=false`、engine=sections；结果：

| 观测 | 0.14.33 | 0.14.34 |
|---|---|---|
| coverage.ratio | 0.365 | **0.442** |
| 提取词数（同一粗略口径） | 2260 | **2739** |
| Fabrication Steps… 在 page.md | 缺失 | **存在** |
| Conclusion 在 page.md | 缺失 | **存在** |
| 索引及分节 | 6 节、5006 token | **6 节、5006 token，文件均存在** |

逐块检查的 39 个长 Markdown 块全部能在 page.md 找到；Fabrication Steps 的 4 个被检查块及 Conclusion 的 1 个均匹配。分节 tokens 求和、index.total_tokens 与 meta.tokens_total 都为 5006。

最小离线回归也通过：普通句 `The mode is excited by light.` 连同后续 Conclusion 被保留；真正独立的 Cited By 标题会切掉推荐尾部，保留它之前的结论。没有重现裸 `cited by` 子串误截断。

剩余提示为“没有 MathML，公式可能是图片”和疑似残留导航词 sign in；本轮未把它们描述为已修复，也没有将结构一致性检查扩大为逐句语义完整度证明。转换不产生浏览器动作，实际额度未变化。

## F34-01 · P1 · 原生宿主漏放行已批准的等待动作

位置：`src/scholar_search/adapters/bridge/policy.py:21`，拒绝处 `:90`；宿主调用校验处 `src/scholar_search/adapters/bridge/host.py:205`。

`await_gate_clear` 已加入 core.contracts、core.params、core.policy、page manifest 和 worker 能力声明，但 bridge.policy 另有独立 VERBS，仍只有原先的动作，缺少它。

安装版纯离线交叉核验（无真实浏览器动作）：

```json
{
  "core_verb_allowed": true,
  "parameter_validation": null,
  "host_verb_allowed": false,
  "host_request_validation": "policy.verb"
}
```

参数使用实际计划的 `timeout_ms=10000/poll_ms=2000` 及合法门标记；不是未知参数或超时上限问题。真实回包与这个最小校验完全一致。

**建议：** 在宿主闭合词汇表同步放行 ADR 0027 已批准的动作，保留原有参数和权限边界；不用删除白名单或跳过校验。补一个真正穿过 host `validate_request` 的用例，并让核心允许动作、出版社实际计划、宿主允许动作与运行中 worker 声明形成契约验证。仅测试 worker CAPABILITIES 不能覆盖第二道白名单。

修复后先用假扩展/动作帧验证请求确实被转发，再做有限真实复验。还应实测窗口聚焦：当前 worker 分支明确设置 maximized，但没有显式 `focused:true`；本轮因分支未执行，不据此认定真实前台行为一定失败，也不将其判为通过。

## 证据与复验顺序

本轮只做一篇一次真实读取，2 额度；其余是状态查询和已保存文件的本地解析。没有自动重试、制造验证码、下载 PDF/CAJ、写入文献管理器或修改产品代码。

下一步先补宿主动作白名单及跨层契约；之后再在自然验证上核对真正的窗口和等待行为。Springer 截断项本轮已通过，后续回放可继续使用同一个输入，无须在线重新抓。

脚本位于 `work/verify/2026-11-26-codex-01434/`：安装迁移、复用的正式 MCP 被动观察入口、`offline_review.py`。源文件保持审阅基线，没有修复实现。

私有运行证据位于 `%LOCALAPPDATA%\scholar-search\verification\2026-11-26-codex-0.14.34-p5\`：

- `initial-status-events/summary.json`：运行版本和能力声明。
- `natural-wiley-events/summary.json`、`natural-wiley-actions.jsonl`：真实自然墙、宿主拒绝和终态。
- `springer-saved-events/summary.json`、`conversions/springer-saved/`：正式 MCP 本地转换结果。
- `springer-inspection.json`、`offline-review.json`：分节一致性、输入哈希及跨层校验。
- `failures.json`：本轮唯一真实读取的 blocked 结果；`STOP.json` 只用于本轮验收入口防止再次在线访问，未用于更改产品风险状态。

公共审计材料没有收录文章全文、Cookie、账号、桥接 token 或私有补丁实现。
