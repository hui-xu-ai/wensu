# T0 复现结果（2026-11-26）

- 环境：Windows / Edge（wensu 自管 profile `E:\LiteratureEdgeProfile`）/ 安装版 **0.14.26 + 私有 warmup 补丁**；仓库 HEAD `c3a2027`
- 额度：开工 300 → 收工 **298**（明细见结论 3）
- **验证档位**：① 四条误判路径用仓库自带 `FixtureAdapter` 夹具做**确定性复现**（零额度、零网络、可复跑）；② 真实链路做了**一次** `page_read` + 两次 `snapshot`（ACS，2 额度，`__cf_chl_tk` 真墙）。档位不夸大：① 证明代码路径，② 证明活体行为，两者不能互相替代。

## 结论 1：N1 的四条误判路径，四条全部命中（确定性）

命令：`.venv\Scripts\python.exe work\scratch\t0-branch-repro.py`（需 `PYTHONPATH=src`、`TEMP` 指向工作区）

| 路径 | 输入 | 现码返回 |
|---|---|---|
| **1a** 跨导航取标题 | 两次 goto：首页 `请稍候…` → 文章 **标题为空**（扩展 `title: updated.title \|\| ""` 的真实形态） | `blocked/challenge`，`signal=title:请稍候`，`quota 1`，**`final_url` 却是文章 URL**（标题与 URL 不配对） |
| **1b** 前台标签定案 | 300 s 内有墙标记 + 前台是 `science.org` 的验证页 | `blocked`，`signal=title:active-tab`，**`final_url=https://www.science.org/doi/10.1126/scirobotics.adh4060`**，`quota 0` —— 与报告 L26 **同一串 URL** |
| **1c** 标题子串过宽 | `"Loading: Just a moment please — Journal of the American Chemical Society"` | `challenge_in_title()` 返回 `just a moment` ⇒ **普通长标题被判墙**（同仓库 `risk.py:94-104` 用精确/前缀规则，只有这里最宽） |
| **1d** 泛化 CAPTCHA 选择器 | 页面正常、标题正常，`captcha_visible=true`（reCAPTCHA 徽标形态） | `blocked`，`signal=captcha`，`quota 1`（payload 无 `reason` 字段，与 `errors.to_payload` 一致） |

## 结论 2：活体机制 = **标题采样时刻**，而墙是暂态的

真实链路（ACS `10.1021/jacs.4c07518`）：

```text
12:50:35  goto 首页（私有补丁）
12:50:37  goto 文章            ← 两次 goto，与 audit.jsonl 一致
12:50:4x  page_read → blocked / signal=title:请稍候 / quota_charged 1
12:52      snapshot → blocked / RISK_CAPTCHA / discarded 51,593 B / url 带 __cf_chl_tk=…
12:53      snapshot → ok，5,120,619 B，标题=真实文章标题（挑战页**自己消失了**）
```

即：Cloudflare 中间页 40 秒内自动放行，而判定用的是 `goto` 返回**那一刻**的标题，之后没有任何"它清掉了吗"的复核。扩展其实已经在跟踪这件事（`GATE_GRACE_MS=1500` + `halted`，`background:545-548/586-606`），但**内核从不读 `halted`** —— 这是 T1 最便宜的一处修复。私有补丁让导航变两次 goto，使 1a 成为**常态而非偶然**。

## 结论 3：撞墙报价 1、**实扣 2**（P3-11 的硬证据）

`page_read` 回包写 `quota_charged: 1`，但额度 300 → 298 = **扣 2**；`audit.jsonl` 里那一次调用有**两条 `goto`**（12:50:35 / 12:50:37）。原因：`policy` 按网络动作数计费，`quota_charged` 却是常量（`service.py:998/1010`，`bootstrap.py:34` 也只报 2）。⇒ T2/T4 必须把"报价"改成**实测值**，否则用户永远对不上账。

## 结论 4：**P1-3「判 abstract_only 其实有正文」已经在 0.14.26 修好了**

对报告 L08 那份**同一个** `page.mhtml`（`pages\Hierarchical-Engineering-of-Atomically-Precise-Gold-Nanoclus-28b470af\page.mhtml`，5,140,139 B）：

```text
classify → status=ok  prose_words=10,322  prose_paragraphs=75  headings=0
page2md  → bytes_md=130,399（14 节）
```

⇒ 报告 L08 记录的是 **0.14.20** 的行为（"会话开始时 0.14.20"），0.14.25 的"用正文体量判文章"已修复这一条。**T5（判定换同一把尺子）从"最高价值"降为"低优先级加固"**；报告该条应标注"已在 0.14.25/0.14.26 修复，待回归确认"。

## 结论 5：**P1-5 分节失真仍在，两份样本都复现**（→ T6 上调到本轮）

| 样本 | 现码 `index.json` 分节 |
|---|---|
| JACS Perspective（上面那份 L08 抓取） | `01-introduction` **24,576 tokens**，其余 13 节各 **613** |
| ACS 刚抓的 Cu 团簇文（2026 年新文） | `01-introduction` **15,616**，其余 5 节各 **488** |

数字与报告完全一致（613 / 488 是同一段导航垃圾的两种长度）⇒ 分节走查只认 `//section[@id]` 与 `class="section-title"`（`page2md.py:514-544`），ACS/Wiley 的正文容器不匹配，整篇正文落进第一节；`NOISE`（`page2md.py:46`）只进 `meta.noise_hits`，不丢弃小节。

## 偏差声明（计划 vs 实际）

- 计划里的 **T0-3（两路实盘并发，4 额度）没有跑**：1b 已经用确定性方式复现了 L26 的**同一串 URL**，机制（锁外的前台读取 + 无身份校验）已在代码层证实；实盘并发是时序敏感的（正因如此报告里它"偶尔"出现）。**保留到 T3 验收阶段再跑**（T3 的夹具体就是 1b 的形态）。
- 计划里的"三组实盘复现"合并成"一组实盘 + 四条确定性"：省 2–4 额度，且确定性结论更强（可回归、可断言）。

## 对计划的影响（已同步进 `plan.md`）

1. **T1 增**：消费扩展已有的 `halted`（1.5 s 宽限期）作为判墙前提之一；`_still_rendering` 目前显式排除 `blocked`（`service.py:84-98`），要允许"墙标题 + 短延时后复核"。
2. **T2/T4 增**：`quota_charged` 改为实测网络动作数（结论 3），并回 `quota_reason`。
3. **T5 降级**：判定尺子已基本正确，只做"抽取失败则退化为现有分类"的兜底，不再作为主项。
4. **T6 上调到本轮**：P1-5 两份样本实测仍在，且直接影响调用方"按节阅读"。

## 可复跑清单

```powershell
cd D:\Python\DeepSeek\DateWork\scholar-search
$env:TEMP=$env:TMP=$env:TMPDIR="D:\Python\DeepSeek\DateWork\.tmp"; $env:PYTHONPATH="src"
.\.venv\Scripts\python.exe work\scratch\t0-branch-repro.py                                    # 四条路径（0 额度）
.\.venv\Scripts\python.exe work\scratch\t0-classify-vs-md.py <page.mhtml> <可写输出目录>       # 判定 vs page2md（0 额度）
```

> 注：子进程写不进仓库树（老坑），`page2md` 的输出目录必须落在仓库外（本次用 `D:\Python\DeepSeek\DateWork\.tmp\`）。

---

# T1 结果：判墙只认同源证据（2026-11-26）

**验证档位：单元测试（真实夹具回放）+ lint/type 全绿**；真实链路复验留到本轮收尾统一跑（`t0-branch-repro.py` 可直接作为"改后应不再误判"的对照，四条全部翻绿）。

## 改了什么（每行都能追溯到 T0 结论）

| 改动 | 文件 | 对应 T0 结论 |
|---|---|---|
| 标题证据只取**最后一条导航**；不再回退到前面 outcome 的标题 | `core/service.py:928-936` | 1a |
| 标题证据还要求 `data["url"]` 与本次 publisher/DOI **同源**（新增 `_page_evidence_site`） | `core/service.py:138-152`、`:940-945` | 1b |
| 扩展已上报的 `halted`（门标题是否持续 1.5 s）现在是**判墙前提**：`halted is False` ⇒ 不判墙，交给抓取分类 | `core/service.py:937-941` | 结论 2（墙是暂态的） |
| 墙标记后拍的**前台标签**只有同源才可作为证据；不同源则继续导航，不把他站 URL 写进 `final_url` | `core/service.py:864-870` | 1b（L26） |
| `challenge_in_title` 由**子串**改为 `risk._title_is_gate` 同款（精确，或前缀 + 余部 ≤32 字符 + 无 CJK），常量 `_TITLE_TAIL_CHARS = 32` 说明两处规则不许再漂 | `core/pageprobe.py:69-101` | 1c |
| CAPTCHA 选择器去掉泛化的 `[class*='captcha' i]` / `[id*='captcha' i]`，改为具名元素；知网滑块 `#tcaptcha_transform_dy` 保留，reCAPTCHA 只认**挑战对话框** `bframe`，不认常驻徽标 `anchor` | `extension/content/actions.js:13-24` | 1d |

## 测试（先红后绿）

`tests/unit/test_page_read_wall.py` 新增 4 条，全部先失败再修好：

| 用例 | 断言的旧行为 | 现在 |
|---|---|---|
| `test_two_navigations_do_not_lend_each_other_titles` | 两条 goto（私有补丁形态，用 `monkeypatch` 模拟）+ 第二次标题为空 ⇒ `blocked` | 不 blocked，`status == ok` |
| `test_a_wall_on_another_site_is_not_evidence` | 墙标记 + 前台是 `science.org` 验证页 ⇒ `blocked`，`final_url` 是他站 | 不 blocked，`final_url` 不含 `science.org` |
| `test_a_gate_title_that_did_not_persist_is_not_a_wall` | `halted=false` 仍 `blocked` | 不 blocked 且真的抓到了字节 |
| `test_a_plain_title_that_merely_mentions_the_marker_is_not_a_wall` | 普通长标题命中 `just a moment` | `None`；`请稍候…`／`Just a moment...`／`Attention Required! \| Cloudflare` 仍命中 |

回归：`pytest tests/unit` 全量通过；`ruff check`、`ruff format --check`、`mypy --strict` 全绿。

## 没有做的（明确记录，避免"以为做了"）

- **"正文达标不判墙"没有新增代码**：`classify_mhtml` 本来就用 `prose_words < 1200` 作为墙的闸门（`pageprobe.py:238`），即"有正文就不是墙"已经成立；T1 把它从"事后"补到了"事前"（标题证据 + `halted`）。不重复实现。
- **`_still_rendering` 仍显式排除 `blocked`**（`service.py:84-98`）：现在有 `halted` 兜在前面，暂态墙在标题关就被放过，不会进入二次抓取那条路；若真实链路发现仍会误判，再改这条假设。
- **扩展未做版本改名**：只改了 `actions.js` 的内容脚本（非 service worker），按 HANDOFF 的坑，worker 改名只在正式发版时连同版本号一起做。

---

# T2 结果：「未读到全文」统一口径（2026-11-26）

**验证档位：单元测试 + 静态门**（`release-check` 10 门）；真实链路复验合并到本轮收尾。

## 改了什么

| 改动 | 位置 | 为什么 |
|---|---|---|
| `read_page` 变成薄包装 + `_read_page` 干活，统一补**顶层字段** `full_text`（`ok` ⇒ `true`）与 `full_text_reason`（`paywall`/`pdf_only`/`abstract_only`/`doi_not_found`/`unsupported_site`/`blocked`/`not_written`） | `service.py:154-168`、`:827-838` | 用户要的"统一为未读到全文"落在一个可编程字段上；`status`/`reason` 原值不动，旧调用方零改动 |
| `pdf_only` 真的产生：页面挂了 PDF 链接、且没有正文/编号标题/文章结构时判 `pdf_only`，不再落到 `abstract_only`（后者会被读成"没权限"） | `pageprobe.py:277-282` | 报告"站点只给 PDF 却报没机构权限" |
| `_page_next` 的 `no_html` 文案改中性：**"未读到全文，不等于没有权限"** + 三种常见原因 + `pdf_url` 路线，且**删掉**了"ask the user to sign in" | `service.py:129-134` | 同一段文案被 40+ 次调用照抄进结论 |
| `skills/paper-page/SKILL.md`：判据从 `status=no_html` 改成先看 `full_text`，并明写"不要推断成没有机构权限" | `SKILL.md:96-104` | 子代理的"权限"结论就是照这段抄的 |
| MCP docstring + `schemas/tools.json` 同步（`scripts/dump-tools.py` 重生成） | `server.py:822-843`、`schemas/tools.json` | 文档承诺过 `unparsable`，但全树 0 产生点；本次把它从清单里去掉，`pdf_only` 有了真实现 |
| 撞墙时 `quota_charged` 改为**实测网络动作数**（`_charged_units`） | `service.py:138-147`、`:1013-1017` | T0 结论 3：报价 1、实扣 2（audit 两条 goto）。单次导航仍是 1，两次导航如实报 2 |

## 测试（先红后绿）

- 新增 `test_full_text_is_the_field_to_branch_on`：五种 `no_html`/`unsupported_site`/`blocked` 都 `full_text=false` 且 `full_text_reason` 正确，同时断言 `status` 未被改动。
- 新增 `test_a_pdf_only_landing_page_says_pdf_only`（先失败：当时返回 `abstract_only`）。
- 新增 `test_a_paywall_answer_points_at_a_file_it_actually_wrote`：把报告 L32 的"给了路径却没有文件"钉成不变量。
- 重写 `test_next_asks_the_user_to_sign_in_instead_of_retrying` → `test_next_does_not_blame_the_readers_permissions`：断言文案**不含** `sign in`、含 "no access"（作为"这不是"的说明）、含 `pdf_url`、且 ≤300 字符。

## 没有做的（明确记录）

1. **`unparsable` 没有强行造出来**：计划里写"把 `pdf_only`/`unparsable` 做出来"，但 `unparsable` 在今天没有任何可判定的语义（没有可复现的样本），凭名称编一个只会再造一个说谎的值 —— 改为**从文档清单里删掉**，`pdf_only` 则按真实语义实现。这是对计划的一处有意偏离。
2. **抓取路径的 `quota_charged` 仍是常量 `PAGE_READ_QUOTA=2`**：warmup 两次 goto + 抓取实扣 3、报价 2。改它会牵动 `bootstrap.py` 的报价表、`test_action_cost_matches_plans.py` 与 budget 文档，放到 T4（缓存/额度一起改）以免一处改动混两件事。
3. **`bytes` 仍是"去 `<script>` 之前"的桥回传长度**（`test_snapshot_verb.py:123/205` 把它钉住了）。真正的问题是"给了路径却没有文件"，已用不变量测试覆盖；字节语义不在本轮改。

---

# T3 结果：并发串话（2026-11-26）

**验证档位：单元测试 + 静态门**；实盘两路并发仍留到收尾（T0 已用确定性方式命中 L26 同一串 URL）。

## 根因（已核实）

锁只保护"导航 + 抓取"（`with self._browser_transaction()`），而**决定复用哪个标签页的那次读取在锁外**——于是 A 的"前台标签快照"与 B 的"工作标签导航"可以重叠，A 把 B 的页面当成本文（L26/L27）。同时 `_snapshot_locked` 的 docstring 自述"调用方已持锁"，那处调用却未持锁。

## 改了什么

| 改动 | 位置 | 为什么 |
|---|---|---|
| 把"墙标记 + 前台标签探测 + open-tab 复用"整段**移进** `with self._browser_transaction():` | `service.py:958-1001` | 消除"锁外读页 / 锁内导航"的重叠窗口；顺带恢复 `_snapshot_locked` 的契约 |
| 缓存命中仍在锁外返回 | `service.py:895-911` | 0 额度的免费路径不该为了一把浏览器锁排队（这也是为什么要挑着搬，而不是整段包住） |
| 响应新增 `captured_url`：**实际抓到的那个页面**的 URL | `service.py:1129-1132` | 计划里写的 `requested_doi`/`resolved_doi` 属于"让调用方能自检"；实际更有用的是"抓的是哪一页"，调用方可直接与 DOI/`final_url` 比对 |

## 测试（先红后绿）

- 新增 `test_the_probe_of_the_tab_in_front_holds_the_browser_lock`：monkeypatch `_snapshot_locked`，在里面对 `state_dir/browser.lock` 做一次 50 ms 的 `interprocess_lock`，断言**拿不到**（说明锁确实被持有）。这条是结构断言，不依赖时序，不会 flaky。
- 新增 `test_the_answer_names_the_page_it_captured`：`captured_url` 必须是真相。
- 夹具随之修正：探针进了同一个事务，就与导航**共用同一个 adapter 脚本**（`test_page_read_wall.py` 两条、`test_page_read_open_tab.py` 一条）——这是行为变更的正常后果，不是"改测试迁就实现"。

## 没有做的（明确记录）

**`status: "busy"` 没做**。计划里"冲突时返回 busy"需要：新错误码 + `server.py` 映射 + 工具 schema/文档 + 与"锁内可以等 180 s"的既有设计做取舍，属于**新的设计决策**，不是修 bug 的必要条件。当前先用"锁覆盖选页 + 同源证据"消掉串话；是否再引入 busy 语义，建议单独一轮/单独 ADR 决定。

---

# T4 结果：旧缓存不再无法刷新（2026-11-26）

**验证档位：单元测试 + 静态门**。

## 改了什么

| 改动 | 位置 | 为什么 |
|---|---|---|
| 缓存条目新增**判定指纹** `judge`（外加 `reason`/`prose_words`/`final_url`/`captured_url`）；`_page_cache_get` 要求 `judge == _PAGE_JUDGE_REV` | `service.py:154-166`、`:779-795`、`:816-835` | 报告 P0-2：同一 DOI 一小时内只能拿回同一份"判成摘要"的旧快照。指纹进**条目**而不是键，旧条目自动失效、**不删任何文件、不需要用户清缓存** |
| `read_page(..., refresh: bool = False)`：`refresh=True` 跳过缓存重新导航 | `service.py:854-870`、`:917` | 用户唯一的强制手段；默认关，因为"再导航一次"正是 2026-11-24 D1/D2 事故的成因 |
| DOI 建 target 时 `casefold()` | `service.py:914-918` | 实测同一 DOI 因大小写各存一条（一条 blocked、一条 ok），墙标记保护不到另一写法 |
| MCP 工具签名 + docstring + `schemas/tools.json` 重生成 | `server.py:switch` | `additionalProperties: false` ⇒ 不重生成就拒收新参数 |

## 测试（先红后绿）

- `test_a_capture_without_a_judge_stamp_is_not_served`：把条目改回旧格式（无 `judge`）⇒ 必须不再被当作缓存命中，而是重新导航。
- `test_refresh_navigates_again_on_request`：第二次普通调用 `cached=True/0 额度`（既有行为不变），`refresh=True` 必须重新导航且计费。
- `test_doi_case_does_not_create_a_second_entry`：大写 DOI 写入后，`page-read.json` 里只有一条小写键。
- 既有 `test_page_read_idempotent.py` 的"第二次 cached、0 额度"断言仍通过（默认路径一字未改）。

## 影响面（对真实环境）

本机 `%LOCALAPPDATA%\scholar-search\state\page-read.json` 现有 45 条旧条目**全部没有 `judge`** ⇒ 从这一版起它们不再被当作缓存命中（也不会被删除）；下一次读取会重新导航并写入带指纹的条目。这是有意的：那 45 条里有 6 条 blocked 标记与 1 条"判成摘要"的 ok 快照，正是报告里反复出现的元凶。

---

# T6 结果：page2md 分节失真（2026-11-26，P1-5）

**验证档位：单元测试 + 两份真实抓取的实测对照**。

## 根因（探针实测，不是推断）

`_section_entries` 的 `class="section-title"` 分支用 `title_element.getparent()` 当容器。**ACS 把 14 个节标题全挂在同一个 div 下**，于是 14 个条目的 `_own_blocks(容器)` 返回**同一批 529 块 / 106,817 字符**（探针 `probe-collect.py` 直接打印出来）。下游的指纹去重于是让第一个条目吃下整篇正文、其余 13 个只剩各自唯一的残留垃圾 —— 这就是"`01-introduction` 24,576 tokens，其余各 613"的真相：**613 是残留导航，不是被切开的小节**。

同时确认了 `_own_blocks` 只跳过嵌套的 `<section id>`，而 ACS 用的是 `class="section-title"`（已一并修）。

## 改了什么

| 改动 | 位置 | 效果（实测） |
|---|---|---|
| `_without_shared_container_duplicates()`：块列表完全相同的条目只保留一个 | `page2md.py:567-590`、`:642` | JACS 抓取：**14 节 → 1 节**；ACS 新文：**7 节 → 2 节**（Introduction + Supporting Information），`bytes_md` 130,399 → 97,913（删掉的 32 KB 全是 `Close Figure N` / `Google Scholar` 垃圾） |
| `_own_blocks` 跳过嵌套的 `class="section-title"` 子树 | `page2md.py:475-487` | 外层标题不再吞子节正文 |
| `warnings` 新增"正文章节不足"：`tokens_total ≥ 5000` 且 `sections_total ≤ 2` 时报出 | `page2md.py:1562-1569` | 站点给不出可用容器时，调用方**知道**按节阅读无效，而不是读到一份假目录 |

## 偏离计划的一处（重要）

计划写的是"条分节按 `<h2>/<h3>` 实际层级**重建**"。实测后我**没有**做重建，理由：ACS 的容器是共享的，重建等价于重写 `_own_blocks` / `_section_entries` 的核心走查（1400 行文件里最危险的一段），而现有夹具只覆盖 Elsevier/JATS 形态；在没有 ACS 形态的 fixture 之前动它，等于用一个样本赌所有出版商。本轮交付的是**确认过的那一半**：垃圾小节不再冒充章节、失败状态如实上报。

⇒ **遗留 TODO（下一轮）**：为"共享容器"形态加脱敏 fixture，再把走查改成"以标题为边界切分"，目标是 JACS 那份能切出 ≥4 个真实小节。

## 测试

- `test_section_titles_sharing_a_container_are_not_reported_as_sections`：两条标题共用一个容器 ⇒ 只出一个 `##`，且两段正文都在其中（不重复）。
- `test_a_long_document_in_one_section_says_the_split_failed`：长文单节 ⇒ `sections_total ≤ 2` 且 warnings 含"章节不足"。
- 全量 `pytest tests/unit` 通过（606 passed）。

---

# 真实链路复验（2026-11-26，仓库代码 + 正在运行的浏览器）

**做法**：`SCHOLAR_SEARCH_HOME=…\wensu-test-home` + `PYTHONPATH=src`（复刻 HANDOFF 的真机套路），复制运行中宿主发布的桥接端点，**不启动第二个宿主**。额度记在隔离家里，**用户额度未消耗**（仍 298）。

## 结果（三条都符合预期）

| 观察 | 说明 |
|---|---|
| 第一次 `page_read(10.1021/jacs.4c07518)` → `blocked`，`signal=title:请稍候`，`final_url` 是文章 URL（同源），`quota_charged: 1` | 真墙（Cloudflare 中间页）**如实拦下**；T1 的同源规则没有把真墙放过，报价 1 也与"只跑了一次 goto"一致 |
| 等 15 s（挑战页自清）后 `page_read` → **`ok`**，`full_text: true`，`captured_url` = 文章 URL，`bytes 4,807,928`，`quota_charged: 2` | T2 的 `full_text`、T3 的 `captured_url` 在真实返回里成立 |
| 同一份抓取 `page2md` → `bytes_md 61,272`，`engine: sections`，warnings 含**新的"正文章节不足"** | T6 的告警在真实页面上真的出现 |

## 复验发现的一条新事实（记为 TODO，不在本轮修）

**0 额度的 open-tab 复用对 ACS 这类站点实际不生效**：`service.py:936` 的复用判据是 `identifier in open_tab["url"]`，而 ACS 的落地 URL 是 `/jacsat/article/146/41/28131/...`，**不含 DOI**。于是即使人已经把文章摊在屏幕上，读取仍会重新导航（2 额度）并可能再次撞墙。本次实测就是这样：上一个答案已经写了墙标记，15 s 后那次调用仍然重新导航。

修法（下一轮）＝把复用判据从"URL 含 DOI"放宽到"同域名 + 抓到的页面自证是文章（`full_text` 或 `prose_words` 达标）"，同时保留 T3 的同源校验。这属于策略变更（放宽复用＝放宽"只读眼前这一页"的边界），建议单独一轮 + 真实样本推演，不塞进本轮。

---

# P3-11 / open-tab / P2-9 结果（2026-11-26，第二轮）

**验证档位：单元测试 + 静态门**（真实链路在发版前统一复验）。

## P3-11 额度语义：只有导航计费，报价原来是错的

取证：`policy.py:354` 的 `state.used += 1` 只对 `NETWORK_VERBS`（`goto/click/select/type`）生效，`_snapshot_locked` 是 `adapter.execute` 直连（`service.py:1238`）⇒ **抓取本身不计费**。所以"page_read = 2"这个报价在两个方向上都错：单次导航实扣 1、私有补丁两次导航实扣 2。

| 改动 | 位置 |
|---|---|
| 所有返回点改**实测**计费 `_charged_units(outcomes)`（含抓取路径、抓取后判墙、DOI 不存在） | `service.py` 5 处 |
| 新增 `quota_reason ∈ {cache_hit, open_tab, challenge, navigate, unsupported_site}` | 同上 |
| `ACTION_COST["page_read"]` 2 → **1**（发布版是一次导航；两次导航的变体由 `quota_charged` 如实回报） | `bootstrap.py:33-35` |
| 工具 docstring 同步（"charged per navigation，抓取免费"） | `server.py:822-827` |

测试：`test_page_read.py` / `test_page_challenge.py` 里钉住旧价 2 的两处改成 1 + 断言 `quota_reason`；新增断言在 open-tab 用例里（0 / `open_tab`）。

## open-tab 0 额度复用：改为按页面自证身份

上一条复验发现 ACS 落地 URL 不含 DOI，导致 `identifier in url` 永不成立、人在看文章也重新导航（2 额度 + 再撞墙）。

改法：新增 `pageprobe.citation_doi(path)`，读页面自己的 `<meta name="citation_doi">`（真实 ACS 抓取里存在，实测 1 处）；复用判据变成"URL 含 DOI **或** 页面自证 DOI 相等"。这是**正向身份**，不是"看起来像文章"。

测试：`test_a_page_that_names_its_doi_is_reused_without_asking_the_site`（0 额度、`source=open-tab`）、`test_a_page_naming_another_doi_is_not_reused`（别人的 DOI ⇒ 不复用且删掉猜出来的快照）。

## P2-9 `10.3866`（物理化学学报）覆盖缺口

`publishers.py` 新增 `Publisher("pku-whxb", ("whxb.pku.edu.cn",), ("10.3866",))`；host 取该刊 PDF 页脚反复印的 `www.whxb.pku.edu.cn`（[期刊站](https://www.whxb.pku.edu.cn/)）。

**已知残留**：若 doi.org 实际跳转到该社平台 `ccspublishing.org.cn`，仍会报 `unsupported_site`。那个域名承载多个期刊，加进白名单是策略决定（ADR 0019 的"策划列表"），需要先真机看一次落地地址；本轮不擅自扩大白名单。

---

# 0.14.27 发布与实测（2026-11-26）

| 步骤 | 结果 |
|---|---|
| `v0.14.27` + `npm-v0.14.27` tag 推送 | main `c3a2027..923dd49`；CI 出 PyPI |
| `pnpm publish` `packages/dsh-wensu` | `@hui-xu-ai/dsh-wensu@0.14.27` Published |
| 桌面 bundle | `remove_bundle` → `install_bundle @0.14.27`（走官方 registry），applied |
| 本机 CLI | `pip install -U wensu==0.14.27`；`wensu setup`（需先停 `native-host/main.py` 那个 python 进程，否则 rmtree 报 WinError 32） |
| `wensu doctor` | cli 0.14.27 / extension 0.14.27 / mismatch false |
| MCP 进程 | 重启 `wensu serve` 后 `status` 报 0.14.27 + extension 0.14.27 |

## 现场实测（额外交互，隔离家以外）

```text
page_read(10.1021/jacs.4c07518) → blocked / signal title:请稍候 / quota_charged 1 / quota_reason challenge / full_text false
  （真墙；public page_nav 只导航一次，所以是 1，不是 2）
等 20 s 让挑战页自清
page_read 同一 DOI → ok / source open-tab / quota_charged 0 / quota_reason open_tab / full_text true
  ← 这就是 open-tab 新身份校验在真实站点的证据：ACS 落地 URL 不含 DOI，旧版只会重新导航（再撞墙、再扣额度）
page2md → 65,261 B，engine sections+trafilatura，warnings 含新的「正文章节不足」
```

额度 298 → 297（一次撞墙导航 1 单位）。

## 两个必须交代的副作用

1. **私有 warmup 补丁被升级覆盖**：装机版 `core/page_nav.py` 现在是公开的 23 行版本（补丁是 121 行）。要恢复请跑
   `D:\Python\DeepSeek\Private\wensu-warmup\install-warmup.ps1`（那是你的私有仓库，我没有代跑）。
   影响：每次 `page_read` 从两次 goto 变回一次（额度更省，但撞墙概率回到公开版水平）。
2. **extension 需要 reload 一次**：`actions.js` 的 CAPTCHA 选择器改动属于内容脚本，`doctor` 报的 0.14.27 读的是磁盘 manifest；
   要让新选择器真正生效，需在 Edge 的扩展页点一次「重新加载」（或重启浏览器）。我没动你的浏览器。






