# wensu 0.14.57 · 纯官方版真实验证超时验收

日期：2026-11-27，Asia/Shanghai。**本次为纯官方版，不含私有导航补丁。**

结论：指定 ScienceDirect 页面自然出现机器人验证；一次直达导航后，真实等待 10.127 秒仍未清除，工具正确返回 verification_timeout，并停止。验证页没有作为文献发布，未重试或代点。

## 1. 测试基线

- 安装：`C:/Users/xuhui/AppData/Local/scholar-search/installations/0.14.57/venv/`。
- `core/page_nav.py` 的 SHA-256 与该 wheel 的 RECORD 一致，`page_warmup.json` 不存在。
- 在全新 Python 进程离线检查导航工厂：只有一次直达 goto，不经过出版社首页。
- 实际 worker：background-0.14.57.js；version/host_version=0.14.57，handshake=ok，coordination_writable=true。
- 当前聊天的旧 MCP 连接仍报 Transport closed，因此使用上述安装的全新 MCP stdio 进程；没有调用旧常驻进程。
- 沿用已有 `E:/LiteratureEdgeProfile` 和浏览器会话，没有清 Cookie、缓存、配额、冷却或租约。模式为默认 observe。

只调用一次：

```json
{
  "url": "https://www.sciencedirect.com/science/article/pii/S1385894723029534",
  "refresh": true
}
```

没有补传 DOI、换网址或重复读取。

## 2. 实际回包

```json
{
  "status": "blocked",
  "terminal": "timeout",
  "reason": "verification_timeout",
  "stage": "wall",
  "signal": "title:请稍候",
  "title": "请稍候…",
  "waited": true,
  "wait_reason": "verification_timeout",
  "action_required": "manual_verification",
  "mhtml_path": null,
  "bytes": 0,
  "quota_charged": 1,
  "full_text": false,
  "full_text_reason": "verification_timeout"
}
```

job_id：`289b612a2249`。MCP 读取总耗时 **11.645 秒**。

动作审计提供了实际执行时间，不只是回包声称 waited=true：

| 动作 | ok | 耗时 |
|---|---|---|
| goto | true | 1476 ms |
| await_gate_clear | true | **10127 ms** |

这里 await_gate_clear 的 ok=true 表示等待动作已执行并正常回包，不表示验证已通过；读取终态仍为 timeout。

## 3. 计费与收尾

| 项 | 结果 |
|---|---|
| 实际导航数 | 1 |
| 配额 | 286→285，差额 1，与回包一致 |
| browser_lease.state | free |
| browser_lock | free |
| browser_busy | false |
| cooldown_until | null |
| coordination_writable | true |

返回的风控信号为标题验证。工具未返回 403/429 拒绝信号，也没有设置 24 小时冷却。本报告不根据验证页外观猜测未观测到的 HTTP 状态。

本轮没有发布新的文献捕获；先前已存在的文献文件没有删除。未执行 snapshot、page2md 或任何后续在线计划。

## 4. 只读 UI 观察

在线计划结束后，仅通过 Computer Use 读取当前窗口和截图：

- 地址栏为指定的 ScienceDirect URL。
- 页面明确显示 **Are you a robot?**，并要求完成 captcha challenge。
- 观察时窗口处于最大化状态（窗口控件显示“还原”）。
- 没有点击、键入、刷新或操作验证控件。

没有记录等待期间完整的前台切换时间线，因此只确认事后窗口最大化，不能据此断言自动抢焦点过程已验收。截图包含页面展示的网络标识，未另行复制进仓库报告；验收 JSON 只保存上述必要观察摘要。

## 5. 通过与未覆盖范围

通过：纯官方基线、单次直达导航、自然验证识别、真实约 10 秒等待、verification_timeout/wall/waited=true 的区分、无文献发布、实际扣费和收尾字段。

未覆盖：人工完成验证后的同次调用续抓、自然自清、bridge.timeout 迟到回执、enforce/旧代续体围栏，以及本次被墙挡住后的文章身份和正文捕获。normal_capture_checks 在该样本中不适用，不能把未执行的成功分支当成身份修复回归。

本次与之前“官方包＋私有补丁”的成功样本必须分开解读；不把此前两次导航的结果当作纯官方版行为。

## 6. 证据

运行目录：`C:/Users/xuhui/AppData/Local/scholar-search/verification/2026-11-27/official-0.14.57-8821182d/`。

- `acceptance.json`：官方文件校验、原始读取回包、前后完整 status、normal_capture_checks（本次不适用）、wall_checks、只读 UI 摘要。
- `actions.jsonl`：本次 goto 和 await_gate_clear 的原始动作审计行。
- 探针：`work/scratch/verify-official-read-0.14.57.py`，已执行一次，复查请只读取留存证据，不再次访问站点补样本。

所有墙分支断言均成立。没有修改产品实现、安装私有补丁或清理风控状态；验证页面保留在浏览器中。
