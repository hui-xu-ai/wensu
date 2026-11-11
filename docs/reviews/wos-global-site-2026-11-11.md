# Web of Science 全球站（www.webofscience.com）支持评估

**日期**：2026-11-11（当日三次修订）
**最终结论**：全球站已可用（0.12.54），**通过 BibTeX 导出取数**，不依赖接口抓取；
影响因子来自用户自备 JCR 表建成的本地库。

## 一、最终形态

```
检索：goto 高级检索 → 输入 → 提交 → 等结果列表
导出：#export-trigger-btn → #exportToBibtexButton → 内容切「完整记录」→ #exportButton
取数：扩展回报下载路径 → 内核读 .bib → parse_bibtex → Record
影响因子：ISSN 查本地 jcr.sqlite（不回落到 0，查不到即 null）
```

真实样本（166 KB，39 条）：DOI 39/39、摘要 39/39、关键词 33/39、影响因子 35/39。
**缺影响因子的 4 条全是会议论文**（ISSN `1084-6999`、`0277-786X` 为会议系列），JCR 不收
会议录，属正确行为而非匹配失败。

代价：**每次检索 8 个网络动作**（镜像站抓取是 4 个），因为导出需要四次点击。

## 二、为什么不用接口抓取

`capture.js` 在顶层窗口 hook `window.fetch` 与 `XMLHttpRequest`，而 `.com` 上
`runQueryGetRecordsStream` 的请求**不经过它们**（`data-wensu-seen` 记录了页面所有
fetch/XHR 路径，其中没有该端点）。请求由我们无法覆盖的上下文发出。

导出方案把"猜站点内部实现"换成"用站点自己提供的公开功能"，且 BiBTeX 是规范格式，
可离线回放测试。

## 三、四次失败与根因（按发现顺序）

| 现象 | 根因 | 修法 |
|---|---|---|
| `policy.params` | 原生宿主跑的是旧版参数表 | 装新版本（`ALLOWED_KEYS['click']` 加 `expect_download`） |
| `produced no file` | `onCreated` 监听器在点击**返回后**才挂，事件早已触发 | 点击前挂 |
| `bridge.error: timed out` | 内核 socket 读超时 = 动作超时（15s），与服务端同时到期 | 客户端多等 2 秒 |
| `bridge.timeout` | 下载等待吃掉宿主全部 15 秒预算 | 等待上限 = 声明预算 − 3 秒 |
| `[saw not-a-bib:blob:…]` | 导出是 **blob URL**，创建时 `filename` 为空，被名称/URL 判断排除 | 改按标签页归属判定 |
| 无 `[saw …]` | `onCreated` **一次都没触发**（文件仍完整落盘） | 改为轮询 `downloads.search` |

**教训**：前三次都在推断"它为什么没触发"，实际它每次都触发、每次都被自己的过滤规则挡掉。
加上"被拒绝的下载连同原因一起回报"之后，一次就定位了。

## 四、已知限制

**装了第三方 "WoS BibTeX assistant" 扩展时必须关掉**。实测：它开着时导出弹窗里四个
选择器 `wait_for` 全部超时；关掉后 46ms / 0ms 秒过。它会重新渲染弹窗，可见性判断看到的是
已脱离文档的节点。

## 五、影响因子库

- `wensu jcr import <xlsx>` → `%LOCALAPPDATA%\scholar-search\data\jcr.sqlite`
- 实测导入 22 249 JCR 行 + 21 772 中科院分区行，2.5 秒，7.2 MB
- **不随包分发**：数据归 Clarivate
- 读取用标准库（`zipfile` + `ElementTree`），与 openpyxl 交叉验证一致
- **ISSN 优先**：工作簿刊名被截断到约 29 字符（`CA-A CANCER JOURNAL FOR CLIN`），
  刊名只能做前缀兜底；多个命中时返回空 —— 错的影影响因子比没有更糟
- edition 取自列头（`2024JIF` → 2024），不取表名（`2025JCRIF-分区`）


