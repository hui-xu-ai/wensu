# wensu 0.14.55 · 宿主可写性与指定 ScienceDirect 样本

日期：2026-11-27，Asia/Shanghai。仓库参考：`2200fae`。实际测试对象为官方 PyPI 0.14.55 独立安装。

**worker 与 coordination_writable 两项通过。ScienceDirect 只读一次，得到身份校验误拒绝，未取得验证墙终态；没有重试。**

## 1. 用户要求的 status 字段

用户确认重新加载 0.14.55 后，实际 `status.browser_profile.bridge_build`：

```json
{
  "version": "0.14.55",
  "worker": "background-0.14.55.js",
  "handshake": "ok",
  "host_version": "0.14.55",
  "coordination_writable": true
}
```

这部分不访问任何站点。可写性由浏览器启动的宿主执行创建/写入/删除探测文件得到，已经有当前宿主可写该目录的真机证据。

证据范围仅为这次写删探测；没有自然超时或迟到回包，不能将完整归档、锁、去重和恢复协议一起标成通过。

## 2. 安装与调用来源

- Python：`C:/Users/xuhui/AppData/Local/scholar-search/installations/0.14.55/venv/Scripts/python.exe`。
- native host 注册到同一版本的 `browser/native-host/`；保留旧版本和现有 Edge，不关闭或重启浏览器。
- 已有扩展目录更新为 0.14.55，用户手动重载。实际握手确认加载了新文件名。
- 桌面 bundle 同步至官方 npm 0.14.55，doctor 的 CLI/扩展/bundle 版本一致，verdict=ok。
- 私有补丁仅安装到本地 0.14.55 包并自检通过；没有复制到本仓库。
- 真实调用经上述新解释器启动的 MCP stdio 服务，运行模式 observe，专用 profile 为 `E:/LiteratureEdgeProfile`。
- 本轮未修改产品源码、配额、冷却或租约状态；没有调用 PDF/CAJ 下载能力。

## 3. 指定 ScienceDirect URL 的单次真实读取

用户原链接尾部带全角逗号，query 里的 `=` 也被编码。测试去掉尾部标点和追踪 query，保留同一 PII：

```text
https://www.sciencedirect.com/science/article/pii/S1385894723029534
```

仅调用一次 `page_read(url=<上述 URL>, refresh=true)`；没有补传 DOI，没有换网址重试。

实际结果：

```json
{
  "terminal": "no_page",
  "status": "no_page",
  "reason": "capture_mismatch",
  "stage": "identity",
  "doi": "",
  "declared_doi": "10.1016/j.cej.2023.144222",
  "captured_url": "https://www.sciencedirect.com/science/article/pii/S1385894723029534",
  "final_url": "https://www.sciencedirect.com/science/article/pii/S1385894723029534",
  "tab_id": 1244772373,
  "navigation_id": "6e46b73e-ac49-4544-b35d-ee869a9db4b2",
  "capture_navigation": "match",
  "mhtml_path": null,
  "quota_charged": 2
}
```

- job_id：`c8637324eff0`；读取耗时 7.545 s。
- 当前调用时间段的动作审计：两条 goto 成功、随后一条 sleep。没有记录 risk 事件，也未返回 wall/verification_timeout 等终态。
- 配额 290→288，差额 2，与回包和实际两条导航动作一致。
- 收尾：bridge_ready=true、coordination_writable=true、browser_busy=false、browser_lease.state=free，cooldown_until=null。
- mhtml_path=null：身份分支拒绝发布并删除了这次暂存捕获，没有可交付的 Elsevier 文献文件。

因此本次不算验证墙协议通过。既没有真实 10 秒验证超时，也没有人工清墙/自然自清的确认样本；不能据此断言该站不会出现验证。

窗口清单只显示当前激活的扩展页标题，未取得目标文章/验证页面截图；没有把 UI 最大化或前台行为写成已验证。

## F55-01 · P1 · URL-only 请求被空 DOI 错误比较而误拒绝

位置：`src/scholar_search/core/service.py::_page_identity`，约 357 行；请求 identifier 的初始化约 1442 行，调用身份判断约 1774 行。

只传 URL 时 identifier 是空字符串。当前判断逻辑是：

```python
wanted = identifier.casefold()
if declared_doi:
    return (False, "declared") if declared_doi.casefold() == wanted else (True, "mismatch")
```

于是任何正常声明非空 DOI 的页面都会与空字符串比较，得到 mismatch。它并不证明抓到了另一篇论文。

用已安装 0.14.55 的真实函数、仅输入本次回包元数据离线复现：

| 请求约束 | 返回 `(refused, identity)` |
|---|---|
| identifier=""，即原 URL-only 请求 | `(true, "mismatch")` |
| identifier=页面自报 DOI | `(false, "declared")` |
| identifier=明确不同的 DOI | `(true, "mismatch")` |

实际捕获 URL 与请求 URL 完全相同，capture_navigation=match；本次失败的直接原因是上述空 DOI 比较，不能按 next 提示声称“标签页移动了”。本轮没有按该提示重试。

还有一个相关边界：URL 中解析到 DOI 时使用 startswith(wanted)，wanted 为空会无条件匹配。空 DOI 请求需要单独语义，不能继续进入有 DOI 约束的比较分支。

### 建议的最小修改

- 区分“用户提供了 DOI”与“用户只提供 URL”。只有前者可以据页面 DOI 不同判定 DOI mismatch。
- URL-only 请求改为核对请求 URL 与捕获 URL 的文章身份；ScienceDirect 应核对 PII，而非只看同属一个出版社。
- 保留真正的 DOI 冲突、另一 PII、导航身份 mismatch 的拒绝，不要用“空 DOI 一律放行”削弱隔离。
- declared_doi 继续返回页面真实声明，但不要把它事后当成用户一开始提供的约束。
- 失败原因和 next 只陈述已知事实，不在没有证据时归因于用户移动标签页；不要建议自动重试。

### 离线验收

至少新增四组：同 PII 的 URL-only 请求含 DOI；不同 PII；明确请求 DOI 与声明 DOI 冲突；URL-only 且页面不声明 DOI。用 fixture 检查真实 read_page 回包，不能只测 helper。无需再次访问本次 ScienceDirect URL。

当前误拒绝还将 capture_mismatch 写入了页面 blocked 缓存。这个副作用也应随修复检查；本轮保留现状，没有清理缓存或风控状态。

## 4. 上一轮三个内容问题的离线复验

只重用 0.14.53 留下的 MDPI MHTML，没有再次打开 MDPI 网站：

| 原问题 | 0.14.55 结果 |
|---|---|
| F53-01 三张正文表格丢失 | tables_rendered=3、table_rows=25；四个原缺失表头均出现 |
| F53-02 PDF 指向宣传册 | 返回 `https://www.mdpi.com/1424-8220/26/4/1303/pdf`，不再是 flyer.pdf |
| F53-03 成功结果缺 declared_doi | 相关成功回包 fixture 通过；没有另做一次线上成功读取 |

coverage 从 0.597 变为 0.625。19 个 MathJax 公式无对应 LaTeX 的告警仍保留，不将其当成已恢复的公式。

`tests/unit/test_real_capture_findings.py` 4 项通过；service.py、pageprobe.py、page2md.py 已排除 Windows 换行差异后核对，仓库与所安装 wheel 的源码文本一致。

## 证据与后续使用

- 本次验收 JSON：`C:/Users/xuhui/AppData/Local/scholar-search/verification/2026-11-27/wall-0.14.55-22465f07/acceptance.json`。
- 旧 MDPI 的新版离线输出：上述目录 `mdpi-offline/`。
- 实际业务审计：`C:/Users/xuhui/AppData/Local/scholar-search/audit/audit.jsonl`；验收 JSON 已摘取本次调用时间段内的动作，不包含 HTML、Cookie 或端点 token。
- 调用脚本：`work/scratch/verify-real-wall-0.14.55.py`，会真实访问网站；本轮已经执行一次，复查此报告请用保存的 JSON/离线函数，不要为补墙样本重新运行。
