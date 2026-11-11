# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/).

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












