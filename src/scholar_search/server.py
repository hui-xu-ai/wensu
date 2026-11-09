"""MCP server: four stable tools over the service facade."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from .core.contracts import SearchQuery
from .core.errors import (
    ActionError,
    BridgeError,
    BridgeTimeout,
    ChannelError,
    ChannelNotFound,
    ParseError,
    PolicyError,
    RiskBlocked,
    ScholarSearchError,
)
from .core.export import record_from_payload
from .core.service import ScholarService


def _filters_payload(page: Any, query: SearchQuery) -> dict[str, Any] | None:
    """What was filtered, and how much it removed.

    A caller seeing fewer records than `total` had no way to tell whether the site
    had fewer, the year filter removed them, or an impact-factor threshold did —
    all three look like a smaller list. Only filters that were actually requested
    appear, so an absent key means "not applied" rather than "applied and empty".
    """

    applied: dict[str, Any] = {}
    dropped: dict[str, int] = {}
    if query.year_from is not None or query.year_to is not None:
        applied["year_from"] = query.year_from
        applied["year_to"] = query.year_to
        # Local, not site-side: it removed records from this page only.
        applied["year_scope"] = "page"
        if page.dropped_year:
            dropped["year"] = page.dropped_year
    if query.min_citations is not None:
        applied["min_citations"] = query.min_citations
    if query.min_impact_factor is not None:
        applied["min_impact_factor"] = query.min_impact_factor
        # Channels drop journals with no metric, which lowers recall by design.
        applied["impact_factor_drops_unrated"] = True
    if query.sort_by != "none":
        applied["sort_by"] = query.sort_by
    if query.sources_only:
        applied["sources_only"] = list(query.sources_only)
    if not applied:
        return None
    if dropped:
        applied["dropped"] = dropped
    return applied


# Never dropped by a projection. `url` is what `detail` needs to follow a record;
# the quota pair is what tells the caller what the call cost. Projecting them away
# would answer "here are your three fields" and silently hide both the next step and
# the price of the one just taken.
_PROJECTION_ALWAYS = frozenset({"url", "quota_charged", "quota_remaining"})


def _project(records: list[dict[str, Any]], fields: list[str] | None) -> list[dict[str, Any]]:
    """Keep only the requested fields, always keeping enough to identify a record.

    `include_abstract` on 25 rows is tens of kilobytes, and most callers want a
    title, a year and a DOI. Projection is applied after serialisation so the
    derived `doc_type_unified` can be requested like any other field.

    An unknown key raises instead of being ignored: a caller that asked for
    `["titel", "year"]` and received an empty record would have no way to notice the
    typo, and the empty result looks exactly like a channel with no metadata.
    """

    if not fields:
        return records
    wanted = {name.strip() for name in fields if name.strip()}
    if not wanted:
        return records
    available = set(records[0]) if records else set()
    unknown = wanted - available
    if unknown:
        raise ValueError(
            f"unknown field(s): {', '.join(sorted(unknown))}. "
            f"available: {', '.join(sorted(available))}"
        )
    kept = wanted | _PROJECTION_ALWAYS
    return [{k: v for k, v in record.items() if k in kept} for record in records]


def _page_payload(page: Any, query: SearchQuery | None = None,
                  fields: list[str] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "records": _project([record.to_dict() for record in page.records], fields),
        "total": page.total,
        "page": page.page,
        "page_count": page.page_count,
        # Non-zero with empty records means the local year filter removed
        # everything on this page — not that the topic has no papers that year.
        "dropped_year": page.dropped_year,
        # "no_match" means the channel proved the query matched nothing. Without it
        # an empty page is indistinguishable from a failed capture.
        "empty_reason": page.empty_reason,
        # True means nothing was spent: the answer came from the cache.
        "cache_hit": page.cache_hit,
        # The expression that actually reached the site, when it differs from the
        # query the caller typed. Absent when the channel does not reshape queries.
        "query_effective": page.query_effective,
    }
    if query is not None:
        applied = _filters_payload(page, query)
        if applied is not None:
            payload["filters"] = applied
    return payload


def _error_code(error: Exception) -> str:
    """A stable code a caller can branch on, independent of the message wording."""

    if isinstance(error, RiskBlocked):
        return "RISK_BLOCKED"
    if isinstance(error, PolicyError):
        return f"POLICY_{(error.rule or 'rule').upper().replace('.', '_')}"
    if isinstance(error, BridgeTimeout):
        return "BRIDGE_TIMEOUT"
    if isinstance(error, BridgeError):
        return "BRIDGE_ERROR"
    if isinstance(error, ParseError):
        return "PARSE_ERROR"
    if isinstance(error, ActionError):
        return f"ACTION_{(error.code or 'failed').upper().replace('.', '_')}"
    if isinstance(error, ChannelNotFound):
        return "CHANNEL_NOT_FOUND"
    if isinstance(error, ChannelError):
        return "CHANNEL_ERROR"
    return "ERROR"


def _retryable(error: Exception) -> bool:
    """Whether repeating the same call could plausibly succeed.

    Transport timeouts can: the page was slow, not wrong. Policy refusals and parse
    failures cannot: the same request produces the same refusal. A risk block is the
    one case where retrying is actively harmful.
    """

    if isinstance(error, RiskBlocked):
        return False
    return isinstance(error, (BridgeTimeout, BridgeError))


def _payload(
    error: Exception, *, channel: str | None = None, quota_charged: int = 0
) -> dict[str, Any]:
    if isinstance(error, RiskBlocked):
        payload: dict[str, Any] = dict(error.to_payload())
        payload["code"] = "RISK_BLOCKED"
        payload["retryable"] = False
        payload["quota_charged"] = quota_charged
        return payload
    payload = {
        "status": "error",
        "code": _error_code(error),
        "message": str(error),
        "kind": type(error).__name__,
        "channel": channel,
        "retryable": _retryable(error),
        "quota_charged": quota_charged,
    }
    # A caller that cannot act on an error will improvise. When the bridge is the
    # problem, say what the one permitted reaction is — an agent that was left to
    # guess once killed the user's browser.
    action_error = error if isinstance(error, ActionError) else None
    if action_error is not None and (action_error.code or "").startswith("bridge."):
        payload["remediation"] = ScholarService.BRIDGE_REMEDIATION
        payload["retryable"] = True
    return payload


def _quota(service: ScholarService) -> int | None:
    # Brief: this runs twice per search, and the full payload is mostly constants.
    value = service.status(brief=True).get("quota_remaining")
    return value if isinstance(value, int) else None


def build_server(service: ScholarService) -> FastMCP:
    mcp = FastMCP("wensu")

    @mcp.tool()
    def search(
        query: str,
        channel: str = "cnki",
        sort: Literal["relevance", "date", "citation"] = "relevance",
        page: int = 1,
        year_from: int | None = None,
        year_to: int | None = None,
        source_types: list[str] | None = None,
        limit: int = 20,
        include_abstract: bool = False,
        sort_by: Literal["none", "citations", "year"] = "none",
        min_citations: int | None = None,
        sources_only: list[str] | None = None,
        min_impact_factor: float | None = None,
        site_sort: Literal["relevance", "date", "citation"] | None = None,
        local_sort: Literal["none", "citations", "year"] | None = None,
        fields: list[str] | None = None,
        count_only: bool = False,
    ) -> dict[str, Any]:
        """Search a channel for bibliographic records. Read-only.

        channel: "cnki" (default; Chinese literature, Chinese queries) or
        "webofscience" (English literature; also accepts a Web of Science expression
        such as TS=(ionic AND actuator) AND PY=(2021-2026) — with no year range the
        last five years are applied inside the expression).

        Returns a shortlist by default: abstracts are omitted unless
        include_abstract is true, and sort_by / min_citations / sources_only filter
        locally without any browser action. For the full record call detail(url) —
        after a search it is served from the cache, not the site, and detail infers
        the channel from the URL.

        An empty records list is a normal answer, not a failure: read `total` and
        `dropped_year` before concluding that a topic has no papers.

        **`total` is the site's count for the query, before any local filter.** With
        a year range applied, `total: 363` alongside nine records does NOT mean
        "363 papers in that year" — it means the site matched 363 and this page lost
        11 of its 20 to the year filter. `filters.year_scope: "page"` says so
        explicitly, and `filters.dropped.year` gives the count. To get a year-accurate
        total, put the year in the query (`PY=(2026)` on Web of Science,
        `SU='x' and 年='2026'` on CNKI) or use `site_sort=date` and read the newest
        page. `empty_reason: "all_dropped_by_year"` is the case where the whole page
        was filtered away.

        min_impact_factor is honoured by channels that ship journal metrics
        (currently webofscience); records whose journal has no metric are dropped,
        which lowers recall by design.

        Two parameters sort and they are not interchangeable:

        * `site_sort` (`relevance` / `date` / `citation`) asks the site to re-sort.
          That is two extra clicks and costs quota.
        * `local_sort` (`none` / `citations` / `year`) re-orders the page already in
          hand: free, no browser action, no quota.

        The older names `sort` and `sort_by` still work and mean the same thing; the
        new names say which one is which.

        `fields` projects each record to the listed keys (plus `url`, which `detail`
        needs). `include_abstract` on 25 rows is tens of kilobytes; most callers want
        a title, a year and a DOI.

        `count_only` drops `records` entirely and returns the count plus the
        diagnostics that explain it. Testing whether an expression parses and matches
        anything should not cost a full page of context: the recorded advice was
        `limit: 1, fields: ["title"]`, which still returns a record.
        """

        # The explicit names win; the older ones remain as aliases.
        effective_site_sort = site_sort if site_sort is not None else sort
        effective_local_sort = local_sort if local_sort is not None else sort_by

        before = _quota(service)
        request = SearchQuery(
            text=query,
            channel=channel,
            sort=effective_site_sort,
            page=page,
            year_from=year_from,
            year_to=year_to,
            source_types=tuple(source_types or ()),
            limit=limit,
            include_abstract=include_abstract,
            sort_by=effective_local_sort,
            min_citations=min_citations,
            sources_only=tuple(sources_only or ()),
            min_impact_factor=min_impact_factor,
            )
        try:
            result_page = service.search(request)
        except (RiskBlocked, ScholarSearchError) as error:
            after = _quota(service)
            charged = (before - after) if before is not None and after is not None else 0
            return _payload(error, channel=channel, quota_charged=max(0, charged))
        payload = _page_payload(result_page, request, fields)
        after = _quota(service)
        spent = max(0, before - after) if before is not None and after is not None else 0
        payload["quota_charged"] = spent
        # The balance, not just the price. Without it a caller has to insert a
        # `status` call between every planning step to know whether it can afford
        # the next one.
        payload["quota_remaining"] = after
        if count_only:
            # Keep what explains the number: total alone cannot say whether the
            # expression failed, matched nothing, or was filtered away.
            explained = _page_payload(result_page, request)
            keep = ("total", "query_effective", "empty_reason", "dropped_year",
                    "filters", "cache_hit", "quota_charged", "quota_remaining")
            for key in keep:
                if key in explained:
                    payload[key] = explained[key]
            payload["records"] = []
        return payload

    @mcp.tool()
    def detail(
        url: str,
        channel: str | None = None,
        include_abstract: bool = False,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Fetch full metadata for one record.

        `url` may be either the URL `search` returned, or a bare DOI such as
        `10.13841/j.cnki.jxsj.2026.11.001`. CNKI detail URLs are several hundred
        characters of encrypted signature — this one has no parameters but `v=` —
        so passing them back verbatim is easy to truncate. A DOI is short, stable and
        already in every record.

        **`include_abstract` defaults to false**, matching `search`: a CNKI abstract
        runs about 1200 characters and a WoS one about 1000, which is most of what a
        detail response weighs. A caller that wants the volume, issue, pages and DOI
        should not pay for text it will not read. `fields` projects the rest, and
        always keeps `url` so the record stays followable.

        A DOI costs one extra search to resolve into a URL, because that is the only
        way to reach the detail page. A URL that is already cached costs nothing.

        `channel` is optional: it is inferred from the URL's host, or from the DOI
        prefix. Pass it only to override that inference.
        """

        identifier = url.strip()
        is_doi = identifier.lower().startswith("10.") and "/" in identifier

        before = _quota(service)
        try:
            result: dict[str, Any]
            if is_doi:
                result = service.detail_by_doi(identifier, channel=channel).to_dict()
            else:
                resolved = channel or service.channel_for_url(identifier)
                if resolved is None:
                    return {
                        "status": "error",
                        "code": "UNKNOWN_CHANNEL",
                        "message": f"no channel claims the host of {identifier!r}",
                        "channel": None,
                        "retryable": False,
                        "quota_charged": 0,
                    }
                result = service.detail(identifier, channel=resolved).to_dict()
        except (RiskBlocked, ScholarSearchError) as error:
            after = _quota(service)
            charged = (before - after) if before is not None and after is not None else 0
            return _payload(error, channel=channel, quota_charged=max(0, charged))
        # `detail` spends quota exactly like `search` does, but used to return no
        # quota field at all — so a caller tracking its budget had to insert a
        # `status` call after every lookup to find out what it had just spent.
        after = _quota(service)
        result["quota_charged"] = (
            max(0, before - after) if before is not None and after is not None else 0
        )
        result["quota_remaining"] = after
        if not include_abstract:
            result["abstract"] = None
        if fields:
            result = _project([result], fields)[0]
        return result

    @mcp.tool()
    def detail_many(
        urls: list[str],
        channel: str | None = None,
        include_abstract: bool = False,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Fetch several records in one call.

        Each lookup costs the same as `detail` and they run in sequence on purpose:
        the policy layer serialises network actions anyway, so firing them in
        parallel would only queue them while each held a timeout budget.

        `include_abstract` and `fields` behave as in `detail`. A batch of twelve
        abstracts is roughly 14 KB, so the default is off here too — this is the call
        that most needs it, since the cost multiplies by the batch size.

        A failure on one record does not abandon the rest — the response is
        `{"results": [{"url", "ok", "record"|"error"}], "ok_count", "failed_count"}`,
        so a caller can retry just the ones that failed.
        """

        results: list[dict[str, Any]] = []
        for url in urls:
            try:
                record = detail(url, channel, include_abstract, fields)
            except (RiskBlocked, ScholarSearchError) as error:
                results.append({"url": url, "ok": False, "error": _payload(error)})
                continue
            if record.get("status") == "error":
                results.append({"url": url, "ok": False, "error": record})
            else:
                results.append({"url": url, "ok": True, "record": record})

        return {
            "results": results,
            "ok_count": sum(1 for item in results if item["ok"]),
            "failed_count": sum(1 for item in results if not item["ok"]),
        }

    @mcp.tool()
    def export(
        records: list[dict[str, Any]],
        format: Literal["ris", "endnote", "markdown", "csv"] = "ris",
        out_path: str | None = None,
        include_abstract: bool = False,
    ) -> dict[str, Any]:
        """Render records as RIS or EndNote text.

        With `out_path`, the text is written there and **not** returned: a caller
        that wants 143 records on disk should not have to pull them through its
        context to do it. Without it, the text comes back inline as before.

        `include_abstract` defaults to false here even though the records may carry
        one. An `AB` field roughly quadruples an RIS entry, and an export is usually
        for a reference manager, which fetches abstracts on its own.
        """

        try:
            typed = [record_from_payload(item) for item in records]
            if not include_abstract:
                typed = [replace(record, abstract=None) for record in typed]
            text = service.export(typed, fmt=format)
            if out_path:
                target = Path(out_path).expanduser()
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
                # The body is deliberately omitted: it is on disk, and returning it
                # anyway would defeat the point of writing it there.
                return {
                    "written": True,
                    "path": str(target.resolve()),
                    "format": format,
                    "records": len(typed),
                    "bytes": len(text.encode("utf-8")),
                    "include_abstract": include_abstract,
                }
            return {"format": format, "text": text, "records": len(typed)}
        except (RiskBlocked, ScholarSearchError, TypeError, ValueError, OSError) as error:
            return _payload(error if isinstance(error, Exception) else ValueError("bad record"))

    @mcp.tool()
    def status(brief: bool = False) -> dict[str, Any]:
        """Session state: channels, cooldown, quota, bridge readiness.

        `brief` returns only `version`, `bridge_ready`, `bridge_last_seen`,
        `quota_remaining` and `cooldown_until`. The full payload is about 500 tokens,
        more than a search, and three of its blocks — `channel_capabilities`,
        `detail_capabilities`, `action_cost` — are static. Poll `brief` while planning
        and read the full answer once.
        """

        return service.status(brief=brief)

    return mcp
