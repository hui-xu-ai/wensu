# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/).

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












