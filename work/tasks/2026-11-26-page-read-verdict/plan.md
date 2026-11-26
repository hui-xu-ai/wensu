# wensu 0.14.26 修复计划：判定可信性 / 并发安全 / 「未读到全文」口径

- 日期：2026-11-26　目标版本：0.14.27（bug 修复，四个发行物同版本号）
- 依据：`Test\hierarchical-assembly-review\wensu-test-report.md`（P0-1…P3-12）+ `wensu-session-log.md`（L01–L50）+ 用户实测补充两条（N1 误判验证、N2 口径统一）
- 仓库：`D:\Python\DeepSeek\DateWork\scholar-search`（HEAD `c3a2027`，0.14.26）
- **验证档位：本计划依据静态只读取证（代码逐处核实 file:line）+ 用户日志转述**。报告里 L04/L26/L27/L34 的**原始 payload 不在仓库内**，所以"是哪一条分支返回的"属**推断**；T0 就是把这个推断变成事实，再动手。
- 私有补丁 `D:\Python\DeepSeek\Private\wensu-warmup\page_nav.py`（替换 `core/page_nav.py`，导航变两次 goto）**列为本轮非目标，一行不改**；但所有修复必须在"两次 goto"形态下仍然正确（T1/T3 的用例显式覆盖）。
- **本轮范围 = T0–T6**（口径三选已定，见 §5；T6 由 T0 结果从下一批上调）；T7 下一批。
- **T0 已执行**（2026-11-26）：结果见 `work/verify/2026-11-26/RESULT.md`。四条误判路径全部确定性复现，另有三处新事实（墙是暂态的 / 撞墙报价 1 实扣 2 / P1-3 已在 0.14.26 修好、P1-5 仍在）已同步进 T1/T2/T4/T5/T6。

## 0. 一句话

判定要从"猜证据"改成"**同源证据 + 与 page2md 同一把尺子**"；「没读到」统一成一个可编程字段；并发选页纳入锁并做身份校验。

## 1. 取证结论（已逐条核实）

### N1：页面正常却判成机器人验证 —— 四条独立路径

| # | 事实 | 位置 |
|---|---|---|
| 1a | **跨导航取标题**：`final_url` 取最后一个 outcome，而标题是"遍历**所有** outcome 取最后一个非空" —— 两次 goto 时若第二次（文章）标题为空就回退到第一次（出版社首页，可能正处 Cloudflare 中间页）的标题 | `core/service.py:928-934`；标题可能为空见 `extension/background-0.14.26.js:846-865`（`title: updated.title \|\| ""`，内容脚本 1s 超时） |
| 1b | **拿前台标签定案**：300 s 内有 blocked 标记 → 下一次调用先拍**前台标签**，该标签标题命中即直接判墙，`final_url` 写成**那个标签**的 URL、`signal` 硬编码 `title:active-tab`（L26 的 `science.org` 就是这样来的） | `core/service.py:859-877`、`742-758`（TTL 300 s） |
| 1c | **标题规则过宽**：`challenge_in_title` 用子串 `in`；同仓库 `risk.py` 用的是"精确匹配，或前缀匹配且余部 ≤32 字符且不含 CJK" —— 三套规则宽严不一，最宽的那个在判墙 | `core/pageprobe.py:79-88` vs `core/risk.py:94-104` |
| 1d | **泛化 CAPTCHA 选择器**：`[class*='captcha' i]` / `[id*='captcha' i]` 命中 reCAPTCHA 徽标等正常可见元素 → `captcha_visible=true` → RiskGuard 硬信号 | `extension/content/actions.js:13-17`、`29-44` |

补充：`_classify_saved` 只把导航 URL 传给分类器，全代码**没有任何一处**校验"这份字节属于本次导航的那个标签"；`_snapshot_locked` 的 docstring 要求调用方已持锁（`service.py:1126`），但 1b 那处在锁外调用它。

### N2：「没读到」被翻译成「没有机构权限」

| 事实 | 位置 |
|---|---|
| `_page_next` 把 `paywall` / `abstract_only` 一律翻成"浏览器没登录出版社 → 让用户登录（机构访问/校园网）" | `core/service.py:129-134` |
| 调用方技能直接把该 reason 解释成"没有机构访问权限" | `skills/paper-page/SKILL.md:96-101` |
| MCP 文档承诺 `pdf_only` / `unparsable` 两个 reason，**但全树无任何产生点**（我 grep 了 `src/**.py` + `scripts/*.py`，0 命中）→ "站点只提供 PDF" 只能落到 `abstract_only`，再被上一行翻成权限问题 | `server.py:831-833`；产生点缺失 |
| 判定顺序把标记词放在正文体量之前：`blocking` 命中即 `no_html/paywall`，压过 6,000 词正文 | `core/pageprobe.py:271-278` |

### P0-1 并发串话

锁只保护"导航 + 抓取"（`service.py:900` 起），**决定复用哪个标签的那次读取在锁外**（`:841-894`）；全浏览器只有一个共享工作标签（`background:242`/`:499`），`activeTab()` = 最后聚焦窗口的前台标签（`:509`），`goto` 永远打同一个 tab（`:737`/`:770`），读完不归还。抓取后 `_classify_saved(saved, url=final_url)` 用的是导航 URL，不是 `saved["url"]`（扩展 `:677`/`:690` 其实已回传）。

### P0-2 旧缓存无法刷新

键 = URL 原文、只认 `status=="ok"`、TTL 3600 s、只存 6 个标量（status/mhtml_path/bytes/headings/title/at），**不存判定依据**，也**没有任何 refresh 入口**（`server.py:821` 只有 url/doi，`schemas/tools.json` 还是 `additionalProperties: false`）。实测 `state/page-read.json` 里那条 4,347,806 B 就是报告里的旧快照；同一 DOI 因大小写不同各存一条（墙标记保护不到另一写法）。

### P1-3 判定尺子与内容尺子不是同一把

`pageprobe.classify_mhtml` 认编号标题 / `<article>`+6 标题+3 章节名 / ≥1200 词且 ≥25 词段落；`page2md` 走 `//section[@id]` 任意 h1–h3 + `class="section-title"` + trafilatura 兜底 —— 同一份 MHTML 两边读数因此可以背离（L08：判 `abstract_only`，实抽 97,827 字符）。**关键**：`service.page2md` 已能在进程内 0 额度调用（`service.py:1085-1112`），所以"换尺子"不需要任何新网络动作。

### P1-5 / P2-6 / P2-7 / P2-8（第二批）

- 分节只认 `//section[@id]` 与 `class="section-title"`（`page2md.py:514-544`），ACS/Wiley 正文容器不匹配 → 整篇落进第一个能匹配的节；`NOISE`（`page2md.py:46`）只进 `meta.noise_hits`，**不用于丢弃小节**，所以 `Cookie List` 能成节。
- `truncated = len(records) < page.total`（`service.py:1991-1993`）；范围导出 `total=None`（`parse_bibtex.py:210`）。"站点命中数 vs 本页条数 vs limit 截断"三者没有区分字段。
- `relevance` 不发任何排序动作（`plan_search.py:153-160`）→ 站点保持它当前的次序，于是 L15/L16 清一色 2026。

## 2. 修复设计

### T0 把推断变成事实（前置，不改产品代码）

用隔离家 `SCHOLAR_SEARCH_HOME=…\wensu-test-home` + `PYTHONPATH=src`（HANDOFF 现成套路），装**带私有补丁**的形态，跑三组受控复现并把每次 payload 原样落盘 `work/verify/2026-11-26/page-read/*.json`：

1. 同一 DOI 连续两次 `page_read`（复现 L34 的"首次 blocked/扣 1、重试 ok"）—— 记录 `signal`、`title`、`final_url`、`quota_charged`；
2. 同 DOI 在浏览器里手动过墙后再调（复现 L26/L27 的前台标签分歧）—— 记录 `signal == "title:active-tab"` 是否出现、`final_url` 与请求 DOI 是否同源；
3. 两路并发不同 DOI（T1 的用例前置）—— 记录是否出现 `final_url` 串台。

→ verify: 三份 payload 落盘 + 一段结论写入 `work/verify/2026-11-26/RESULT.md`，明确"命中的是哪条分支"。
→ 若第 1 组无法复现，则 N1 改由 `captcha_visible`（1d）解释，T1 的权重相应调整（见 §5 待定 2）。

### T1 判墙只认同源证据（N1）

改动（全部在公开仓库；语义只收紧"证据归属"，**不放宽** ADR 0004）：

1. `service.py:928-934`：标题与 URL 配对 —— 只接受"该 outcome 自己的 `data["url"]` 与 target 同主机"的标题；最后一条 outcome 标题为空时**不再回退**前面的 outcome（无证据 = 继续采集，由分类器裁决）。
2. `pageprobe.challenge_in_title` 收紧到 `risk.py:94-104` 同款（精确，或前缀 + 余部 ≤32 字符 + 无 CJK）；现有 prefix 样本（`请稍候…`、`Just a moment...`）仍须命中。
3. `service.py:859-877`：前台标签复用分支加同源校验 —— `open_tab["url"]` 与请求 DOI/publisher 域同源才可作为证据；不同源则忽略该快照并继续导航，**不得**把别人的 URL 写进 `final_url`。
4. `service.py:985-1000`：拿到快照后若 `probe["prose_words"] >= PROSE_WORDS`（正文达标），**不判墙**（body wins）——只对"已捕获"的字节生效，不新增网络动作。
5. `actions.js:13-17`：去掉 `[class*='captcha' i]` / `[id*='captcha' i]` 泛化匹配，保留知网 `tcaptcha` 具体 id + 现有可见性/尺寸判据（滑块必须仍能识别）。
6. 响应增 `challenge_evidence`：`{signal, evidence_url, same_origin}`，让调用方可自证 —— 与 P0-1 的 `requested_doi`/`resolved_doi` 合并成同一组字段。
7. **消费扩展已有的 `halted`**（`extension/background-0.14.26.js:545-548/586-606` 的 1.5 s 宽限期，今天上报了但内核从不读）：判墙要求 `halted === true` 或"标题与 `data.url` 同源且前缀精确命中"；同时允许"墙标题 + 短延时（`sleep` 免费）后复核"，因为实测 ACS 的中间页 **40 s 内自己消失**（RESULT 结论 2）。
   ⚠ `_still_rendering`（`service.py:84-98`）现在**显式排除** `blocked`（注释：墙体不是"没画完"，二次快照＝二次取墙）—— 这正是暂态墙被判死的根因，改动时要把这条假设翻过来。

→ verify: `pytest tests/unit/test_page_read_wall.py tests/unit/test_page_challenge.py tests/unit/test_page_read_open_tab.py tests/unit/test_risk.py -q`（现有 `quota_charged==1` 断言与 prefix 样本必须仍绿）+ 新增 4 条用例（二次 goto 首尾标题、跨站前台标签、正文达标不判墙、含 "just a moment" 的普通长标题不判墙）。
→ 风险：收紧会削弱真墙拦截。故保留 1b 的"同 publisher 域"档位（ADR 0018/0022 的 0 额度通道不能废），只砍"跨站证据"。

### T2「未读到全文」统一口径（N2）

1. 顶层新增 `full_text: bool`（`ok` 时 true，其余 false）+ `full_text_reason ∈ {paywall, abstract_only, pdf_only, unsupported_site, doi_not_found, not_written}`；`status`/`reason` 原值**保持不变**（向后兼容，调用方现有分支不坏）。
2. **让 `pdf_only` 真的产生**：`pdf_url` 非空、正文与摘要都不足 → `reason="pdf_only"`（今天这种页只能落 `abstract_only`，再被翻成权限问题）。`unparsable` 同理：抽取器抛错/空结果时产生。
3. 重写 `_page_next` 的 `no_html` 文案为中性口径：**"未读到全文（不代表没有权限）"** + 列三种常见原因 + 给下一步（`pdf_url` 路线 / 换 DOI / 换渠道），单条 ≤300 字符（`test_response_budget.py` 会拦）。
4. 同步 `skills/paper-page/SKILL.md:96-101` 与 `server.py:829-833` 的 docstring；`schemas/tools.json` 用 `scripts/dump-tools.py` 重生成。
5. L32 诚实性：`paywall`/`abstract_only` 不再"报字节却不落盘"——要么真落盘并让 `bytes` = 磁盘实际大小，要么不返回 `mhtml_path`；二选一必须自洽（现读 `service.py:1002-1015`、`1082`、`1192`）。

→ verify: `pytest tests/unit/test_page_read.py tests/unit/test_page_probe_paywall_order.py tests/unit/test_response_budget.py tests/unit/test_tools_json_matches_server.py -q` + 新增用例：`pdf_url` 存在且无正文 → `reason=="pdf_only"` 且 `full_text is False`；`_page_next` 文案不含 `sign in`/`without permission` 类措辞。

### T3 并发：锁覆盖选页 + 身份校验（P0-1）

1. 把 `service.py:841-894`（缓存判断 / 墙标记 / 前台标签复用）整体移入 `with self._browser_transaction():`（`:900`），恢复 `_snapshot_locked` 的契约。
2. 抓取后新增 `saved["url"]` 与 `final_url`/`target` 的一致性判定（扩展已回传该 url，零额外额度）；不一致 → 不作数、返回 `busy` 或重取。
3. `locking.py` 增 `blocking=False` 分支，冲突抛可映射错误；`server.py` 映射成 `status:"busy"` + "another page read is using the browser; retry later"（别让 4 路并发静默排队 3×180 s）。
4. 响应带 `requested_doi` / `resolved_doi`（与 T1 同一组字段）。

→ verify: `pytest tests/unit/test_page_read_open_tab.py tests/unit/test_browser_lock.py（新增）-q`；新增两条夹具：前台是**另一 DOI**的页面（断言不复用/不复述其 URL）、两线程并发（stub adapter + `threading.Barrier`，断言 `final_url` 不串台）。
→ 风险：不新增标签页（不动"只留一个窗口"的 0.14.17 约定）；`test_page_read_idempotent.py:66-71` 的"第二次 cached、0 额度"必须保持。

### T4 缓存：判定指纹 + 强制刷新（P0-2）

1. `_page_cache_put` 多落 `judge`（判定契约版本号）、`reason`、`prose_words`、`final_url`；`_page_cache_get` 要求 `entry["judge"] == _PAGE_JUDGE_REV`，否则视为未命中。
   → 旧条目自动失效、**不需要用户清缓存**（键形状不变，也不碰 `test_page_read_open_tab.py:137`）。
2. `read_page(..., refresh: bool = False)` + `server.py` 参数 + `schemas/tools.json` 重生成；`refresh=True` 跳过缓存（仍走墙标记那条 0 额度前台路径）。
3. 缓存键对 DOI 大小写归一（仅归一键，导航用原值）。
4. 命中回包补 `reason`/`prose_words`/`judge`，`final_url` 取条目里真实落地 URL（今天填的是请求 URL）。

→ verify: `pytest tests/unit/test_page_read_idempotent.py tests/unit/test_page_read_open_tab.py tests/unit/test_tool_schema_contract.py -q` + 新增：旧条目（无 judge）不被命中；`refresh=True` 必重新导航。
→ 风险：`refresh` 会重新导航（正是历史事故 D1/D2 的成因）⇒ **默认关、显式开**，且命中路径默认行为一字不改。注意：0.14.26 那两份 4.34 MB 独立抓取证明"重抓仍是空壳"，所以 T4 不是 L08 的根治，根治在 T5。

### T5 判定与 page2md 用同一把尺子（P1-3）—— **已降级为低优先加固**

**T0 更正**：报告 L08 的"判 `abstract_only` 其实有正文"是 **0.14.20** 的行为；对同一份 `page.mhtml` 跑现码得 `status=ok, prose_words=10,322`，0.14.25 已修。所以本项**不再作为主项**，只做两件收尾：① 抽取失败时退化为现有分类（不把"判 ok"变成抛错）；② 把 L08/L13 两份真实抓取登记为回归 fixture，并在报告里标注"已修复待回归"。

原设计保留如下（仅在需要时执行）：

`_classify_saved` 在本地已有 MHTML 的前提下，用 `service.page2md` 同一套提取器（进程内、0 额度、0 网络）算"正文词数/段落数/是否含真实章节名"，作为 `status` 的**主判据**；`pageprobe` 的标记词降级为"原因"，不再压过正文体量：

- `prose_words >= 阈值` → `ok`（哪怕标题像墙、哪怕 side-bar 印着 Purchase）；
- 否则按原因细分（`paywall` / `pdf_only` / `abstract_only` / `doi_not_found`）。

→ verify: `pytest tests/unit/test_page_probe_letter.py tests/unit/test_page_probe_paywall_order.py tests/unit/test_page_probe.py（若存在）-q` + 新 fixture：JACS 6c13448 的 page.mhtml（判 `ok`，`prose_words > 8000`）、ACS ic1c03019 落地页（判 `no_html`，不是 `ok`）、Wiley anie.202005087（含 institutional access 标记但正文完整 → `ok`）。
→ 风险：抽取耗时（5 MB MHTML 秒级），落在已付费的 `page_read` 里可接受；须加"抽取失败退化为现有分类"的兜底，避免把判 ok 变成抛错。

### T6 page2md 分节 + 截断告警（P1-5 / P2-6 / P3-10）—— **T0 实测后上调到本轮**

T0 用两份真实抓取证实 P1-5 **仍在**：JACS Perspective `01-introduction` 24,576 tokens + 13×**613**；ACS 2026 新文 15,616 + 5×**488**（数字与报告一致）。

分节按 `<h1>/<h2>/<h3>` 实际层级重建（现逻辑只认两种容器）；导航类小节黑名单（`Cookie`、`Google Scholar`、`Close Figure`）真正**丢弃**而不只记 `noise_hits`；`warnings` 增报"正文集中于单节"的降级状态、被截断段落数与阈值、被图片化的具体字段名（空间群等）。
→ verify: `pytest tests/unit/test_page2md.py tests/unit/test_page2md_math_budget.py -q` + 3 份真实产物回归（`md/jacs6c13448`、`md/d3sc02793g`、`md/anie202205385`：断言 ≥4 个非空非导航小节、gist 不含 "Google Scholar"）。
→ 注：**2,000 字符截断在 0.14.26 源码里找不到**（`page2md.py` 只有 `_MAX_PARAGRAPH_CHARS=1200` 的**切分**与 `MATH_MAX_CHARS=4000`），报告 L38/L39 可能是**读取侧**截断。T6 第一步先复现，复现不出就记为"非 wensu 缺陷"，不硬改。

### T7 WoS total / truncated / 排序回显（P2-7 / P2-8，第二批）

`total` 表达站点真实命中数，新增 `total_capped_at_limit` 区分"站点就这么多"与"被我 limit 截断"；`effective_sort` 回显（`relevance` 若沿用站点当前次序，就如实写 `effective_sort: "site-default"`，不要假装生效）；`site_sort=relevance` 与 `page>1` 的互斥约束保持。
→ verify: `pytest tests/unit/test_search_truncated.py tests/unit/test_wos_query.py tests/unit/test_wos_export_sort_plan.py -q` + 真实检索一条 >200 命中的式子核对站点计数。

## 3. 改动面清单（逐个说明为什么必须改）

| 文件 | 批次 | 为什么必须改 |
|---|---|---|
| `src/scholar_search/core/service.py` | T1-T5 | 判墙证据配对、锁范围、身份校验、缓存指纹、口径文案、判定尺子（6 处独立位置） |
| `src/scholar_search/core/pageprobe.py` | T1/T2/T5 | `challenge_in_title` 收紧、判定顺序、`pdf_only`/`unparsable` 的产生点 |
| `src/scholar_search/core/locking.py` | T3 | 需要"冲突即可返回 busy"的非阻塞分支 |
| `src/scholar_search/core/errors.py` | T3 | 承载 busy 映射（`_CLEARABLE_SIGNALS` 同时要审） |
| `src/scholar_search/server.py` | T2/T4 | MCP 工具签名加 `refresh`、docstring 口径、busy 映射 |
| `schemas/tools.json` | T2/T4 | `additionalProperties: false` ⇒ 不重生成就拒收新参数（CI 有闸门） |
| `extension/content/actions.js` | T1 | CAPTCHA 选择器泛化误报 |
| `extension/background-0.14.26.js` | T1/T3 | goto 回包补 `tab_id`/`halted`（内核拿不到"墙出现过又消失"）；工作标签写回 |
| `skills/paper-page/SKILL.md` | T2 | 调用方口径（"没有机构访问权限"就是从这里说出去的） |
| `tests/unit/*`（T1-T7 各自的用例） | 全部 | 行为变更必补测试 |
| `CHANGELOG.md` + 五处版本号 + worker 改名 | 发版 | AGENTS.md 硬规则 |

**不改**：私有补丁 `page_nav.py`、`ADRs`（若口径变更需新增 ADR，见 §5）、用户 `%LOCALAPPDATA%` 数据。

## 4. 非目标（明确不修）

- 不绕过任何站点风控；不识别验证码；不自动重试。
- 不下载 PDF/CAJ（AGENTS.md 硬约束）——**"只提供 PDF"只做口径，不做抓取**。
- ACS 落地页只给 Abstract、Elsevier/Springer 部分文章订阅制：站点设计，只做 `pdf_url` 指路。
- 不动"只留一个窗口"的标签策略（0.14.17 的成果）。

## 5. 已定口径（2026-11-26 用户确认，三选全部取 A）

1. **口径形态 = A 向后兼容**：`status`/`reason` 原值不动，顶层新增 `full_text: bool` + `full_text_reason ∈ {paywall, abstract_only, pdf_only, unsupported_site, doi_not_found, not_written}`；并把今天从不产生的 `pdf_only` / `unparsable` 做出来。
2. **N1 收敛 = A 三件套**：同源证据 + 标题规则收紧到 `risk.py` 同款 + 正文达标不判墙；真墙仍拦截，"同 publisher 域"的 0 额度前台复用档位保留。T0 复现只是**确认主因（1a/1b/1d 哪条）**，不改强度。
3. **批次 = A（T0 后微调）**：本轮 T0–T6 —— T0 已完成；T1 判墙同源证据（+`halted`）、T2 口径、T3 并发、T4 缓存/实测额度、T5 降级加固、T6 page2md 分节（**上调**，因实测仍在）。T7（WoS total/sort）仍下一批。

## 6. 验收与档位

| 档 | 内容 | 谁能做 |
|---|---|---|
| 单测 | 上述各 T 的 `verify` 命令 + `pytest -q` 全绿 + `mypy --strict` + `ruff` | 我 |
| 真实链路 | 隔离家 + 私有补丁形态：同一 DOI 两次 page_read 不再误判；两路并发不串台；JACS/ACS/Wiley 三篇判定与 page2md 一致；`refresh=true` 生效 | 我（耗额度，需你放行额度） |
| 发版闸门 | `python scripts/release-check.py` 10 门全绿 → 五处版本号 + worker 改名 → tag → `pnpm publish` → 市场索引 | 我 |
| 用户验收 | 你按报告 T1–T8 的用例复跑；确认"没读到全文"不再被说成"没有机构权限" | 你 |

## 7. 回滚

每个 T 一次原子提交（Conventional Commits + 会话前缀），`git revert <sha>` 即可回退；`page-read.json` 因新增 `judge` 字段会在旧代码下被当作普通条目（旧代码不读该字段），**无数据迁移、无需清理**。
