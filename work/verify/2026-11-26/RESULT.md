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

