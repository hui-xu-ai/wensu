# wensu 0.14.43 · 两次 goto 的捕获导航复验

**不通过，P1：用户担心的正常读取误拒已真实复现。** 私有补丁的两条 goto 返回不同导航 ID，snapshot 正确跟随第二条文章导航，但内核取第一条 ID 比较，判 `capture_navigation=mismatch`，拒绝发布。

日期：2026-11-27，北京时间。基线 `d1290bb`。本轮仅验证用户指定这一项，没有批量检索、重复访问或修改产品实现。

## 运行身份与范围

官方 PyPI 包、npm bundle、独立 venv、全局 CLI、扩展和 native host 已更新为 0.14.43。用户确认重载扩展；正式 MCP 新会话返回：

```json
{
  "version": "0.14.43",
  "host_version": "0.14.43",
  "worker": "background-0.14.43.js",
  "handshake": "ok"
}
```

私有补丁在两个安装环境自检通过。安装版 53 个 Python 文件与审阅源码一致，排除预期的私有 `core/page_nav.py` 覆盖点；磁盘 worker 与审阅源码一致（换行归一化）。没有使用本聊天旧 MCP 常驻实例。

先以零浏览器动作确认该样本的安装版导航计划确实包含两条 goto，再通过原始 MCP `page_read` 显式刷新读取 **`10.3390/s26041303` 一次**。适配器仅被动记录结果，不改动作与回包。

## 真实导航序列

三个动作均报告同一个 tab_id：`1244771923`。

| 动作 | navigation_id |
|---|---|
| 第一条 goto | `829c8f4b-0437-4c82-963b-9e7addfdbc59` |
| 第二条文章 goto | `72bed8cc-61d0-4d6a-8b3b-85bec308cb2f` |
| snapshot | `72bed8cc-61d0-4d6a-8b3b-85bec308cb2f` |

**捕获 ID = 第二条文章导航 ID，且不等于第一条 ID。** 两条 goto 均 ok=true、navigation_attempts=1。文章落地地址与捕获地址相同，页面自报 DOI 也是请求的 `10.3390/s26041303`。

正式 MCP page_read 耗时 7.991 s，实际回包：

```json
{
  "terminal": "no_page",
  "stage": "identity",
  "reason": "unverified_capture",
  "capture_navigation": "mismatch",
  "mhtml_path": null,
  "bytes": 0,
  "quota_charged": 2,
  "job_id": "934657773050"
}
```

这不是字段 absent，也不是误测旧 worker；新校验真实执行并拒绝了本次捕获。

## 根因与改进建议

位置：`src/scholar_search/core/service.py:1728`。

`read_nav = next(... for outcome in outcomes ...)` 取**首个**非空 navigation_id。私有两导航形态里，它是第一条 goto 的 ID；扩展 snapshot 记录的是该 tab 最近一次、也就是第二条文章 goto 的 ID。因此本例扩展捕获归属正确，内核比较基准选错。

建议将 read_nav 绑定到选中捕获对应的有效文章导航。本次形态应使用第二条成功 goto；若另有 full-view 后续导航，也应按实际捕获来源绑定，不能通用地取整条读取的第一个 ID。保留真正的 mismatch 拒绝，不把校验降为只记录或 absent。

最小回归至少覆盖：单 goto 捕获相符通过；两 goto 捕获跟随第二条通过；两 goto 捕获仍跟随第一条时拒绝。可以先用本轮 ID 序列离线回放，修复前无须再次访问该网站。

## 证据与边界

本轮真实读取 **1 次、2 额度，296 → 294**；没有重试，未触发冷却，没有执行全文转换或下载 PDF/CAJ。没有据单样本推断所有站点或并发场景的稳定性，但该样本已经反证“两 goto 正常路径能稳定 match”的预期。

脚本：`work/verify/2026-11-27-codex-01443/`，包含安装迁移、复用的正式 MCP 观察入口和纯本地 `review_identity.py`。

原始证据只在 `%LOCALAPPDATA%\scholar-search\verification\2026-11-27-codex-0.14.43-p5\`：

- `two-goto-mdpi-events.json`：实际版本、工具参数及原始回包。
- `two-goto-mdpi-actions.jsonl`：两条 goto 与 snapshot 的 ID、tab 和结果。
- `two-goto-mdpi-summary.json`、`identity-review.json`：费用、失败终态、ID 对照与安装一致性。

没有将私有补丁实现、首页表、文章全文、Cookie、账号或桥接 token 写入公共审计材料。
