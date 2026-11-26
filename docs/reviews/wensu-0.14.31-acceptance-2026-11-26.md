# wensu 0.14.31 验收与残留问题

**主要修复已生效，但整体验收仍不通过。** 新 worker、MDPI 主文献 DOI、正文提取退路、普通同 DOI 并发去重均有实际证据；仍确认三个 P1：等待失败会暗中再导航、段落退路没有更新分节索引、同出版社错误文章仍可被认作本篇。另有五项 P2，详见下文。

日期：2026-11-26，北京时间。仓库基线 `b841ff5`，测试对象为官方安装版 **0.14.31**。本轮只安装、测试和写审计材料，没有修改产品实现、提交或发布代码。私有补丁保持独立，其实现及出版社首页表没有进入本报告或验收脚本。

## 安装和证据边界

- 官方 PyPI 包和 npm bundle 均为 0.14.31；独立 venv、全局 CLI、DSH desktop bundle、扩展文件和 native host 注册已更新，`doctor` 三方版本一致。
- 用户确认重新加载扩展。新建官方 MCP stdio 会话验证实际握手，不使用本聊天残留的旧 MCP 常驻实例做新版页面测试。
- 保留 `E:\LiteratureEdgeProfile`、真实配额、冷却及已有页面；没有重置风控、批量关浏览器、安装提取器可选依赖或下载 PDF/CAJ。
- 私有补丁在两个安装环境的自检均通过，备份在新版安装目录 `upgrade-backups/20261126-195021`。本次真实导航两条，不能把内核动作数等同于 HTTP 请求总数。
- 安装版与仓库 **53 个 Python 源文件**比较，除预期的私有 `core/page_nav.py` 覆盖点外，没有差异（换行归一化）。
- 本机扩展目录中的 `background-0.14.31.js` 与本轮审阅和离线回放的仓库 worker 内容一致（换行归一化）。
- `scripts/release-check.py` 十门全通过：版本、工具 schema、CHANGELOG、测试、lint、格式、类型、计划、资源、wheel。格式检查 141 文件，类型检查 53 文件，wheel 75 文件且包含两个渠道。没有把收集数量或省略的测试输出当作通过数量。

真实站点只发起指定 MDPI 文章的一次读取；`page_read(refresh=true)` 耗时 **9.729 s**，后续本地转换 **0.631 s**。真实额度 **267 → 265**，能力门和全部离线测试额外消费 **0**。验收脚本没有并发压测或重复发起该读取；本轮未记录浏览器内部全部 HTTP 请求，不能由此断言内部没有额外尝试。

## 观测点 1：实际 worker 与握手

**通过。** 正式 MCP status 的 `browser_profile.bridge_build`：

```json
{
  "version": "0.14.31",
  "worker": "background-0.14.31.js",
  "handshake": "ok",
  "host_version": "0.14.31",
  "capabilities": ["goto", "snapshot", "sleep"],
  "channel_capabilities": ["read_html", "read_text", "scroll", "click", "type", "select", "wait_for"]
}
```

前置能力门也复验通过：`page:mdpi` 计划要求 `wait_for`，返回 `action.unsupported`；执行器收到动作数 **0**、额度变化 **0**。测试包装器在门失效时也禁止发送动作。

## 观测点 2：MDPI 主文献 DOI

**本例功能通过，成功回包的观测字段仍不完整。** `10.3390/s26041303` 实际返回 `ok/full_text=true`，捕获文件 670,051 B。

安装版 `citation_doi` 返回 `10.3390/s26041303`；另用 lxml 独立读取主文档 head 中 meta 的真实 name/content 属性，得到同一个 DOI，排除了只用被测正则自证的情况。本例不再误取 Nano Letters 参考文献的 DOI。

成功的 `page_read` 回包本身**没有 `declared_doi` 字段**，需读取捕获文件才能看到该值；目前该字段只在不匹配错误分支等位置出现。因此交接中若要求直接检查成功回包的 `declared_doi`，这项可观测性尚未交付。

## 观测点 3：正文保留和低覆盖率告警

| 输入 | engine | 源词数 | 转换词数 | coverage.ratio | 分节索引 |
|---|---|---:|---:|---:|---|
| 本轮 MDPI 真实捕获 | `sections` | 6848 | 4156 | **0.607** | 16 节、7421 token |
| 上轮 ACS 捕获，本轮仅离线重转 | `paragraphs` | 5034 | 2059 | **0.409** | **仅 1 节、4 token** |
| 无标准容器的纯合成正文 | `paragraphs` | 805 | 800 | **0.994** | **0 节、0 token** |

MDPI 正文覆盖改善目标通过；其实际 engine 为 `sections`，与交接列出的两个 engine 字面预期不一致，但本例有可用的标准分节，这个取值本身不能认定为缺陷。ACS 段落退路确实触发，`page.md` 从上轮 1,572 B 增至本轮 **16,113 B**；meta 报告 `bytes_md=16042`，与 Windows 换行落盘后的文件大小口径略有差别。

**正文到下游的完整链路尚未通过。** ACS 的 `index.json` 仍只有 Supporting Information，`core_tokens=0`。合成页更直接：`page.md` 含正文标记，`sections/*.md`、`page.brief.md` 和 `page.core.md` 都没有该标记；覆盖率 99.4% 也不能发现此问题。详见 R31-02。

低覆盖告警边界：1004 源词 → 0 词、ratio=0 时，出现“正文可能大量缺失”；**404 源词 → 0 词、ratio=0 时没有这个告警**。所以“凡 ratio<0.3 必告警”的验收条件仍不满足，详见 R31-08。

coverage 是粗略空白分词比例，包含页面非正文，不是语义完整度或准确率，也不能代替逐篇正文核验。

## 观测点 4：同 DOI 两个同时到达的请求

**普通请求场景通过。** 使用安装版 service、策略、锁和合成适配器，令两个请求在锁前同时缓存未命中，再允许竞争：

```json
{
  "statuses": ["ok", "ok"],
  "cached_flags": [true, false],
  "reported_costs": [0, 2],
  "synthetic_quota_used": 2,
  "executed_goto_count": 2,
  "one_navigation_plan_goto_count": 2,
  "same_capture_path": true
}
```

执行顺序由锁竞争决定，不是提交数组顺序：先取得锁者访问一次，后取得锁者 `cached=true/quota_charged=0`。没有第二组导航。测试只在每个线程的第一次缓存查询设置 barrier，避免把新版锁内第二次查询也拦住而造成测试自身死锁。

范围：这是两个线程共用正常运行目录、`refresh=false` 的特定交错；没有声称覆盖所有跨进程、不同访问参数、刷新请求及真实站点场景。

## 仍确认的问题

### R31-01 · P1 · 导航等待失败会在扩展内部再次导航

位置：`extension/background-0.14.31.js:792`，重试在 `:826`。

`navigate()` 同时包含 `tabs.update`、`waitNavigated` 和 `waitComplete`；外层 catch 捕获整个函数的异常，300 ms 后再次调用。因此注释声称“只重试被拒绝的 update，不重试等待失败”，与实际控制流不同。

本轮用 Node VM 执行原始代码块，所有浏览器 API 都是假对象：第一次 update 已成功，然后等待抛错。结果 **两次 accepted tabs.update**，内部延时 **300 ms**。没有真实网络调用。

影响：内核一条 goto 可以变成多次导航，后一次还可能晚于 host 超时；内核节流、计费和审计看不到内部次数。这是重复站点访问的具体风险，不能据此反推此前某次风控一定由它导致。

建议：区分“导航未发出”与“已发出但结果未知”；等待失败后返回当前已知状态或未知状态，不重新发导航。尝试次数、实际导航开始和终结应进入回包。验收必须让“update 成功、wait 失败”时 update 总数为 1。

### R31-02 · P1 · 段落退路修了 page.md，却没有修分节和摘要输入

位置：`src/scholar_search/page2md.py:1007`、`:1022`、`:1693`。

`sections_found` 来自先前失败的分节遍历；paragraph fallback 只替换 body、engine，没有重建 sections。后面的 `_write_chunks`、`_write_brief`、选读和 core 输出继续使用旧 sections。

证据：ACS 正文 Markdown 16 KB，索引仍只有 Supporting Information 的 4 token；纯合成正文覆盖率 0.994，索引却为 0。现有“章节不足”告警按旧索引 tokens_total>=5000 触发，索引被算成 0/4 时也不会提醒。

影响：AI 依据 index 分节读取、摘要或 core 阅读时，仍几乎拿不到正文。用户看到转换成功和覆盖率正常，也无法发现数据传递中断。

建议：最终选中的正文及其结构只产生一份统一中间表示，各输出均从它生成；无法分节时生成诚实的单正文块，并明确告警。验收应同时检查 page、index、所有 chunks、brief/core 的来源一致性，不能只检查 engine 和 coverage。

### R31-03 · P1 · 同出版社的另一篇文章仍被当成本篇

位置：`src/scholar_search/core/service.py:216` 及 `:1304` 附近。

合成回放请求 `10.1002/pen.23634`，捕获地址却为 `https://onlinelibrary.wiley.com/doi/10.1002/another-paper`，没有 citation_doi；仍返回 **`ok/full_text=true`**。

当前同出版社域名足以放行。0.14.31 去掉末两段域名猜测的修复有效，`unrelated.edu.cn` 已被拒绝；但出版社归属和文章身份仍是两件不同的证据。

建议：请求 DOI、实际导航、捕获 URL、主文献元数据、tab/navigation 标识共同绑定；同域但没有文章身份凭证时返回未确认，明显为另一 DOI 时拒绝。验收覆盖同出版社错页、跳到期刊首页、标签被用户切换三种情况。

### R31-04 · P2 · 刷新覆盖同一路径，其他任务的输入会变化

位置：`src/scholar_search/core/service.py:1421`。

同 URL 和标题先后 `_write_page` 两次，返回相同路径；第一任务持有的路径已经读到第二次内容。URL 哈希消除了不同 URL 的一部分碰撞，但没有提供不可变的捕获版本。

建议：以 capture_id/内容哈希创建新版本并原子发布，转换绑定输入哈希；旧任务完成前不覆盖其输入。验收“任务 A 持有旧捕获，任务 B 刷新，A 仍读取原字节”。

### R31-05 · P2 · 判定规则已改，缓存 judge 仍为 1

位置：`src/scholar_search/core/service.py:271`、`:860`。

0.14.30→0.14.31 改了捕获归属规则，但 `_PAGE_JUDGE_REV` 没变。合成一个 judge=1、尚未过期且文件存在的旧 PKU 缓存项，captured_url 为现在已拒绝的 `unrelated.edu.cn`；0.14.31 仍直接返回 **ok/cached=true/额度0**，不重新校验身份。

这是旧缓存兼容风险的合成证明；没有证明用户真实缓存里存在这种条目，也没有修改或清空真实缓存。

建议：规则语义变化同步提升判定版本，并持久化必要的身份元数据；旧项本地可重判则重判，否则视为未命中，不重置配额或风控状态。

### R31-06 · P2 · 第一导航被拒时，回包多报额度

位置：`src/scholar_search/core/service.py:1176`。

本机安装的两导航计划，合成第一条 goto 返回 403：正确停止并返回 blocked，但 `quota_charged=2`，临时策略账本实际只用了 **1**。错误分支按计划动作数收费描述，而不是已执行动作数。

影响是回包与账本不一致；本例没有多扣真实额度。建议按已执行 outcome 或策略记账事件统一生成费用；覆盖每个停止阶段。

### R31-07 · P2 · meta 属性名的“精确匹配”仍有缺口

位置：`src/scholar_search/core/pageprobe.py:138`。

`\bname` 也会匹配 `data-name` 的后半段。有效 HTML：

```html
<head>
  <meta data-name="citation_doi" name="citation_reference" content="10.9999/wrong">
  <meta name="citation_doi" content="10.9999/right">
</head>
```

实际返回 `10.9999/wrong`。这是最小合成鲁棒性回归，不是声称 MDPI 当前包含此结构；MDPI 的原问题本轮已通过。`content` 的同类正则也没有按 HTML 属性结构解析。

建议：用已有 HTML 解析器读取真正的 head/meta 属性，测试 data-name/data-content、引号内另一种引号、属性顺序和大小写。

### R31-08 · P2 · 少于 500 源词的严重正文缺失不告警

位置：`src/scholar_search/page2md.py:1687`。

代码额外要求 `source_words>=500`，所以本轮 404 源词、转换为 0、ratio=0 的合成页没有“正文可能大量缺失”告警。与交接“<0.3 必告警”的验收要求不符。

建议：至少对非空源正文变成空输出强制告警；其他比例阈值若需要最小样本数，应明确进入契约。验收覆盖阈值两侧及非英文分词场景。

## 并发隔离和站点风控的结论

**当前继续保持在线网络计划并发 1，多个文献的冻结快照可用于并行本地处理。** 同 DOI 去重修复减少了正常重复请求，但尚不能消除上面的隐藏再导航，也不能解决可变文件和错误文章身份。

条件性架构风险仍在：共享运行目录的锁测试，临界区最大同时进入为 1；不同运行目录的锁为 2。锁绑定 `SCHOLAR_SEARCH_HOME/state/browser.lock`，没有绑定真实浏览器资源。**如果**两个 home 指向同一个浏览器，就不能靠目录隔离保证浏览器串行。本轮没有复制真实 host 端点或实际运行这个危险组合。

上一轮的超时取消问题也仍需单独验收：host 超时移除 pending 不代表浏览器动作已撤销。这里只有静态风险证据，没有补成真实浏览器端的端到端复现；应在假浏览器中重放晚到完成、取消确认和下一任务启动。

推荐的数据交接最小模型为：`job_id/request_id + requested_doi + declared_doi + captured_url + tab/navigation_id + capture_sha256 + extractor_revision + verdict/evidence`。先按实际浏览器归属排队，完成身份校验并冻结捕获，再并行提取和分析。下游关联使用文献身份及哈希，不依赖最后活跃标签、同名文件或数组位置。

本轮没有自然遇到持续真墙，也没有证明同一文章上的中间页自清；这两项仍未验收，不通过重复访问补样本。没有站点侧检测日志，因此不能给出“不被判为爬虫”的保证。Cloudflare 官方说明其检测会结合请求特征、会话和浏览器信号，不能由本地 900 ms 动作间隔推导网站认可的安全频率。[Cloudflare 检测引擎说明](https://developers.cloudflare.com/bots/concepts/bot-detection-engines/)

## 建议下一轮验收顺序

1. **先补 R31-01/02/03**：已发出导航后的等待失败不得再导航；正文所有输出源一致；同出版社错文献不允许报本篇成功。先用本轮离线用例验收，不需要重新请求出版社。
2. **再补版本和文件一致性**：不可变 capture、判定 revision 更新、首条停止的真实计费、真正的 HTML 属性读取、覆盖率告警边界。
3. **最后补共享浏览器与消息终结**：统一资源队列、tab/navigation 租约、超时取消确认；用假浏览器和多独立服务进程检验。放宽在线并发仍需新的 ADR，不建议用站点压力测试探索限制。

## 复现材料

本轮脚本：`work/verify/2026-11-26-codex-01431/`。

- `setup_review_install.py`：复用已审阅的安装迁移，仅替换目标版本。
- `live_mcp_check.py`：复用正式 MCP 的一次访问与被动观测脚本；禁止已有证据的真实用例自动重跑。
- `offline_checks.py`：同 DOI 竞争、错文章身份、快照覆盖、旧缓存、停止费用、元数据属性、覆盖率边界、正文与索引一致性；只使用合成适配器，另读取已保存文章做本地转换。
- `navigation_replay.cjs`：Node VM 执行原始 worker 重试块，浏览器和计时 API 为假对象，无网络。

原始证据只存于 `%LOCALAPPDATA%\scholar-search\verification\2026-11-26-codex-0.14.31\`：normal-events/summary/navigation、offline-checks、capability-check、navigation-replay，以及 ACS 本地转换输出。文章全文、桥接 token、Cookie、账号和私有补丁未写入本轮公共审计材料。
