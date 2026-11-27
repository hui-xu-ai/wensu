# wensu 0.14.57 · F55-01 单次真实读取复验

日期：2026-11-27，Asia/Shanghai。交接单：`work/tasks/2026-11-27-lease-receipt/codex-request-0.14.57.md`。仓库参考：`55eb3ca`。

基线澄清：本报告的真实读取使用“官方 0.14.57＋本地私有导航补丁”，不是纯官方版基线。用户随后更正流程：今后默认使用官方版，除非明确要求，不使用私有补丁。当前安装已恢复官方文件；该次历史结果仍按补丁环境解读，不能用来验收纯官方版的验证墙行为。

**F55-01 已通过真实链路复验：URL-only 请求成功，identity=url，不再与空 DOI 比较而误拒绝。除“按 DOI 命名目录”这一项外，交接单列出的正常读取、捕获、计费和收尾条件均成立。**

## 1. 安装与握手

- 官方 PyPI 0.14.57，新 venv：`C:/Users/xuhui/AppData/Local/scholar-search/installations/0.14.57/venv/`；未覆盖 0.14.55 venv。
- 新宿主注册到 `…/installations/0.14.57/browser/native-host/com.scholar.search.json`，执行该版 coordination 权限设置。
- 0.14.57 扩展资源已导出，并同步到已有加载目录；用户明确确认“已重新加载 0.14.57”。
- 桌面 bundle 同步 0.14.57，doctor verdict=ok；私有补丁仅装入该独立安装且自检通过，没有进入本仓库。
- 真实调用由新安装解释器启动的 MCP stdio 服务执行，profile 为 `E:/LiteratureEdgeProfile`，模式为默认 observe。

读取前后的实际握手均为：

```json
{
  "version": "0.14.57",
  "worker": "background-0.14.57.js",
  "host_version": "0.14.57",
  "handshake": "ok",
  "coordination_writable": true
}
```

## 2. 唯一一次真实请求

```json
{
  "url": "https://www.sciencedirect.com/science/article/pii/S1385894723029534",
  "refresh": true
}
```

没有补传 doi，没有重试，没有更换网址，没有清缓存、冷却或租约文件；没有重跑任何历史 MDPI/Springer 用例。

## 3. 实际结果与断言

| 项 | 实际结果 |
|---|---|
| status / terminal / stage | `ok / ok / publish` |
| identity | `url` |
| full_text | `true` |
| 题名 | A chemotactic microrobot with integrated iridescent surface for optical-tracking |
| captured_url / final_url | 均与请求的 ScienceDirect URL 相同 |
| declared_doi | `10.1016/j.cej.2023.144222` |
| capture_navigation | `match` |
| tab_id | `1244772567` |
| navigation_id | `8c982fb5-667c-4acd-8fb2-cc4570426e02` |
| job_id | `b2dda71c4858` |
| 捕获大小 | 2,874,736 bytes |
| SHA-256 | `69f82f474e0ca43f0ae8879f7835d921ec3d2ce822f2a3c53638a0466c9842d3`；重算与回包相同 |
| MCP 读取耗时 | 6.636 s |
| 配额 | 288→286，实际扣费 2，与 quota_charged=2 一致 |
| 动作审计 | 两条成功 goto、一条成功 sleep；没有 risk 事件 |
| 结束 browser_lease.state | `free` |
| 结束 browser_lock / browser_busy | `free / false` |
| cooldown_until | `null` |

保存文件的 citation_doi 已离线核对为 `10.1016/j.cej.2023.144222`，不只依赖回包字段。

### 目录命名：交接单有一项未满足

实际发布路径：

```text
C:/Users/xuhui/AppData/Local/scholar-search/pages/A-chemotactic-microrobot-with-integrated-iridescent-surface-ae7b52ea/page.mhtml
```

文件归属正确：在 home 的 pages 下，不在 browser-state/pages；但没有放进预期的 `10.1016_j.cej.2023.144222/`。

原因可从 `src/scholar_search/core/service.py:1905` 看出：发布时仍传入请求 identifier；URL-only 请求的 identifier 为空，于是 `_page_slug_for`（约 470 行）按标题和 URL 哈希命名。页面已发现的 declared_doi 没有用作该存储键。

这不影响本轮 URL 身份修复、捕获归属或文件完整性通过，但严格按清单不能称“全部断言全绿”。若 DOI 目录确为要求，应在 URL 身份核验通过后，以有效的页面 DOI 生成存储键；若保留 URL-only 的标题/哈希规则，则应调整交接断言。不能只是移动验收文件伪装成产品输出，本轮未移动发布文件。

## 4. 用户遇墙与本次采样的差异

用户报告手动点击此链接会遇到机器人验证。本次 wensu 专用 profile 的唯一调用成功返回论文正文，没有返回 blocked、verification_timeout、navigation_unconfirmed 或 waited 等验证终态，动作审计也没有 risk 事件。

因此只能确认这次样本没有提供墙协议证据，不能推断用户不会遇墙，也不能把人工点击、自清、最大化前台或真实等待超时写成通过。两种访问表现不同的原因本轮未单独验证。

没有为取得验证样本再次访问，也没有代点验证码。

## 5. F56-01 权限分支

按交接单的附带检查，使用仓库 `.venv` 解释器在默认沙箱下运行一次 status，实测：

```json
{
  "version": "0.14.57",
  "browser_lock": "denied",
  "browser_busy": false,
  "browser_lock_held": false
}
```

安装版在实际读取前后均为 browser_lock=free。权限不足与锁竞争已在这两种真实执行环境中分开；没有为这个检查创建竞争读取或访问站点。

## 6. 留存证据

本轮目录：`C:/Users/xuhui/AppData/Local/scholar-search/verification/2026-11-27/real-0.14.57-8c19518e/`。

- `acceptance.json`：原始 MCP 读取回包、前后完整 status、各项断言、配额差额、审计行及 denied 分支观测摘要。
- `actions.jsonl`：本次时间窗的动作审计行。
- `capture/page.mhtml`：发布文件的验收副本，保留用于离线复查，原发布文件仍在 home/pages。
- `capture-sha256.txt`：验收副本 SHA-256，与原发布文件和回包一致。
- 探针：`work/scratch/verify-real-read-0.14.57.py`。本轮已执行一次；它会访问真实网页，复核本报告请使用留存文件，不重复执行。

本轮只新增验收探针和报告，未修改仓库产品实现，未公开私有补丁。
