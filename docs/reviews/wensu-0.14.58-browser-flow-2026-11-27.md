# wensu 0.14.58 人工验证与全文获取重测

日期：2026-11-27，Asia/Shanghai。

本报告替代同名旧报告。旧报告混入其他审计项目的验收结论已撤回，本次只验收人工点击验证和最终全文获取结果。

## 验收结果

| 验收项 | 本次结果 |
|---|---|
| 点击机器人验证后进入文献网页 | 成功，用户明确确认“已点击验证，并进入文献网页” |
| 获取完整全文 | **失败**，当前页抓取超时，未获得正文文件 |

这里的全文获取失败是工具本次未取得正文，不能据此判断网页本身是否提供完整正文。

## 测试步骤

使用官方 0.14.58，实际 worker 为 `background-0.14.58.js`，handshake 为 `ok`。

目标：`https://www.sciencedirect.com/science/article/pii/S1385894723029534`。

1. 通过公开 MCP `page_read(url=目标, refresh=true)` 正常访问一次。验证页出现，工具等待超时；用户随后说明当时尚未点击。
2. 用户在保留的验证页手动点击，并明确确认已进入文献网页。
3. 通过公开 MCP `snapshot()` 读取当前页，未重新导航。调用约 17.034 秒后返回 `bridge.error: timed out`，未取得 MHTML，未执行正文转换。

最终没有可核验的正文内容，因此按“全文获取失败”记录。开始时用户尚未点击这一事实与后续抓取失败分别保留，不据此推断根因。

## 原始回包

人工验证后抓取回包的关键字段：

```json
{
  "status": "error",
  "code": "ACTION_BRIDGE_ERROR: TIMED OUT",
  "stage": "snapshot",
  "quota_charged": 0,
  "retryable": false
}
```

本轮实际导航 1 次，总消耗 1 额度，余额 281；收尾 browser_lock 和 browser_lease.state 均为 free。使用 wensu 完成测试，未使用 Computer Use，未修改产品代码。

## 留存证据

运行目录：`C:/Users/xuhui/AppData/Local/scholar-search/verification/2026-11-27/focused-fulltext-0.14.58-7f6b297c/`。

- `acceptance.json`：本轮请求、首次回包、用户确认、前后状态及额度。
- `after-manual-verification.json`：用户完成验证后对当前页的抓取回包及前后状态。

旧轮原始证据保留在运行目录，不纳入本次验收结论。
