# Channel contract

A channel is a site knowledge pack. It answers two questions: *which actions
produce a page*, and *how to read that page*. Everything else is the kernel's
job.

## Layout

```
channels/<name>/
├── manifest.json
└── <site_version>/
    ├── __init__.py        # exports the Channel implementation
    ├── selectors.py       # selectors, isolated on purpose
    └── *.py
```

`<site_version>` is the site layout generation, not the project version. When
the target site changes layout, add a new directory; keep the old one for
rollback.

## Manifest

```json
{
  "channel": "cnki",
  "site_version": "2026.10",
  "schema_version": 1,
  "min_core": "1.0.0",
  "domains": ["kns.cnki.net", "www.cnki.net"],
  "verbs": ["goto", "wait_for", "type", "click", "select", "read_html", "read_text", "scroll", "sleep"],
  "detail_url_prefixes": ["/kcms2/article/abstract"],
  "capabilities": ["search", "detail", "journal", "export"]
}
```

Rules enforced by `ChannelManifest.validate()`:

- every verb must exist in the kernel vocabulary;
- domains are bare host names (no scheme, no path, no wildcard);
- capabilities are a subset of `search | detail | journal | export`;
- `detail_url_prefixes` restricts which URLs `detail` may open.

## Methods

```python
plan_search(query: SearchQuery) -> Plan
parse_search(html: str, *, query: SearchQuery) -> SearchPage
parse_export(text: str, *, query: SearchQuery) -> SearchPage   # 可选
plan_detail(url: str) -> Plan
parse_detail(html: str, *, url: str) -> Record
plan_journal(*, issn: str, year: int, issue: str) -> Plan
parse_journal(html, *, issn, year, issue) -> SearchPage
```

**`parse_export` is optional and changes how the plan's result is read.** A channel that
defines it must produce a file: its plan ends with a `click` carrying `expect_download`, the
extension reports the completed download path in `data.download`, and the kernel reads that
file and passes its text here instead of looking for an `html`/`text` action payload. The
kernel decides by attribute presence, so a channel without it is unaffected
([ADR 0016](adr/0016-wos-global-site-bibtex.md)).

When such a channel reports no file, that is a failure (`export.missing`), not an empty
result — reading an empty page instead would report "no records found" for a run that never
obtained any.

Plans contain only the nine allowed verbs. `goto` URLs must satisfy the
manifest's domains; `detail` URLs must additionally match a declared prefix.

## Contract tests

A channel is not loadable until `tests/contract/` passes:

1. manifest validates;
2. verbs ⊆ kernel vocabulary and contain no download/eval/file marker;
3. declared domains are bare hosts;
4. every plan produced for a sample query stays inside the domain allowlist;
5. parsers return records that validate against `schemas/record.json`;
6. parsers raise `ParseError` (not `KeyError`) on malformed input.

## Compatibility

`min_core` is a semver range checked by the registry. If two versions declare
compatible ranges, the highest `site_version` wins; a pin in configuration can
force an older one for rollback.
