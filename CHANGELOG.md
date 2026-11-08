# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/).

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












