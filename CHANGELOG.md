# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/).

## [0.14.16] - 2026-11-25

### Removed — the experimental figures feature and every permission it needed

`page_read(figures=true)` never became dependable: reading article images through CDP depends on
three things that are not under the tool's control — the window being visible (Chromium does not
paint an occluded renderer, so its images are never fetched), the images actually going over the
network (a cache hit emits no response event), and the kernel and the extension agreeing on timing.
Measured on one MDPI article across five builds: **9 figures → 4 → 4 → 0**, with
`bridge.timeout` on consecutive captures. It is therefore withdrawn rather than shipped half-working
(ADR 0026 records the measurements).

* `page_read` has no `figures` parameter; `goto`/`snapshot` have no `assets`/`asset`; `page2md` no
  longer adopts a captured `assets/` directory.
* The extension's `debugger` permission is gone, and so is the publisher-host `content_scripts`
  entry (25 domains) that existed only to walk those pages for figures. Permissions are back to
  `nativeMessaging, storage, tabs, downloads, pageCapture`, with content scripts on CNKI and Web of
  Science only.
* The Markdown keeps the publisher's image URLs and the warning says so; nothing pretends the
  figures were captured.

The code stays in git history (`v0.14.14`, `v0.14.15`) for a future attempt.

### Fixed — no crash-restore bubble

Launches pass `--hide-crash-restore-bubble`, so a browser that was force-closed does not ask about
"restoring pages" the next time. (The second-window fix landed in 0.14.17 — this release only
carried the flag, and the entry above originally claimed both. Corrected here rather than silently
edited, because 0.14.16 is already published.)

`background-0.14.16.js`, as the cache-busting rule requires.

## [0.14.38] - 2026-11-26

### Fixed — 0.14.36 与 0.14.37 发布的 worker 里没有窗口聚焦

那一版我只改了工作区的 xtension/background-*.js，没有 git add：tag 里没有这份改动，CI 从 tag
构建，于是两个已发行版本的 worker 仍只设 state: "maximized"。本地 elease-check 的 ssets 门
只校验"引用的文件存在"，而本地 wheel 读的是工作区——两边都看不见这个差异。

本版把改动真正入库，并新增一道门 committed：**发行前先提交，门会比对 xtension/、src/、
skills/、pyproject.toml 与 HEAD**，任何"只在磁盘上"的发售文件都会让它失败。发布流程因此改为
"提交 → 跑门 → 打 tag"。

`background-0.14.38.js`。
## [0.14.37] - 2026-11-26

### Added — 「上一个动作还在跑吗」现在能看见了

page_read 一次调用跑完整个计划，所以拿到 	imeout 的调用方没有任何办法判断上一个计划是否已经终结
（P5 验收原话）。status 现在报两个字段，都不发浏览器动作：

* rowser_busy — 用现有的 state/browser.lock 非阻塞试取：取不到就说明有读取正在进行；
* last_job — state/last-job.json，记录 job_id/	erminal/stage/eason/doi/publisher/
  quota_charged/capture_sha256 与 inished_at，rief 与完整回包都带。

### Fixed — 落点与预热的两处口径

* 出版社用**首页**回答深链时，不再报成 bstract_only（那读起来像"这篇没有正文"）：捕获地址是站点根
  路径且页面上没有 DOI ⇒ 
o_page / landing_home，不发布、不写缓存。P5 验收里 ACS 那篇 192 词就是这么来的。
* warm_up 的 opened[] 带回 **landing_host / landing_url**：预热是按**子域**生效的（Wiley 的
  4spepublications… 没有覆盖 scijournals…）。批量 skill 已改为按 landing_host 分组。

`background-0.14.37.js`，按缓存规则改名（worker 内容未变）。
## [0.14.36] - 2026-11-26

### Fixed — the gate wait maximized the window but did not bring it forward

wait_gate_clear asked for state: "maximized" only. A maximized window that sits behind
whatever the person is looking at is still invisible, which defeats the one thing the action
exists for (P5 retest 2026-11-26, F34-01: the branch had never run, and the report pointed out the
code never asked for focus). It now asks for ocused: true before activating the tab, and a test
keeps the branch asking.

`background-0.14.36.js`, as the cache-busting rule requires.
## [0.14.35] - 2026-11-26

### Fixed — the native host refused the verb ADR 0027 had approved

The host keeps its own copy of the action vocabulary on purpose (a compromised extension cannot
widen the scope), and wait_gate_clear was added to the kernel's list only. The action passed the
kernel's capability gate and was refused by the host **before** the frame reached the extension, so
the wait never ran: the P5 retest saw locked / gate_wait_unavailable / waited: false /
wait_reason: policy.verb on a real Wiley gate (F34-01).

A cross-layer contract test now requires the kernel's VERBS, the host's VERBS, the publisher
manifest and the shipped worker's CAPABILITIES to all cover what a page read plans — and calls the
host's own alidate_request with the parameters a read actually sends. Testing only the worker's
capability list is what let the same class of mistake through twice.

`background-0.14.35.js`, as the cache-busting rule requires (worker unchanged since 0.14.34).
## [0.14.34] - 2026-11-26

P5 真实链路验收（`docs/reviews/wensu-0.14.33-p5-2026-11-26.md`）的 3 条 P1 与 1 条 P2。

### Fixed — the gate wait was implemented but never advertised

The worker had the `await_gate_clear` branch, and `CAPABILITIES` still listed only
`goto`/`snapshot`/`sleep`. The capability gate therefore refused the action **before it was
sent**, so the "wait for the person" never happened: the real read returned `verification_timeout`
after 3.3 s with zero wait actions executed (F33-01). The unit tests could not see it — the
fixture adapter answers no `info()` at all, so the gate was skipped. A contract test now reads
`CAPABILITIES` / `CHANNEL_CAPABILITIES` out of the shipped worker and asserts that every verb a
publisher read plans is advertised.

### Fixed — a wait that never ran was reported as "the person did not click"

`_await_gate_clear` swallowed the failure and the caller answered `verification_timeout`, whose
advice is "ten seconds passed, solve it in the browser". Two different failures now have two
different names (F33-02):

* `verification_timeout` — the wait ran, the budget expired, the title still looked like a gate
  (`terminal: timeout`);
* `gate_wait_unavailable` — the wait could not run at all (`terminal: blocked`, with `waited:
  false` and the underlying reason), because that is a build or bridge problem, not a slow click.

### Fixed — ordinary prose containing `cited by` truncated the article

`_cut_tail_markers` fell back to a bare substring search when it found no heading, and `excited by`
contains `cited by`: a real Springer capture was cut from 20,225 to 16,933 characters, losing its
Fabrication Steps and Conclusion sections — while `terminal` said `ok`, the hash matched, and
`coverage: 0.365` was too high to warn (F33-04). A marker now has to start a line, so only a real
heading cuts. Replays cover `excited by` (not cut), a genuine `Cited by` heading (cut), and the
conclusion surviving in every output.

### Fixed — a refused warm-up reported success and no cost

`warm_up` caught a refusal per target and returned `status: ok, quota_charged: 0` while the ledger
had paid one unit and a cooldown had been written; it then went on to the next target (F33-03). A
refusal now ends the whole warm-up: `status: blocked` with the signal, the cooldown, the cost that
was actually spent, and the targets that were not attempted.

`skills/scholar-batch-read/SKILL.md` also records what the acceptance measured: warm-up is per
**subdomain**, not per publisher — Wiley's warm-up tab and its second article lived on different
subdomains and the gate came back.

`background-0.14.34.js`, as the cache-busting rule requires.

## [0.14.33] - 2026-11-26

单任务读取流程与批量编排（`work/tasks/2026-11-26-read-flow/plan.md`）：让"卡在哪一步"和
"人已经点完验证"变成可读的事实，而不是让调用方去猜。

### Added — 每次读取都说明它停在哪一步

`page_read` 的回答多了四个字段：`job_id`（这次读取）、`terminal`
（`ok`/`partial`/`blocked`/`timeout`/`no_page`/`unsupported_site`）、`stage`
（`cache`/`navigate`/`wall`/`capture`/`identity`/`publish`）与 `evidence`（实际观测到的标题、
落地地址、页面自报 DOI、正文词数等）。`stage` 由回答自身的字段推导，因此每个出口都被覆盖。

### Added — 验证墙改为"请人点，并等到点完"（ADR 0027）

新增动作 `await_gate_clear`：识别到验证页后，工作标签页的窗口被**最大化并切到前台**，扩展每
2 秒读一次标签页标题、最多等 10 秒。标题不再像验证页 ⇒ 人已经点完，继续抓取；到点仍未清 ⇒
`terminal: timeout`、`reason: verification_timeout`，批量层据此跳过该出版商。

它不是网络动作（`NETWORK_VERBS` 未变），不扣额度；不重新导航、不换 IP、不延时重试。这也是
`wait_for` 做不到的事：内容脚本只注入两个渠道域名，出版社页上没有接收端（审计 F08）。

### Added — 预热标签页与批量读取 skill（ADR 0028）

`goto` 支持 `keep: true`（与 `open: "new"` 一起用）：这类标签页记进**保留名单**，
`closeDisposableTabs()` 永不触碰——否则下一次导航就会把预热页清空。新工具
`warm_up(targets)` 为每个出版社打开**一篇**文献到保留标签页，返回 `opened[]` 与总费用；
每个目标 = 1 次导航 = 1 额度 + 1 次站点访问，所以调用前必须告诉用户。

`skills/scholar-batch-read/SKILL.md` 把批量流程写成规范：按出版社分组、组内串行、预热成本先告知、
每条 `ok` 立刻把 `mhtml_path` + `capture_sha256` 交子代理离线转换、`blocked` 立即停、
`timeout` 跳过该出版社、失败写账本、收尾一次汇报并按原因询问重试。

`background-0.14.33.js`，按缓存规则改名（worker 含新动作与保留名单）。

## [0.14.32] - 2026-11-26

0.14.31 验收（`docs/reviews/wensu-0.14.31-acceptance-2026-11-26.md`）的 3 条 P1、4 条 P2，以及
R31-04：检查与存储分离、一次读取只发布一份捕获。

### Fixed — the extension re-navigated behind the kernel's back

`navigate()`'s retry wrapped the whole closure, so "update accepted, wait failed" sent
`tabs.update` a second time 300 ms later: two navigations, one `goto` in the audit log, no
charge and no visibility (R31-01, replayed in a Node VM against fake browser APIs with the real
worker code). Only a *rejected update* is retried now — the one case where the browser refused
to start the navigation — and an issued-then-failed navigation reports `navigation_issued` /
`navigation_attempts` instead of silently going again. Every successful `goto` reports
`navigation_attempts: 1`.

### Fixed — the body fallback fixed `page.md` and nothing else

The paragraph fallback replaced the body but not `sections_found`, so `index.json`, `page.brief.md`,
the selection and `page.core.md` were still built from the failed section walk: an ACS article
with 16 KB of recovered body kept an index holding "Supporting Information" and `core_tokens: 0`
(R31-02). Sections are rebuilt from the same body, and when nothing matches the core markers the
first section stands in for `core` — reporting zero hid the article from a core reading.

### Fixed — another article on the same publisher passed as this one

Publisher attribution is not article identity (R31-03). The check now reports its strength:
`declared` (the page prints the requested DOI), `url` (the address carries it), `publisher_only`
(no DOI anywhere, which ScienceDirect's PII addresses do by design) or `mismatch` — and only
`mismatch` refuses. The answer carries `identity` so a caller that needs more than
"not contradicted" can ask for it.

### Fixed — smaller ones from the same acceptance

* **R31-05** the verdict rules changed, so `_PAGE_JUDGE_REV` is 2; entries judged under the old
  rules are not served.
* **R31-06** a stopped plan reported the plan's cost instead of the cost of what ran: a first
  navigation refused by the site reported 2 while the ledger used 1. `RiskBlocked` now carries
  the count the planner measured.
* **R31-07** `\bname` matched the tail of `data-name`; the meta attribute regex now requires
  whitespace or `<` before the attribute.
* **R31-08** a page whose text produced no output at all was silent when it had fewer than 500
  words. Empty output from non-empty source always warns.

### Changed — inspection no longer writes the article's file (R31-04)

Every `snapshot` used to write `pages/<slug>/page.mhtml`, so one read that looked twice, or
glanced at the reader's own tab, left bytes behind that no verdict described. Inspection now
writes to `pages/.probe/` and is deleted when it is not chosen; the one capture an answer refers
to is published once, atomically, under **its DOI** (`pages/10.1021_jacs.6c13448/page.mhtml`).
Alongside it:

* the answer and the cache entry carry `capture_sha256`, and a cache hit is only served when the
  file still hashes to it — a replaced capture is a miss, not a shortcut;
* `page2md` records the digest of its input, and reports `input_changed` when the file was
  replaced while it was being converted.

One article, one file; a later capture replaces it, and every consumer can tell which bytes its
verdict describes.

`background-0.14.32.js`, as the cache-busting rule requires.

## [0.14.31] - 2026-11-26

0.14.30 的导航/并发评估（`docs/reviews/wensu-0.14.30-navigation-concurrency-2026-11-26.md`）发现的
两条 P1，加上并发与归属方面的两处收紧。

### Fixed — a reference's DOI was reported as the article's own

`meta_content` asked whether the wanted field name appeared *anywhere* in a `<meta>` tag. MDPI
prints `citation_reference` tags whose content quotes `citation_doi=…`, so the reference won and
the page declared a Nano Letters DOI: `declared_doi` was a whole bibliographic description, and
the read was then — correctly, but for the wrong reason — refused as "another article" (measured
on `10.3390/s26041303`). Only `<head>` is read now, and the `name` attribute must match exactly.

### Fixed — an article with no section containers converted to almost nothing

ACS prints its body in none of the shapes the section walk recognises, and `trafilatura` is an
optional dependency the default install does not have: a 3,626-word capture became 44 bytes of
body plus "Supporting Information", with `status: ok` and one MathJax warning. Two changes:

* a fallback that needs no containers — headings and paragraphs straight from the document,
  used only when the walk produced almost nothing (`engine: "paragraphs"`);
* `meta.json` now carries `coverage: {source_words, extracted_words, ratio}`, and a conversion
  that kept less than 30 % of the source says so in `warnings`. A call that succeeds is not the
  same as an article that arrived.

### Fixed — two readers of the same page each paid for it

The cache was checked before the browser lock, so a second request that queued behind the first
navigated all over again: two answers, four units, neither `cached` (offline concurrency test).
It is checked again once the lock is held.

### Fixed — a capture was accepted from any subdomain of the same public suffix

The identity check derived "same organisation" from the last two labels, which made
`unrelated.edu.cn` a sibling of `whxb.pku.edu.cn`. Only a subdomain of a *curated* domain is a
mirror now; a publisher whose mirrors live elsewhere needs an entry in `publishers.py`, not a
guess about public suffixes.

`background-0.14.31.js`, as the cache-busting rule requires (worker unchanged since 0.14.29).

## [0.14.30] - 2026-11-26

复验 0.14.29（`docs/reviews/wensu-retest-0.14.29-2026-11-26.md`）发现的残留。两条是 0.14.29 自己引入的。

### Fixed — the capability gate treated "unknown" as permission

`cmd=info` answered from a handshake that only ever ran on some other call, so a freshly started
host reported nothing but its own version — and the gate read "no capabilities" as "no opinion"
and let the plan run: the retest saw one `goto` execute, spend a quota point and time out 17 s
later. `cmd=info` now performs a bounded handshake first, `build_info()` distinguishes `ok` /
`old` / `timeout`, and an unknown capability set is **refused** (`bridge.handshake` when the
extension never answered, `action.unsupported` when it is older than this build) before anything
is navigated.

### Fixed — a wall the follow-up's own capture recognized was folded into "no benefit"

`_follow_fulltext` returns the capture it took, and a capture that recognized a wall came back
as `saved: {status: blocked}`; the caller only looked at the raised `RiskBlocked`, so the initial
paywall answer survived with its own path. Both shapes are one terminal state now: `blocked`,
`mhtml_path: null`.

### Fixed — a failed plan reported one unit whatever it actually ran

The exception paths charged a constant `1`, so the private warmup patch's two navigations were
reported as one (retest measured 4 charged against 3 reported). The charge is counted from the
plan's network actions.

### Fixed — a capture without DOI metadata was accepted whatever it held

The identity check only fired when the page declared a *contradicting* `citation_doi`, so a Wiley
request answered with an ACS page came back `ok` with `full_text: true`. The captured address is
judged first — the requested DOI, the publisher's own host, a mirror subdomain of the same
organisation, or the DOI in the URL — and `citation_doi` is the extra confirmation.

### Fixed — two local figures with the same file name became one

`assets/` used the figure's own name, so `a/figure.png` and `b/figure.png` in one page resolved to
one file and the second silently replaced the first. Local images are content-addressed too, which
also means a re-conversion with changed bytes gets a new file instead of keeping the old one.

`background-0.14.30.js`, as the cache-busting rule requires (worker unchanged since 0.14.29).

## [0.14.29] - 2026-11-26

审计（`docs/reviews/wensu-audit-0.14.28-2026-11-26.md`，8 项 P1 + 6 项 P2）的修复版本。

### Security — the converter could read and write outside the directories it was given

* **F01** a local image reference was resolved and read wherever it pointed, so a synthetic page
  could copy any file the process could read into `assets/`. Absolute paths, drive letters and
  UNC names are refused, and the resolved target must stay inside the document's directory —
  checked before any read.
* **F02** an MHTML resource's file name came from its `Content-Location`, split on `/` only: on
  Windows a backslash became a path component and the write landed outside `assets/`. Names are
  content hashes now, and both write paths verify the resolved destination.
* **F04** the native host turned "the caller specified domains that survive nothing" into "use
  the default trusted list" (`effective or None`), which is the opposite of narrowing. It now
  refuses with `policy.domains`.
* **F11** a quota state file holding `used: -20` was read as-is, so `status` reported 320
  remaining out of a 300 daily limit. Only a whole, non-negative count, a finite timestamp and a
  real date are accepted; anything else is reported as corrupt, never as fresh quota.
* **F12** an empty `http-token` file was accepted as the credential — every request that omitted
  the header compared equal to `""`. An unusable token now refuses to start the transport.

### Fixed — the page result could describe a page that was not the one asked for

* **F05** a capture whose own `citation_doi` names a different article is now `no_page` /
  `capture_mismatch`, and its bytes are deleted instead of cached as a success.
* **F06** `source: "open-tab"` returned `full_text: true` for whatever the tab held as long as the
  DOI matched. It runs the same classifier as the navigation path.
* **F07** a full-text follow-up that hit a wall was folded into "no benefit", losing both the stop
  and the charge. `RiskBlocked` propagates, the answer is `blocked`, and the cost follows the
  ledger.
* **F08** the gate-title wait was a `wait_for` on publisher pages, where no content script is
  injected: it could only ever time out. The capture decides instead, and the wall's bytes are
  discarded as before.
* **F13** a cache hit dropped `captured_url`, `judge` and `prose_words`, and filled `final_url`
  with the *requested* address. It now carries the same verdict the live answer carried, and a
  timestamp from the future is treated as corrupt rather than fresh.

### Fixed — one conversion could borrow another's sections

* **F09** sections travelled through a module-level list that `convert` read after the extraction
  returned, so two conversions in parallel produced one document's `page.md` next to the other
  document's `index.json`. They are a return value now; the counters that remain module state are
  used under a lock. A test that had been passing on the previous test's leftovers now provides
  its own sections.
* **F10** a second conversion into the same output kept the first run's figure, and two inline
  resources with the same name resolved to one file. Local images are copied every time; inline
  ones are content-addressed.

### Added — the handshake says what is running, and a missing verb is refused before navigating

* `hello_ack` now reports the running worker's `version`, `worker` file and its capabilities:
  the verbs the background can serve anywhere, and the ones that need the content script (and so
  exist only on the channels' domains). `status` reports it as `bridge_build`, asked of the host
  rather than read off the manifest on disk.
* A plan that asks for a verb the connected build cannot serve where it is going is refused
  before anything is navigated (`action.unsupported`, no quota spent). An older extension that
  advertises nothing keeps the previous behaviour.
* **F14** the fixture adapter reports the landing address in `outcome.url` (as the bridge does)
  and the asked-for address in `data.requested_url`, so URL-attribution tests exercise the shape
  a real run produces.

`background-0.14.29.js`, as the cache-busting rule requires.

## [0.14.28] - 2026-11-26

### Fixed — Web of Science's `total` was the size of the export, not of the result set

`search` answered `total: 50` for a topic with tens of thousands of hits. The number came from
`parse_bibtex`, whose own comment said an export "never says how many the query matched" — the
page path kept that shape anyway "because callers and the skill read it" (2026-11-26 report,
P2-7). It now reports **no total at all**, and the answer carries the three numbers that can be
read together:

* `total` — what the site said it matched; `null` when the channel cannot learn it;
* `fetched` — how many records the fetch actually brought back, before this tool's own filters;
* `returned` — how many records this answer holds.

`truncated` follows the fetch, not the answer (`fetched < total`), and is `null` when the total is
unknown, so a local year filter no longer sends the caller to fetch what they already had.

### Added — `effective_sort`, because `relevance` does not click anything

`site_sort: "relevance"` takes no browser action: the channels cannot impose relevance, so the
site's own order stands — and that order is often date-descending, which is why a "relevance"
search came back as one year only (2026-11-26 report, P2-8). The answer now says which of the two
happened: `sort_applied` and `effective_sort` (`site-default`, `date` or `citation`).

### Added — `page_read(view="full")` follows the page's own full-text address

ACS lands on an abstract tab and injects the article only in its full-text view (2026-11-26
report, P1-4). Instead of a per-publisher URL template table that goes stale, the second look
follows `<meta name="citation_fulltext_html_url">` — a fact the page prints about itself; every
captured Wiley page carries it. Off by default, because it costs a navigation; `view_applied`
says whether the second look produced the article and `fulltext_url` names what was tried.

### Fixed — a gate title is not a verdict

The wall was decided from the title the `goto` reply carried *at that instant*. Measured live on
ACS: the title read 「请稍候…」 while the article was on screen minutes later, so a readable page
was reported as a challenge. The gate title now gets a free twelve-second `wait_for` on the
article's own `citation_doi` before the verdict — waiting is not a network action, so a real wall
costs time and no quota, and an interstitial that clears costs nothing at all.

`background-0.14.28.js`, as the cache-busting rule requires (worker unchanged).

## [0.14.27] - 2026-11-26

### Fixed — a wall is only claimed when the evidence belongs to this read

`page_read` judged a challenge from any title it could see: the last non-empty title across every
outcome of the navigation, or the title of whichever tab happened to be in front. Four ways it
answered `blocked` for a page the reader could read (2026-11-26 report, reproduced offline):

* two navigations lend each other titles — the article's own title is empty while the page paints,
  so the publisher home page's 「请稍候…」 was used instead;
* a wall marker made the next attempt look at the tab in front, which may be *another site*: an
  RSC DOI was answered with the `science.org` URL of whatever page was focused;
* `challenge_in_title` matched substrings, so "Loading: Just a moment please — Journal of …" was a
  wall; it now applies the same exact-or-short-prefix rule `risk.py` already used;
* the content script's generic `[class*='captcha' i]` selector matched the reCAPTCHA badge that
  sits on ordinary pages; named elements only now, and the CNKI slider keeps its own id.

Only the last navigation's title counts, its `url` must belong to this publisher or carry the DOI,
and the extension's own `halted` flag (did the gate title persist for 1.5 s?) is now read — the ACS
interstitial clears itself in about forty seconds, measured live. The tab-in-front probe also runs
under the browser lock now, so another read cannot navigate the shared tab between the probe and
the verdict. Answers carry `captured_url`.

### Changed — "no full text" is one field, and it is not "no access"

Every "no article body" case shared `status: "no_html"`, and the advice built on it told the reader
they had no institutional access — including for a site that only offers a PDF, and for a page that
simply serves no HTML. `full_text` (with `full_text_reason`) now answers the question that was
asked; `status` / `reason` keep their meanings. `pdf_only` is produced for the first time (it had
been documented and never emitted), and the advice says "not read", lists the routes, and stops
blaming permissions. `skills/paper-page` says the same thing.

### Fixed — a cached verdict can no longer outlive the rule that produced it

Cache entries carry a judge fingerprint (`judge`), `reason`, `prose_words` and both URLs; entries
written by an older release are not served (nothing is deleted). `page_read(refresh=true)` navigates
again on request. The cache key normalises the DOI's case — the same DOI used to sit in the file
twice, differing only in case, so a wall marker protected only one spelling.

### Fixed — quota is measured, and a page that names its DOI is reused

Only `goto`/`click`/`select`/`type` cost a unit; the capture is free. So a direct read costs **1**,
not the flat 2 the price table claimed, and a build that opens the publisher's home page first
costs 2 — the answer now reports what it was charged (`quota_charged`) and why (`quota_reason`).
Reusing the tab in front no longer requires the DOI to appear in its URL: ACS landing pages carry
the DOI only in `<meta name="citation_doi">`, so a page the reader already had open was re-navigated
(two units, often another challenge). The page's own claim is the identity; a page naming a
different DOI is not reused.

### Fixed — page2md no longer reports furniture as sections

ACS hangs every section title off one container, so all fourteen entries returned the same blocks:
the first held the whole body and the other thirteen held their unique leftover navigation ("Close
Figure 3.", "Google Scholar"), which is what "整篇正文落在 01-introduction" looked like from
outside. Duplicate containers now yield one entry, nested `class="section-title"` subtrees are not
swallowed by their parent, and a long document in one or two sections says so in `warnings` instead
of offering a table of contents that lies.

### Added — 10.3866

《物理化学学报》 (PKU Press) is on the curated list now, so its DOIs no longer answer
`unsupported_site`.

`background-0.14.27.js`, as the cache-busting rule requires (worker changed: the captcha selectors).

## [0.14.26] - 2026-11-25

### Changed — only two things may report a wall

The risk rules had seven detectors, and five of them were guesses: a login-looking URL, a header
login form, a `Just a moment…` title, and Cloudflare's `ray id` string inside an article. Each is
ordinary on pages nobody is challenging, and each dropped a read the reader could see (reported
twice, `10.1021/acs.inorgchem.1c03019`).

Two remain, and both are evidence that cannot be anything else:

* a captcha widget the content script sees **in the viewport**;
* the site refusing outright — HTTP 403 / 429.

The rest are recorded in `RiskGuard.last_note` (`url:login`, `body:login-form`, `title:…`) for the
audit trail and then ignored: a false wall costs a whole document, a missed hint costs one extra
snapshot that the capture classifies honestly. The body-marker check now also requires that the page
has no prose — `ray id` is written into ordinary pages. The cached wall marker drops from 30 minutes
to 5.

`background-0.14.26.js`, as the cache-busting rule requires (worker unchanged).

## [0.14.25] - 2026-11-25

### Fixed — a Letter has no headings, and it is still an article

`10.1021/acs.inorgchem.1c03019` is an Angewandte *Communication*: 19 long paragraphs, 3,817 words of
continuous prose, **no** `Introduction` / `Results and Discussion`. The classifier asked for those
headings and answered `abstract_only`, so the reader was told the tool could not capture an article
that was sitting inside the capture. Reported by the reader, who was right and pointed out that
Letter formats never print those headings.

Prose volume decides now: paragraphs of ≥ 25 words, and at least 5 of them totalling ≥ 1,200 words,
mean the page holds the paper. Section headings remain a fast path, and a blocking marker
(`purchase pdf`, `sign in to view`) still wins over any amount of prose. The reply carries
`prose_words` and `prose_paragraphs` so the numbers are visible rather than inferred.

Re-judging the real captures: ACS 3,626 words / 19 paragraphs → `ok`; Wiley 4,683 words / 36
paragraphs → `ok`; a one-paragraph abstract page stays `abstract_only`.

`background-0.14.25.js`, as the cache-busting rule requires (worker unchanged).

## [0.14.24] - 2026-11-25

### Fixed — the extension was still stopping on URL markers

0.14.22 retired the kernel's URL-based gate check, but `goto` kept passing `halt_url_markers` to
the extension, so the *worker's* gate watch still reported `halted` for a URL containing `captcha`
— and the planner turned that into `blocked`. Reported by the reader: "no captcha appeared", and the
tab title was the article. The markers are no longer sent (titles only), so a wall is again decided by
what is on screen.

`background-0.14.24.js`, as the cache-busting rule requires (worker unchanged).

## [0.14.23] - 2026-11-25

### Fixed — a page shell is not an article body

ACS `10.1021/acs.inorgchem.1c03019` was reported `ok` while the capture held only Abstract,
Supporting Information, Figures and the purchase/rent offers — no Introduction, no Results. The
shape test asked for "an `<article>` element and six headings", and navigation headings satisfied
it, so the reader was told the article had been captured when the Markdown had no body in it.

The test now also requires **three of the article's own section names** in the prose
(`introduction`, `experimental section`, `results`/`discussion`, `conclusion`, `methods`), which a
landing page does not print. Re-judging the saved captures: the Wiley full text stays `ok`, the ACS
shell becomes `no_html` / `abstract_only` — the honest answer, and the one that tells the reader to
sign in rather than to read an empty Markdown.

`_still_rendering` also stops treating a soft marker (`institutional access`) as "the page is
closed": it now looks at `blocking_hits`, so a page that is still painting gets its second look.

`background-0.14.23.js`, as the cache-busting rule requires (worker unchanged).

## [0.14.22] - 2026-11-25

### Fixed — a URL that *looks* like a challenge no longer stops the read

`10.1021/acs.inorgchem.1c03019` was reported `blocked` while the reader saw no captcha at all. The
audit shows why: `signal: verify_redirect`, produced by matching `captcha` inside the URL. ACS hops
through such a URL and lands on the article, so the plan was dropped for a wall that did not exist —
and a 30-minute wall marker made the next attempts answer from that memory instead of navigating.

Stopping now requires evidence the reader can also see: a gate title (`just a moment`, `请稍候`,
`验证中心`, …) or `captcha_visible` from the content script. A verification-looking URL on its own
is ignored; if the page really is a wall, the capture's own body markers (`Body.ray id`, challenge
text) still report `blocked` a step later, and that verdict *is* based on the page.

`VERIFY_URL_MARKERS` stays in the module, retired, with the reason next to it.

`background-0.14.22.js`, as the cache-busting rule requires (worker unchanged).

## [0.14.21] - 2026-11-25

### Fixed — a full Wiley article was reported as a paywall

Reported by a reader: `10.1002/anie.202005087` opened fine in the browser, but the tool kept saying
it could not capture the text. The capture was **not** empty — 4.1 MB holding Abstract / Introduction
/ Results and Discussion / Conclusion, `article_tags: 2`, `body_headings: 41` — but one
"institutional access" string in the sidebar made the classifier answer `no_html` / `paywall`.

The paywall markers are now split by what they mean:

* **blocking** — `purchase pdf`, `sign in to view`, `buy article`, `rent this article`: the body is
  behind a wall, so they decide even when the page looks like an article (a `<section>` wrapper
  around an abstract is still an abstract);
* **soft** — `get access`, `access through your organization`, `institutional access`: printed for
  readers who are already entitled, so they only count when the page does not have an article body.

Re-judging the real capture after the change answers `ok`. `tests/unit/test_page_probe_paywall_order.py`
pins both directions, and the pre-existing "abstract page that wraps sections" case still reports
`paywall`.

`background-0.14.21.js`, as the cache-busting rule requires (worker unchanged).

## [0.14.20] - 2026-11-25

### Fixed — the second window was `--load-extension`, not Edge restoring a session

Every `wensu browser start` passed `--load-extension`, and Edge answers that by opening its
extensions/settings window beside the startup window — two windows on every cold start. The flag was
being passed because the check for "is this extension already known" looked in `Preferences`, while
Edge records extensions in **`Secure Preferences`**. The profile has carried the extension all along
(`extensions.settings.gmaimbocfj… → …\scholar-search\browser\extension`, verified), so the flag was
pure overhead.

`start` now reads both files (and accepts the saved `extension_id` as a match) and passes
`--load-extension` **only** when the profile does not know the extension — i.e. the genuine first
run. Measured with the flag: two windows; without it: one.

`background-0.14.20.js`, as the cache-busting rule requires (worker unchanged).

## [0.14.19] - 2026-11-25

### Fixed — the restored window is closed, not just the empty one

0.14.17 closed the startup window when it held nothing but browser-internal pages. That is not the
case after a force-kill: `profile.exit_type` stays `Crashed`, so Edge restores the previous session
— the work window **plus** a second window carrying the tabs of earlier runs (measured 2026-11-25:
"新建标签页 和另外 2 个页面" beside the work tab). Writing `session.restore_on_startup` into the
profile does not help, because the browser rewrites `Preferences` on every exit; the value was gone
by the next start.

The cleanup therefore moved into the extension, which can see what a window contains: a window is
closed when **every** tab in it is blank or on a site this tool may navigate (the search sites and
the publisher list). A window holding anything else — the reader's own pages — is left alone.

`background-0.14.19.js`, as the cache-busting rule requires.

## [0.14.18] - 2026-11-25

### Refactor — the page navigation lives in one small module

`page_read` decides how it reaches an article in exactly one place now: `core/page_nav.py`, whose
`article_navigation(service, target, publisher)` returns the actions for that read. It is a pure
move — the build still opens the article address directly, once, and the reply is unchanged.

`tests/unit/test_page_nav_contract.py` pins the signature and the "exactly one navigation" rule, so
a future refactor cannot quietly change how many requests a read makes.

### Docs

* `packages/dsh-wensu/README.md` listed **seven** tools; the server exposes **eight** (`page2md`
  was missing). Fixed, with the one-line description the tool already carries.
* ADR 0019 and the README no longer explain a step this build does not perform; the changelog
  entries for 0.13.7 were reworded to say what changed without describing the dropped technique.

`background-0.14.18.js`, as the cache-busting rule requires.

## [0.14.17] - 2026-11-25

### Fixed — one browser window instead of two

`wensu browser start` left **two** windows: Edge's own startup window plus the one the extension
creates for the work tab. The extension now closes the startup window after moving the work tab out,
and only when that window holds nothing but browser-internal pages (`about:blank`,
`edge://newtab`, `edge://welcome`) — a window with the reader's own tabs is never touched.

Verified live after a cold start: a single minimized window remains, and `wensu doctor` reports all
three components on the same version.

`background-0.14.17.js`, as the cache-busting rule requires.

## [0.14.15] - 2026-11-25

### Changed — formulas: wait for MathJax, stop truncating, and say what is actually missing

Asked whether a mature HTML→Markdown project could do this better, the honest answer came from six
saved captures: **none of them contains MathML** (`<math>` = 0, `mjx-assistive-mml` = 0) and the
160-character truncation never fired (`math_truncated` = 0 everywhere). No converter — pandoc,
`markdownify`, `html-to-markdown`, MarkItDown — can recover LaTeX the DOM never had.

What changed:

* `content/readiness.js` now also waits for MathJax to finish typesetting (no empty `mjx-lazy`
  shells, no `mjx-container` without children) before the capture walks the page. Measured on the
  MDPI sample: empty shells **313 → 51**, and the formulas that do render are at least true to what
  the reader saw.
* `MATH_MAX_CHARS` 160 → 4 000: the cap is a safety limit, not a fidelity policy, and a long sum is
  not improved by losing its tail.
* The warning now says what is true — the page provides no MathML, so the Markdown has no LaTeX —
  instead of advising the reader to "make the page render original MathML", which is not something
  they can do.

Still open, deliberately: sites that typeset formulas as SVG only (MDPI, Cambridge) need OCR to get
LaTeX back. `texify`/`pix2tex` would work locally but pull a model of a few hundred MB, so it stays
an opt-in experiment rather than a default; cloud APIs (Mathpix, Jina) remain rejected — they would
send the article to a third party.

`background-0.14.15.js`, as the cache-busting rule requires.

## [0.14.14] - 2026-11-25

### Fixed — figures are saved, and the page is asked when it is ready

The previous two releases proved the pieces and delivered nothing: a cold cache captured a skeleton
(`status: no_html`) and the figures that *were* found never reached disk. Both had the same shape —
the tool was guessing instead of asking the browser — and both are fixed here.

* **Publisher pages now carry a content script** (`content/readiness.js`, 25 publisher domains from
  ADR 0019). It answers "is the article body actually here" using the browser's own view
  (`article`/`section[id]` present and ≥1500 characters of text, waiting up to 12 s), then scrolls the
  page once in viewport steps so `loading="lazy"` figures are downloaded. A `goto` with `assets`
  waits for that walk (20 s budget); a host without the script answers immediately and the old
  stopwatch still applies.
* **Figure bytes travel with the capture reply.** Reading them back by index failed three live runs
  in a row with `snapshot.expired`, while the bytes were already in hand — so up to 1.2 MB of figure
  data now rides along (the frame holds 2 MB and the page's own first chunk takes ~256 KB). Whatever
  does not fit is still readable by index, and a failure is named in `figures.skipped`.
* **`page2md` matches figures by filename stem.** The page's `<img src>` names `…-g001-550.jpg` while
  the browser downloaded `…-g001-550.webp`; matching whole URLs relinked nothing on the first live
  run.

Live, cold cache, one MDPI article (`10.3390/s26041303`) in **10.8 s**: `saved: 9` figures,
146,831 bytes, including the four article figures `g001`–`g004`; `skipped: 1` (a consent beacon);
`page.md` now points at `assets/08.webp` instead of the publisher's CDN.

`background-0.14.14.js`, as the cache-busting rule requires.

## [0.14.13] - 2026-11-25

### Fixed — the figures a live run found in the browser now land on disk

`page_read(figures=true)` did read real bytes out of the browser (`Network.getResponseBody`
returned an SVG starting with `<svg data-name="Layer 1"`), but four things kept them from becoming
files. Each was found by looking at a real MDPI article:

* **captured too early.** At the 1.2 s settle the page had only header logos; the same page six
  seconds in had its four article figures (`sensors-26-01303-g001…g004.webp`) in the network. Two
  extra waits of 2.4 s (a single `sleep` may not exceed 3 s) are now taken when figures are asked
  for — the measured trigger was the reader's own "refresh and wait".
* **tracking beacons ate the budget.** Twelve `uct.service.usercentrics.eu` beacons filled the
  12-image cap before any figure was seen. Known analytics/consent hosts are dropped, and images
  under 4 KB are kept only if there is room.
* **cached responses report `contentLength: 0`**, so the size cap was never enforced. The cap is
  now applied to the decoded bytes.
* **the "article is already open" shortcut skipped the navigation**, and the debugger had never
  been attached — so no bodies could exist. With `figures` the page is always navigated again.

`figures` is now always present in the reply (`{saved, skipped, bytes, files}`), and
`tests/unit/test_page_read_figures.py` pins the kernel half with a scripted adapter.

`background-0.14.13.js`, as the cache-busting rule requires.

## [0.14.12] - 2026-11-25

### Added — `page_read(figures=true)` saves the article's images

The capture never carried them: measured on two real pages, 36 `<img>` tags produced **zero** image
parts (every `cid:` was a stylesheet), because `pageCapture` skips cross-origin CDN images. The
Markdown kept the publisher's URLs, so reading offline had text and no figures.

Since no extension API hands back a response body, and every alternative either re-requests the
image or is blocked (canvas tainting, `webRequest`, disk cache, MITM — all rejected in ADR 0026),
the images are read out of what the browser **already downloaded**, through the same protocol the
DevTools Network panel uses:

* the debugger attaches **before** the navigation (`goto` carries `assets`), because
  `Network.getResponseBody` only knows requests made while attached;
* only image responses are kept; 12 figures / 1.2 MB each / 8 MB total, and anything skipped is
  named in `figures.skipped` with a reason;
* the reply carries a manifest and no bytes — each figure is read back in chunks over the existing
  `snapshot` token path, because a frame is capped at 2 MB;
* the debugger detaches in a `finally`, so the browser's notice does not outlive the capture;
* `page2md` adopts `<page_dir>/assets/`, copies it beside the Markdown and rewrites the links, so
  the output directory stays self-contained.

Off by default: without `figures` the debugger is never touched. `manifest.json` gains the
`debugger` permission, which is the largest permission change this project has made — the site sees
**no new request** (the notice is only local to the browser).

`background-0.14.12.js`, as the cache-busting rule requires.

## [0.14.11] - 2026-11-25

### Fixed — every search paid 8.5 s for host endpoints that no longer existed

Chasing the ~9 s that a walled search spent *outside* its audited actions (the audit showed a
single 3.5 s `goto`) turned up a leak with a fixed price per search. The native host writes
`host/hosts/bridge-<pid>.json` and never removes it, so the directory had accumulated **fourteen**
files whose processes were long gone. `BridgeAdapter.pin()` pings every candidate before choosing
one, and on this machine each dead endpoint took ~605 ms to fail: **8,515 / 8,527 / 8,520 ms**,
measured three times with the browser lock free and no network action involved.

A candidate whose recorded pid is not running can never answer, so it is dropped and deleted
before the pings (`core/process.py` now owns the liveness probe; the doctor uses the same one).
Files written in the last minute are kept, so a host that is still starting cannot lose its
endpoint to a race. Measured after the fix: entering a browser transaction **630 ms → 615 ms** for
a pid that had been recycled by a browser, and a walled WoS search went from **11,746 / 12,192 /
13,618 ms to 3,307 ms**.

`background-0.14.11.js`, as the cache-busting rule requires.

## [0.14.10] - 2026-11-25

### Fixed — a login wall is reported when it lands, not when the wait runs out

Found by pointing the browser at a real WoS wall (Clarivate login, `access.clarivate.com`) and
timing it: the kernel took **11.7 s** to answer `RiskBlocked: login_redirect`, while the page had
said so in the first second. `waitNavigated` only considered a navigation done when its URL became
*allowed*, and a wall is by definition outside the allowlist, so the wait ran out its whole 10 s
budget. A completed document now ends the wait wherever it landed; the caller hears
`policy.domain` in about a second and the kernel classifies the redirect.

The same run found the second half of it:

- **`navigation.stalled` fired on a redirect back.** `/verify/home` is redirected to `/wos/` by the
  site, and the tab ends on the URL it started from — reported as "nothing navigated". A stall now
  means only what it says: the tab is still not on an http(s) page after a retry.

`background-0.14.10.js`, as the cache-busting rule requires.

## [0.14.9] - 2026-11-25

### Fixed — the window the browser opens *after* the sweep is minimized too

0.14.8's boot sweep minimized what existed at the moment the extension connected. The browser
brings up its own first window a moment later, and that one stayed on screen — measured live, one
window minimized and one still titled `about:blank` in front of the user. Windows created during
the first 90 s of a session are now minimized as they appear; a window opened later behaves like
any other, and one the user restores by hand is never fought over (restoring is not creation).

`background-0.14.9.js`, as the cache-busting rule requires.

## [0.14.8] - 2026-11-25

### Changed — the browser runs minimized, out of the user's way

`wensu browser start` used to leave two windows on screen: the browser's own and the isolated work
window (ADR 0018). The profile's windows are now minimized once per browser session, and the work
window stays minimized when it is created or reused. The one exception is a human-verification
gate: the window comes back to `normal` (still unfocused) because somebody has to look at it. A
window the user restores by hand stays restored — the sweep is marked in `storage.session`, so it
runs once per browser session, not on every service-worker restart.

This is measured, not assumed. With the work window hidden for **5m40s**, an in-page `sleep(150)`
answered in **155 ms** median — the same as unfocused (156 ms) and as a short minimize (153 ms) —
so Chromium's hidden-page throttling does not reach this tab and the 150 ms pacing of ADR 0023 is
untouched. ADR 0018 修订 1 records the decision.

### Changed — the service worker's file name carries the version

`background-0.14.8.js`, as `tests/unit/test_service_worker_cache_busting.py` requires.

## [0.14.7] - 2026-11-25

### Fixed — the first navigation after a browser start no longer fails

Three separate things made `goto` answer `policy.domain` for a tab that had simply not navigated
yet. All three are fixed, and the service worker's file name now carries the version.

1. **The wait was abandoned** (0.14.5's regression). `gateWatch` returns an already-resolved
   promise when it has no gate markers, and racing the real navigation wait against it completed
   instantly — both `waitNavigated` and `waitComplete` were dropped and the tab was read back
   before the document arrived. It now returns `promise: null` and the goto awaits the real wait.
2. **A rejected update was final.** Edge answers `tabs.update` on a work tab a previous session
   left behind with "Navigation rejected."; the action now retries once. The retry is the update's,
   not the wait's: a page that did not load is the site's business, an update Edge refused on our
   own tab is ours.
3. **An accepted-but-ignored update was misread.** If the tab is still not on an http(s) page
   after the navigation, nothing was navigated — the extension now opens a tab of its own instead
   of insisting (and reports `navigation.stalled` with a `diagnostics` trail if even that fails).
   `navigation.stalled` deliberately does not fire when the tab is *already* on the requested
   document: navigating to the page you are on leaves the URL unchanged and is entirely normal.

### Changed — the service worker's file name carries the version

Edge keeps serving the cached copy of a service worker whose file name did not change. On
2026-11-25 that meant five fixes in a row were tested against a script nobody was executing, with
the repository and the assets directory both holding the new code. The worker is now
`background-<version>.js` and `tests/unit/test_service_worker_cache_busting.py` fails when the
name and the version disagree — a version bump without a rename is exactly that.

## [0.14.6] - 2026-11-25

### Fixed — a `goto` no longer skips its own navigation wait

0.14.5's gate watch raced the navigation wait against a "there is no gate to watch for" promise
that was **already resolved**. The gate watch is only armed by `page_read`, so every other
navigation — every search — won that race instantly, abandoned both waits (`waitNavigated`,
`waitComplete`) and read the tab back while the previous page was still on screen. When that page
was off the channel's domain (`about:blank` right after `wensu browser start`, or `doi.org` after a
failed `page_read`) the answer was `policy.domain` for a navigation that had merely not committed
yet: one unit spent and a retry needed. Seen on the 0.14.5 install check — the first search after a
browser start failed once, then worked.

`gateWatch` now returns `promise: null` when it has nothing to watch and the `goto` awaits the real
wait instead of racing it. The fake-browser probe pins both directions
(`tests/js/gate_watch_probe.js`, new `late_commit` case): a navigation whose document arrives 2.5 s
late used to answer `policy.domain` in **19 ms**, and now answers `ok` when the document lands;
a wall (never completes) still ends the wait at 1.5 s. Live: the first search after a browser
restart succeeds on the first attempt.

## [0.14.5] - 2026-11-25

### Fixed — a zero-hit search is no longer reported as a refused expression

The 2026-11-25 acceptance run (Chinese UI) sent two legal zero-hit expressions and got back
`query.rejected` quoting the advanced-search **help panel** (「布尔运算符 : AND, OR, NOT字段标识 :…」),
3 units each. Two causes: the diagnosis read the whole page, so the help panel below the alert
answered instead of the alert itself; and the zero-result wording list is English-only
(`EMPTY_MARKERS`), so a localized empty page matched nothing and fell through to the refusal
branch. A channel may now name its alert container (`alert_selector`); the diagnosis reads that
element alone, and **an alert that does not refuse the expression is the zero-hit answer** — no
wording list, so it works in any UI language. `query_error` also stopped counting words the search
form prints on its own.

### Changed — the result wait is taken in slices, so the site's own answer arrives first

A refusal or a zero-hit search used to be readable only *after* the result-list wait had spent
its whole budget — 10.8 s on the live site, because only then did the kernel look at the page.
The first attempt at this fix looked **once**, right after the click: the audit trail shows that
look passing in **2 ms** with nothing in the DOM yet (2026-11-25), and the answer still cost the
full wait.

The wait is now taken in 1.2 s slices, and between slices the page is asked what its alert says
(a `read_text`, free, no quota). Whichever of "results are up" and "the site answered" comes
first wins. Measured on the live site the same afternoon:

| case | before | after |
|---|---|---|
| zero-hit search | 19.4 s | **8.6 s** (`empty_reason: no_match`) |
| refused expression | 22.0 s | **9.2 s** (site's own sentence) |
| …of which is *waiting* | 10.8 s | **1.7 s** |

The remaining time is the search's own head (navigate, type, submit, 900 ms pacing), which a
failure cannot skip. A successful search is unchanged: it pays at most one extra slice before the
list is noticed, and a channel without an alert container keeps the single whole wait.

### Changed — a verification wall ends the wait about 10 s earlier

`page_read` on a walled publisher used to spend its whole navigation budget on a page that was
already final: a verification interstitial never fires the load event, so `waitComplete` polled for
**12.12 s** (measured 2026-11-25) while the document title had said 「请稍候…」 from the first
second, and nothing was captured at the end of it. The `goto` action now carries the kernel's own
gate markers (`halt_url_markers`, `halt_titles` — from `core/risk.py`, so the extension keeps no
second copy) and the extension runs a watcher beside both waits: once a marker has persisted for
1.5 s it stops waiting and reports what is on screen. The grace is what keeps a challenge that
solves *itself* cheap. A navigation without markers behaves exactly as before, and the kernel still
decides `blocked` with its stricter rule (ADR 0025). Measured in the fake-browser probe
(`tests/js/gate_watch_probe.js`): a wall answers in **1.5 s** instead of 12.1 s, a challenge that
clears itself at 0.6 s is **not** reported as a wall, and a navigation without markers is unchanged
at 15 ms.

### Fixed — a DOI that does not resolve is its own answer

`10.1016/j.snb.2026.000001` came back as `no_html` / `abstract_only` with "ask the user to sign
in", kept 267 KB of the publisher's error page, and charged 2. It is now `reason: doi_not_found`
(recognized from the page title and H1), the capture is discarded rather than saved, and 1 unit is
reported for the navigation that did run. Verified on the live site 2026-11-25: nine seconds,
`reason: doi_not_found`, `title: "Error: DOI Not Found"`, `quota_charged: 1`, `mhtml_path: null`,
and the hint names the identifier instead of a sign-in.

### Fixed — the wall advice matches what the code does

`blocked` answers said "do NOT call `page_read` again — use `snapshot`", written before open-tab
reuse existed; following it walked away from the 0-quota path. The three places that carry the
hint (`_page_next`, the risk advice, the `page_read` docstring) now say: solve the wall in that
browser window, then call `page_read` again.

### Docs — the `scholar-search` skill caught up with the tools

It said "seven tools" (no `page2md`), quoted 20–22 s for a Web of Science round (measured 10–15 s)
and 15 s for CNKI (measured ~5 s), told agents to report `cooldown_until` after a wall (none is
written since ADR 0022 rev 1) and priced a zero-hit search at 8 units (it costs 3 — the export
chain never runs). Added a `page_read` → `page2md` section, and `scholar-install` no longer tells
an agent to `wensu reset` a cool-down that was never recorded.

### Added — a per-debit quota ledger, so a total can be reconciled

`state/quota.json` keeps one number per day, which is enough to enforce the cap and not enough to
explain it: the 2026-11-25 acceptance ledger disagreed with the day's total by one unit and nothing
on disk named the call that made the difference (the audit trail records actions, and several
actions belong to one call). Every debit now leaves one line in
`state/quota-ledger-<day>.jsonl` — timestamp, channel, verb, amount, and the counter afterwards.
No query, no URL, no page content, exactly as the privacy rules require of the audit log. One file
per day, so it is bounded by the daily cap instead of growing without a limit. The counter stays
the authority: if the ledger cannot be written the charge still happens.

### Fixed — a capture's directory name is unique again

`page_read` stores a capture at `<home>/pages/<slug>/page.mhtml`, and the slug was the document
title truncated at 80 characters — `…Proximity-Sensing-and` in the report (P9). A second paper in
the same series therefore wrote into the first one's folder and replaced it, after which `page2md`
produced Markdown of the wrong article for the first path. The name keeps its readable title prefix
(60 characters) and gains an 8-character hash of the URL, so the folder is still recognisable and
two articles can no longer share one. Captures already on disk are untouched: the page cache stores
the path it wrote.

## [0.14.4] - 2026-11-24

### Fixed — a refused search expression now says why

Web of Science answers a bad expression with an alert instead of a result list, so the tool
waited out its 15 s readiness budget and then reported "the result list never appeared".
Measured 2026-11-24 with `TS=(ionic OR electroactive) AND actuator`: the site had already said
「检索错误: 布尔运算符的使用无效。请检查您的检索式…」 and nothing read it. The failure path now takes
one free look at the page (`read_text`, not a network action) and, when the alert is a refusal
rather than a zero-result message, raises `ChannelError` quoting the site's own sentence
(`query.rejected`). Zero-result pages keep their own wording, and a capture timeout keeps the
diagnostics it already had.

### Changed — waiting for a download got its own budget

A click that waits for a file may now wait 55 s instead of 15 s. It is a ceiling, not a pause:
the wait ends when the file lands. Every other action keeps the 15 s limit, and the record-range
cap stays at **500** — two 500-record exports are faster than one 1000-record file and much less
likely to fail on the download (ADR 0024).

### Added — after a wall, `page_read` reads the tab the reader is on

A wall is now remembered for 30 minutes as a marker (no file, no capture). The next attempt for
the same URL looks at the person's own tab first: if it already holds the article — they solved
the challenge by hand — that capture is reused with `quota_charged: 0` and **no navigation**; if
it is still the wall, the answer is `blocked` without touching the browser. A capture that turns
out to be some other page is deleted rather than left behind. `snapshot` also stopped raising
`policy.url_scheme` for a browser-internal tab: it answers `status: "no_page"` with a sentence a
person can act on. `wensu doctor` reports `bridge_host` (endpoint, pid, alive) — reloading the
extension restarts the native host on a new port, and "no native host is serving the profile"
never said so.

### Fixed — MathJax pages were reported as failing formulas

`page2md` counted the empty MathML that MathJax keeps in `mjx-assistive-mml` for screen readers
as real formulas, so a Wiley article said "6 formulas failed" while the Markdown could never
contain a marker for any of them — nothing was there to convert (each node is
`<math data-semantic-type="empty"/>`, and the drawn formula lives in `mjx-container` as an SVG).
Those nodes are removed before counting, `mjx-container` is counted as `mathjax_graphics`, and
the warning names the drawings ("look at the PDF") instead of a conversion failure.

### Changed — `page2md` is type-checked like the rest of the package

Its 25 pre-existing warnings are fixed (annotations on the lxml helpers, `Any` for the
duck-typed meta dict, casts where a dict value is really an int), and the `ignore_errors`
exemption in `pyproject.toml` is gone. Only third-party modules without stubs or without being
installed (`lxml`, `trafilatura`, `markitdown`) keep `ignore_missing_imports`.

### Changed — WoS round trip: interval 1200 → 900 ms, shorter settles, smaller dwell

Measured live (3 records, 7 charged actions): a round takes **44.8 s**, down from 48.2 s, and the
first estimate ("20–22 s") was simply wrong — the time is mostly the site's own work: ~8.8 s for
the SPA to render results after submit, ~4.4 s for the export download, ~1.1 s per export-dialog
step. What *is* ours: 7 × 900 ms spacing (6.3 s) and 5.1 s of `settle` pauses. Both are trimmed
here (interval 1200 → 900, export settles 1200–1800 → 600–900 and the rest by ~30%), and the
extension's post-navigation dwell drops from 500–1500 ms to 250–450 ms — that last one only takes
effect after the extension is reloaded. ADR 0021 records the measurement and the honest floor:
~30 s of a round is the site's own rendering and download.

### Changed — a verification wall stops the plan but no longer cools the tool down (ADR 0022)

ADR 0004 cooled everything for 24 h on any risk signal. With page reading (ADR 0019) that turned
one expected event — a site asking a human to click once — into a day of downtime for the whole
tool, and it closed the very recovery path it left open: `snapshot` also consulted the guard, so
"solve it, then snapshot" was refused. **Revised the same day (revision 1): the channel is
irrelevant.** CNKI's `/verify/home` slider and Web of Science's Cloudflare interstitial are the
same event as a publisher's wall, and restricting the exemption to `page:*` meant a solved slider
still locked the tool. Now the signal decides: `captcha`, `verify_redirect` and `login_redirect`
stop the plan, write an audit entry with `cooldown_until: null` and return `blocked` with advice
for the person in front of the browser; `http_403`, `rate_limited` and `text_marker` still cool
down 24 h, because those do mean "stop coming back".

### Fixed — the risk rules now name Cloudflare's interstitial

The root cause of the wall being captured was here, not in `page_read`: `RISK_TITLE_MARKERS`
held 安全验证 / 验证中心 / sign in / access denied, but not 「请稍候」 or `Just a moment`, so
`inspect()` saw nothing wrong in the `goto` outcome and the plan continued to sleep and
snapshot. With those titles listed, the wall trips inside the navigation action: the planner
stops before the next action and `page_read` answers `blocked` (with `signal`) without ever
capturing anything.

### Fixed — `snapshot` refuses to save a wall, and nothing may close the recovery path

`snapshot` wrote the file *before* checking, so a challenge page was persisted as if it were
an article. The check now runs first: on a wall it answers `blocked`, reports
`discarded_bytes`, and writes nothing. It also no longer asks the risk guard for permission
first — it issues no request to any site (ADR 0018). Both tools turn a `RiskBlocked` into a
payload instead of an MCP error.

### Added — the "no bulk text in answers" budget is a test

`docs/architecture.md` invariants 7–9 state the flow (capture only after the page is known to
be an article, fidelity decided by code, never by a model) and the excerpt rule if one is ever
added. `tests/unit/test_response_budget.py` enforces the cheap half: every tool answer is
≤4 KB, every string ≤300 chars, and nothing carries page markup.

### Fixed — a challenge wall is recognized before anything touches it

`page_read` used to navigate, capture, and only then classify the bytes — so a Cloudflare wall
(title 「请稍候…」, ~73 KB) was saved as if it were a page, cost the full 2 quota units, and
replaced a body that had already been captured. The wall's title arrives with the `goto`
reply, so the navigation is now its own plan: on a wall the tool stops right there, **captures
nothing**, reports `quota_charged: 1`, and says to ask the user and then use `snapshot`. The
wall check is `challenge_in_title` in `core/pageprobe.py` (short, unambiguous list; a false
positive would call a readable article a wall), and the tool's own description now states that
a wall is never captured or saved.

### Changed — the network interval drops from 3000 ms to 1200 ms (ADR 0021)

A Web of Science search is 8 charged actions (`goto`, `type`, 6 × `click`; `wait_for`/`sleep`
are not charged), so the 3 s floor was **24 s of pure waiting** per round and the audited round
took ~40 s — the direct cause of "检索太慢". The floor was a guess from before any measurement;
a full day of live use produced no captcha/403/`blocked` signal, and the owner's stopwatch on
the site itself shows 0.9–1.6 s pacing is unremarkable. `HARD.min_interval_ms` is now `1200`
(jitter kept, concurrency 1, ≤3 pages, ≤300 actions/day unchanged), a round should land at
**~20–22 s**, and ADR 0021 records the alternatives, the risk, and the rollback threshold: any
`blocked`/`RISK_CAPTCHA`/403 within 7 days means reverting to 3000 ms and recording an incident.
`AGENTS.md`, `docs/acceptance.md`, `docs/wos-channel.md` and the `scholar-search` skill (which
now states the expected duration) are updated with it.

### Fixed — the CLI and MCP payloads both carry `returned` / `truncated`

The two new fields were added to `SearchPage` but not to `_page_payload`, so the surface that
builds every answer silently dropped them; both surfaces are built by that one function, which
is exactly why the omission was worth checking in both places.

### Fixed — `total == limit` no longer needs a second search to interpret

`total == limit` could not distinguish "the site matched exactly this many" from "cut at my
own limit"; one caller spent a second search — 8 quota points and a whole cycle — resolving
that doubt (2026-11-24 report, D4). Measured live, `total` *is* the site's count (`limit: 3`
returned 3 of `total: 50`), so every answer now carries `returned` and `truncated`, where
`truncated` compares the **fetched** count against `total` — a later year/impact filter that
drops records cannot make a complete fetch look truncated. A `records_from`/`records_to` range
reports `truncated: false`: its size is part of its contract.

### Not a bug — the quota charge matches the metered file

The report's D5 (`quota_charged: 8` while `remaining` dropped 9) does not reproduce. One
controlled Web of Science search: response `quota_charged: 8`, `quota_remaining: 233`, quota
counter `used` 59 → 67 = **+8**, and the audit shows 8 charged verbs (`wait_for`/`sleep` are
not charged). The tool measures the delta itself (`before - after` around the call), so the
9 was a reading taken at a different moment, not an accounting error.

### Fixed — `page_read` no longer navigates the same article twice

Re-navigating is what replaced a good capture with a challenge page (2026-11-24 report,
D1/D2), and it charged two quota points for a page already on disk. A successful capture is
now remembered for an hour (`<home>/state/page-read.json`); asking again for the same URL
answers from it with `cached: true` and `quota_charged: 0`, and a capture whose file has
disappeared is not reused. The `blocked` hint also stopped advising the one action that makes
it worse: it names `snapshot` + `page2md` and says, in as many words, not to call
`page_read` again.

### Added — `page2md` is a tool, not a command line

The last link of "read the paper" was a CLI call, so a session whose shell could not be
provisioned lost the chain *after* the page had been captured — and, since the shell needs a
workspace grant, it looked like the plugin demanding full access (2026-11-24 report, D3 + D7).
`page2md(mhtml_path, out_dir)` now runs the converter inside the server: **0 quota**, no
shell, no permission to provision. It answers `page_md`, `index_json`, `engine`,
`math_engine` and `warnings`; `page_read`'s `next` names it instead of a command. The
`paper-page` skill gained the same rule plus the order that actually works when a publisher
challenges the browser: **never re-call `page_read`** — let the human solve it, then
`snapshot`, then `page2md` (D1/D2).

### Changed — a formula can no longer inflate the Markdown

`page2md`'s builtin MathML path fell back to the flattened text of the whole tree, so a
matrix or an aligned system arrived as hundreds of characters of symbol soup: unreadable,
and paid for by every consumer of the Markdown. A formula that does not convert is now a
one-token `[math]` marker, and a converted one is cut at `MATH_MAX_CHARS` (160) with its own
warning. The wording no longer promises a marker where the extractor actually dropped the
node — measured on the Wiley sample: 6 counted failures, 0 markers in `page.md`.

### Added — setup and doctor say when pandoc is missing

pandoc sharpens formula conversion; without it the builtin converter runs, so it is a
quality knob rather than a dependency. `wensu setup` and `wensu doctor` now name the install
command (`winget install JohnMacFarlane.Pandoc`) instead of leaving the degradation to be
discovered in `meta.json`. Nothing is downloaded automatically: pulling a third-party binary
is the user's decision, not a convenience.

### Added — `wensu doctor` answers "is the build that answers the build that was installed"

The three versions live in three places (this package, a DSH profile's `node_modules`, the
browser's asset copy), so the check that mattered on 2026-11-24 — CLI `0.13.2` behind a
`0.14.2` bundle and extension — could only be made by reading a profile manifest by hand.
`wensu doctor` prints the three versions plus bridge/quota state and a verdict
(`ok` / `partial` / `mismatch` / `unknown`), exits 1 on a mismatch, and never calls an
unknown artefact "ok". Pinned by `tests/unit/test_doctor.py`.

### Fixed — `ruff check .` was red for files no release touches

CI runs `ruff check .`, but `work/` (local probe scripts and past acceptance runs) and
`tools/proj` (pydev scaffolding copied in from the preset) are not shipped code and were
failing it on every push since the scaffolding landed. Both are excluded now, and the four
remaining findings in the repo's own `tools/bootstrap-project.py` are fixed properly
(`contextlib.suppress` instead of `try/except/pass`, a stale `noqa`, two wrapped lines).
Shipped code is still linted in full.

### Fixed — `mypy src` failed on Linux on a Windows-only module

`core/browser.py` asks `msvcrt` whether something holds the profile's `LOCK` file. Typeshed
hides `locking`/`LK_*` when the checker does not run on Windows, so CI's Linux job reported
four `attr-defined` errors while the local Windows run was clean — and a `type: ignore`
would have been the mirror image (`warn_unused_ignores` fails the Windows run). The module
is now viewed through `cast(Any, ...)`, which checks identically on both platforms;
verified with `mypy --platform linux src` and the normal run.

## [0.14.3] - 2026-11-24

### Changed — the bundle's own metadata described a smaller tool than it is

`packages/dsh-wensu/package.json` still said "read-only … bibliographic search", and its
README called itself seven tools while listing five and ending with "不下载全文，只出题录" —
a sentence that stopped being true when `page_read` + `page2md` landed. Both now name the
full-text path (`page_read` in the signed-in browser, `wensu page2md` for the Markdown) and
list all seven tool ids. npm metadata is immutable per version, so this text ships with the
next `pnpm publish`, not with the current 0.14.2 listing.

### Fixed — `status(brief)` hid the one field that answers "which build is this"

`brief` is the cheap payload a planning caller reads; it returned this package's version and
said nothing about the copy the browser actually loads. On 2026-11-24 a machine answered
`version: 0.13.2` while the market bundle and the extension were both 0.14.2: the guard
(`extension_version_mismatch`) existed, but only in the ~500-token full payload, so the skew
went unnoticed for a whole session. Both extension fields now ride along in `brief`, read
once and shared with `browser_profile`. Pinned by a case in
`tests/unit/test_extension_version_reported.py`.

### Fixed — `page_read` pointed wheel users at a file they never received

The hint said "run `tools/page2md.py`", a path that exists only in a source checkout: the
wheel ships `src/scholar_search` and `tools/` is not in the sdist either, so every
`pip install wensu` user was told to run something they did not have (2026-11-24).

The converter moved to `src/scholar_search/page2md.py` and ships with the package;
`wensu page2md --in <mhtml> --out <dir>` is the command, `tools/page2md.py` stays as a thin
shim for the docs that still call it, and the hint now names the command. `mypy` keeps its
25 pre-existing warnings via a `scholar_search.page2md` override — fixing them is its own
change, and relocating a file must not turn the `types` gate red. Pinned by
`tests/unit/test_page2md_cli.py` (CLI wiring, a real MHTML → `page.md`, and the hint text).

### Fixed — the browser accumulated one work tab per extension reload

`workTab()` remembered its tab in `storage.session`, which is emptied when the extension
reloads, while the tab it named survives: every reload opened one more `about:blank` and
nothing ever closed the old one. 2026-11-24, reported as the browser slowing down; visible
in the tab strip rather than in the audit log, because opening a tab is not an action.

The id now lives in `storage.local`; every tab this extension created is listed in
`wensuOwnedTabs`; a forgotten id is adopted with the spares closed, so the count can only go
down. The work tab also moved into a window of its own (`wensuWorkWindowId`, `focused: false`)
and is pinned, so it no longer takes a slot in the user's tab strip. Pinned by
`tests/js/tab_lifecycle_probe.js` and 11 cases in `tests/unit/test_extension_tab_lifecycle.py`.

## [0.14.2] - 2026-11-22

### Fixed — the CNKI record range lost records, then overshot, then failed on small sets

Three defects, all found by running the range against the live site:

* **short reads.** The grid fills in chunks, so one read caught a page with 20 of its
  50 rows: 150 asked, 120 returned. Each page is now read twice (a `read_html` is a read
  verb, so the second one is free) and the merge deduplicates;
* **overshoot.** With two reads a page can hand back more rows than its own span — a
  150-record range returned 170. The response is now trimmed to the requested span in
  `_present`, so the contract holds whichever channel answered;
* **a range wider than the result set errored out.** Nine hits and a 150-record range
  meant a `click.page-turn` that found no next page, and the whole call failed even
  though the first page was already on screen. A failed page turn now means "that was
  the last page": the page on screen is read and returned (9 records for that query).

A CNKI range must also start at record 1 — the channel turns pages, it does not jump to
page 11 — so `records_from=51` is refused with a message that says which range works.


## [0.14.1] - 2026-11-22

### Added — the same record range on CNKI (three pages, 150 records)

CNKI has no export dialog with a record range: `#batchOpsBox` holds format links only and
`#selectCheckAll1` checks just the page on screen. The same parameters therefore read by
**turning pages**: `records_from=1, records_to=150` reads three pages in one call and
merges them, deduplicating by `url`. The cap is 150 rather than 500 because the
interaction rules allow at most three pages per call, at fifty rows a page.

Each turn waits 3 s + 1.5 s: a 2.5 s settle read the *previous* grid (measured), and one
`sleep` may not exceed 3 s. Real run 2026-11-22: 150 records, 44.7 s, 150 distinct
URLs, `total: 6304`.


## [0.14.0] - 2026-11-22

### Added — read a record range from one export (up to 500 a call)

`search` takes `records_from` / `records_to` (Web of Science):
`records_from=1, records_to=500` reads the first five hundred hits out of one BibTeX
export instead of ten fifty-record pages, and `records_from=501` reads the next batch.
Before this, going deeper meant `exclude_ut` — re-running the whole search with the
identifiers already in hand — so a thousand records cost twenty searches with their
navigations. One export is the lighter path for the site as well as for the caller.

The dialog's range control was observed live before being used (radio `#radio3-input`,
then `input[name=markFrom]` / `name=markTo`, which stay disabled until the radio is
picked); ADR 0020 records the decision and the rejected alternatives. Three limits are
deliberate:

* one export carries at most **500** records here. The site allows 1000, but a bigger
  file does not arrive inside the 15 s one action may wait for its download (measured:
  500 arrived, 1000 produced no file at all);
* `records_from/records_to` are mutually exclusive with `page`, and a span over the cap
  is refused with a message that says what to do instead;
* `total` is `null` for a range read. An export says how many records it carries, not
  how many the query matched — reporting the file size as `total` would have said
  "1000 hits" for a query with tens of thousands.

`exclude_ut` keeps working but its documented purpose narrows to hiding records
already at hand; the skill, README and tool description say so. Channels that read the
result page (CNKI) refuse a range instead of quietly returning fifty records.


## [0.13.8] - 2026-11-22

### Changed — the reader opens the article directly, and the docs say so

Three places still described the step that 0.13.7 dropped: the MCP tool description in
`server.py`, ADR 0019 decision 3, and the README's tool table. They now describe what the build
does — open the article address, stop at a challenge — so read and behaviour say the same thing.


## [0.13.7] - 2026-11-22

### Removed — a navigation step that did not belong in a public build

`page_read` now makes exactly one navigation per call: it opens the article address directly,
exactly as a reader who copied the URL would, and when the site challenges it answers `blocked` /
`challenge` so the human solves it in the browser (ADR 0004, ADR 0019). One step was dropped, and
with it one field in the publisher registry that only that step had used.

The `goto` parameters `open`, `close`, `wait` and `dwell_ms` stay: they are tab semantics, covered
by tests, and carry no site-specific logic.

## [0.13.6] - 2026-11-22

### Fixed — the 0.13.3 probe called a whole Nature article "abstract only"

The rule that stopped an abstract page being reported `ok` leaned on numbered headings or
six `<section id=…>` wrappers. Nature-style pages have neither: the article lives in an
`<article>` element and its headings are unnumbered ("Abstract", "Main", "Methods"), so
`page_read` answered `no_html` / `abstract_only` for `10.1038/s41586-020-2649-2` and took a
second look at a page that was already complete. The probe now also accepts "`<article>`
element plus at least six `<h2>`/`<h3>` headings"; the counts (`article_tags`,
`body_headings`) are part of the answer. The abstract-shell case is unaffected: it carries
no `<article>` element.

## [0.13.5] - 2026-11-22

### Changed — `goto` can return without waiting for the load event

`goto` takes `wait: "none"`: the navigation is issued and the command returns. A caller that
replaces the tab's contents immediately afterwards does not need the load event, and waiting for
it cost about 0.9 s per navigation. `goto` also accepts `dwell_ms: 0`, which is what a caller
wants when the load wait is the only thing worth waiting for.

## [0.13.4] - 2026-11-22

### Changed — the pause after a navigation is a fixed 0.6 s

`goto` with a dwell pauses 600 ms instead of the previous 500–1 500 ms jitter, so a caller can
say how long a tab stays on one page instead of inheriting a random one.



## [0.13.3] - 2026-11-22

Fixes from `wensu-风险与缺陷测试报告-2026-11-22.md` (D1–D5, E2, E4). The report's 13
`xfail(strict=True)` cases now pass with the markers removed.

### Fixed — a human-verification wall was read as "an abstract shell" (D1, safety)

Wiley answered a plain article URL with a Cloudflare interstitial; `page_read` classified it
`no_html` / `abstract_only`, which did two wrong things: it told the caller to "sign in to the
publisher" (a dead end — the site wanted a person, not a session) and it matched
`_still_rendering()`, so the service slept and took a **second snapshot of the wall**. ADR 0004
says stop at the first challenge, so the probe now names it before anything else:
`status="blocked"`, `reason="challenge"`, `signal="url:…"` or `"body:…"`. URL features
(`__cf_chl_rt_tk`, `/cdn-cgi/challenge-platform/`) are checked first because a redirect leaves
them in the address bar, then body markers (`Ray ID`, `challenge-platform`, `__cf_chl_opt`,
`请稍候`, …) — the run's `final_url` was clean, so a URL-only rule would have missed exactly
the case that exposed this. `_page_next()` now says: finish the challenge in the browser, then
call again — never "sign in", never a retry.

### Fixed — every date-sorted Web of Science search failed on the global site (D2)

`sort_actions()` ended with `capture_wait()`, which waits for `#wensu-wos-capture[data-ready]`.
That node is raised on the Clarivate mirror, where the kernel reads the NDJSON stream; the
global site streams the same data without `window.fetch`, so the marker never appears. Every
`site_sort=date|citation` search on `www.webofscience.com` died at step 7/19 at the cost of 5
quota. The export path now builds its sort actions with `capture=False`; the mirror keeps its
wait (it is the only readiness signal there).

### Fixed — the extension closed its own tab, adopted the user's, and pinged a third publisher (D3–D5)

* a tab opened for a single navigation (`open: "new"`) was **closed** on the next one, leaving
  no controlled tab for a search; it is now **blanked** (`about:blank`) and kept, and the
  following navigation lands in it (same id);
* `workTab()` adopted any in-scope tab — including a page the user was reading — and then
  navigated it. It now only ever drives the tab it recorded, and creates `about:blank` when
  there is none;
* creating that tab at `https://www.sciencedirect.com/` sent a request to Elsevier even when
  reading a Wiley DOI; it now starts blank and the next `goto` (domain-checked) takes it to the
  right publisher.

### Fixed — `page2md` required `trafilatura` (E2) and `blocked` hid its cost (E4)

`trafilatura` is an optional source: the section walk works without it and the documented
markitdown fallback could never run. It is now imported in a `try`, and the engine reports
`sections` with `trafilatura_missing: true`. A `blocked` answer now carries `quota_charged`
like every other answer (the two navigations are what the quota paid for).

## [0.13.2] - 2026-11-22

### Fixed — the extension asked for `chrome.storage` without the permission

`goto` remembers its working tab in `chrome.storage.session`. The manifest never declared
`storage`, so `chrome.storage` is `undefined` and every navigation failed with
`Cannot read properties of undefined (reading 'session')`. It stayed hidden because the copy
loaded in the browser was an older build (0.12.48) that kept the tab id in a variable; the
first time the refreshed copy was loaded, `page_read` broke on step 1.

The permission is now declared. A probe that runs one plain `goto` and one
`goto open:"new"` against the live bridge is in `work/scratch/probe-goto.py`.

Also learned the hard way: `wensu assets --target <live dir> --force` replaces the whole asset
tree and **deletes the generated files** next to it (`com.scholar.search.json`, `scholar-host.exe`,
`python-path.txt`), which breaks the native host registration until `wensu setup` runs again.
Refresh assets first, then run `setup` — never the other way round.

## [0.13.1] - 2026-11-22

### Changed — `goto` can use a separate tab for one navigation

Two parameters of the existing `goto` verb (no new verb): `open: "new"` opens a separate tab
for a single navigation, `close: "disposable"` handles the ones this extension created on the
next navigation, and `dwell_ms` lets a caller shorten the pause after a navigation (the default
stays 500–1 500 ms, drawn at random). Only tab ids the extension itself recorded are ever
touched, and a failed cleanup is not a plan failure.

## [0.13.0] - 2026-11-22

Third feature release of the page reader, and the first one numbered as a minor version:
`page_read`, MHTML capture and the literature map are new capabilities, so the version that
carries them is 0.13.0 rather than another patch. The 0.12.58 / 0.12.59 numbers published
earlier today carried the same features as pre-release patches and stay in this file as
history.

What 0.13.0 adds on top of them, both found by driving the real browser after a fresh login:

### Fixed — the article body was captured before it rendered

Publisher bodies paint after the load event. `page_read` navigated and captured immediately,
so an accessible ScienceDirect article came back as 1.8 KB of "Highlights" and was reported
`no_html` / `abstract_only`. The plan now waits `1 200 ms` after reaching the article, and if
the capture still holds no numbered heading **and** no sign-in prompt — a page that is late,
not closed — it takes one bounded second look (`1 500 ms`, same page, same 2-action quota)
and keeps it only when that look finds the article. A page that does print a sign-in prompt is
never retried: that is the paywall case below.

### Fixed — `page_read` called an abstract page `ok`

See 0.12.59: the probe counted `<section id=…>` wrappers, which an abstract page also has.
It now counts the article's own numbered headings, and trusts an unnumbered page only when it
wraps six or more sections and carries no paywall marker.

## [0.12.59] - 2026-11-22

### Fixed — `page_read` called an abstract page `ok`

The probe decided from how many `<section id=…>` wrappers a page carried. A ScienceDirect
abstract page carries plenty of them (highlights, abstract, recommended articles), so a page
with no article body was reported `status: "ok"` — the real run after 0.12.58 returned `ok`
with `sections: 7` for `…/article/abs/pii/…`, and the Markdown that followed was 9 KB of
teasers. The page also prints a sign-in prompt, which the old rule only honoured below three
wrappers.

The honest signal is the article's own numbering: an abstract page has no `<h2>1. Introduction`
and no other numbered heading. `classify_mhtml` now reports `headings`, and a page without any
numbered heading that carries a paywall marker is `no_html` / `paywall`; without the marker and
without sections, `no_html` / `abstract_only`. `next` now says what actually fixes this:
**ask the user to sign in** (institutional access / campus network) in that browser window and
call `page_read` again — never retry by yourself (ADR 0004). The same guidance is in the
`paper-page` skill, next to the existing captcha section.

## [0.12.58] - 2026-11-22

### Added — read an online paper's page as Markdown (`paper-page`)

`tools/page2md.py` turns a saved publisher page into Markdown an agent can read: `##`/`###`
sections in document order, formulas as LaTeX (`$…$`, `$$…$$`), tables as GFM pipe tables,
figures inlined at their position with captions copied into `assets/`.

Extraction merges two passes because either alone loses content: section aggregation (walks
`section[@id]` and `*[class~="section-title"]`, descending into leaf `div`/`span` — a real
Elsevier article had 13 `<p>` elements and **zero** formulas inside them, with 114 formulas
sitting in `div`s) and trafilatura for the long prose. MathML goes through pandoc in one batch
call when pandoc is installed, falling back to a built-in MathML→LaTeX subset converter.

`meta.json.warnings` records where fidelity was lost (no MathML at all, built-in converter,
failed formulas, tables left inline, missing images) so the skill can tell the user to check
the PDF before quoting a number. The skill lives in `skills/paper-page/`; MHTML input from
`chrome.pageCapture` is the next milestone ([ADR 0018](docs/adr/0018-page-snapshot.md)).

### Added — `snapshot`: save the open tab as one MHTML file

The sixth tool and the tenth verb. `chrome.pageCapture.saveAsMHTML` writes the page the user
already has open — images and CSS included — through the browser's own download manager into
`wensu-pages/…mhtml`; the bridge only relays `{path, bytes, url, title}` because a saved
article is 1–5 MB and the bridge is line-delimited JSON with a 1 MB frame cap.

It issues no request, so it spends **no quota** and is exempt from the channel domain
whitelist — the one place that rule bends, and only for a tab that is already open
([ADR 0018](docs/adr/0018-page-snapshot.md)).

A verification wall is reported, not read: when the tab is showing a captcha the result carries
`status: "blocked"` / `code: "RISK_CAPTCHA"` / `retryable: false`, so the caller stops instead of
summarising the challenge page (ADR 0004; no cooldown, because nothing was automated).

### Added — `page_read`: the browser opens the publisher page itself

The seventh tool, and the one that answers "read this paper" without the user having to
open it first: give a DOI (preferred) or an article URL and the browser opens that address
and saves it as MHTML — 2 quota units, and nothing else is clicked or typed.

Answers with a status the caller can act on: `ok` (path to convert), `no_html` with
`reason` = paywall / abstract_only / pdf_only and a `pdf_url` when one exists,
`unsupported_site` for a DOI outside the curated list (25 publishers, not "any https"),
and `blocked` when the site challenges the browser. The list lives in
`core/publishers.py`; see [ADR 0019](docs/adr/0019-publisher-page-read.md).

### Fixed — `page.md` kept 37 % of the publisher's tail

`_cut_tail` only knew the literal headings (`Recommended articles`, `Cited by`). ScienceDirect
prints no such heading: it re-exports the introduction, every section title and every figure
caption again, then the declarations and a wall of other papers' abstracts. On the acceptance
article that tail was 21 401 of 58 470 characters, and it carried other papers' numbers into
`page.md`. The cut is now structural: blocks that start a piece of backmatter end the document
(declarations, acknowledgements, funding, data availability, CRediT, recommendation cards),
and so does a *replay* — a block that repeats earlier text while a second block in the next
four repeats too. A single repetition is left alone, because quoting an earlier paragraph is
normal prose. `page.md` went from 14 617 to 9 636 estimated tokens on that article.

### Changed — `index.json` is a map a reader can answer from

`numbers` used to be bare strings (`"15.5%"`). A reader that got the value could not tell what
it measured, and the acceptance run dropped the whole pool — four of ten questions were lost
that way. Each entry is now `{"value": …, "ctx": …}`, where `ctx` is the sentence the value
came from, copied verbatim; a value inside a table row takes its table's caption. Percentages
and unit-bearing quantities are kept before bare decimals, so a six-slot section no longer
spends its budget on geometry and loses its claim.

`key_sentences` keeps two sentences per section (four for core or value-dense sections), cut at
a word boundary with `…`, and a sentence that repeats a figure caption is dropped. Sentences
that state a *direction* (`gradient`, `uniform`, `tends to`, `shift`, `evolve`) now score, so
"the distribution tends to a radial gradient when α = 0" stops disappearing.

The bookkeeping fields (`index`, `chars`, `level`, `core`, `paragraphs`, `keywords`,
`core_hint`) are gone and the JSON is written with `indent=1`: the map now costs 4 302 tokens
against 9 636 for the article (44.6 %), and four rounds of blind acceptance (10 questions, a
full-text arm and a map-only arm, an independent judge) ended at **9/10 with no contradiction
and no fabricated number** (`work/tasks/paper-digest/verify/round7/RESULTS.md`).

Also fixed in the same pass: `_gist` split sentences on the decimal point ("…is 0.5" became
"…is 0."), and `numbers` missed `0.70`, `58.86°` and `1 × 10⁻³` because a unit was required.

### Known limitations

- A value inside a table keeps the table's caption, not its row and column labels: the map
  gives `17.94 mm`, not "high-porosity thickness".
- A key sentence cut with `…` loses whatever qualified it (`works well for the present SMMR
  model`, `1 × 10⁻³`).
- Formulas are still images when the page carries no MathML; anything formula-level needs the
  PDF. `meta.json` says so in `warnings`.

## [0.12.57] - 2026-11-18

### Fixed — the DSH bundle was refused by DSH 0.2.2-rc.3

DSH moved to `0.2.2-rc.3` and the bundle stayed pinned to `0.2.2-rc.2`. The install survived
it, the plugin still showed `enabled: true`, and the tools were simply absent:

```
error.code: incompatible-version
runtimeVersion: 0.2.2-rc.3   requirements.engines.dsh: 0.2.2-rc.2   rows: []
```

`@deepseek-ai/dsh-mcp-client` declares its ten core peers at **exact** versions, so a bundle
is usable on one DSH build only. The dependency and `engines.dsh` are now both `0.2.2-rc.3`.
This is not a one-off: **every DSH release needs a matching bundle release**, which is the
price of exact peers and the reason `engines.dsh` is exact too (a range would accept a core
the pinned client cannot run on — that is what made the 0.2.2-rc.2 breakage silent).

Users still on DSH `0.2.2-rc.2` should keep 0.12.56; 0.12.57 is refused there explicitly
rather than failing later.

### Fixed — the quoted price of an action was wrong for Web of Science

`status.action_cost` advertised 4 quota units for a Web of Science search; the plan bills
8 (the BibTeX export path adds six clicks). `ACTION_COST` is now a module constant that
`tests/unit/test_action_cost_matches_plans.py` derives from the plan itself, so a change to
a plan fails the suite instead of making the published price a lie. `site_sort` and
`page_turn` are quoted per channel (Web of Science has no page turn — it points at
`exclude_ut` instead).

A bare DOI costs more than the field said: on CNKI it runs a search first, 3 + 1 = 4,
where the same article by `url` costs 1 (and 0 the second time). Documented in the skill
and in the tool description.

### Fixed — `query_effective` showed the text the caller sent, not what ran

The Web of Science BibTeX path filled the field with `query.text`, and the service only
fills it when it is empty — so the appended `AND PY=(…)` never appeared, and a caller
checking whether the year bound landed saw a bare `TS=(…)`. The channel now leaves the
field empty and lets `effective_query()` describe the expression.

### Added — `status` reports which extension copy the browser loads

`browser_profile.extension_version` and `extension_version_mismatch` compare the copied
`manifest.json` with the package. Without them a copy three versions behind was invisible:
the package said 0.12.56 and nothing said 0.12.53.

### Changed — `wensu setup` refreshes copied assets instead of skipping them

`copy_assets` used to raise `FileExistsError` for any existing destination, and `setup`
swallowed it and returned 0 — so the upgrade path printed "done" while leaving the browser
on an old extension. A destination that matches the source is now skipped silently
(idempotent); one that differs is replaced, and the message says the extension needs a
reload. `--force` split into `--force-assets` and `--force-skills`: refreshing assets is
routine, replacing a skills directory deletes local edits.

### Added — an installed skill that differs from the bundled one is reported

`wensu setup --skills-dir` now prints `N differ from this build (…); pass --force-skills to
replace them` instead of saying nothing. Three copies of these skills exist on a working
machine, and eight of twelve disagreed while every command reported success.

### Fixed — `schemas/tools.json` is generated, and three gates enforce it

The file called itself the stable tool surface while missing `exclude_ut`, the two sort
aliases and `status.brief`; nothing read it, so nothing failed. It is now produced by
`scripts/dump-tools.py` from `list_tools()`, and `--check` runs in the test suite, in
`release-check.py` and in CI.

### Fixed — `filters` echoes `local_sort` rather than the legacy alias `sort_by`

The skill documented the new name; the response used the old one, so a caller who set
`local_sort` and looked for it in `filters` found nothing.

### Fixed — copied assets no longer carry machine-local host files

`native-host/python-path.txt`, `scholar-host.exe`, `com.scholar.search.json` and
`run-host.cmd` are written per machine by `install.ps1` and are ignored by the repository.
A checkout's copies were being copied into the runtime directory, shipping one machine's
paths to another.

### Docs

The upgrade flow is one flow again (`wensu setup`, no flag), `docs/integration/dsh.md`
lists five tools instead of four, and the `status` fields an integration needs are
documented there.

## [0.12.56] - 2026-11-11

### Fixed — `wensu reset --confirm` did nothing to a running service

The block message tells the user to clear the cooldown with `wensu reset --confirm`. Doing
that left the service locked anyway, for the full 24 hours, with no explanation:

```
CLI  after reset → cooldown_until: null      (file removed)
MCP  next call   → still blocked, same deadline
```

`RiskGuard` keeps the deadline in memory as a second lock, and `cooldown_until()` returned
the **later** of memory and disk. A one-shot CLI process cannot reach another process's
memory, so following the documented remedy appeared to do nothing.

That memory lock exists on purpose — deleting a file must not unblock a process that is
already running — so the fix is not to weaken it but to make the clear **visible**. `clear()`
now writes `{"cleared_at": …}` instead of deleting the file, and `cooldown_until()` drops
its memory value when that marker is newer than the moment the value was recorded. A clear
that happened *before* a later trip cannot undo it, and a state file from an older version
(no marker) behaves exactly as before.

Verified against the live MCP server: a planted cooldown disappeared from a running process
after `wensu reset --confirm`, with no restart.

## [0.12.55] - 2026-11-11

Fixes the DSH bundle against DSH 0.2.2-rc.2, where it had silently stopped working.

### Fixed — the MCP tools disappeared after a DSH update

Reported symptom: after updating DeepSeek Harness, no wensu tools were available. The
service itself was healthy — `wensu status` reported `bridge_ready: true`, and a direct MCP
handshake against `wensu serve --transport stdio` answered `wensu 0.12.53` with the `tools`
capability — but the Host's tool list contained nothing from wensu and the loader entry
`mcp-scholar-search` was `inactive`.

The cause was an **exact version pin**:

```
DSH core                         0.2.2-rc.2
bundle dependency                @deepseek-ai/dsh-mcp-client  0.2.2-rc.1   (exact)
that plugin's peers              10 core packages, each requiring exactly 0.2.2-rc.1
```

`@deepseek-ai/dsh-mcp-client` declares its peers at exact versions rather than ranges, so
the RC bump invalidated all ten. DSH rejects the whole row when a peer is unmet, and the
bundle's `engines.dsh` was `>=0.2.2-rc.1 <0.3.0` — loose enough to accept rc.2, which is
why nothing warned and the failure was invisible until someone looked for the tools.

### Changed — the dependency and `engines.dsh` now agree, exactly

Both are pinned to `0.2.2-rc.2`. The loose `engines` range was the actual defect: it
claimed compatibility the dependency did not have, so DSH's version gate could not do its
job. With an exact `engines`, a mismatched core is **refused with a message** instead of
being installed and going quietly inactive.

The consequence is stated in `packages/dsh-wensu/README.md`: **every DSH release needs a
matching bundle release**. That is what exact peers mean, not an oversight.

Verified after the change: the loader entry became `active` and the four
`mcp__wensu__*` tools appeared in the Host tool list.

## [0.12.54] - 2026-11-11

The global Web of Science site now yields records. It does so by asking the site for a
BibTeX export instead of trying to read a response that a content script cannot see, and
the impact factor comes from a local database built from the user's own JCR workbook.

### Added — reading the global site through its BibTeX export

On `www.webofscience.com` the result payload never passes through the page's
`fetch`/`XMLHttpRequest`; the requests the site makes are not visible to a content script,
so the capture path used by the mirror cannot work there. Rather than keep guessing at the
site's internals, the channel now drives the export the site already provides:

```
#export-trigger-btn → #exportToBibtexButton → record content → #exportButton → a .bib file
```

Each selector was observed on the live page, because each step only exists after the
previous one. The dialog opens on **作者、标题、来源出版物**, which carries neither DOI nor
abstract, so the plan switches to **完整记录** every time — without that the exported file is
unusable.

The entry key is the UT (`@article{ WOS:…`), so `url`, `detail`, `exclude_ut` and the export
formats work unchanged: both paths produce the same `Record`. Measured on a real 166 KB
export: 39 records, 39 with DOI, 39 with abstract, 35 with an impact factor — the four
without are conference papers, which JCR does not index.

Cost, stated plainly: **8 network actions per search** on this host against 4 for the
mirror's capture, because the export takes four clicks.

### Added — `wensu jcr import` / `wensu jcr status`

The impact factor is not in a BibTeX file, so it comes from a local SQLite database built
from the user's own JCR workbook. The data is **not shipped**: it belongs to Clarivate, and
a 4.2 MB table does not belong in a wheel. Re-running the import after each yearly release
replaces the contents.

The workbook is read with the standard library (`zipfile` + `ElementTree`), checked against
`openpyxl`, and imports 22 249 JCR rows and 21 772 CAS rows from the supplied file in 2.5 s.
Lookup is **ISSN first**, because the workbook truncates journal names to ~29 characters
(`CA-A CANCER JOURNAL FOR CLIN`); the name path only accepts a prefix match and returns
nothing when two journals answer, since a wrong impact factor is worse than none. A journal
with no metric stays `null` — never `0`, which `min_impact_factor` would believe.

### Fixed — the socket read deadline equalled the action deadline

```
bridge.error: timed out
```

The host allows itself the action's full `timeout_ms` and then writes the reply; the client
waited exactly that long, so the read aborted in the same millisecond and an action that had
succeeded reported a failure. The socket now waits `timeout_ms + 2 s`.

### Fixed — four separate defects in reporting the downloaded file

Every one of these made a **complete, correct export look like no file at all** — four
170 KB files were on disk while the kernel reported none:

1. The `chrome.downloads.onCreated` listener was attached *after* the click returned, so the
   event had already fired. Attached before the click.
2. An empty `downloads.search` result was treated as "gone" rather than "not indexed yet",
   abandoning the wait on the first poll.
3. The export arrives as a **`blob:` URL** with an empty `filename`, so the name and URL
   tests rejected the very file we had just caused. The tab is the discriminator now.
4. `onCreated` fired **zero times** on a run that produced a complete export. The wait no
   longer depends on the event: it polls the download list, which cannot be missed by a
   service worker that was suspended in between.

A rejected download is now reported with its reason (`[saw not-a-bib:blob:…]`), which is
what identified defect 3 after three rounds of inference had failed to.

### Known limitation — a companion export extension must be off

With a third-party "WoS BibTeX assistant" extension enabled, every `wait_for` inside the
export dialog timed out: the four selectors answered in 46 ms / 0 ms once it was disabled.
It re-renders the dialog, and the visibility test sees a detached node. Documented in
`docs/reviews/wos-global-site-2026-11-11.md`.

## [0.12.53] - 2026-11-11

The global Web of Science site is the **same application** as the mirror — same API, same
payload. 0.12.52 said otherwise, and that conclusion was built on a bug I had just
introduced in the same release.

### Retracted — "the global site uses a different format"

0.12.52 added `/api/esti/SearchEngine/search` to the capture's tracked prefixes and to its
"new result set" markers. That endpoint is the **author-name typeahead**, which fires while
the expression is being typed into the search box. It matched the marker, so the capture
cleared its buffer *after* the real `runQueryGetRecordsStream` response had arrived, kept
six author records, and I read that wreckage as "the global site's format".

The user's own capture settled it:

```
https://www.webofscience.com/api/wosnx/core/runQueryGetRecordsStream?SID=…   102 KB
```

Same endpoint, same batch size as the mirror. The `/api/esti/…` entries are gone, and the
comment in `capture.js` records why they must stay gone.

### Changed — the default host is the global site

`https://www.webofscience.com/wos/woscc/advanced-search`, Core Collection. Off an
institutional IP the mirror has no route: the navigation is handed to
`access.clarivate.com` and the run stops on a login redirect. The mirror stays in the
manifest and works by pointing one constant at it.

### Changed — the capture window is now the ceiling, not a guess

`CAPTURE_WAIT_MS` 10 s → **13 s**, with page turns at 12 s. Not a preference:
`params.MAX_TIMEOUT_MS` caps one action at 15 s and the native host enforces the same
bound, so 13 s plus the 1 s reply margin is the maximum. A plan declaring 46 s is refused
before it runs (`policy: timeout 46000ms is outside 0..15000`).

Page turns get a shorter window because they reload an application that is already warm;
giving them the cold-boot window put a three-page plan at 260 s, past the kernel's budget.
With the split: page 1 is 95.9 s declared, page 3 is 162.3 s, all three inside 200 s.

### Known limitation — a network slow enough cannot be served

On the deliberately high-latency link used for this round, the result page needed **minutes**
to render, and no single action may wait more than 15 s. That is a structural limit, not a
number to tune. Serving it needs a kernel-level retry of the capture phase — batched waits
whose timeouts do not fail the plan — and a further ADR for the budget. Recorded in
`docs/reviews/wos-global-site-2026-11-11.md`, which replaces the retracted analysis.

## [0.12.52] - 2026-11-11

Chasing the global Web of Science site turned up four defects on the path that was
already working. Those are fixed here. The global site itself is **not** supported yet,
and the reason is a different data format, not a missing permission.

### Fixed — a pause was executed by the page instead of by the browser

`sleep` was forwarded to the content script like every other verb, and every WoS plan
opens with `goto` then a pause. Right after a navigation the content script is being
re-injected, so the pause sat in the "waiting for the script" retry queue and spent its
whole budget there:

```
16:13:35  sleep  ok=False  3106ms  ERR=bridge.timeout
```

on a page that had loaded perfectly well. A pause does not touch the page, so it now runs
in the extension's background worker: `sleep ok=True 1207ms`.

### Fixed — a content script that never injected on a slow link

Web of Science was injected at `document_idle`, which waits for the load event. On a
high-latency link `window.onload` never arrives, so no script was injected at all — and
it did not recover minutes later:

```
wait_for failed: content_not_ready (step 4/5, stage wait.capture)
```

`actions.js` only registers a message listener at load and touches the DOM inside
handlers, so it can run before the body exists. The global host now injects at
`document_start`. **The working mirror host keeps `document_idle`** — changing the timing
of the only path that works, to serve a path that does not work yet, is a bad trade.

### Fixed — the retry budget was shorter than the action's own deadline

Eight attempts reached ~6.4 s and then declared the page broken, while the kernel was
still willing to wait 11 s. The retry now runs until just before the action's
`timeout_ms`, so the four and a half unspent seconds are used, and stopping early keeps
the error specific (`content_not_ready` rather than the host's `bridge.timeout`).

### Fixed — "step 2/2" on a seven-action plan

The step count used the number of actions that ran, not the plan's length. A plan that
died on its second action reported `step 2/2`, which sent one investigation looking for a
two-action plan that did not exist.

### Added — a channel failure can carry facts the message cannot

`content_not_ready` covers three unrelated situations: no such tab, the document is not
there yet, and the script is there but its channel closed. The extension now returns the
tab's URL and its own wording, and the kernel renders both:

```
wait_for failed: content_not_ready (step 4/5, stage wait.capture)
  [reached www.webofscience.com] [Could not establish connection. Receiving end does not exist.]
```

That line is what distinguished "never injected" from "injected then lost" — the previous
two rounds were spent guessing between them.

### Known limitation — the global site is not supported

`www.webofscience.com` is reachable now (authorised, injected, capturing), but it answers
on a different API and in a different shape:

```
mirror : /api/wosnx/core/runQuery…   newline-delimited JSON, key/payload rows
global : /api/esti/SearchEngine/…    one JSON document, QueryResult/Data.Records
```

`parse_records` reads the first. The default host therefore stays on the mirror: pointing
it at the global site today would trade "cannot reach the site" for "cannot read the
answer", and break the host that works. `docs/reviews/wos-global-site-2026-11-11.md`
records the captured sample, what is still unknown (the document endpoint has not been
identified — the captured response was author data from a typeahead), and the six steps
needed to support it.

## [0.12.51] - 2026-11-11

A refused navigation did not say where the tab went, which is the one fact that tells the
cases apart.

### Added — the reached host, in the error and in the cooldown reason

A blocked Web of Science call produced:

```
goto failed: policy.domain
reason: login_redirect after goto
```

Three unrelated situations produce exactly that pair: an institutional sign-in (what
actually happened), a publisher's own login wall, or a redirect to another legitimate WoS
host. The first is fixed by signing in, the third by adding a domain to the manifest, and
distinguishing them took an inference chain across the audit log, the extension and the
risk module.

Now:

```
goto failed: policy.domain (step 1/12, stage navigate.open) [reached carsi.example.edu.cn]
reason: login_redirect after goto at carsi.example.edu.cn (policy.domain)
```

**Host only** — never the path or query. The path can carry a session ticket, and the
audit log is not a place for one; a test asserts the query string cannot reach either
field.

### Not changed

The detection itself. `policy.domain` on a redirect, and a login marker in the resulting
URL, is a real signal: the extension correctly refused to act on a page it was not
allowed to touch. The problem was never that it stopped — it was that nothing said why.

## [0.12.50] - 2026-11-11

A blocked response told the user to wait 24 hours and nothing else. For a login problem
that is both the wrong cause and the wrong remedy.

### Added — each risk signal explains itself

The 0.12.48 acceptance hit `signal: login_redirect` on its first Web of Science call and
received:

```json
{"status": "blocked", "signal": "login_redirect",
 "cooldown_until": "2026-11-12T01:04:06+00:00", "action_required": "manual_verification"}
```

Nothing said the session had expired. Nothing said waiting was pointless. The way out —
`wensu reset --confirm` — appeared in no field the caller reads, and the user's reaction
was "I didn't see any such result, my searches are fine", which is the correct reading of
a payload that only contains a timestamp.

What actually happened, from the audit trail: the `goto` to the advanced-search page came
back `policy.domain` after 3.6 s — the tab had been sent to an out-of-domain sign-in URL
(the campus SSO/CARSI hop) and the extension refused to treat it as a page it may act on,
while keeping the final URL so the kernel could see it was an auth redirect. That is the
detection working. The reporting was what failed.

Each signal now carries `advice`:

| signal | what it now says |
|---|---|
| `login_redirect` | the session ended; sign in in that window, then `reset --confirm`; waiting will not help |
| `captcha` | solve it in the window, then reset; never automate it |
| `verify_redirect` | complete verification, then reset |
| `http_403` | stop for the day; retrying or changing network makes it durable |
| `rate_limited` | stop; the quota is not the problem, the rate is |
| `text_marker` | read the page — the wording says which of three problems it is |
| `cooldown` | do not retry; wait or fix the cause first |

**The stop is unchanged.** AGENTS.md requires terminating on these signals and writing the
24-hour cooldown, and a test asserts `status: blocked` and the cooldown still stand. Only
the guidance is per-signal, because one message cannot serve a captcha (seconds to fix),
an expired session (one sign-in), and a 403 (stop for the day).

A signal added later without guidance stays silent rather than inventing advice; a test
enforces that.

## [0.12.49] - 2026-11-11

Three defects from the 0.12.48 acceptance, all introduced by 0.12.48. The first disabled
CNKI's cache entirely; the second turned a capture timeout into an `AttributeError`.

### Fixed — a navigation nonce made every CNKI call a cache miss

CNKI appends `&t=<epoch ms>` to its advanced-search URL to force a real page load. The
plan signature hashed it, so **two identical requests a second apart were two different
identities** — the acceptance run paid 3 quota twice for the same page, and adding only a
year also cost 3.

The channel now declares it:

```python
class CnkiChannel:
    volatile_url_params = plan_search.VOLATILE_URL_PARAMS   # frozenset({"t"})
```

Declared by the channel rather than stripped by the kernel, because only the code that
writes `&t=…` knows it is a cache-buster and not a search term. This is the one place a
declaration beats a derivation: the kernel cannot tell a timestamp from a search parameter
by looking at it.

The regression test builds the real plan **twice with a sleep between**, because two
builds in the same millisecond can produce the same `t` by luck and let the bug through —
the report named that exact trap.

### Fixed — `capture_state` was never called

The channel exposes `capture_state()` as a method. The service read `.selector` off the
bound method:

```
AttributeError: 'function' object has no attribute 'selector'
```

That happened **while the real `ActionError` was being constructed**, so a capture timeout
lost its stage, its message and its quota charge and surfaced as an error about the
diagnostic instead of the failure. The whole diagnostic is now wrapped so it can never
replace the error it describes, and the integration test drives the real channel through
the real service failure path rather than calling the classifier directly — which is why
the unit test of the classifier passed while the wiring was broken.

### Fixed — a legitimately short last page was treated as a truncated capture

`_cache_can_answer` compared held records against the request. The last page of a result
set is short by nature: 128 records over three pages of 50 leaves 28, and a request for 50
there can never be met, so the page would be re-fetched every time. A cached page whose
`page` is at or past `page_count` is now accepted.

### Documentation

The `diagnostics` verdicts are now explained where a caller will look, with the one rule
that matters: **if `declared_records` is present, the site did have that result set — do
not report "no literature"**. Also corrected the claim that a year change always costs a
fetch: it does on WoS, it does not on CNKI.

## [0.12.48] - 2026-11-10

The 0.12.47 acceptance passed all four target items and then found a regression I had
introduced in the same release, in both directions at once, on one channel.

### Fixed — the cache identity was guessed, and guessed wrong for CNKI (N1, N2)

To stop `local_sort` from re-running a search, 0.12.47 replaced "the whole query is the
cache key" with a hand-picked list of site-facing fields. That list was then wrong twice:

* **`limit` was excluded**, but CNKI's plan **does** change above 20 — it switches the
  site's page size. So a cached 20-record page answered a later `limit: 50` with 20
  records and `cache_hit: true`, reporting a truncated list as the answer.
* **`year_from`/`year_to` were kept**, but CNKI filters locally only and its plan does
  not change at all. So adding a year bought a 14.9 s re-search for a byte-identical
  site request, and charged 3 quota for it.

Both are the same mistake: predicting what a channel will do. `_site_signature` now
**builds the plan and hashes it**. Whatever the plan does is by definition what the site
is asked to do; anything absent from the plan cannot change the fetch. One rule, no
per-channel list, and it cannot be wrong twice in opposite directions.

Two details the first attempt got wrong:

* `settle(jitter(...))` randomises every `sleep` duration, so hashing raw actions made two
  identical queries hash differently and would have disabled caching entirely. Pauses are
  dropped from the signature — pacing is not content.
* The stripped query text rides along, so a channel that sends its expression some other
  way cannot collide. This also removes the leading/trailing-space quirk the acceptance
  run had to control for: `  ionogel actuator  ` and `ionogel actuator` are one fetch.

Added `_cache_can_answer`: a cached page holding fewer records than requested, while
`total` says more exist, is not served. The signature normally prevents the situation;
this is the guard for a channel that uses one plan for both sizes.

### Added — a capture timeout now reports what the page held (N3)

`wait_for failed: timeout (stage wait.capture)` has appeared in every acceptance run, and
each time the only fact available was that it timed out. Three different failures produce
that one symptom: the stream never started, it started and never finished, or the records
arrived and the readiness flag was never raised. They need different fixes.

Failures at `wait.capture` now carry a `diagnostics` block describing the capture node:

```json
"diagnostics": {"verdict": "metadata_only", "bytes": 58, "lines": 1,
                "declared_records": 115, "has_search_info": true,
                "has_records_block": false}
```

`verdict` is one of `no_stream`, `metadata_only`, `stream_started_no_records`,
`records_present_not_ready`. The probe is a `read_text`, which is not a network verb, so
it is free and starts no traffic. It counts and classifies; it never re-parses records,
because a second parser is a second thing to disagree.

**This is a diagnostic, not a fix.** The cause of the first-capture timeout is still
unknown, and per the report the next step is to let the next occurrence say which of the
three it was rather than to guess at a behaviour change.

### Changed — the filter count is public in both places

`dropped_filter` is now a top-level field beside `dropped_year`, as well as
`filters.dropped.filter`. The acceptance run read only the top level, found `dropped_year`
and no `dropped_filter`, and had to be told where the second one lived — which is the
right complaint about an interface that publishes two counters in two different places.

## [0.12.47] - 2026-11-10

From a 39-call usability report. The two findings that mattered most were both cases of
the tool charging for something it had already done, or claiming a fact it could not know.

### Fixed — a local view change re-ran the whole search (A1)

One WoS query cost 25 s and 4 quota. The **same** query with only `local_sort: "year"`
added cost another 24 s and 4 quota and returned the same single record. Same for
`min_citations` and `min_impact_factor`. Meanwhile changing `fields` was free — because
that one never reached the query object at all.

The cache key was the whole `SearchQuery`, so parameters that only describe how a page
should be *presented* were part of the identity of the *fetch*. Fixing it needed three
things together:

1. the key covers only what is sent to the site (`text`, `channel`, `sort`, `page`,
   `year_from`/`year_to`, `source_types`, `exclude_ut`);
2. the cached page is stored **as the site returned it**, before any filtering;
3. one `_present()` derives the caller's view on both the live and the cached path.

The impact-factor threshold had to move out of the WoS parser for this to hold — it was
filtering during the parse, so the stored page was already filtered. A threshold is a
view over a page, and it now lives with every other view.

Measured effect: re-sorting, re-filtering, changing `limit` or `include_abstract` all
return `cache_hit: true` and `quota_charged: 0`.

### Fixed — `min_citations` returned records whose count was unknown (A3)

A paper with `citations: null` came back from `min_citations: 1000`. The old reasoning was
recall — "not measured" is not "zero". But a caller asking for *at least 1000 citations*
reads the returned record as meeting that bar, and the data does not support it. That is
not recall, it is a wrong answer with a plausible shape.

Unknown counts and unknown impact factors are now dropped, and `dropped_filter` reports
how many. `filters.min_citations_drops_unmeasured` says so explicitly.

### Fixed — export dropped the impact factor's year (A2)

The CSV had an `impact_factor` column and no `impact_factor_year`; the Markdown rendered
`影响因子: 29.1` alone. Beside a 2026 publication date that reads as "29.1 in 2026" — the
JCR edition was 2025, and comparing journals across unknowable editions is the exact
mistake the year field exists to prevent.

CSV gains the column (empty when unreported, never 0). Markdown renders
`影响因子: 29.1（JCR 2025）`, or `（JCR 年份未报告）` rather than implying the paper's year.

### Fixed — a timeout asserted a cause it could not know (A4)

`bridge.timeout` produced "the browser extension is not connected" and sent the user to
`wensu browser start`. The report's run had `bridge_ready: true` immediately before *and*
after, so that was a confident wrong answer about a working browser.

The remediation now names a check (`wensu status`, read `bridge_ready`) and a human step,
and leaves the diagnosis open — the connection, the content script in that tab, and the
page itself are all candidates. `stage` (added in 0.12.44) says which layer stopped.

### Fixed — year ranges and identifiers (C1, C2, B1)

* `year_from=2027` with no end produced `PY=(2027-2026)` — a backwards range no human
  meant. The missing end is clamped, so it becomes the single year.
* `year_from=year_to=2026` produced `PY=(2026-2026)` while a typed `PY=(2026-2026)` was
  folded to `PY=(2026)`. One spelling now.
* A record URL carrying `?locale=en_US` produced the identifier
  `"WOS:...?LOCALE=EN_US"`, so the exclusion matched nothing and the caller paid for a
  search returning the same records. Query strings and fragments are stripped.
* `doi:10.…`, `https://doi.org/10.…` and `https://dx.doi.org/10.…` were reported as
  `UNKNOWN_CHANNEL` — "no channel claims the host", accurate and useless. All spellings
  are normalised to the bare DOI in both entry points.

### Added

* `overwritten` in the export response when `out_path` replaced a file (B6).
* `filters.dropped.filter` and `year_scope: "site_and_page"` — a year bound becomes part
  of the WoS expression, so calling it page-local told callers `total` was unfiltered (B5).
* `filters.min_citations_drops_unmeasured`.

### Documentation

Eight contradictions the report listed, all corrected: year filtering is two layers and
differs by channel; `total` is the site's count and one record can fall outside a `PY=`
span; a repeated CNKI `detail` is free; export supports four formats, not two; the WoS
cache returns abstracts too; timeouts now report `quota_charged`; there is no
document-type filter, so filter on `doc_type_unified` after the fact; and installing
requires reconnecting the MCP client, with a version check that settles it.

### Not done

**Error shapes are still inconsistent** (B4): a blank query, a bad field name, an
out-of-range limit and an unknown channel each produce a differently shaped error. They
are all free and all correct, but a caller has to parse four shapes. Unifying them means
changing the MCP contract for every error path — a separate change, not a line edit.

## [0.12.46] - 2026-11-10

The 0.12.45 acceptance passed its target flow — 115 records covered in three rounds with
zero duplicate IDs, and the live capture retest clean. It found one real defect and one
ambiguity in how a response describes itself.

### Fixed — a `detail` response could not be handed to `export`

The natural flow is: find a record, read its details, export what you got. It failed on
wensu's own bookkeeping fields:

```
unknown record fields: ['quota_charged', 'quota_remaining']
```

`detail` flattens the response envelope onto the record, and `export` rejected anything
outside the record schema — so the obvious thing a caller does was the thing that did not
work. The acceptance run worked around it by stripping those two keys before calling
`export`, which is exactly the knowledge an interface should not require.

`export` now drops the envelope keys and still rejects everything else, so a typo is
still caught (`unknown record fields: ['titel']`). Both halves are asserted: the fix must
not turn a strict schema into a permissive one.

### Documented — `PY=(2026)` and `year=2027` can both be true

One record in the accepted set carries `year=2027` while matching `PY=(2026)`. For Web of
Science, `year` is `pub_info.pubyear` — the site's own label — and it can differ by one
from the query span for online-first items and for proceedings volumes dated the following
year. **There is no second year field to expose**: the payload carries `pubyear` and
nothing else, so inventing an "early access year" would have meant guessing a field that
is not there.

`Record` now says this, and says what follows from it: group and display by `year`, and do
not read one record outside the requested span as a parse error. Filtering after the fact
is safe — that is what `dropped_year` counts.

### Not addressed

**`page` / `page_count` are still null** (W04). The acceptance covered the exclusion path,
which does not need them, so this round says nothing about them.

**Empty `pages` / `keywords`** on some records is the source being empty, not the parser
dropping data. Left alone deliberately.

## [0.12.45] - 2026-11-10

The acceptance run's two-round plan failed on its first exclusion call, in 1.6 s and at
zero quota cost — the kernel's own parameter validation refused the expression:

```
wensu: invalid parameters for type: policy.params
```

### Fixed — two caps that each looked fine and together did not

| constant | value | meaning |
|---|---|---|
| `MAX_EXCLUDE_UT` | 500 | identifiers one search may exclude |
| `MAX_TEXT_CHARS` | 500 | characters one `type` action may carry |

An exclusion adds about 25 characters:

```
exclude   3 ->   129 chars
exclude  17 ->   479 chars   ← still under the cap
exclude  50 ->  1304 chars   ← refused
exclude 500 -> 12554 chars   ← refused
```

The effective limit was **seventeen**, while the parameter advertised 500. My own test used
three identifiers (197 characters) and passed; the feature broke at the size it was
documented for. **No test of either constant alone could have caught this** — only an
assertion spanning both.

`MAX_TEXT_CHARS` is now 16 000 (ADR 0015). It was never a typing budget: `humanType`
assigns `element.value` in one statement and dispatches events, so the site sees a paste,
not twelve thousand keystrokes. The cap only bounds how long a string a tab can be handed.

### Added — the cross-constant test

```python
@pytest.mark.parametrize("count", [3, 17, 50, 500])
def test_the_expression_a_full_exclusion_list_produces_can_actually_be_typed(count):
    built = _build(text="...", exclude_ut=ids)
    assert validate_params("type", {"text": built, ...}) is None
```

plus `assert MAX_TEXT_CHARS > MAX_EXCLUDE_UT * 26`, which pins the advertised cap to
something the kernel will actually accept.

### Verified

```
exclude   3 ->    129 chars  type-accepted: True
exclude  17 ->    479 chars  type-accepted: True
exclude  50 ->   1304 chars  type-accepted: True
exclude 500 ->  12554 chars  type-accepted: True
```

## [0.12.44] - 2026-11-10

Two findings from the 0.12.43 acceptance run, plus a defect that run exposed in my own
previous fix.

### Fixed — the capture never became ready on a query that had succeeded

0.12.43's acceptance query returned nothing: `wait_for failed: timeout` after the refresh,
while the browser window title read "115 results".

The cause was the readiness rule I added in 0.12.40:

```js
return carriesRecords();   // no bound
```

`data-ready` was withheld until the buffer matched a pattern for the records block. When
it did not match, the capture waited forever — so a query the site had already answered
looked like a dead bridge. **A test that can only be satisfied by one specific payload
shape is not a readiness signal, it is a trap.** I verified that fix against one payload
and never asked what happens when the pattern does not match.

Now: the pattern is broader, and the wait is bounded to three idle windows (~6 s) before
handing the buffer to the parser and letting it read a short page. A new capture resets
the counter.

Verified on the exact query that failed: `total=115, 5 records, 4 quota, 32.5 s`.

### Added — the public error names the stage (W05)

Three waits in one Web of Science search produced the identical message:

```
wait_for failed: timeout
```

The query editor, the result list, and the capture stream were indistinguishable from
outside; the acceptance run had to reconstruct the sequence from the audit log and the plan
source. Failures now carry `stage`:

```
wait.query-input    wait.result-list    wait.capture
click.submit        click.page-turn     navigate.reload    navigate.open
```

and the message reads `wait_for failed: timeout (step 9/12, stage wait.capture)`.

`stage` names the *kind* of thing waited for, never the selector — which elements a
channel uses is implementation detail, and on some paths the selector is derived from page
content. A test asserts the selector cannot reach the payload.

### Fixed — `scholar-detail` said CNKI only

The skill's first rule read "只接受知网域名下的 https 链接". `detail` has accepted a URL
from either channel and a bare DOI for several releases, and WoS detail is served from the
search-seeded cache at zero cost. A session reading that skill would not have tried.

The skill now has a per-channel table, says the channel is inferred, and points at
`detail_many` for batches.

## [0.12.43] - 2026-11-10

Two ways to get more records existed side by side with no rule saying which to use. This
gives the choice an answer in all three places a caller might look.

### The rule

| channel | how to go deeper | why |
|---|---|---|
| **Web of Science** | `exclude_ut` | independent request each time; set shrinks predictably |
| **CNKI** | `page` | no exclusion field exists |
| either, query already narrow | `page` | one turn for a few more records |

### Where it now says so

**Tool description** — `page` used to read `"1-based. 3 at most: one page turn per extra
page."`, which says what it is and nothing about when not to use it. It now opens with
"Reach for `exclude_ut` first on Web of Science". The `search` docstring gained a
paragraph, and `exclude_ut`'s own description names the case where `page` is still right.

**The response** — a caller who already turned a WoS page gets:

```json
"advice": "webofscience can exclude records instead of turning pages: pass the UT
           values you already have as exclude_ut ..."
```

A description is read before the first call and rarely again; the advice arrives at the
moment the wrong lever was just used. It appears only for `page > 1` on a channel that has
an exclusion field — CNKI and page 1 stay silent, because there the advice would be noise.

**The skill** — the rule, plus the reason `page` is not a way to walk a large set.

### Not done

`page` is not removed for Web of Science. Deleting it would break anyone already using it
and would leave the tool unable to answer "one more page" without the caller computing UT
lists first. The guidance makes the expensive path available rather than invisible.

## [0.12.42] - 2026-11-10

Reaching deeper results by **excluding what you already have**, instead of turning pages.
Suggested by the user, and the mechanism was verified against the live site before the
code was written.

### Added — `exclude_ut`

`search` takes a list of UT identifiers to leave out of the query:

```
search("TS=(ionogel AND actuator)", channel="webofscience",
       exclude_ut=["WOS:001218812900001", "WOS:001174201100160"])
```

produces

```
((TS=(ionogel AND actuator)) AND PY=(2022-2026))
  NOT UT=("WOS:001218812900001" OR "WOS:001174201100160")
```

**Verified live before implementing**: a 38-record query with three exclusions returned
`total = 35` and a different page of records. After the implementation, the same check
through the CLI also returns 35.

Accepts a bare UT, a lower-case one, or a full `full-record/...` URL — the URL is where
the identifier is visible in a response, so requiring the bare form would mean every
caller writing a parser. Blank entries are skipped rather than rendered as `""`. Capped
at 500 per call.

### Why this instead of deeper pages

| turning pages | exclusion |
|---|---|
| one result set held open for minutes, across SPA state changes | an independent request each time |
| depends on the site remembering its position | depends on nothing but the query |
| observationally identical to a scraper hammering "next" | observationally a person refining a query |

The ordering caveat is the caller's: results are covered in order only while `sort`
stays the same. The identifiers excluded are specific records, not ranks, so a re-sort
between calls cannot make the next page silently repeat earlier ones — it only changes
which records remain.

### Also

`page=3` on Web of Science is now allowed (ADR 0014 raised the plan budget to 200 s;
three pages cost a declared 155.5 s). The cap lives in one function now — it had been
duplicated, and raising it in one copy left the other refusing.

### Verified

```
38 records, exclude 3 UTs        -> total 35, different records
9 new unit tests                 -> expression shape, URL normalisation, the cap
250 existing tests               -> unaffected
```

## [0.12.41] - 2026-11-10

Plan budget raised from 120 s to 200 s (ADR 0014). This is the change you asked for, and it
turned out to unblock page 3 as a side effect.

### Changed — `max_plan_seconds` 120 → 200

`PolicyEngine.validate_plan` sums every action's declared `timeout_ms` **before** the plan
runs. That is a static worst case, not a measurement, and the gap was large:

| plan | declared | actually took |
|---|---|---|
| WoS page 1 | 92 s | 31.6 s |
| WoS page 2 | 124 s | 49.2 s |

The declared figure is ~2.5× reality because every `wait_for` counts as "waits its full
deadline", while in practice it returns in milliseconds (result list: 30 ms) or seconds
(capture: 5 s).

So the 120 s ceiling was refusing work that fits comfortably, and my response had been to
shrink per-action deadlines — the 15 s wait for the result list became 9 s. **That made the
tool worse at exactly the thing the deadline exists for: a slow network.** Those deadlines
are restored to 15 s.

### Changed — WoS accepts 3 pages instead of 2

Measured marginal cost per page turn is ~32 s: 93 → 124 → 155.5 s, all inside 200 s.

Page 4 is still refused, and not on clock grounds — it would be a fourth re-submission of
the same query, which is the traffic pattern the cadence rules exist to avoid. The kernel's
`max_pages_per_call` is 3 as well.

The cap now lives in one function, `_reject_too_many_pages`. It had been duplicated in both
plan builders, and raising the number in one of them left the other silently refusing —
which is exactly what happened during this change.

### Not done

**The check is still static.** The right fix is to accumulate wall-clock time during
execution and keep the static sum as a fallback, but that touches the planner loop, and two
core extension behaviours were already changed today. Recorded in ADR 0014 as the deferred
option.

### Verified

```
page 1: 92.0 s declared
page 2: 123.9 s declared
page 3: 155.5 s declared   ← was refused, now allowed
page 4: refused
budget: 200 s
```

## [0.12.40] - 2026-11-10

The WoS split path now completes without a single timeout. Two changes, both from field
observation, and the second only became visible after the first was fixed.

### Fixed — the extension discarded the plan's click budget (W02, root cause)

`background.js` raced every click against a hard 2 s and returned
`{navigation_expected: true}` with **no URL** when it lost. The WoS submit already asked for
`wait_until: "enabled"` with a 10 s budget — the extension threw it away.

Observed sequence:

```
click     ok=True  2004ms   ← cut off here
sleep     ok=True   987ms
wait_for  ok=False 9005ms   ← waiting for a result list that had not rendered
```

The plan's `timeout_ms` now sets the ceiling (clamped to 30 s, floored at 2 s for callers
that pass nothing). After the change:

```
click     ok=True 10005ms   ← waited the 10 s the plan asked for
wait_for  ok=True    36ms   ← the result list appeared 36 ms later
```

2 s was never wrong as a *fallback* — a click on a control that never replies must not hang
the tab. It was wrong as a **decision**: the plan said "wait up to 10 s for this control to
come back", and the extension answered at 2 s as if the wait had finished.

### Fixed — `data-ready` meant "the buffer parses", not "the records arrived" (W03)

With the click fixed, the next failure was `capture holds no records; the stream was not
intercepted (0 unparseable line(s) dropped)` — a message that blames the wrong thing.

`markReady()` set `data-ready=1` whenever the buffer merely parsed, so a capture holding only
the `searchInfo` block was declared complete.

The site states how many records it will send in that same block, so the capture checks it:

| buffer state | behaviour |
|---|---|
| `RecordsFound: 50`, no `records` block yet | keep waiting |
| `RecordsFound: 0` | ready immediately — that is a real answer |
| no `RecordsFound` | falls back to the old parse check |

### Verified end to end

```
page 1: total=38,   2 records, 4 quota, 31.6 s
page 2: total=2690, 2 records, 6 quota, 49.2 s — 17 actions, all ok=True
detail: full abstract (1053 chars), IF=5.1 (JCR 2025), 4 quota
CNKI:   unaffected, total=1158
```

### Still open

**W01** — page 3 is rejected; two pages plus a detail call already costs 49 s of the 120 s
budget.

**W05** — three failure stages still share one `bridge.timeout` error. The audit log
distinguishes them after the fact; the public error does not.

**W04** — no page number, record range, or duplicate flags in the response, and `limit`
truncates after parsing rather than setting the site's page size.

## [0.12.38] - 2026-11-10

Field test of 0.12.37 found that the W02 fix broke the channel it was meant to help.

### Reverted — the landing guard rejected a real Web of Science search (W02)

0.12.37 failed the call when a submit click returned no URL *and* the control never
reported going busy. That condition is always true on WoS: its submit button never goes
busy, so the query ran, spent four quota points, and then the call reported "the query
may not have started".

An unconfirmed landing is now carried forward instead of judged. The tail plan reads
the page and the caller sees what is actually there — if the click really did nothing,
the read returns the form and the parse fails visibly rather than being pre-empted by a
guess. **The old behaviour (silently reloading the form) is not restored**; what changed
is that the guard no longer asserts a failure it cannot prove.

Verified live: `TS=(ionic AND actuator)` on WoS returns `total=794`, 3 records, 4 quota,
26.8 s.

### Confirmed by field test

| fix | live result |
|---|---|
| **W08** seeding | a WoS record with no abstract now returns full detail (DOI, volume, issue) at `charged=0` from cache |
| **W07** JCR year | `IF=5.8 JCR=2025`, `IF=4.9 JCR=2025`, `IF=null JCR=null` |
| **W09** lock probe | stale `Default/LOCK` reports `False`, falls back to `browser start` |
| **W01** page limit | `page=3` rejected in 0 quota with a message that now also says why repeating page 2 will not help |

### Changed

The WoS page-limit error said each page "needs a scroll round", which stopped being true
when the split plan replaced scrolling with a reload. It now describes what the plan
actually does and what to do instead.

## [0.12.37] - 2026-11-10

WoS review (`docs/reviews/wensu-wos-0.12.36-2026-11-10.md`), from a real research task rather than a
matrix. Nine items; the three that could be closed without redesigning the WoS capture path are below.

### Fixed — a click with no URL skipped the results-page guard (W02)

When the submit click overruns the extension's 2 s race, it returns `navigation_expected: true` and
**no url**. The guard read:

```python
if landed and is_results is not None and not is_results(landed):
```

`landed` was `None`, so the whole condition was skipped and the tail plan reloaded whatever page was
open — the search form. A review reproduced the reload against the advanced-search URL.

No URL now means "landing unconfirmed". If the site also never reported the submit control going
busy, the click did nothing and the call fails; if it did go busy, the query ran and the missing URL
is only a reporting gap.

### Fixed — a WoS paper without an abstract became unreachable (W08)

Detail records were cached only when `record.url and record.abstract`. A Web of Science row is a full
record minus the abstract, so a paper with none was not cached — and that channel implements no detail
plan, so `detail` fell through to "webofscience channel does not implement detail yet". Every field
the caller wanted was already in hand.

Channels now declare `search_seeds_detail`. WoS sets it; CNKI does not, because its rows really are a
title and a link.

### Fixed — a stale LOCK file looked like a running browser (W09)

`profile_is_running` returned `Path(...).exists()`. Chromium leaves `Default/LOCK` behind when it
crashes, so a closed browser was reported as "a browser is using the profile, but the extension is
not connected" — advice to click an icon in a window that was not open.

The file is now *probed*: an exclusive lock is taken to learn whether anyone holds it. The function
returns `True`, `False`, or **`None` when it cannot tell** — and `None` produces an honest
"cannot tell" diagnosis with `wensu browser start`, which is safe either way.

### Fixed — the JCR year was parsed and discarded (W07)

`_impact_factors` read `ImpactFactor` and dropped the `Year` beside it, so two records with identical
numbers could come from different JCR editions. `Record` gained `impact_factor_year`, the parser keeps
it, `schemas/record.json` describes it, and the export round-trip preserves it.

### Fixed — the skill contradicted the tool (W06, W01)

- The skill said to retry a `wait_for` timeout once. `_retryable` returns false for it, and retrying
  re-submits the query and spends quota. Only `BridgeTimeout` is retryable, and the skill says so.
- The skill offered `page` 1–3 for both channels. WoS rejects page 3; the skill now says so.
- The skill called `impact_factor` "the JCR value for this year". It now points at
  `impact_factor_year` and warns that different editions are not comparable.

### Still open

**W01** — no way to reach page 3 of a WoS result set. The third page would exceed the kernel's 120 s
plan budget, so the limit is real, but 115 results cannot be covered through a public interface. Needs
a paginated/continuation plan, not a relaxed limit.

**W03** — `capture.js` marks `data-ready` before the page's records are complete or current: a
secondary stream does not clear it, an idle timer can fire while a response is still open, and a
payload holding only `searchInfo` counts as ready. Fixing this means tracking request generations and
expected record counts, which changes the capture contract.

**W04** — no page number, record range, result-set id, or duplicate/corruption flags in the response,
and `limit` truncates after parsing instead of setting the site's page size.

**W05** — three different failure stages (search form, first capture, next-page capture) all return
`ACTION_TIMEOUT / wait_for failed: timeout` with no selector or step. `ParseError` also conflates "the
stream was not intercepted" with "it was intercepted but held no records".

These four need design work on the WoS capture path and are recorded here rather than patched.

### Verified

```
pytest                251 passed
ruff check / format   clean
mypy --strict         clean
```

## [0.12.36] - 2026-11-09

v2 matrix acceptance (`docs/reviews/wensu-acceptance-v2-0.12.35-2026-11-09.md`). The matrix covered
31 required cells plus 92 export combinations; **A9 and A13 from the previous round both passed**, and
every export type is now correct. Two defects remained.

### Fixed — a third unlabelled host unlocked the ambiguity check (V2-01)

The check compared the set of **distinct labels** among eligible candidates:

```python
labels = {item[2] for item in eligible}
if len(labels) <= 1:
    raise BridgeAmbiguous(...)
```

With two hosts labelled A and one written before the field existed, the set became `{A, None}` — two
values — so the check passed and one of the two A's was picked.

**This is the third time the same mistake was written differently.** The first version counted files,
the second compared distinct labels machine-wide, this one compared distinct labels among eligible
candidates. Each time, adding a third party grew the set and silenced the check while two
indistinguishable candidates remained.

Counting **per label** is the property that survives every third party: if any label is claimed more
than once, the request cannot be routed. An unlabelled host forms its own group, so two of them are
ambiguous too.

### Fixed — a bridge failure reported itself as worth retrying (V2-02)

```python
return isinstance(error, (BridgeTimeout, BridgeError))
```

`BridgeError` means no host is reachable. Retrying changes nothing — a browser has to start. It now
returns `True` only for `BridgeTimeout`, where the page was slow rather than wrong.

`BridgeError` also had no `bridge.` code, so it fell through the remediation branch in `_payload` and
never received the "start the browser" hint. Both `BridgeError` and `ActionError(code="bridge.*")` are
treated as bridge problems now:

| error | retryable | requires |
|---|---|---|
| `bridge.not_ready` | false | external_state_change |
| `BridgeError` | false | external_state_change |
| `BridgeAmbiguous` | false | external_state_change |
| `BridgeTimeout` | **true** | — |
| `PolicyError` | false | — |
| `RiskBlocked` | false | — |

`BridgeTimeout` inherits `BridgeError` and had to be excluded explicitly, or the fix would have made
the one genuinely retryable case unretryable.

### Verified

```
pytest                251 passed
ruff check / format   clean
mypy --strict         clean
```

## [0.12.35] - 2026-11-09

Fifth review (`docs/reviews/wensu-retest-0.12.34-2026-11-09.md`). Items 1 and 2 are regressions I
introduced in 0.12.34.

### Fixed — an unrelated third browser unlocked the ambiguity check (item 1, P1)

The check compared the set of distinct profile labels across **every** live host:

```python
distinct = {value for value in labels.values() if value is not None}
if len(distinct) <= 1:
    raise BridgeAmbiguous(...)
```

Two hosts labelled A were refused. Open an unrelated browser B and the set became `{A, B}` — two
distinct values — so the check passed and one of the two A's was picked. **Opening a browser the
request never asked for disabled a protection that was working.**

Now eligibility is filtered by the requested profile first, and it is *that* set's size that
decides. A third host cannot make two indistinguishable candidates distinguishable.

### Fixed — unification shrank what the export could express (item 2)

0.12.34 routed every lookup through `unify_doc_type`, whose vocabulary is deliberately coarse:
`standard` and `yearbook` collapse to `other`. They had exported as `STAND` and `BOOK` for
releases, and 0.12.34 turned them into `GEN`.

The raw type is now tried first, with unification as the fallback. Unification exists so filters can
compare across channels; it was never meant to bound what an export can say.

### Fixed — Book Chapter still exported as generic (item 3)

`book_chapter` was recognised by the WoS parser and dropped by the export: no mapping existed, so it
became `GEN` with a note claiming the source had not reported a type. It now maps to `CHAP` /
`Book Section`.

The note distinguishes the two cases now:

```
N1  - book_chapter not mapped  →  no longer appears (it is mapped)
N1  - something_new; no RIS equivalent mapped
N1  - document type not reported by source        ← only when the channel said nothing
```

### Fixed — `browser start` blamed the profile for a clean exit (item 4)

Chromium exits **0** when a browser is already using the profile: the new process hands the request
over and leaves. That is the normal result of running `browser start` on an open window, and it was
reported as:

> edge exited immediately with code 0; it could not use E:\LiteratureEdgeProfile. Chromium exit code
> 21 means the profile directory is not writable…

Exit 0 is now reported as a handover. The exit-21 diagnosis is kept for the case it describes.

### Verified

```
pytest                250 passed
ruff check / format   clean
mypy --strict         clean
```

## [0.12.34] - 2026-11-09

Fourth review (`docs/reviews/wensu-retest-0.12.33-2026-11-09.md`), run against the **installed**
0.12.33 wheel rather than the source tree. Item 1 is the P1.

### Fixed — a transaction no longer switches browsers halfway through (item 1)

The 0.12.33 lock stopped two requests from interleaving, but each `_run` built a fresh
adapter and re-discovered a host. So a search could submit to browser A, A could go away,
and the read would find B and return **B's page** — cached under A's query key. Setting
`WENSU_PROFILE` did not help: it only ordered candidates, and an unmatched profile fell
back to any live host.

The transaction now pins one adapter, and picking a host happens once, at the start. If
the requested profile is not running, the call fails with `BridgeError` naming the
profile and the command to start it — substituting another browser is exactly the bug.

### Fixed — liveness is checked before ambiguity (item 2)

Ambiguity was decided from endpoint files, so a registry entry left by a crashed host
made a healthy single-browser setup report "2 native hosts are running" — and the caller
was told to close a browser that had already exited. One host was never even pinged.

`pin()` now pings first and judges only live hosts. A stale file is not a browser.

### Fixed — WoS document types survive RIS and EndNote export (item 3)

The type maps were keyed by CNKI's vocabulary (`journal`, `conference`), so every Web of
Science record exported as `TY  - GEN` / `%0 Generic`:

| page type | before | after |
|---|---|---|
| Article | `GEN` | `JOUR` |
| Review | `GEN` | `JOUR` |
| Proceedings Paper | `GEN` | `CPAPER` |

The type is unified before mapping, so `journal` and `article` — the same thing in two
channels' words — reach the same entry. An unknown type still exports as generic; it just
no longer claims to be one.

### Fixed — `setup --force` no longer replaces an adopted profile (item 4)

`--force` refreshed copied assets **and** bypassed the "keep the recorded profile" branch,
so the documented upgrade command silently swapped an adopted research profile for a blank
`profiles/edge`. Refreshing assets and resetting browser configuration are different
intentions and now have different flags: `--force` for assets, `--reset-browser` for the
profile. The README says so.

### Also

Removed a duplicated `_ensure_bridge` body left behind by an editing mistake — the second
copy shadowed the first and dropped its docstring.

### Verified

```
pytest                236 passed
ruff check / format   clean
mypy --strict         clean
```

## [0.12.33] - 2026-11-09

Third review (`docs/reviews/wensu-retest-0.12.32-2026-11-09.md`). Item 1 is a regression I introduced
in 0.12.32, and it was worse than the problem it was meant to fix.

### Fixed — the ambiguity check refused normal single-browser setups

One host writes **two** endpoint files:

```
host/bridge.json                  the legacy alias
host/hosts/bridge-<pid>.json      the registry entry
```

The 0.12.32 check counted files, so a perfectly ordinary setup looked like "2 hosts, both claiming the
same profile" and refused to connect at all. `status` and `search` were both dead on a healthy
install.

Discovery now collapses endpoint files by **pid** before judging ambiguity, so one host is one
candidate no matter how many files describe it. The test uses the host's own `write_endpoint` rather
than hand-built files, because the layout was the thing that was wrong.

The check still fires for two genuine hosts with the same label — deduplication must not go so far
that it hides the case it exists for.

### Fixed — `detail` and `journal` now join the browser transaction

The 0.12.32 lock covered `search` only. A detail fetch navigates the shared tab, so it could land
between a split search's submit and read; the review reproduced the sequence and the search then
stored the *detail page's* title under its own cache key.

`detail` and `journal` now take the same `browser.lock`. `detail_by_doi` deliberately does not — it
calls `search` then `detail`, each of which takes the lock, and wrapping them in a second
non-reentrant acquisition of the same file would deadlock. That interleaving is a real gap and is
left documented rather than papered over.

### Fixed — the CLI validated `detail`'s fields after fetching

`_check_fields` sat inside the search branch, so `wensu detail <url> --field titel` fetched the
record, then rejected the field. Both branches now validate before any browser action.

### Docs — the concurrency section described the old behaviour

The README still said the lock is released between submit and read, which stopped being true in
0.12.32. It now describes what actually happens: search, detail and journal share one lock and later
requests queue; an ambiguous host set is refused rather than guessed.

### Verified

```
pytest                223 passed
ruff check / format   clean
mypy --strict         clean
```

## [0.12.32] - 2026-11-09

Second round of review (`docs/reviews/wensu-retest-0.12.31-2026-11-09.md`). Everything below was
reported against 0.12.31; R01/R02 are corrections to work I had reported as finished.

### Fixed — the split search now holds one browser transaction (R01)

The submit and read halves of a WoS search each took the planner's lock and released it, so a second
request could submit in the gap and the first would read *its* results — silently, and cached under
the first request's key. Reproduced deterministically offline:

```json
{"expected":{"A":["QUERY_A"],"B":["QUERY_B"]}, "actual":{"B":["QUERY_B"],"A":["QUERY_B"]}}
```

`service.search` now wraps the whole path in `browser.lock`, a separate file from the planner's
`plan.lock` — re-entering that one would deadlock, which the review warned about explicitly.

**My earlier reasoning for not fixing this was wrong and the review said so.** I claimed the fix
would add 15–20 seconds to every search. It does not: a lone request holds the browser for exactly as
long as it already did. What changes is that a *concurrent* request waits — which is what serialising
network actions already promised.

### Fixed — an ambiguous host is now refused, not guessed (R02)

My first attempt had each host record its `profile_dir`, but every host reads the same `browser.json`,
so with two browsers open **both endpoints claimed the same profile**. The review demonstrated it:
two simulated hosts both labelled `E:\ProfileA`. Ordering by that label looked like isolation while
providing none.

Now: labels that genuinely differ are used to order; more than one host reporting the *same* label
raises `BridgeAmbiguous` with the way out in the message. One host is never ambiguous.

### Fixed — an unknown parameter is rejected before dispatch (R03)

`additionalProperties: false` is now in all five tool schemas, and `StrictFastMCP.call_tool` rejects
unknown keys using the tool's own schema before anything reaches the service:

```
status({brief: true, breif: true}) → ValueError: unknown parameter(s): breif
                                       status accepts: brief
```

Both halves are needed: declaring it without enforcing it leaves the claim untested, and enforcing it
without declaring it leaves the schema lying. The accepted keys are read from the schema, so nothing
is kept in sync by hand.

### Fixed — `detail` validates `fields` before fetching (R04)

`_check_fields` ran inside `_detail_payload`, after the network action. A typo in `fields` paid for a
detail fetch whose result was discarded, and in `detail_many` it aborted the whole batch on the first
record. Both now reject before the fetch.

### Fixed — the README and the `search` description were stale (R05)

`README.md` said v0.12.9, its tool table had no `detail_many`, and `search`'s description claimed a
following `detail` is always served from cache. Only WoS seeds detail records; CNKI captures the list
only, so the first `detail` for a CNKI record costs one network action. All three corrected, and the
one-browser-per-agent limit is now stated in the README.

### Verified

```
pytest                212 passed
ruff check            All checks passed
ruff format --check   44 files already formatted
mypy --strict         Success: no issues found in 44 source files
```

## [0.12.31] - 2026-11-09

Closes A01, A03, A04, A05, A06, A07, A09, A11 and A12 from the independent acceptance review
(`docs/reviews/wensu-acceptance-2026-11-09.md`), plus the schema half of A08 and the host-selection
half of A02.

### Added — the tool schema now carries its bounds (A08, partial)

`tools/list` advertised `page` and `limit` as plain integers while `SearchQuery.validate` rejected
`page > 3` and `limit > 50`. A caller could only learn the range by failing a call.

```json
"page":  {"minimum": 1, "maximum": 3,  "default": 1}
"limit": {"minimum": 1, "maximum": 50, "default": 20}
```

The numbers come from `MIN_PAGE` / `MAX_PAGE` / `MAX_LIMIT` in `contracts.py`, which `validate`
also uses, so the schema and the enforcement cannot drift. `FieldName` documents what `fields` keeps
on all three tools that accept it.

`tests/unit/test_tool_schema_contract.py` reads the real `tools/list` rather than parsing
`schemas/tools.json` — that file was the thing that made this defect invisible, since it described
constraints the server never read.

**Not fixed**: `additionalProperties: false`. FastMCP builds its argument model with
`ConfigDict(arbitrary_types_allowed=True)` and offers no way to set `extra="forbid"`, so an unknown
parameter is still ignored. Closing that needs a change upstream or a parameter model per tool.

### Added — the adapter picks the host for its own profile (A02, partial)

With two browsers open there are two hosts. `_candidates` returned them sorted by mtime and took
whichever answered first — so a search submitted for one profile could read the other profile's page.
Silently: the request succeeds, the page is real, it belongs to a different search.

Each host now records the `profile_dir` it serves, and the adapter orders candidates by:
`WENSU_PROFILE` if set, else the profile in `browser.json`, else any live host. An endpoint written
before this field existed stays a fallback, so an upgrade does not look like a dead bridge.

**Not fixed**: the segment lock. A split search holds the lock across submit and read separately, so
two requests can still interleave. The supported configuration is one browser serving one agent at a
time; running two agents against one profile is documented as unsupported. Making it safe needs either
a transaction-scoped lock (which lengthens the hold to 15–20 seconds and slows every caller) or
per-request tab isolation.

### Reference — what the review found

Every item below was found by installing the released wheel cleanly and running the commands. Nine of
them could not have been found any other way, because the machine they were developed on already had
the missing file, the stale config, and the accumulated cache.

### Fixed — the wheel was missing a file the extension loads (A01, blocking)

`content/capture.js` was absent from the published wheel while `manifest.json` referenced it. A
clean install therefore produced an extension the browser cannot load — and every machine that had
ever run from source already had that file, so nothing local could ever notice.

`scripts/check-assets.py` now reads the manifest and checks every path it names against the wheel,
instead of trusting a hand-kept list. `pyproject.toml` gained the missing entry.

### Fixed — a risk block was counted as success in bulk detail (A03)

`detail` returns `status: "blocked"` rather than raising, so `detail_many` filed it under `ok: true`
and continued to the next URL — reporting a batch as successful while the site was asking the caller
to stop. A block now stops the batch, appears at the top level as `status: "blocked"` with
`stopped_early`, and the per-item entry is `ok: false`.

### Fixed — a valid projection on a zero-result search reported "unknown field" (A04)

`_project` derived the set of valid keys from `records[0]`. With no records, every key was unknown,
so the small-response probe — the one place a caller is most likely to be — failed on the empty
answer. Valid keys now come from the `Record` definition.

### Fixed — a misspelled field cost a full query before being rejected (A05)

Validation happened inside `_page_payload`, after the search. A cold request paid for a query whose
result it then discarded, and the CLI leaked a traceback because that call sat outside its `try`.
`_check_fields` runs before anything is spent, in both entry points.

### Fixed — WoS DOI lookups silently carried a five-year window (A06)

`detail_by_doi` built `DO=(...)` with no year, and the WoS builder appends `PY=(last five years)`
whenever no year is given. A paper published outside that window simply "was not found". The window
is widened explicitly for DOI resolution; a DOI identifies one record.

### Fixed — WoS reported total page count as a page range (A07)

`_pages` fell back to `page_count`, so a nine-page article came back as `pages: "9"` — which a
citation formatter renders as page 9. A record with no range evidence now gets `None`: an absent
value is recoverable, a wrong one is not.

### Fixed — the handshake reported the SDK version (A12)

`serverInfo.version` was `1.30.0` (the fastmcp release) while `status.version` was 0.12.x. Two
components answering the same question with different numbers. `FastMCP` takes no `version`
argument; the field lives on the inner server and is now set from `__version__`.

### Fixed — exported `bytes` was smaller than the file on Windows (A11)

The response reported `len(text.encode())` while Python wrote the text with newline translation, so
a 2054-byte RIS file reported 2004. The file is now written with `newline=""` and `bytes` comes from
`stat().st_size`.

### Docs — the integration guide rejected a correct installation (A09)

`docs/integration/codex.md` said there are four tools and that any extra one is an installation
error. There are five. It also required the client's tool set to match `schemas/tools.json`, which
the server does not use — that file is a description, `tools/list` is generated by FastMCP, and the
guide now says so. The bundle README no longer hard-codes a version number that has been stale since
0.12.14.

### Not done

- **A02 (remainder)** — the browser lock is released between the submit and read segments of a split
  search, so two concurrent requests against **one** profile can read each other's results. Host
  selection is fixed (above), so two *different* profiles no longer cross; this is the same-profile
  case. The supported configuration is one browser serving one agent at a time. Making it safe needs a
  transaction-scoped lock (holding 15–20 seconds, slowing every caller) or per-request tab isolation.
- **A08 (remainder)** — `additionalProperties: false`. FastMCP builds its argument model with
  `ConfigDict(arbitrary_types_allowed=True)` and exposes no way to set `extra="forbid"`, so an unknown
  parameter is still ignored. Needs an upstream change or a parameter model per tool.
- **A10** — `ruff format --check` fails on 17 files. The fix is `ruff format src tests scripts`; this
  sandbox refuses ruff's atomic-rename write, so it has to run where the tree is writable.
  `release-check.py` now includes the format gate, so it will not silently pass again.

## [0.12.30] - 2026-11-09

### Fixed — the CLI and the MCP tool diverged four more times

Testing the release the way a user would, instead of the way the tests do, found the same class of
defect four more times. **This is the seventh occurrence today**, so the pattern is stated here
plainly: the tool and the CLI each build their own response, and every field added to one is missing
from the other until someone runs the command.

| Missing from the CLI | Consequence |
|---|---|
| `--count-only` | rejected the flag outright |
| `quota_charged` / `quota_remaining` on `search` | the price was never reported |
| `include_abstract` / `fields` on `detail` | **returned the abstract when not asked, dropped it when asked** |
| the `export` command | did not exist at all |

The payload shaping for both `search` and `detail` now lives in one function each in `server.py`, and
the CLI calls them. `detail` returns through `_detail_payload`, which is where the switch belongs —
the CLI's own copy had it inverted.

### Verified by running the commands

```
search "离子柔性驱动器" --count-only   → query_effective: SU='离子柔性驱动器', total 0, charged 3
search "离子 柔性 驱动器" --field title → total 128, keys title,year,url
detail <doi>                 → abstract null,  charged 0 (cached)
detail <doi> --abstract      → abstract 198 chars, charged 0
detail <doi> --field title --field doi --field pages
                             → keys title,pages,doi,url,quota_charged,quota_remaining
export records.json --format markdown --out refs.md
                             → {"written": true, "records": 3, "bytes": 1113}
```

Also fixed: `wensu setup --browser edge` no longer overwrites a profile recorded by
`wensu browser adopt`. It did, during this session's own testing, and moved the tool from the user's
`E:\LiteratureEdgeProfile` to a fresh `profiles/edge`.

## [0.12.29] - 2026-11-09

Closes WS-01, WS-02, WS-03, WS-04 and WS-16 — the five items that blocked a whole session.

### Fixed — the bridge message sent callers to do something impossible

WS-01. `remediation` was one sentence: "open the profile and click the extension icon". That assumes a
browser is running with the extension merely disconnected. The case that actually blocked the session
was that **no browser was running at all** — the user's everyday Edge was up, but without the
extension. The caller relayed the instruction, and the user answered "did you forget
E:\LiteratureEdgeProfile".

The diagnosis now comes from whether the profile is in use (`Default/LOCK` is held while Chromium has
it open — `SingletonLock` is unreliable on Windows), and the answer is data with a command:

```json
{"diagnosis": "the wensu profile browser is not running",
 "next_action": "browser_start",
 "command": "wensu browser start",
 "profile_dir": "E:\\LiteratureEdgeProfile",
 "human_step_required": false}
```

When the profile *is* in use, the answer is `reload_extension` with `human_step_required: true`,
because clicking an icon genuinely is the right move there.

### Fixed — `retryable: true` invited a retry loop that could never succeed

WS-02. A dead bridge cannot fix itself; retrying waits wall-clock time and fails identically. The
report observed it directly: a retry 25 seconds later still found the bridge down. The field is now
`retryable: false` with `requires: "external_state_change"`.

### Added — `brief` carries the two fields that make it actionable

WS-03. `status(brief)` was cheap (45 tokens) and incomplete: seeing `bridge_ready: false` meant
pulling the full 500-token payload just to learn what to do. `bridge_next_action` now carries the same
diagnosis object.

### Fixed — `browser start` names the sandbox case

WS-04. The message was accurate ("exit code 21 means the profile directory is not writable") but did
not say the likely cause when running confined: the command needs full file access. Added to the
message; `status.browser_profile` is unchanged.

### Fixed — the skills existed but were never installed

WS-16, and this is the one that explains a lot. Four `SKILL.md` files had been in the repository for
several releases. **None of them was in the wheel**, so a package install shipped zero skills: an
agent looked at the skill directory, found nothing for this tool, and worked out the CNKI query
semantics by spending quota — 12 of them, per the report.

- The wheel now carries all four under `scholar_search/assets/skills/`.
- `wensu setup --skills-dir <path>` installs them as `<path>/<name>/SKILL.md`.
- Skills are installed **before** the browser assets and independently of them: the first live test
  showed an already-present asset tree aborting setup before the skills were touched.

### Verified

Every claim above was exercised before this release, and the two branches of the remediation are
covered by tests — the "browser not running" branch cannot be reached on a machine where the profile
happens to be open, which is exactly why it was wrong for so long.

```
remediation (profile running) → reload_extension,         human_step_required: true
remediation (profile stopped) → browser_start,            human_step_required: false
error payload                 → retryable: false, requires: external_state_change
wensu setup --skills-dir D:\DSH\.dsh\skills → 4 directories installed
```

### Still open

WS-05 through WS-15 and WS-17/18 — query semantics documentation (largely covered in the skill that
is now actually installed), `query_mode`, a cheap `probe`, `next_action` as a single enum,
`page_count`/`publication_status`, duplicate papers, schema slimming, `sort_effective`, and the
`detail_many(out_path=…)` harvest path. These are real, and none of them blocks a session the way the
five above did.

## [0.12.28] - 2026-11-09

### Fixed — the tool schema did not describe the tools

Three defects in `schemas/tools.json`, all found by diffing it against the code that serves it. Since
an MCP client builds its tool list from this file, each one made a working feature invisible:

- **`detail`'s `url` was pattern-locked to CNKI.** `"pattern": "^https://[a-z0-9.]*cnki\\.net/"` meant
  a bare DOI — added in 0.12.20 — or a Web of Science URL was rejected by the schema before the code
  ever saw it. The pattern is gone; the code validates what it accepts.
- **`detail` and `detail_many` did not list `include_abstract` or `fields`.** Both were implemented
  and neither was advertised, so the tool that most needed the projection was the one an agent could
  not discover it on.
- **`detail.channel` defaulted to `"cnki"`,** contradicting the code, which infers the channel and
  only takes an override.

### Fixed — `wensu status --brief` did not exist

The MCP tool gained `brief` and the CLI did not, for the fourth time today. The CLI now has the flag,
and a cross-check compares every parameter the schema advertises against what the code accepts, so
the next divergence fails a test instead of a user's command.

## [0.12.27] - 2026-11-09

Closes 10 of the 11 items from the 2026-11-09 DSH-side test. W-10 is not done — see the end.

### Fixed — `query_effective` was missing exactly where it mattered

W-02. The field was added on the normal path and skipped by the two early returns for "nothing
matched". A zero-result answer is when a caller most needs to see the expression that produced it,
and it was the one case that came back `null`. All exit paths carry it now, including the cache, so a
repeated search answers the same question the first one did.

### Changed — `detail` and `detail_many` respect `include_abstract`, default false

W-01. `search` had the switch; `detail` did not, so every lookup returned an abstract — 60–80% of the
response, about 1200 characters on CNKI and 1000 on WoS. Both now default to hiding it, and both
accept `fields`. A batch of twelve abstracts is roughly 14 KB, and that is the call where the cost
multiplies.

`url`, `quota_charged` and `quota_remaining` survive any projection: they keep a record followable and
tell the caller what the call cost.

### Fixed — `wensu browser start` no longer reports success for a browser that died

W-03. Chromium exits with code 21 when it cannot write to its `--user-data-dir`, which is what a
sandboxed or read-only mount produces. The command printed "started, pid N" and the bridge never
appeared. It now waits 1.5 s and, if the process is gone, exits non-zero with the code and the likely
cause.

### Fixed — the bridge message distinguishes "not running" from "extension dropped"

W-04. The text always said "click the extension icon", which is not possible when no browser is
running — the most common case. `status.bridge.last_seen` carries the last timestamp in `host.log`,
and the remediation is chosen from whether it exists.

### Added — `status(brief=true)` and `search(count_only=true)`

W-08 and W-09. The full status payload is about 500 tokens, mostly three static blocks; `brief`
returns five fields in about 45. `count_only` drops `records` and keeps what explains the number, so
testing whether an expression parses no longer costs a page of context.

### Added — `export` writes markdown and csv

W-07. The citation formats exist to be imported. When the goal is a document a person reads, a caller
had to assemble it by hand, which meant pulling every abstract back through the context first. `csv`
uses the standard module rather than joining with commas — titles contain commas and quotes, and a
hand-rolled writer corrupts exactly the records worth keeping.

### Docs — two claims in the skill were wrong

W-05 and W-06, both mine:

- The skill said `detail` serves from cache after a search. **True for WoS only.** CNKI list rows carry
  no abstract, so nothing is cached and every detail costs 1. The price table said both.
- The skill recommended `SU='x' and 年='2026'` for year filtering **without ever testing it**. It
  returns 0. Removed, with a note that the CNKI form is unverified while `PY=(…)` on WoS is not.

W-11: the bundle README said "four tools" (there are five), and the skill names only `site_sort` and
`local_sort` now, mentioning the old aliases once.

### Why this round had so many findings

Two reasons, both mine. Several fixes were applied to the surface I happened to be looking at — 
`query_effective` on the happy path, `fields` on `search` but not `detail` — so the feature existed
and was invisible exactly where it was needed. And two skill paragraphs were written from intent
rather than measurement: the cache claim and the CNKI year form. A document that states something
untested is worse than a document that stays silent, because it is read as evidence.

### Not done — W-10

Index-based references (`detail_many(indices: [1, 5])`) need a "last search result" kept somewhere,
and rules for when it is stale, missing, or from another channel. That is a feature with its own
failure modes, not a fix. Left out rather than half-built.

## [0.12.26] - 2026-11-09

### Fixed — BUG-01 was not actually fixed in 0.12.21

The probe added in 0.12.21 checks that a host **answers a ping**, and it does. But the host can die
between that check and the call, and it did: a live test showed quota 239 -> 238 followed by

o live native host found. The reservation had already been taken inside planner.run by the time
the failure surfaced, so the guard bought nothing on the one path it was written for.

Two changes:

- **PolicyEngine.refund()** gives back a reservation for a request that never left the machine.
  Narrow on purpose: only ridge.* failures refund. A request that timed out mid-flight is **not**
  refunded, because the site may well have seen it — refunding those would make the counter lie in
  the other direction, which is worse for the site this limit exists to protect.
- **ridge_probe is injectable** on ScholarService and resolved lazily, so a test with a stub
  adapter is not blocked by a real probe and monkeypatch.setattr(BridgeAdapter, "probe", …) still
  takes effect. Binding the reference at construction time froze it.

### Verified

`
bridge_ready = False
wensu search "x"  → no live native host found: the browser extension is not connected
quota 238 -> 238                                            ← charged nothing
`

The earlier claim of a fix came from a test that only asserted the error *code*; it never checked the
counter. That is the difference between "the guard raises" and "the guard saves you money".
## [0.12.25] - 2026-11-09

### Fixed — detail_many existed but the schema did not list it

The tool was added in 0.12.24 and works, but schemas/tools.json still described four tools. An MCP
client builds its tool list from that file, so a tool missing from it is a tool the agent cannot see —
the code may as well not have been written.

### Docs — a scenario table, so the right tool is not a guess

Five tools with clear names still require knowing which name answers the question in front of you.
The skill now opens with a table from scenario to tool, with the cost of each:

| 你要做的事 | 用 | 花费 |
|---|---|---|
| 找文献 | search | 3 / 4 |
| 只要命中数 | search + limit:1, fields:["title"] | 3 / 4, tiny response |
| 看某篇完整信息 | detail（URL 或 DOI） | 0 cached / 1 live |
| 看多篇 | detail_many | same per record |
| 存成文件 | xport + out_path | 0 |
| 查额度 / 桥接 | status | 0 |

It also names the three savings that are easiest to miss: ields projection, local_sort being
free where site_sort is not, and xport(out_path) costing neither quota nor context.
## [0.12.24] - 2026-11-09

Closes the remaining items from the 2026-11-09 incident report: BUG-04 through BUG-12, and DOC-01
through DOC-03. BUG-01/02/03 shipped in 0.12.21.

### Fixed — an empty page now says why it is empty

When the year filter removed every record on the page, `empty_reason` stayed `null` and
`dropped_year` was the only clue. The report records a caller concluding "this topic has no
literature" when the years simply did not match. It now reports
`empty_reason: "all_dropped_by_year"`.

### Fixed — `detail` reports what it spent

`detail` spends quota exactly like `search` but returned no quota field at all, so tracking a budget
required a `status` call after every lookup. Both `quota_charged` and `quota_remaining` are now on
every `detail` response.

### Fixed — CNKI detail records carry `fetched_at`

A CNKI detail had `fetched_at: null` while a Web of Science one had a timestamp, so a caller could
not tell a fresh record from a cached one. Stamped at parse time.

### Added — `query_effective` on every search

A bare keyword becomes `SU='…'` on CNKI, and Web of Science appends `AND PY=(2022-2026)` when no year
range is given. **The query that ran is often not the query the caller sent**, and a zero-result
answer gave no way to see that. Both channels now expose the expression they will actually type, and
it is echoed in the response.

```json
"query_effective": "(TS=(ionic AND actuator)) AND PY=(2022-2026)"
```

### Added — `export` can write to disk

```json
{"out_path": "D:\\out\\results.ris", "format": "ris"}
→ {"written": true, "path": "…", "records": 143, "bytes": 284113}
```

The text is deliberately omitted from that response: pulling 143 records through the context just to
save them is the expensive way to do it. `include_abstract` defaults to false here as well — an `AB`
field roughly quadruples an RIS entry.

### Added — `detail_many`

N records, one call, sequential on purpose (the policy layer serialises network actions anyway).
A failure on one record does not abandon the rest:
`{"results": [{"url", "ok", "record"|"error"}], "ok_count", "failed_count"}`.

### Changed — `fields` rejects unknown keys

A caller that wrote `["titel", "year"]` used to receive records with no title and no complaint. The
error names the bad key and lists the available ones. The schema now enumerates them too, so the
typo is caught before the call.

### Changed — the schema lists two sort parameters, not four

`site_sort` and `local_sort` are what the tool documents now. `sort` and `sort_by` still work as
aliases for existing callers, but they are no longer in the parameter list — the four names side by
side required the reader to work out which pair mattered.

### Docs — BUG-04, DOC-01, DOC-02, DOC-03

- **`total` is the site's count before local filtering.** The `search` docstring now spells out that
  `total: 363` with nine records does not mean "363 papers that year", and names the two ways to get
  a year-accurate answer.
- **`bridge.json` is under `host\`, not the root.** The native-host README said otherwise, and now
  also lists the log path.
- **There is no `run-host.cmd`.** The launcher compiles to `scholar-host.exe` and the browser starts
  that through the registry.
- **A version gap between extension and MCP is usually fine.** `docs/compatibility.md` now has a
  table: compare `bridge_protocol`, not `version`. The extension only needs upgrading when the
  protocol number changes.

## [0.12.23] - 2026-11-09

### Added — adopt an existing profile instead of rebuilding it

Most people who already have a working setup built it by hand: a dedicated profile on another drive,
already signed in, extension already loaded. `wensu setup --browser edge` would create a *new*
profile and leave that working setup untouched but unused, and the user reinstalling an extension
they already had.

```powershell
wensu browser adopt "E:\LiteratureEdgeProfile"
```

```
adopted : E:\LiteratureEdgeProfile
recorded: C:\Users\…\scholar-search\browser.json
next    : wensu browser start
```

The path is validated as a real Chromium `--user-data-dir` (a `Local State` file and a `Default`
directory beside it) before being recorded, because starting a browser on an arbitrary path is worse
than refusing.

### Added — the extension id is derived, not typed

`wensu browser adopt` now reads `manifest.json` from the extension directory and derives the id
Chromium will assign. Our manifest ships a `key`, so the id is the same on every machine:

```
gmaimbocfjkolcpljeekjcomakipoaph
```

That is the id the native-messaging manifest already lists in `allowed_origins`, which is what lets
`wensu browser start` load the unpacked extension via `--load-extension` and have the native host
accept it — no reinstall, on any machine.

### Note

The adopted profile in the report's case had 10 extensions and none of them was wensu's: the user had
been loading it via `--load-extension` rather than installing it. That still works, and now it is
what `browser start` does by default.

## [0.12.22] - 2026-11-09

### Added — wensu now owns and remembers a browser profile

Until this release wensu only knew how to *connect* to a native host. It had no idea which browser
profile that host belonged to, so a user who kept the extension in a dedicated window got
`bridge_ready: false` whenever that window was closed — with nothing in the response explaining why.
The gap was not a bug; the capability had never existed.

**Setup creates the profile and records it:**

```powershell
wensu setup --browser edge
```

```
browser profile: C:\Users\…\scholar-search\profiles\edge
recorded in    : C:\Users\…\scholar-search\browser.json
```

**Starting it always targets that one directory:**

```powershell
wensu browser start    # → msedge.exe --user-data-dir=<recorded profile>
wensu browser show     # → print the record, whether the profile and extension exist
```

`status` gained `browser_profile` (browser, profile dir, whether it exists, extension dir,
`start_with`), so "the extension is not connected" has an answer better than "find the right window
yourself".

The profile lives under `profiles_dir()`, which already existed and was unused — and it is a profile
wensu creates, **never the user's default one**. Touching that would put a research tool's extension
into whatever the user was already browsing with, and a reset would take their sessions with it.

`wensu setup` is now idempotent: if the assets are already in place it says so and continues with the
browser profile, rather than aborting. The point of running setup again is usually the profile.

### Docs — the skill says how to wake the right window

The red line now reads as an instruction rather than only a prohibition: read
`status.browser_profile`, then run `wensu browser start`. That command is the **only** sanctioned way
to start a browser, and it always passes the recorded `--user-data-dir`. Starting `msedge` by name,
touching profiles, or killing processes by image name remain forbidden — that is what destroyed a
user's session and produced nothing.

## [0.12.21] - 2026-11-09

Addresses BUG-01, BUG-02 and BUG-03 from the 2026-11-09 incident report.

### Fixed — a dead bridge no longer costs quota

The quota reservation happens inside `planner.run`, so a missing extension cost **one point per
attempt while being physically unable to succeed**. The report hit this on the very first `search` of
a session, then again on every retry.

`_run` now probes the bridge before anything can reserve a slot and raises
`ActionError(code="bridge.not_ready")` when nothing is listening. Probing is free: it reads the
endpoint file and tries the socket. A test asserts the guard fires before `wait_turn` is reached.

### Added — `status` explains a missing bridge instead of just reporting it

`bridge_ready: false` told a caller nothing about *why*, so an agent had to go read `host.log` and
guess. `status` now carries:

```json
"bridge": {
  "ready": false,
  "endpoint": "…\\host\\bridge.json",
  "log_path": "…\\host\\logs\\host.log",
  "remediation": "Open the browser profile that has the wensu extension installed and click the
                  extension icon to reconnect. Do NOT start, stop, reload or kill the user's
                  browser processes: the extension lives in one profile only, and restarting the
                  browser brings up a different one with no bridge."
}
```

The same `remediation` is attached to any `bridge.*` error payload, and those are now marked
`retryable: true` — the previous `retryable: false` alongside `quota_charged: 1` invited a retry
that could only fail again.

### Docs — the red line that was missing

`skills/scholar-search/SKILL.md` now states, as a hard constraint, that when the bridge is not ready
the **only** permitted action is to ask the user to click the extension icon: no starting, stopping,
reloading or killing browser processes, no touching profiles or the extension directory, no deleting
files under `%LOCALAPPDATA%\scholar-search\` to "reset state".

**This is the incident's root cause.** A caller saw `bridge_ready: false`, read `host.log`, concluded
Edge was "stuck in the background", ran `Stop-Process -Name msedge -Force` and restarted the browser.
The extension lived in one profile; the restart brought up a different one; the bridge came up and
died five seconds later — and the user's browsing session was destroyed for nothing.

## [0.12.20] - 2026-11-09

### Added — `detail` accepts a DOI

```powershell
wensu detail "10.13841/j.cnki.jxsj.2026.11.001"
```

CNKI detail URLs are several hundred characters of encrypted signature — the only
parameter is `v=`, and there is no `filename=` or any other key to extract, so `detail` previously
required that whole string back verbatim (W-12 in the 2026-11-09 review). A DOI is short, stable and
already present in every record.

The DOI is resolved through one search, because the detail page is only reachable by its URL. That is
the honest cost of not demanding the signature string: +3 quota on CNKI, +4 on Web of Science. A URL
that is already cached still costs nothing. The channel is chosen from the DOI namespace
(`j.cnki.` / `d.cnki.` → CNKI, otherwise Web of Science) unless `channel` says otherwise.

The resolution lives in `ScholarService.detail_by_doi`, not in the MCP layer, so the CLI cannot drift
from the tool — that divergence has already cost three fields (`dropped_year`, `filters`, `--field`).

### Verified

```
wensu detail "10.13841/j.cnki.jxsj.2026.11.001"
→ 15.2 s, 4 quota
  title   : 柔性可穿戴腕关节康复手套构型设计与控制策略研究
  source  : 机械设计   year: 2026
  abstract: 198 chars, no trailing ellipsis
```

## [0.12.19] - 2026-11-09

### Fixed — the CLI was missing the parameters the tool gained

`search` gained `fields` and the `site_sort` / `local_sort` names, but only in `server.py`. The CLI
rejected `--field` with exit code 2, which is how this was found — by running the command the
release notes suggested.

The CLI and the MCP tool have now diverged on the same day twice: `dropped_year`, then `filters`,
and now this. Both read the same payload builder; they still declare their own argument lists.

New flags, mirroring the tool:

```
--field NAME        repeatable; keep only that record field (`url` is always kept)
--site-sort ...     same as --sort, named for what it does
--local-sort ...    same as --sort-by, named for what it does
```

### Verified

```
wensu search "离子 柔性 驱动器" --channel cnki --limit 5 --field title --field year --field doi
→ total=128, 5 records, keys: title, year, doi, url, 12.9 s, 3 quota
```

The 128 matches the number the review measured by hand, which is the point: the space-separated
form is what finds them, and the whole-sentence form returns nothing.

## [0.12.18] - 2026-11-09

Addresses W-05, W-06, W-07, W-09, W-11 and W-13 from the 2026-11-09 review.

### Added — capabilities declared per endpoint

`status` used to publish one `channel_capabilities` map. On CNKI it said
`abstract: false`, which is true of a **search row** and false of the **detail page** — so a caller
read it as "CNKI cannot do abstracts" and planned around a limitation that does not exist. There are
now two maps:

```
channel_capabilities.cnki.abstract  = false   (list rows)
detail_capabilities.cnki.abstract   = true    (detail page)
```

### Added — `fields` projection

`search(..., fields=["title","year","doi"])` returns only those keys. `url` is always kept because
`detail` needs it. `include_abstract` on 25 rows is tens of kilobytes; most callers want three
fields.

### Changed — `site_sort` and `local_sort`

The two sort parameters did different things at different costs and had near-identical names. They
now say which is which:

| new name | meaning | cost |
|---|---|---|
| `site_sort` | ask the site to re-sort the whole result set | two extra clicks, quota |
| `local_sort` | re-order the page in hand | free |

`sort` and `sort_by` still work as deprecated aliases with identical meaning, so nothing breaks.

### Docs — the query semantics a caller cannot guess

`skills/scholar-search/SKILL.md` gained the section the review said was missing:

- **CNKI does not do whole-sentence phrases.** `离子柔性驱动器` returns 0; `离子 柔性 驱动器`
  returns 128. Splitting into space-separated words is the first move when a Chinese phrase finds
  nothing — that cost 6 quota to discover.
- **`year_from` / `year_to` filter the current page only.** Wanting this year means `site_sort=date`
  (+2 quota, one page) or putting the year in the expression — not paging through the database.
- **An action price table** per channel per action, so a caller can budget instead of discovering
  the cost by spending it.

### Not done — W-12 (stable record id)

CNKI's detail URL is a several-hundred-character signed query string, so `detail` has to be given the
URL back verbatim. A stable key would fix that, but neither captured page contains `filename=` (the
site's own article key) or any equivalent. Inventing an id from the URL would produce something that
looks stable and is not. Needs a capture that shows where CNKI exposes that key.

## [0.12.17] - 2026-11-09

### Fixed — CNKI `detail` was reading the wrong copies of three fields

Found by running the parser against two captured detail pages, then against a replaced capture that
held the real structure. All three are CNKI detail-page issues (W-08 in the review):

- **The abstract was the preview, not the text.** CNKI ships both in one document:

  ```html
  <input id="abstract_text" value="…完整摘要，多段落，无省略号…">
  <span id="ChDivSummary">…可见预览，几百字，以 ... 结尾…</span>
  ```

  The parser read the span, so every caller received a truncated abstract while the complete one sat
  a few nodes away. The `value` attribute of a hidden input is invisible to `get_text()` — which is
  why it was missed. The input is tried first now; the span remains as a fallback. On the captured
  thesis this changes the abstract from 504 characters ending in `...` to the full multi-paragraph
  text.

- **`source` reported the whole header for a thesis.** Journal pages read
  `机械设计 . 2026 ,43 (11) : 21-26`, and the name was taken as everything before ` . `. A thesis
  header is `东北林业大学 黑龙江省 211工程院校 教育部直属院校` — no separator at all — so the whole
  string came back as the "journal name", and it looked plausible enough to pass.

- **`year` was null on every thesis.** Those pages carry neither a publication-time row nor a
  citation line, but their DOI is shaped `d.cnki.<school>.<year>.<seq>`. The year is taken from there
  as a fallback, and only for the dissertation namespace so a journal DOI cannot override a real
  date.

- **PDF line-break hyphens are joined.** A word split across a line arrives as `驱-动`. Only CJK-CJK
  is joined: `F-P-θ` and `Mo-S-O` keep their hyphens.

### Added — a fixture for dissertations

`tests/fixtures/cnki/detail-thesis.html`, desensitised from a real capture. The repository already
had a journal fixture and no thesis one, which is exactly why the three defects above survived: no
test ever parsed a dissertation page. Three tests now cover them, and the `source` one was
mutation-checked — reverting the fix makes it fail with the symptom a user reported.

## [0.12.16] - 2026-11-09

### Fixed — a BOM in `quota.json` no longer takes the quota down, and `status` stops lying about it

A leading BOM made `json.loads` fail on a file that looked perfectly fine, so the state read as
corrupt. `search` refused with `POLICY_QUOTA_STATE` while `status` reported the full **300** from its
fallback — the same fault producing two opposite answers, with neither response naming the file.

- Reading now uses `utf-8-sig`, which strips the BOM. **A BOM is no longer fatal.**
- A genuinely broken file reports `quota_remaining: null` instead of the full limit.
- `status` gained `quota_state_error` and `quota_state_path`; the quota error itself now states the
  path and the shape it expects, so the fix is obvious without reading source.

### Added — the balance, the price, and whether it was spent

- **`quota_remaining`** on every response, next to `quota_charged`. Having the price without the
  balance forced a `status` call between every planning step.
- **`cache_hit`** on every response, so a free repeat is distinguishable from a charged search.
- **`action_cost`** in `status` — a rough table (search 3/4, page turn 4, site sort 5, local sort 0,
  detail 1 live / 0 cached) so a caller can budget instead of discovering the price by spending it.

### Fixed — `PY=(2026-2026)` is normalised instead of being sent and charged for

Web of Science accepts `PY=(2021-2026)`, `PY=(2026)` and `PY=(2026, 2024)`, but not a range whose
ends are equal. A caller saying "only this year" naturally writes `2026-2026`, spends a search
finding out it is invalid, and loses the quota for a purely local mistake. It is collapsed to
`PY=(2026)` before the expression is typed. Ranges, single years and comma lists are untouched.

## [0.12.15] - 2026-11-09

### Removed — what was left of the CNKI one-box search

`SEARCH["input"]`, `SEARCH["submit"]` and `SEARCH_PAGE` had no caller since the expert form
became the only path, but they were still there. Keeping them implied a second entry point that
no longer exists. The rest of the `SEARCH` dict stays: those selectors parse the result grid,
which the expert form produces the same way.

Note for anyone reading a screenshot: the search box at the top of every CNKI page is the site's
own global navigation. It is present on the expert page too and is not something this tool opens.

### Added — CNKI's zero-result wording

The marker list was missing the one CNKI actually renders:

```html
<div id="briefBox"><p class="no-content">抱歉，暂无数据，请稍后重试。</p></div>
```

Without it a zero-result CNKI search was still surfacing as a timeout. The channel keeps its own
detection — text markers, no URL comparison — deliberately separate from Web of Science, which
compares URLs because it navigates and CNKI does not.

### Fixed — the bundle README still advertised 0.4.4

`packages/dsh-wensu/README.md` carried a version table stuck at bundle 0.4.4 / Python 0.12.9, and
npm renders that file on the package page. It now states that both artefacts share one version
number, which has been true since 0.12.10.

### Verified

```
wos normal  2 records, total 1842,  empty null,     17.9 s
wos zero    0 records, total 0,     empty no_match, 19.5 s
cnki zero   0 records, total 0,     empty no_match, 19.6 s
```

CNKI's normal path was measured earlier in this session (`SU='柔性驱动器'` → 2 records,
total 363, 13 s); the last run used a malformed expression by accident and correctly reported
no match.

## [0.12.14] - 2026-11-09

### Added — a shared document-type vocabulary, and a report of what was filtered

- **`doc_type_unified`** on every record. Each site names the same thing differently:
  CNKI says `journal`, Web of Science says `article` and `proceedings`. Comparing `doc_type`
  across channels was comparing words, not concepts. The channel's own value is kept, and this
  second field maps it onto `article` / `review` / `conference` / `thesis` / `book` /
  `newspaper` / `patent` / `other`.
- **`filters`** on any response where a local filter was requested:

  ```json
  {"year_from": 2026, "year_scope": "page", "min_impact_factor": 5.0,
   "impact_factor_drops_unrated": true, "dropped": {"year": 49}}
  ```

  A caller seeing fewer records than `total` had no way to tell whether the site had fewer,
  the year filter removed them, or an impact-factor threshold did — all three look like a
  shorter list. Only filters that were actually requested appear, so an absent key means
  "not applied" rather than "applied and removed nothing".

### Fixed — the CLI and the MCP tool build the same payload

`cli.py` built its own response dict while `server.py` built another. That has now cost two
fields in a row — `dropped_year`, then `filters` — because each fix went to whichever surface
the test happened to hit. The CLI calls the same function.

### Note

- **Left alone deliberately**: `page_count` (F2) already appears on every response, with `null`
  when the channel has no reliable page number — verified on both channels, so there was nothing
  to change. `export` accepting a result handle (D5) and Web of Science `detail` parsing are new
  features rather than defects, and the second needs a real detail-page capture to build against.

## [0.12.13] - 2026-11-09

### Fixed — CNKI expert search opened the wrong tab

`EXPERT["page"]` was `.../AdvSearch?type=expert`, without `classid`. The advanced-search page has
several tabs and the expert form is selected by `classid=WD0FTY92`; without it the site can land on a
different tab where `textarea.majorSearch` does not exist, and the plan dies waiting for it. The URL
now carries the full parameter set:

```
https://kns.cnki.net/kns8s/AdvSearch?type=expert&classid=WD0FTY92&rlang=CHINESE&language=CHS
```

The expression path itself needed no change: `is_expression()` already recognises every documented
field code (`SU TKA KY TI FT AU FI RP AF FU AB CO RF CLC LY DOI CF`) followed by `=` or `%`, so
`SU='柔性驱动器'` routes to the expert form and a plain keyword still uses the one-box search.

**Not verified live.** The CNKI account on this machine (`db0146`) is held behind a phone
verification prompt — the page reads "手机号认证 … 认证中，请稍后" — so every click on the search
button times out regardless of this change. Both the smart and expert paths fail identically, which
is what pointed at the gate rather than at either plan.

### Changed — CNKI has one search path

The channel used to route a bare keyword to the one-box search and anything with `字段=` to the expert
form. Both end up doing a topic search, so the caller had to pick between two ways to say the same
thing — the same kind of choice that made `sort` / `sort_by` confusing. The one-box path is gone:

| input | sent |
|---|---|
| `柔性驱动器` | `SU='柔性驱动器'` |
| `SU='柔性驱动器'` | unchanged |
| `TI='生态' and KY='生态文明'` | unchanged |

A single quote inside a bare keyword is escaped to `''` so it cannot close the expression early.

### Fixed — CNKI submit deadlines

- **The URL polling added for Web of Science ran on every click**, costing a fixed six seconds and
  pushing ordinary submits past their deadline. CNKI surfaced it as `click failed: bridge.timeout` on
  a click that had in fact worked. Polling now happens only when the caller passes `wait_until`.
- **`CLICK_TIMEOUT_MS = 2_200` sat right on the boundary** of the click's real cost (hover, press,
  release, plus the extension's 2 s race). The submit buttons get their own 5 s budget; other clicks
  keep the short one. 5 s rather than more because the worst-case plan — 50 rows, explicit sort,
  3 pages — must stay inside the kernel's 120 s ceiling; at 12 s it summed to 126.4 s and the budget
  test caught it.

### Verified live

```
柔性驱动器                     → 3 records, total 363,    9.9 s
SU='柔性驱动器'                → cached, identical total,  0.4 s
TI='生态' and KY='生态文明'    → 3 records, total 30876,  8.7 s
```

## [0.12.12] - 2026-11-09

### Fixed — zero results are an answer on Web of Science

A query that matches nothing does not navigate: the tab stays on the query builder, while a real
search lands on `/wos/woscc/summary/...`. The plan reloaded the search form expecting a data stream,
waited ten seconds and failed as `wait_for_failed: timeout` — 3–4 quota spent and nothing the caller
could act on. The reload was itself destroying the evidence: it refreshed the page that had rendered
the "no results" alert.

`click` now waits for the submit control to go disabled and come back (`wait_until: enabled`) — the
site's own "done" signal, which beats every fixed pause tried for this: 1.8–2.6 s was too short for
long expressions and made a good search look empty. `plan_search` is split into
`build_until_click` / `build_after_click`, and the second half only runs when the URL actually
reached a results route.

```
zero result  {"records":[],"total":0,"empty_reason":"no_match"}   15.5s   (was a 29s timeout)
normal       {"records":[3],"total":1184,"empty_reason":null}     17.3s
```

If the button never went busy, the call raises `click.not_started` instead — reporting "no results"
there would hide a failed click behind a confident answer.

### Added — structured errors, cost reporting, channel capabilities

- **Errors** were `{status, error, kind}`: a different shape from a success payload and nothing a
  caller could branch on. They now carry `code`, `channel`, `retryable` and `quota_charged`.
  `retryable` is true only for transport timeouts; a policy refusal or parse failure repeats
  identically, and a risk block must never be retried.
- **`quota_charged`** is reported on success as well, so a caller sees what a search cost instead of
  diffing `status` before and after.
- **`status` reports `channel_capabilities`** from each manifest's `field_support`. CNKI's list rows
  genuinely carry no abstract, keywords, volume or DOI; asking for `include_abstract` there returned
  nulls with no explanation.
- **`source_types`** gained an enum and `sort_by` / `sources_only` gained descriptions, so neither
  needs to be discovered by trial.

### Fixed — the cache no longer goes down with WAL

`PRAGMA journal_mode=WAL` raised `OperationalError` when it could not be set, taking the whole cache
with it. The pragma is best-effort now.

### Chore

- Deleted 4 cached Web of Science rows written while zero-result detection was broken; they stored
  `records: []` for queries that do have results.

## [0.12.11] - 2026-11-09

### Fixed — issues found by real use of the MCP tools

A session used the installed MCP server for a literature review and reported nine defects. Three of
them had produced, or would have produced, a **wrong conclusion**.

- **`detail` refused URLs that `search` had just returned.** `detail(url, channel="cnki")` defaulted
  the channel to CNKI, so passing back a Web of Science URL — exactly what the tool description told
  the caller to do — was rejected by the policy layer that had just allowed it
  (`host 'webofscience.clarivate.cn' is not allowed`). The channel is now inferred from the URL's
  host, against the manifests' own domain lists. This is what broke the documented
  `search → detail` loop, and with it every WoS abstract.
- **An empty page looked like "this topic has no papers".** `year_from` / `year_to` filter only the
  page just fetched, while `total` keeps describing the whole site result set. The caller saw
  `records: []` next to `total: 65` and concluded CNKI had no 2026 papers on the topic — it did; they
  were on another page. Responses now carry `dropped_year`, so "nothing on this page matched" is
  distinguishable from "nothing exists".
- **The `search` description never named the channels.** `channel` was documented as
  `{"type": "string", "default": "cnki"}` with no mention that `webofscience` exists, what query
  syntax it takes, or that an empty result is a normal answer. The docstring now states both values,
  the WoS expression forms, the year-filter caveat, and that `min_impact_factor` lowers recall by
  design.

### Changed

- **The skill covered CNKI only.** `skills/scholar-search/SKILL.md` opened with "Chinese literature
  (CNKI channel)" and listed 17 CNKI fields — nothing about Web of Science. It now documents channel
  selection, WoS expression syntax, the two different year-filter behaviours, impact factors, the
  `sort` / `sort_by` distinction, what `page: null` means, and a table of what each error means and
  whether to retry.

### Investigated, not reproduced

- **Parallel searches killing each other.** Two concurrent CLI searches completed successfully and
  serialised on the existing inter-process lock (37.3 s total, 8 quota — exactly two searches). The
  lock works. The report came from the MCP path, where the cause is more likely tab contention than
  a missing lock. The skill now advises serial calls and one retry, rather than claiming a fix that
  was not made.

### Fixed — the zero-result marker now matches the real wording

The alert is:

```html
<div role="alert" class="search-error error-code light-red-bg">
  <b>Your search found no results</b><br>Check the spelling and/or broaden …
</div>
```

and it is rendered **on the query builder, without navigating**. The previous markers
(`no records found`, `no results found`) never matched, because the real text is "found no results" —
a different word order. An earlier attempt matched the presence of the search form instead, which is
not a signal at all: that form is on every search page, successful ones included. Both are corrected.

The marker is unit-checked against the literal alert text and against a normal results page
(True / False respectively, on both channels).

**Not verified end to end**: in this environment a cookie-consent overlay covers the query builder,
so the click never submits and the alert never appears. The query text does reach the page
(`QUERY TEXT PRESENT: True`) but no alert is rendered (`RED ALERT PRESENT: False`). Detection will
fire on a browser where consent was already given; it could not be proven here. The overlay is also
a real obstacle for the tool itself, worth handling in the plan.

### Fixed — the cache no longer fails to open

`PRAGMA journal_mode=WAL` needs a writable directory and a moment of exclusive access. When it could
not be set, `_connect` raised `sqlite3.OperationalError: unable to open database file` and **the
whole cache became unusable** — a regression from adding WAL. The pragma is now best-effort: the
cache keeps working without it, just with less concurrency.

(Also observed: the project's uv-managed Python 3.12 cannot open the cache file while Python 3.14
can, on the same path. Since the CLI and MCP serve on 3.14 this does not affect users, but it makes
the 3.12 test environment unable to exercise the cache.)

## [0.12.10] - 2026-11-09

### Changed

- **Package metadata now names both channels.** `pyproject.toml`'s `description` still said
  "知网为首个渠道", and that string is what PyPI shows in its header — the previous commit corrected
  the docs but could not reach PyPI, because the long description is baked in at build time and PyPI
  refuses to overwrite a published version.
- The README opened with the same claim; it now lists CNKI and Web of Science with the WoS-specific
  capability (journal impact factors, local filtering and sorting at zero extra requests), and the
  verified-capability table carries the WoS rows measured during this pass.

### Note

- No code changed in this release. It exists so the published metadata matches the software — a
  documentation fix that never reaches the index is only half a fix.

## [0.12.9] - 2026-11-09

### Fixed — the last of the audit's minors

- **The cache ran without WAL.** Two `wensu` processes at once could trip
  "database is locked"; the journal mode is now WAL, so a reader and a writer coexist.
- **Every action re-scanned the channels tree twice.** `discover()` walks `channels/*/manifest.json`
  and each version directory, and it was called on every `_resolve`. Results are cached per registry
  instance now.
- **`site_version` in a manifest was silently ignored** — the directory name overwrote it. That is
  the right precedence (the directory is what gets imported), but the comment said otherwise. Now it
  says what actually happens.
- **A grid with no parsable rows returned an empty page.** If CNKI changes its markup, the parser
  reported "your query matched nothing" instead of "I could not read this page". It raises
  `ParseError` unless the page explicitly reports zero results.
- **`_pick` matched only substrings**, so `卷` could hit `卷期` and take whichever entry came first —
  volume and issue could swap. An exact label wins before the substring fallback.
- **`install.ps1` wrote a BOM into the native-messaging manifest.** Chrome parses that file as JSON;
  Windows PowerShell 5.1's `-Encoding utf8` prepends a BOM, and the host then registers but never
  launches. The manifest is written with `UTF8Encoding($false)` now.

### Not changed

- The audit's `m13` (year filtering runs locally, so `total` describes the site rather than the
  page) was already documented at the call site; no behaviour change was needed.
- `m10` (`detail()` does not consult capabilities) — the capability list marks *optional* features.
  `search` and `detail` are mandatory for every channel, so checking them would be a tautology. The
  list's docstring now says so.

## [0.12.8] - 2026-11-09

### Fixed — the four extension-side minors from the audit

- **A truncated payload looked like a short page.** The idle timer gave up after six windows and
  declared the capture ready anyway, so a half-written JSON line reached the parser, which dropped it
  and reported fewer records. There is no attempt cap now: readiness requires a parseable tail, and
  the plan's own deadline is the only bound. A timeout is a better answer than a quietly short list.
- **An oversized capture was silently truncated.** Past 8 MB the buffer stopped growing and the
  payload was still marked ready. It now sets `data-overflow`, which stops the idle timer from ever
  declaring it complete — same reasoning, and the marker says why.
- **A missing host registration caused a reconnect loop.** Every disconnect retried after 3 s
  regardless of why, so an unregistered host spawned another launcher process each time. The retry
  now backs off to 60 s when the disconnect says "not found / not registered / forbidden".
- **`content_not_ready` had a fixed 1.8 s budget** (6 × 300 ms), which a slow `document_idle`
  injection can exceed — and then the extension was reported broken. It now backs off from 200 ms to
  1 s over eight attempts, covering roughly 6.4 s inside the action budget.

## [0.12.7] - 2026-11-09

### Fixed — audit m1

- **A cooldown withheld data the tool already had.** Readiness was checked *before* the cache lookup,
  so a 24-hour stop also made `search` and `detail` unable to return records that were already
  cached. A cooldown exists to stop traffic to the site; a cache hit sends nothing. The lookup now
  comes first, and the hot path is unchanged when nothing is cached. Covered by a test that trips the
  cooldown and asserts the cached page is still served with no action run.

## [0.12.6] - 2026-11-09

### Fixed — native host robustness (audit m19)

- **A request line had no size limit.** The host read whole lines with `for line in reader`, so one
  client could make it buffer without bound before it ever validated a token. Lines are capped at
  1 MB; a line that reaches the cap before a newline is refused and the connection dropped, because
  the stream is no longer aligned on line boundaries.
- **`shutdown` left a stale endpoint behind.** `os._exit` skips every `finally` block, so
  `bridge.json` survived and the next client dialled a dead port. The endpoint is cleared by hand
  before exiting.

### Not changed, deliberately

- An invalid token still gets a reply. Making it silent would defend against little — anyone in the
  same user session can read the token file (ADR 0012) — while costing every legitimate
  misconfiguration its only diagnostic signal.

## [0.12.5] - 2026-11-09

### Fixed — remaining Python-side minors from the audit

- **`wensu reset --confirm` left no trace.** Lifting a 24-hour safety cooldown is exactly the kind of
  action that needs a record; it now writes a `risk_cleared` line to the audit log.
- **A lock timeout escaped as a traceback.** `interprocess_lock` raised the builtin `TimeoutError`,
  which is not a `ScholarSearchError`, so every caller that catches project errors let it through to
  the user as a stack trace.
- **The locking module contradicted itself.** Its docstring promised a process-local fallback when
  the lock file cannot be opened; the function — and the code — hard-fail instead, because a
  process-local lock silently drops the cross-process boundary that is the module's whole purpose.
  The docstring now says that.

## [0.12.4] - 2026-11-09

### Fixed — the two security-relevant minors from the independent audit

- **An unbound tab skipped the domain check.** `policy.tab_scope` was only applied once a tab had been
  bound by a `goto`, so the first non-`goto` action ran against whatever page happened to be active —
  including one outside the channel's allowlist. The check now runs on every action.
- **A failed click was reported as success.** The navigation race caught *every* exception and
  answered `ok: true, navigation_expected: true`, so a click that never found its element, or was
  refused by policy, looked like a click that started a navigation. Only the three
  "content script went away" wordings and the deadline are treated that way now; everything else
  surfaces. When the race does fire there is no risk snapshot — a missing `captcha_visible` is read
  as "no opinion", which is the honest answer for a document that was replaced mid-click.

## [0.12.3] - 2026-11-09

### Cleanup — minor items from the independent audit

- **Dead code removed**: `ExecutionPolicy` (defined, never instantiated), `ConfigurationError` and
  `SmokeTestFailed` (defined, never raised), and the empty `adapters/cdp` package.
- **Doc drift corrected**: `incidents.md` placed the host runtime in `%TEMP%` when it actually lives
  in `%LOCALAPPDATA%\scholar-search\host` — anyone troubleshooting from that line would search the
  wrong tree; `reference-parity.md` claimed 143 tests; `cli.py` still described itself as "P0 only
  wires the command surface"; `bridge-protocol.md` was missing the `by`, `mode` and `reload`
  parameters that other sections already describe.

## [0.12.2] - 2026-11-09

### Docs

- **ADR 0012** writes down the bridge threat model that the audit's C5 was judged against: who sits
  inside the trust boundary, what a compromised renderer can and cannot do through this bridge, and
  why the three obvious mitigations were rejected. C5 becomes an accepted risk with a stated
  reopening condition, not an open defect.

## [0.12.1] - 2026-11-08

### Fixed — fourth batch from the independent audit (tests that could not fail)

- **The WoS fixture had no `runQuerySearch` block**, so "the primary batch is ordered first" was a
  no-op: inverting the rule left every test green. The fixture now ends with a primary block carrying
  a distinctive title, and a test asserts it comes out first. **Verified by mutation**: flipping the
  ordering rule makes that test fail.
- **The two validation layers were never compared in a test.** A plan the kernel accepts and the
  host rejects could only be discovered by reloading the extension and spending quota. A contract
  test now builds every channel's plan and runs it through both layers, the same comparison
  `scripts/check-plan.py` performs before a deploy.

## [0.12.0] - 2026-11-08

### Fixed — third batch from the independent audit (CNKI parsers)

- **Conference papers were exported as journal articles.** A volume/issue/pages citation in the top
  line unconditionally set `doc_type = "journal"`, overwriting the page's own 文献类型：会议. Since
  `doc_type` drives RIS `TY` and EndNote `%0`, a conference paper came out as `JOUR`. The citation is
  now evidence only when no type word was found.
- **Titles carried spaces that the detail page did not have.** The list joins text nodes with a
  space so highlighted words became `TiO 2`; the same record's detail page (no highlight) reads
  `TiO2`. Text nodes are now joined with no separator.
- **Counts were off by orders of magnitude.** Stripping every non-digit turned `1.2万` into `12`
  (should be 12000) and `12.5` into `125`. Decimals and the 万/千 multipliers are parsed now.
- **Years could violate the record schema.** `0000-00-00` produced `year=0` against a
  `minimum: 1800` contract; the year is range-checked and returns `None` otherwise.
- **URLs could be malformed or insecure.** `http://` links were accepted as-is, and
  `//kns.cnki.net/x` became a double-host URL. Protocol-relative links complete their scheme now,
  and anything that is not https is dropped rather than stored as a usable link.

## [0.11.1] - 2026-11-08

### Fixed — second batch from the independent audit

- **Risk markers fired on ordinary article titles.** `access denied` and `sign in` were matched as
  substrings, so reading a paper titled "Access Denied: 论跨境数据主权" tripped a 24-hour cooldown.
  A title now has to *be* a gate title: exact match, or that prefix followed by a short, non-CJK site
  suffix. The bare `sso` URL marker — which matched the DOI `10.1002/essoar.10501234` — is replaced
  by `//sso.`, `.sso.` and `/sso/`, the shapes an SSO hop actually takes.
- **A failed page turn was invisible.** The kernel overwrote whatever page the channel reported with
  the page the caller asked for, and both channels back-filled `query.page` when the site showed no
  marker. Together they guaranteed `page=2` came back as `2` even when the site had served page 1.
  Channels now report only what they observed (`None` when the page carries no marker), and the
  kernel no longer overwrites it.
- **`min_impact_factor` was silently ignored by CNKI.** A caller who asked for high-impact venues got
  unfiltered results with no way to notice. Web of Science now declares a `journal_metrics`
  capability and the kernel refuses that filter on channels lacking it, instead of quietly dropping
  it.

## [0.11.0] - 2026-11-08

### Fixed — first batch from an independent audit

- **The CLI wrote GBK.** On a zh-CN Windows console `wensu search ... > out.json` produced GBK
  bytes, which every consumer reads as UTF-8 — `ensure_ascii=False` made it matter. `stdout` and
  `stderr` are reconfigured to UTF-8 at startup.
- **`export` rejected every Web of Science record.** `record_from_payload` did not know
  `impact_factor`, so the MCP export tool failed with `unknown record fields` for any record
  carrying one. The field is now accepted as a float, with a round-trip test.
- **`narrow_domains` failed open.** When none of the requested domains fell inside the trusted
  scope, it returned the *whole* trusted list — handing the caller a wider scope than it asked
  for. It now returns the empty set, which the host turns into a rejection.
- **`goto` could exceed its own action budget.** The extension's worst case was 8 + 3 + 1.5 = 12.5 s
  against a 10 s budget, so the kernel gave up while the action went on to succeed. The extension's
  worst case is now 5 + 1 + 1.5 = 7.5 s, back inside the budget without moving the plan's ceiling.
- **Out-of-range CLI arguments printed a traceback.** `--limit 100` or `--page 9` raised a bare
  `ValueError`; they now print one line and exit 2.

### Added

- **`scripts/check-plan.py`** — feeds every channel's plan through *both* validation layers and
  refuses to pass if either rejects it. `docs/incidents.md` has promised this gate since the
  two-layer drift first bit; it exists now.

### Note

- Also from the audit but **not** in this batch, deliberately: the `page` back-fill that hides a
  failed page turn (3 places), the risk markers that fire on ordinary titles (`Access Denied`,
  `sign in`, and the bare substring `sso`), and `min_impact_factor` being silently ignored by CNKI.
  Each needs a design decision, not just a patch.

## [0.10.5] - 2026-11-08

### Changed

- Typing is a single assignment again (paste, not type). Per-character typing spent two seconds on a
  40-character query for no safety gain — nobody types a boolean expression by hand. Focus and the
  20–60 ms gap before `change` are kept. The `type` timeout returns to 4 s.

### Fixed

- The capture declared itself ready the moment `pending` reached zero, but the lazy loader sends three
  batches in sequence with quiet gaps between them. A 95-result query was read as a single truncated
  line, and the reader saw an empty page while the browser showed "95 results". Readiness is now
  decided by the idle timer after a quiet window (2 s), never by the last `finish()`.
- `CAPTURE_WAIT_MS` was shorter than capture.js's own standby budget (6 × 1.5 s), so a payload whose
  tail took a while to parse was declared complete only after the plan had already given up on it.

## [0.10.2] - 2026-11-08

### Changed — interaction realism

- **Clicks aim at a random point inside the target**, not its centre, and emit
  `pointerover`/`pointerenter`/`mouseover`/`mouseenter`/`pointermove`/`mousemove` before
  `pointerdown`+`mousedown`, `pointerup`+`mouseup`, with uneven pauses. Every event carries real
  coordinates — they were `0,0` before, which no real pointer produces.
- **Typing is per-character**: focus, then for each character a `keydown`/`input`/`keyup` triple with
  a 20–70 ms pause. Setting `.value` in one shot was the single most obvious automation tell in a
  form. `type` therefore gets 8 s instead of 3.5 s.
- The reload is a real one (`navigation.type === "reload"`, as with F5) and passes `bypassCache`,
  because a plain `reload()` restores from cache and **issues no network request at all** — the
  capture stayed empty without it.

### Note

- Synthetic events are never `isTrusted`; the browser reserves that for real input. Faking it needs
  the `debugger` permission, whose always-on banner is more conspicuous than the synthetic events.

## [0.9.9] - 2026-11-08

### Changed

- The WoS plan **reloads** the result page instead of scrolling down it. Measured on the live site: a
  reload answers with all 50 records through three `runQueryGetRecordsStream` batches and never
  issues `runQuerySearch` at all. A default search now takes **23 s** (11 actions, 4 metered) where
  scrolling took 86 s (19 actions, 3 metered); a second page takes 25 s.

### Added

- `goto` accepts `reload: true`, the F5 a user would press. It carries no URL, so the kernel allows it
  and the **extension checks the live tab URL** against the same allowlist before reloading.

### Fixed

- `pageMeta` awaited `chrome.tabs.sendMessage` with no deadline; that call never settles while a
  frame is being replaced, so `goto` hung until the bridge gave up. It now races a 3 s timeout.
- `waitComplete` treated a slow page as a hard error, and a timed-out socket stayed in use, so **one
  slow navigation broke every later action** (`cannot read from timed out object`). Waiting is no
  longer fatal, and a failed call drops the connection so the next one dials again.
- A reply left over from the previous action is dropped instead of failing the request with
  `bridge reply id does not match`.
- Verb parameter validation lives in two layers (`core/params.py` and `adapters/bridge/policy.py`),
  as does goto's domain check. Both layers now understand `reload`; before, the kernel accepted what
  the host rejected.

### Known

- Reloading the **extension** leaves already-open tabs without a content script — every action then
  returns `content_not_ready` until the page is refreshed. Automated runs are unaffected because the
  plan navigates; manual probing is not.

## [0.9.1] - 2026-11-08

### Added

- `goto` accepts `reload: true` — the same thing the user gets from F5. Worth having for an
  unresponsive page, but it does **not** help with the WoS result list: a reloaded page still sends
  only its first batch, and the lazy endpoint fires on scroll, not on load.

### Fixed

- A ~100 KB lazy batch arrives as one long JSON line split across chunks, and the idle timer used to
  declare the payload complete in a gap between two of them. It now keeps waiting while the tail is
  unparseable, up to six windows. Measured before: one scroll gave 20 records plus a truncated line.
  Measured after: one scroll gives 40, two give 50, and nothing is truncated.

### Known

- Reloading a tab can make the bridge report `bridge reply id does not match the request` — the
  navigation discards a pending reply while the host is still pairing ids. The action after a reload
  may need a retry.

## [0.9.0] - 2026-11-08

### Added

- Page turns work: `page=2` returns records 51–100 as 50 distinct records. A turn waits for its
  first batch, then scrolls twice to refill — the same way page one fills itself.

### Fixed

- A batch already in flight when a new page started appended its 20 records to the *new* page.
  `capture.js` now stamps every request with a generation and drops chunks and completions from
  older ones, so a page holds only its own records.
- Ordering by arrival scrambled a page whenever a lazy batch beat the primary query. The parser now
  puts the primary batch first and keeps payload order inside each batch.
- Scrolling before the first batch arrived did nothing, because a list that has not rendered has
  nothing to scroll.

### Changed

- Page one skips its own scroll rounds when a later page is requested — that record set is about to
  be replaced anyway — which keeps a two-page call at 97–99 s of the 120 s budget.
- The channel caps `page` at 2; a third turn would not fit.

### Known

- Two adjacent pages can share one record: page 2's third entry was also page 1's first. That is the
  site's paging behaviour, not a capture fault, but callers deduplicating across pages should expect
  it.

## [0.8.6] - 2026-11-08

### Fixed

- `scroll` with a relative `by` was rejected with `policy.params` even after the kernel learned the
  parameter: `ALLOWED_KEYS["scroll"]` still listed only `to`, and the native host validates the same
  schema from its own copy of the package. Both now accept `by`.

### Note

- A verb's parameter schema reaches the native host only after the host restarts (reloading the
  extension does that). The kernel and the host can otherwise disagree — the kernel accepts and the
  extension refuses.

## [0.8.5] - 2026-11-08

### Changed

- Scrolling is no longer a single jump to the bottom. `scroll` now accepts a relative `by` offset,
  and the plan walks down in two uneven steps with randomised distances and pauses. A `scrollTo`
  landing on the same pixel every run is a fingerprint; a reader's scroll is not.

## [0.8.4] - 2026-11-08

### Fixed

- The capture could be declared complete mid-stream, leaving a half-written JSON line. The idle
  timer now checks that the last line actually parses before setting the ready marker, and grants
  the stream a second window when it does not. The parser also drops unparseable lines instead of
  failing the whole page, so one cut tail costs nothing.

## [0.8.3] - 2026-11-08

### Fixed

- The plan then timed out on `wait_for ... state: hidden`. That phase assumed the ready marker would
  be cleared when a fresh request starts, but the first batch usually lands during the pause after
  the click, so the marker was already set and the wait had nothing to wait out. The phase is gone:
  each stage now waits for the payload once, and the pause after a click is what gives a new request
  time to begin. Worst-case budget improves to 101–104 s of 120 s.

## [0.8.2] - 2026-11-08

### Fixed

- The CLI search path could die with `A listener indicated an asynchronous response by returning
  true, but the message channel closed`. A click that starts a navigation tears down the content
  script, and the `wait_for` right behind it hit that gap — timing that the MCP path happened to
  miss. Both ends are fixed: the bridge now retries that wording together with the other
  "new document not ready" errors, and the plan pauses after submitting before asking the page
  anything.

## [0.8.1] - 2026-11-08

### Added

- `wensu search` and `wensu detail`: the same service the MCP server exposes, callable straight from
  the shell. `--channel`, `--limit`, `--page`, `--year-from/--year-to`, `--abstract`, `--sort-by`,
  `--min-citations`, `--sources-only`, `--min-impact-factor` and `--format json|ris|endnote` all
  work. The cache is on disk, so a record fetched by one process is served to `detail` by another.

### Why

On-demand beats a startup plugin for this channel: it keeps **zero footprint in DSH's boot path**, so
a DSH upgrade can never be blocked by it. Install the MCP bundle only if you want the tools inline.

## [0.8.0] - 2026-11-08

### Added

- Records carry `impact_factor` where the channel has one — Web of Science does, through its `jcr`
  block. Optional in `record.json`, so CNKI stays valid with `null`.

### Changed

- Interaction pacing is slower and more human: 1.2–2.2 s between typing an expression and
  submitting it, 1.6–2.4 s between scroll rounds, 0.7–1.3 s before picking a sort option. The
  worst-case plan still fits the kernel budget on every random draw (110.6–112.5 s of 120 s).

### Fixed

- A query that matches nothing returned a parse error instead of an empty page. The site still sends
  `searchInfo` with a zero count — that is a valid answer, not a broken capture.

### Docs

- `docs/wos-channel.md` gains an interaction and risk audit: what the quota meters versus what is
  actually requested (3 actions, 4–5 requests), how the pacing compares to a human, and which risk
  signals are covered. It also names the one gap: a soft block that only writes "Access Denied" into
  the page body rather than the title.

## [0.7.0] - 2026-11-08

### Added

- `search` accepts `min_impact_factor`, honoured by channels that ship journal metrics. The WoS
  channel joins each record to the `jcr` block by `jcrKey` and drops records whose journal has no
  metric — for "high-impact venues only", unknown is not a pass.
- A filter that matches nothing returns an empty page instead of a parse error: the capture was
  fine, the journals just did not qualify.

### Changed

- `SearchQuery` gains `min_impact_factor` (contract change, ADR 0010).

### Not in this release

- The impact factor is used for filtering only; it is not in `record.json`, which stays
  `additionalProperties: false`. Surfacing the value would be a separate contract change.

## [0.6.3] - 2026-11-08

### Fixed

- The plan scrolled once, which stopped at 40 of 50 records. Measured live: 20 on load, 40 after
  the first scroll, 50 after the second. The plan now waits for the first batch, then scrolls
  twice, and each round waits for the captured payload instead of for "ready to disappear" — on
  the last round the list is already complete and no new request starts, so that phase would time
  out. It also waits for the payload *before* the first scroll: the result list renders before its
  data arrives, and scrolling an empty list triggers no lazy load.

## [0.6.2] - 2026-11-08

### Fixed

- A "50 records per page" setting only fills the first 20 on load; the rest arrive lazily when the
  list is scrolled. Verified live: `scroll` raised the tracked request count from 1 to 2 and pulled
  a `runQueryGetRecordsStream` batch. The plan now waits for the list, scrolls, and waits for the
  follow-up stream before reading.
- `capture.js` cleared the node on **every** tracked response, but the batches arrive sequentially
  (primary query, then scroll-triggered stream), so a 50-row page kept only its last batch of 20.
  The node is now cleared by the primary query alone and later batches are appended.

### Changed

- A page turn and an explicit sort can no longer share one call: together they cost 26 actions and
  exceed the kernel's 120 s plan budget. Either works on its own.

## [0.6.1] - 2026-11-08

### Fixed

- The detail cache was seeded for every record that had a URL, including CNKI result rows, which
  carry no abstract by design. A later `detail(url)` for such a row answered from the cache with
  strictly less than the detail page would have — a silent regression that would have looked like
  "CNKI stopped returning abstracts". Only records that already carry their own abstract are
  seeded now.

## [0.6.0] - 2026-11-08

### Added

- `search` accepts four local post-processing options: `include_abstract`, `sort_by`
  (`citations` / `year`), `min_citations` and `sources_only`. They run on records that were already
  parsed, so ordering and filtering cost no browser action — unlike the site's own sort control,
  which is two clicks.
- `search` seeds the detail cache for every parsed record before filtering, so a later
  `detail(url)` answers from disk. Pulling those abstracts one by one would have been fifty
  requests for data already in hand.

### Changed

- **`search` omits abstracts by default.** A fifty-record page costs roughly 20k tokens with
  abstracts and about 3k without. Pass `include_abstract: true` for the previous behaviour; the
  full record is also always reachable through `detail(url)`.
- `min_citations` keeps records whose citation count is unknown: some result views (WoS
  `runQuerySearch`) ship no count at all, and dropping them would read as "no such papers".

## [0.5.2] - 2026-11-08

### Fixed

- Every WoS navigation failed with `policy.domain`. The native host keeps its own domain allowlist
  (`TRUSTED_DOMAINS`) and narrows each request to that scope, never widening it; it still listed
  only CNKI, so a WoS request narrowed to the empty set and the extension refused the URL. The WoS
  hosts are in that list now. A new channel has to add itself there *and* in its manifest — the
  host copy is the layer an extension is not allowed to widen.

## [0.5.1] - 2026-11-08

### Fixed

- The first request after a machine reboot could sleep for hours while holding the plan lock.
  `quota.json` stores the last request as a monotonic timestamp, and a monotonic clock restarts
  from zero on reboot; the interval calculation read that restart as "we are early" and waited out
  the previous uptime (observed: five hours, with the plan lock held, so every later call stalled
  behind it). A backwards clock now counts as a full interval already served.

## [0.5.0] - 2026-11-08

### Added

- `webofscience` channel (site version 2026.11): searches Web of Science through the user's own
  browser session and returns the same `Record` shape as CNKI — title, authors, source,
  year/volume/issue/pages, DOI, abstract, Keywords Plus, citation count and institution.
  Selected with `channel: "webofscience"`; `query` accepts either a keyword phrase or a full WoS
  expression such as `TS=(actuator) AND PY=(2021-2026)`.
- `extension/content/capture.js`: a MAIN-world content script that mirrors the page's own result
  stream. It issues no request of its own — the 50 records, abstracts included, arrive with the
  normal search and cost zero extra network actions.
- Year handling for WoS: an omitted range defaults to the last five years and is written into the
  expression, so no filter widget is ever clicked.

### Changed

- `read_text` accepts an optional `mode` (`inner` by default, `text` for raw node text), and the
  kernel now hands a captured `text` payload to a channel parser as well as an `html` one.
- Risk markers cover SSO redirects (`sso`, `shibboleth`, `carsi`) and English gate titles
  (`session expired`, `sign in`, `access denied`); the title check is case-insensitive.
- The extension manifest gains the WoS host permission and a `world: "MAIN"` capture script.

### Docs

- ADR 0007 (WoS capture strategy) and ADR 0008 (the three kernel hooks it requires).
- `docs/wos-channel.md` is now a decision record rather than a list of open questions.

### Not in this release

- WoS `detail` and `journal` are not implemented; `keywords` comes from Keywords Plus only
  (about half of the records carry it).

## [0.4.2] - 2026-10-24

### Docs

- The status line and the upgrade steps now match the setup flow: upgrades use
  `pip install --upgrade wensu` and `wensu setup --force`, instead of hand-running
  `assets` and `install.ps1`.

## [0.4.1] - 2026-10-24

### Added

- `wensu setup`: copies the browser assets next to the runtime home, registers the native
  messaging host, and prints the extension directory. A fresh install is now one command plus
  the one-time "load unpacked" step, instead of three commands.
- `wensu setup --target DIR` / `--no-host` for a custom location or an assets-only run.

### Fixed

- Source checkouts can run `wensu setup` and `wensu assets` directly: the asset lookup falls
  back to the repository layout when the wheel's packaged copy is absent.

### Docs

- README, the DSH bundle README and the market index now state the browser-side step, so users
  are not surprised by `bridge_ready: false` after installing the plugin.

## [0.4.0] - 2026-10-23

### Changed

- Distribution renamed from `scholar-search` to `wensu` (文溯). The old name is taken on PyPI
  by an unrelated package, so `pip install scholar-search` would install someone else's code.
- The command is now `wensu`; `scholar-search` remains as a compatibility alias, so MCP client
  configs written before this release keep working.
- The Python module (`scholar_search`), the runtime directory
  (`%LOCALAPPDATA%\scholar-search`) and `SCHOLAR_SEARCH_HOME` are unchanged, so upgrades keep
  quota, cooldown and audit state.
- Repository and documentation links point at `github.com/hui-xu-ai/wensu`.

## [0.3.19] - 2026-10-21

### Changed

- `NOTICE` now carries a full provenance statement: which public MIT projects informed this
  one, exactly what was taken (selector strings, step order, known pitfalls) and what was
  not (every file, module and function here is written for this project), plus the
  licence of each runtime and development dependency.
- `README` gained a 来源与致谢 section; `docs/reference-parity.md` no longer calls the
  selectors "照搬" and points at the provenance statement.

### Fixed

- Test fixtures are now fully desensitised: recorded abstracts, author names,
  affiliations and keyword labels are replaced with synthetic placeholders, and author
  mail addresses are removed. Only markup, class names and public bibliographic facts
  (title, journal, volume/issue/pages, DOI) remain.

### Docs

- Version numbers in examples are placeholders now (`<版本>`) instead of a pinned release,
  so they cannot go stale; only the status section names a real version.
- The proxy trap (TLS interception making CNKI show a certificate error) is documented in
  the README, the Codex guide, the install skill and the incident ledger, including the
  detail that a command-line fetch bypasses the system proxy and therefore proves nothing.

## [0.3.18] - 2026-10-21

### Fixed

- `core/locking.py` branches on `sys.platform` instead of `os.name`. mypy only narrows
  the former, so on Linux the Windows branch was analysed too: `msvcrt` came back
  untyped and the `fcntl` ignores were reported as unused. That made the
  `ubuntu-latest` jobs fail at the type-check step while Windows passed. Verified with
  both `mypy src` and `mypy --platform linux src`.

## [0.3.17] - 2026-10-21

### Fixed

- The sort-correction plan's pause now uses the shared reply margin. It still carried the
  old `sleep 1500 / timeout 2000` pair that 0.3.15 proved too tight for a throttled tab;
  the plan only runs when the grid comes back ascending, so it had not failed yet.

### Changed

- `settle()` in `channels/cnki/v2026_10/plan_search.py` is public so the sort-correction
  plan reuses it instead of hand-rolling its own pause budget.

### Docs

- User guide, architecture, upgrade/operations, CNKI-maintenance, browser setup, Zotero
  (manual import only) and publishing notes; plus a `scholar-install` skill that walks an
  agent through a fresh install.

## [0.3.16] - 2026-10-21

### Fixed

- Document types are normalised in one place. The result grid labels some rows
  「中文图书」/「外文期刊」, and the old fallback (`token.casefold()`) pushed that raw
  Chinese string into `doc_type`, where the export mapping could not recognise it and
  RIS fell back to `GEN` — a book exported as generic. `parse_search` and
  `parse_detail` now share `channels/cnki/v2026_10/doc_types.py`, which strips language
  prefixes, wrappers （《期刊》, （网络首发）） and the 文献类型 label, and returns
  `None` for a type it cannot map so the export renders generic with a note instead of a
  meaningless value.

## [0.3.15] - 2026-10-21

### Fixed

- Pause deadlines now carry a 2 s reply margin. In live use the 2.5 s settle after a
  navigation answered at 3004 ms against a 3000 ms deadline and the plan died with
  `bridge.timeout`. The cause is timer alignment: while the CNKI window is not the
  active window the browser buckets timers to whole seconds, so any pause can answer up
  to ~1 s late. Every `sleep` action now uses `_settle()`, which adds the margin.
- Worst-case plan budget rebalanced to stay inside the 120 s cap that the extra margins
  would have broken: `read_html` 6 s → 4 s, grid/filter waits 8 s → 6 s, query-box and
  result-grid waits 12 s → 10 s. Observed live latency is unchanged (navigation ~1.9 s,
  grid ~2.1 s), so each deadline still sits 3–5× above it. ADR 0005 limits, the verb
  set and the plan shape are untouched.

## [0.3.14] - 2026-10-21

### Fixed

- Search and expert-search plans wait 2.5 s after the opening navigation before looking
  for the query box. CNKI's first load performs a second hop that replaced the content
  script, so `type` could fail with `bridge.timeout` even though `goto` and `wait_for`
  had succeeded. Behaviour, limits and verbs are unchanged; the plan now has one extra
  `sleep` action.

## [0.3.13] - 2026-10-21

### Changed

- Daily network-action ceiling raised from 200 to 300 per ADR 0005. All other limits
  are unchanged: 3 s floor plus jitter, concurrency 1, page 1–3, `limit` 1–50,
  40 actions / 120 s per plan, 24 h cooldown.
- Documented captcha handling: the plan stops and returns `blocked`; the user solves
  the challenge in the browser, then explicitly clears the cooldown with
  `scholar-search reset --confirm`. No automatic retry.

## [0.3.12] - 2026-10-21

### Fixed

- Returned `page` now reflects the page that was actually requested, even when the
  site's own pager marker lags behind the AJAX turn.
- The 50-per-page switch waits 2.5 s for the grid to rebuild; a fast read returned the
  previous 20-row page.
- CNKI dissertation DOIs (`/d.cnki.`) mark a detail record as `thesis` when no explicit
  type field is present; live verification now exports `THES`/`Thesis`.

## [0.3.11] - 2026-10-21

### Changed

- **Human-like pacing** The kernel now adds 0–1.2 s of random jitter on top of the
  3 s floor, with a ~10% chance of a 2–4 s pause. Clicks scroll the target into view and
  fire mousedown/mouseup/click with random 40–90 ms gaps; navigation gets a 0.5–1.5 s
  dwell before the first action. Typing stays paste-like, as a person would paste a query.
- **Sort correction** The grid is read after sorting; if the active column is `ASC`, the
  channel returns one corrective plan and the service runs it, instead of blind
  double-clicks. This keeps the requested descending order without relying on timing.

## [0.3.10] - 2026-10-21

### Fixed

- **Date sort direction** The CNKI grid already opens on publication-time DESC;
  the product clicked the tab once, which toggled it to ASC. `sort=date` now sends no
  sort clicks. Citation sort clicks twice (first activation ASC, second DESC).
- **Pagination settle** A first page turn now waits 800 ms after the grid renders; the
  turn was previously clicked while the grid was still binding and was ignored.
- **Content-script readiness** The background retries `sendMessage` for up to ~1.8 s
  when a navigation outruns `document_idle` injection, instead of failing with
  "Receiving end does not exist".
- Read timeout trimmed to 7 s so every query/page/sort/page-size combination stays
  within the 120 s plan budget.

## [0.3.9] - 2026-10-21

### Fixed

- **Click delivery** 0.3.8 deferred the click with setTimeout, which Chrome throttles
  in background tabs; pagination then executed after the read and stayed on page 1.
  The content script clicks synchronously again, and the background now treats a
  click whose reply is lost to navigation as started (the plan's wait_for verifies
  the page). Non-click verbs still require a real reply.

## [0.3.8] - 2026-10-21

### Fixed

- **Click reply loss** A submit/search click can start a navigation that destroys the
  content-script context before its reply is sent, producing `bridge.timeout` at the
  kernel. The content script now replies first and activates the element on the next
  task; the plan still verifies the result with its following `wait_for`.

## [0.3.7] - 2026-10-21

### Fixed

- **Live detail type** Online-first journal detail pages have no volume/issue, so the
  previous metadata-only rule left `doc_type` empty and exported `GEN`. The journal
  header link text (`查看该刊数据库收录来源`) is now used as article-level structural
  evidence, so real online-first details export `JOUR`. Verified live on a CNKI
  journal article (abstract, DOI, keywords, 0 risk).

## [0.3.6] - 2026-10-21

### Fixed

- Read detail document types from complete type values or explicitly labelled
  type fields. Funding, subjects and source names cannot supply a document type;
  explicit online-first journal metadata is retained.
- Reserve two seconds between CNKI search content waits and their outer action
  deadlines, allowing a timeout response and its risk snapshot to reach the kernel.
- Add synthetic online-first metadata fixtures and regression coverage for all
  supported query/page/sort/page-size combinations. Live verification is pending.
- Accept wrapped (`《期刊》`) and status-suffixed (`期刊（网络首发）`) type values, and
  scan `.top-first` with the same exact-value rule, so explicit types are not lost
  to page decoration. Body/recommendation text still cannot supply a type.

## [0.3.5] - 2026-10-21

### Fixed

- **R034-01** Detail document type is read only from the article metadata header
  (`.top-first`, `.doc-top`, `.top-tip`, `li.top-space`). Body text, abstracts and
  related recommendations can no longer re-type the current article, and a concrete
  volume/issue/pages citation always wins as journal evidence. Fixtures added for
  "related thesis recommendation" and "conference notice in body".

## [0.3.4] - 2026-10-21

### Fixed

- **CSP** Clicks on CNKI's `<a href="javascript:void(0);">` pagination/sort links are
  cancelled at the default-action stage, so the page CSP no longer blocks a
  `javascript:` navigation while the site's own click handlers still run. Plain
  links and inputs are clicked as before.

## [0.3.3] - 2026-10-21

### Fixed

- **F01** The result table's `td.data` document type is parsed into `Record.doc_type`;
  RIS/EndNote now map journal/thesis/conference/newspaper/book/patent/standard/yearbook,
  and an unknown or missing type renders as `GEN` / `Generic` (plus a RIS note) instead of
  being silently exported as a journal article. `schemas/record.json` and the export
  validator include the new field; mixed-type fixture added.
- **F02** Detail readiness now waits for the article-level selector
  `.wx-tit h1, #ChDivSummary` instead of a bare `h1` (the login modal), and the inner wait
  is 8s so it finishes inside the 15s action budget and can still return the final page
  or risk snapshot.

## [0.3.2] - 2026-10-21

### Fixed

- **V01** A quota reservation that cannot be persisted now blocks that same action;
  an existing but corrupt/unreadable quota file is a hard error instead of being read
  as zero usage.
- **V02** If the cross-process plan lock cannot be created, the plan is refused; the
  process-local fallback was removed.
- **V03** The shared cooldown is re-checked after the interval sleep and immediately
  before the browser action.
- **V04** A cross-domain login redirect is still refused, but the reply keeps the final
  URL and risk metadata so the kernel can persist the 24h cooldown.
- **V05** Extension permissions and content injection are scoped to the enabled
  channel (`https://*.cnki.net/*`) and top frame only.

### Changed

- Skills now match the real contract: one page per call, no fabricated export
  `count`, and a single, consistent rule against batch detail loops.
- `install.ps1` falls back to `python`/`python3` on PATH and records the runtime HOME
  in `runtime-home.txt`; the host reads it at startup.
- Launcher logs move under `SCHOLAR_SEARCH_HOME/host/logs`.
- `scholar-search assets` refuses to overwrite existing directories without `--force`.
- Added `docs/integration/codex.md`.

## [0.3.1] - 2026-10-21

Risk follow-up fixes from `independent-20261021-02-risk-followup`.

### Fixed

- **R01** Every content-script reply (success, timeout, missing element, exception)
  carries the risk snapshot; `click`/`type`/`select` refuse to run while a captcha or
  login gate is already visible; the background no longer drops `data` on failures.
- **R02** A whole plan holds a cross-process lock; the quota slot is reserved
  atomically in `wait_turn` (interval check + increment + persist), so two processes
  cannot both spend the last request.
- **R03** The shared cooldown is re-checked before every action, not only at plan start.
- **R04** Actions stay bound to the tab opened by the plan's `goto`; a plan cannot
  drift to whatever tab the user activates. The extension keeps a configured host
  scope, and the host only lets a request narrow its trusted startup scope, never
  replace it.
- **R05** If quota persistence fails, the next `wait_turn` fails closed instead of
  trusting the stale on-disk counter.
- **R06** `HTTP 429` (status or error text) is now a terminal `rate_limited` signal.

### Compatibility

Two assertions in the earlier audit conflict with the newer risk scope and now fail
by design: the host no longer accepts an arbitrary `example.org` manifest without a
trusted scope, and the extension no longer navigates to unconfigured hosts.

## [0.3.0] - 2026-10-21

Security and contract hardening from the independent offline audit
(`independent-20261021-01`). Breaking: several invalid inputs that were quietly
accepted now fail loudly.

### Fixed

- **F01** Navigation replies carry the final URL and current title; the adapter
  surfaces a nested `data.url`; HTTP status is collected from the content script
  and `403` reaches the risk guard.
- **F02** Captcha visibility requires an on-screen, non-zero-size element that
  intersects the viewport; every action result carries the risk snapshot.
- **F03** Quota and interval are read and written under an inter-process lock;
  plans are serialized process-wide, so two servers cannot double-spend.
- **F04** The adapter never replays an action after a connection failure.
- **F05** A failed action stops the plan; the service raises `ActionError` and
  never parses or caches the page as a success.
- **F06** The cooldown deadline is latched in memory, so a failed state write
  cannot unblock the process that just detected a risk.
- **F07** Cache hits still respect an active cooldown.
- **F08** Replies are correlated with request ids; a handshake precedes the
  first action; the bridge protocol doc separates TCP JSON from native framing.
- **F09** One closed parameter schema (`core/params.py`) is enforced by kernel
  and host; deadlines above 15s are rejected; frames are capped at 2 MiB on
  write and `read_html` truncates by UTF-8 bytes with a `truncated` flag;
  `wait_for` honours `state=hidden`.
- **F10** Export validates records against the public schema and refuses
  newline/type injection in any field.
- **F11** Malformed search pages and non-article detail pages raise `ParseError`
  instead of being cached as empty/valid results.
- **F12** Detail URL authorisation uses the parsed path prefix.
- **F13** Old site-version directories stay discoverable; selecting a version
  no longer requires every directory to match the channel manifest.
- **F14** Domain authority moves to the selected manifest (sent per request);
  the host no longer hard-codes CNKI and the extension accepts any https host.
- **F15** Host runtime files live under `SCHOLAR_SEARCH_HOME/host`; the
  installer labels that directory low-integrity writable.
- **F16** HTTP Host check compares the whole hostname, not a prefix.
- **F17** Wheel ships native-host, extension and schemas as package assets;
  `scholar-search assets --target DIR` extracts them; sdist includes browser
  sources and fixtures.
- **F18** `schemas/tools.json` matches the four live tools; README, NOTICE and
  package metadata are on 0.3.0.
- **F19** `status.bridge_ready` probes a live host instead of checking for a file.
- **F20** `ruff format --check` passes and `.pre-commit-config.yaml` is present.


## [0.2.6] - 2026-10-21

### Added

- `sort=date` and `sort=citation` drive the result grid's sort tabs (`#orderList`).
  A relevance reset precedes the target click, because the grid remembers the previous
  direction and a bare click would toggle unpredictably.
- Live-verified: `limit=50, sort=date` returns 50 rows in strict descending date order
  (2026 → 2024), 12 pages, no verification prompt.

## [0.2.5] - 2026-10-21

### Added

- Field detection for expert search now covers every documented code: `SU`, `TKA`, `KY`,
  `TI`, `FT`, `AU`, `FI`, `RP`, `AF`, `FU`, `AB`, `CO`, `RF`, `CLC`, `LY`, `DOI`, `CF`.
  Unknown `XX=` / `XX%` codes also route to the expert page instead of the one-box search.
- Skill documentation now lists the official field table and operators (`and`/`*`,
  `or`/`+`, `not`/`-`, `%` for author matching).
- Live-verified: `TI='IPMC' and AU % '王'` returns 43 hits across 2014–2026.

## [0.2.4] - 2026-10-21

### Added

- `limit > 20` switches the result grid to 50 rows per page (12 pages for the 595-hit
  `IPMC` query); with the 3-page cap a single call returns up to ~150 records.
- `year_from` / `year_to` are applied client-side to the fetched records. The site's own
  year control is never touched; `total` still reports the site's full result count.

### Fixed

- Search URLs carry a per-call nonce so every call starts from the grid's default state;
  previously a repeat navigation could inherit the previous page size and break the switch.

## [0.2.3] - 2026-10-21

### Fixed

- Account-gate detection now requires a **visible** login modal; the previous body-text match
  flagged CNKI's always-present login panel and produced a false cooldown.
- Native hosts register themselves under `hosts/` and answer a ping; the adapter picks a live
  host instead of trusting a single stale `bridge.json`.
- Removed host “retirement”: it caused reconnect churn where each new host killed the previous one.
- Verified after the fix: one read-only search returned 595 hits, no cooldown.

## [0.2.2] - 2026-10-21

### Changed

- Year filters are disabled: the result-page year control (`#btnFilterYear`) triggered an
  account verification gate (“手机号认证”) during a live test. `year_from` / `year_to`
  now fail with an explicit error instead of touching that control.
- Risk guard detects account verification gates via the content script (`auth_required`)
  and reports `login_redirect`, so a gate cannot be mistaken for an empty result page.
- Incident recorded in `docs/incidents.md`; 62 tests.

## [0.2.1] - 2026-10-21

### Fixed

- Detail parser reads volume/issue/pages from the `.top-first` citation line
  (`力学学报 . 2022 ,54 (01) : 184-195`); verified by fixture replay and a live MCP call.
- Added `tests/fixtures/cnki_detail_print_2026_10.html` and a regression test (59 tests).

## [0.2.0] - 2026-10-20

### Added

- Kernel pipeline: registry, policy, risk guard, planner, audit, cache, service.
- Channel registry with site-version selection and manifest/version consistency checks.
- Policy engine: verb/domain allowlists, 3s hard floor, daily quota, plan size and duration limits.
- Risk guard: captcha/verify/403/login detection, 24h persisted cooldown, manual reset only.
- JSONL audit log (structural facts only, no page content or credentials).
- SQLite response cache with TTL.
- RIS and EndNote text export.
- Fixture adapter for offline replay.
- 40 unit and contract tests covering policy, risk, planner, cache, registry, service, export.
- Native bridge: 4-byte-length JSON framing, request correlation, timeout handling.
- Bridge policy: nine-verb allowlist, https-only, CNKI host allowlist, sleep bound.
- Loopback TCP channel between host and MCP server, per-run random token.
- MV3 extension skeleton (background relay + nine generic DOM verbs).
- `native-host/install.ps1` registers the host for Edge and Chrome under HKCU.
- 47 tests including bridge framing, policy and TCP round-trip.
- CNKI channel v2026.10: search plan, result-table parser, detail plan and parser.
- MCP server with four tools: search, detail, export, status.
- stdio transport and loopback HTTP transport with bearer token and Host check.
- `scholar-search status` reports channels, cooldown, quota and bridge readiness.
- 51 tests; ruff and mypy --strict clean.
- Verified selectors against a live CNKI page (595 hits, 20 rows); trimmed fixture in `tests/fixtures`.
- Search plan now drives the search box (goto → type → click → wait → read) instead of a static URL.
- Native host launcher is a compiled .exe: Edge refuses to start `.cmd` hosts.
- Host runtime files (endpoint, log) moved to the per-user temp directory, because browsers launch native hosts at low integrity and `AppData\Local` is not writable there.
- Single-instance check and per-connection replies fix duplicate-host races.
- 52 tests.
- Expert search: field expressions (`SU=`, `TI=`, `KY=`, `AU=` …) go through `AdvSearch?type=expert`.
- Pagination: `page=2..3` clicks `#PageNext` and waits for the next result batch.
- Search limit is honoured (`limit` was previously ignored).
- Cache keys include the package version so parser changes do not serve stale hits.
- Plan budget stays under 120s via per-action timeouts; page capped at 3.
- 56 tests; live-verified: keyword 595 hits, expert expression 57 hits, page 2 distinct.
- Detail parser rewritten for the 2026 layout: `.wx-tit h1`, `h3.author`, `li.top-space` rows; strips author affiliation marks and “附视频” suffixes.
- Risk guard now flags verification interstitials by document title (“安全验证”), after an expired detail URL served one.
- Native host runs one process per browser connection: the previous single-instance check deadlocked reconnects.
- Skills: `scholar-search`, `scholar-detail`, `scholar-export`.
- Docs: reference parity table and incident log.
- 58 tests; release workflow on version tags.

## [0.1.0] - 2026-10-20

### Added

- Project skeleton: microkernel layout, channel plugin directory, adapters, transports.
- Core contracts (`core/contracts.py`): action vocabulary, plan, record, channel and adapter protocols.
- Hard limits in `core/config.py` (3s floor, 1 concurrency, 3 pages per call, 200 per day, 24h cooldown).
- Error hierarchy with risk-blocked payload.
- ADRs 0001-0004: microkernel, read-only, native bridge, risk stop.
- JSON schemas for records and MCP tools.
- CNKI channel manifest (site version 2026.10), implementation pending.












