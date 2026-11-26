# wensu 0.14.44 · 同 DOI 单次复验

**本次通过。** 对 `10.3390/s26041303` 仅执行一次 `page_read(refresh=true)`，私有补丁实际发出两条 goto，捕获与第二条文章导航一致，正常发布。

日期：2026-11-27，北京时间。基线 `2080f2e`。官方 Python 包、宿主、扩展和桌面 bundle 已升级至 0.14.44，私有补丁自检通过。用户确认重载后，正式 MCP 实证 worker=`background-0.14.44.js`、handshake=ok、host_version=0.14.44。

## 请求字段

```json
{
  "status": "ok",
  "capture_navigation": "match",
  "navigation_id": "a50691d8-ff42-48f5-a608-95d41826a5be",
  "mhtml_path": "C:\\Users\\xuhui\\AppData\\Local\\scholar-search\\pages\\10.3390_s26041303\\page.mhtml"
}
```

## ID 对照

| 动作 | navigation_id |
|---|---|
| 第一条 goto | `df7e6884-caba-4413-bbe5-d80846d63125` |
| 第二条文章 goto | `a50691d8-ff42-48f5-a608-95d41826a5be` |
| snapshot | `a50691d8-ff42-48f5-a608-95d41826a5be` |

三个动作的 tab_id 一致。回包 navigation_id 与第二条 goto、snapshot 三者相同；terminal=ok、stage=publish。文件存在，独立计算 SHA256 与回包一致：`5210147e03b31da4f66e86e3dcb671a8cbdc94c9ca0e8283625d177dd3f55902`。

正式 page_read 耗时 8.285 s，费用 2，真实额度 294 → 292。没有重试、批量访问、全文转换或修改产品实现。结论仅覆盖本次真实两导航读取，不扩大为所有站点和并发场景的稳定性保证。

脚本在 `work/verify/2026-11-27-codex-01444/`。私有原始证据在 `%LOCALAPPDATA%\scholar-search\verification\2026-11-27-codex-0.14.44-p5\`：two-goto-mdpi events/summary/actions，以及 `verified-result.json`。公共材料没有收录私有补丁实现、全文、Cookie 或凭证。
