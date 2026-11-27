# wensu 0.14.53 · 真实浏览器验收

日期：2026-11-27，Asia/Shanghai。仓库参考：`d458294`，测试对象为从官方 PyPI 安装的 **0.14.53 wheel**。

**正常导航、正文判定、捕获归属、文件哈希和配额核对通过。另发现三项内容/观测问题；没有主动制造验证或超时。**

## 实际安装与运行链路

- 新解释器：`C:/Users/xuhui/AppData/Local/scholar-search/installations/0.14.53/venv/Scripts/python.exe`。
- 使用新版 setup 导出扩展、注册 native host，并运行安装器的 coordination 权限设置；保留 `E:/LiteratureEdgeProfile`。
- 桌面 profile 的 `@hui-xu-ai/dsh-wensu` 更新至官方 npm 0.14.53，doctor 返回 `verdict=ok`。
- 用户授权的私有补丁仅装入上述独立 Python 安装，自检 `RESULT patch is active`；补丁代码和配置没有复制进本仓库。
- 启动原专用 Edge profile 一次。待宿主就绪后确认：Python/host/extension 均 0.14.53，`worker=background-0.14.53.js`、`handshake=ok`；features 包含 lease_control=1、operation_receipts=1。
- 真实读取经新解释器启动的 MCP stdio 服务执行，没有调用聊天原有的 0.14.44 工具来代替新版。
- 本次运行模式为默认 **observe**。这不是 enforce、旧代续体围栏或迟到回执权限的行为验收。

浏览器窗口标题已经切换为目标文章；窗口保持最小化，Computer Use 未能获取截图。没有将截图检查写成通过。正文与捕获证据来自实际扩展/宿主链路及保存文件。

## 单次真实读取结果

只调用一次：`page_read(doi="10.3390/s26041303", refresh=true)`。本次 refresh 用于验收新版真实导航，避免命中旧缓存；无重复调用、无自动重试。

| 项目 | 实际结果 |
|---|---|
| 文章 | Flexible and Electrically Conductive 3D-Printed Ti3C2Tx MXene–Hydrogel Copolymers for the High-Precision Sensing of Biomechanical Processes |
| 落地 URL | `https://www.mdpi.com/1424-8220/26/4/1303` |
| status / terminal / stage | `ok / ok / publish` |
| full_text / identity | `true / declared` |
| 页面自报 DOI（从保存的 MHTML 独立核对） | `10.3390/s26041303`，与请求一致 |
| capture_navigation | `match` |
| tab_id | `1244772200` |
| navigation_id | `10ed2355-7a3d-4bfd-9e46-b5d20ca813ed` |
| job_id | `8d973c0bb9d9` |
| 捕获大小 | 675,957 bytes |
| SHA-256 | `eada67c46bf47a9ce0e072e6443ea2b582dd4f989770a6dc8b1d08e3b606bbb7`，文件重算与回包相同 |
| MCP 读取耗时 | 7.201 s |
| 审计导航数 | 两条成功 goto；随后一条 sleep；没有 risk 事件 |
| 配额 | 292→290，实际差额 2；回包 quota_charged=2，与审计和账本一致 |
| 收尾 | bridge_ready=true；browser_busy=false；browser_lease.state=free；无冷却 |

因此本次确实验证到了两 goto 形态下的正常捕获归属。最初预计的 1 额度应以实际导航为准；此处是两条计划动作，不是把一次失败请求自动重放。

## 离线转换与保真度

成功后仅对已保存 MHTML 调用 page2md，不再访问网页：

- status=ok，engine=sections，输出 30,947 bytes；16 个提取小节，7421 tokens。
- 引言、实验方法、结果及 `4. Conclusions` 均在 Markdown 中。
- coverage：source_words=6959、extracted_words=4156、ratio=0.597。分母包含页面噪声等，不能据此说“丢失了 40.3% 正文”。
- 新安装未装可选 trafilatura，实际验证的是默认安装的 sections 路径。
- 明确告警：19 个公式只有 MathJax 图形、无 MathML，Markdown 没有对应 LaTeX。本次没有启动 OCR 或下载 PDF，不能宣称公式无损。

## F53-01 · P1 · 默认 sections 路径遗漏三张正文表格

保存的 HTML 有三张正文表格，分别有 5、12、5 行；另有一张 1 行的布局表，不计入正文表格。

转换结果：table_rows=0、tables_rendered=0。表题存在，但多项表头没有进入 Markdown，例如 Sample Composition、Manufacturing Technique、Tensile Strength (KPa)、Mean Absolute Angle Error (°)。这不仅是表格计数器未更新；实际结构和对应表头也缺失。

warnings 只有公式告警，没有这三张表格缺失的告警。

修改落点：`src/scholar_search/page2md.py::_collect_sections/_section_markdown/_extract_body`，以及 `_table_markdown` 和表格遗漏检测。建议让默认 sections 路径保留表格块；不能依赖用户另装可选 trafilatura 才恢复正文表格。无法转换时至少明确计数告警。

回归直接使用本次本地捕获，脱敏后建立最小 fixture：断言三张表的关键表头、代表单元格、表格数，以及 page.md 与 chunks/index 的一致性；无需重访站点。

## F53-02 · P2 · pdf_url 误选为期刊宣传册

同一份已保存 HTML 中：

```text
citation_pdf_url = https://www.mdpi.com/1424-8220/26/4/1303/pdf
返回 pdf_url     = https://mdpi-res.com/journals/3/flyer.pdf
```

`src/scholar_search/core/pageprobe.py:278` 对原始 HTML 执行首个 PDF 链接匹配，选到了期刊宣传册。此字段会误导后续人工定位论文 PDF。

建议优先使用经过校验的 citation_pdf_url，再选择文章正文区中与 DOI/文章地址相符的候选；不以全页第一个 .pdf 作为论文 PDF。只修元数据定位，不增加下载接口。

本轮两个 URL 都只从本地捕获读取，**没有访问或下载其中任一 PDF**。

## F53-03 · P2 · identity=declared，却未返回 declared_doi

页面自报 DOI 正确、身份判定通过，但成功回包顶层和 evidence 没有 declared_doi。_page_evidence 已预留该字段，成功结果的组装没有传入它。

修改落点：`src/scholar_search/core/service.py::_read_page` 成功结果和缓存数据；当前成功组装位于约 1858 行之后。建议把实际用于身份判定的 declared 值原样返回，并覆盖缓存命中，不重新从参考文献猜 DOI。

本轮探针最初因字段缺失得到一个负的 DOI 检查标志；随后改为直接读取保存 MHTML 的 citation_doi，并在验收 JSON 中补充核实结果为 true。**这不是抓错文献**，是对外证据字段缺失。

## 本轮仍未验证

- 没有遇到验证墙、403/429 或 bridge.timeout，因而没有人工清墙、真实 10 秒验证超时、自然迟到回执样本。
- 安装器执行了 ACL 设置，但正常读取成功不能证明低完整性宿主在迟到回包时一定可写 coordination。需要以后自然出现超时再验证，不能制造样本。
- observe 下的正常读取不证明 enforce 行为，也不证明 worker 旧代续体已经全部受围栏保护。
- 单个样本未触发风控，不代表所有出版社、频率或并行工作流都已安全验证。仍按现有串行、配额与遇风控即停规则执行。

## 证据与复现入口

- 验收 JSON：`C:/Users/xuhui/AppData/Local/scholar-search/verification/2026-11-27/real-0.14.53-1a70620c/acceptance.json`。
- 捕获：同目录 `pages/10.3390_s26041303/page.mhtml`。
- 转换：同目录 `pages/10.3390_s26041303/md/page.md`、`meta.json`、`index.json`。
- 动作审计：同目录 `audit/audit.jsonl`。只记录动作、结果和耗时，不包含 Cookie 或 HTML。
- 探针脚本：`work/scratch/verify-real-browser-0.14.53.py`。它会真正访问网站；本轮已经执行一次，**不要为复查上述三项内容问题再次运行**，复查只用已保存文件。

本轮只新增报告和验收探针；仓库产品源码未修改，私有补丁未进入公开仓库。
