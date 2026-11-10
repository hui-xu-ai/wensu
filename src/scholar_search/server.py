"""MCP server: four stable tools over the service facade."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from . import __version__
from .core.contracts import MAX_LIMIT, MAX_PAGE, MIN_PAGE, Record, SearchQuery
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
from .core.service import ScholarService, normalise_doi


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
        # How the year bound acted, per channel. Web of Science writes it into the
        # expression (`query_effective` shows `PY=…`), CNKI filters the fetched page.
        # Calling both "page" told a caller that `total` was unfiltered when on WoS it
        # is not.
        applied["year_scope"] = "site_and_page" if _writes_year_into_query(query) else "page"
        if page.dropped_year:
            dropped["year"] = page.dropped_year
    if query.min_citations is not None:
        applied["min_citations"] = query.min_citations
        # Stated explicitly because it changes what the threshold means: a record
        # whose count the source did not report cannot clear a bar it cannot be
        # measured against, so it is dropped rather than kept.
        applied["min_citations_drops_unmeasured"] = True
    if query.min_impact_factor is not None:
        applied["min_impact_factor"] = query.min_impact_factor
        # Channels drop journals with no metric, which lowers recall by design.
        applied["impact_factor_drops_unrated"] = True
    if query.sort_by != "none":
        applied["sort_by"] = query.sort_by
    if query.sources_only:
        applied["sources_only"] = list(query.sources_only)
    if page.dropped_filter:
        dropped["filter"] = page.dropped_filter
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

# Valid projection keys, taken from the Record definition rather than from whatever
# a particular response happened to contain. Deriving them from the result meant a
# zero-result search reported every field as unknown — the one case where a caller
# is most likely to be running a small probe.
_PROJECTION_KEYS = (
    frozenset(Record.__dataclass_fields__) | _PROJECTION_ALWAYS | {"doc_type_unified"}
)


def _writes_year_into_query(query: SearchQuery) -> bool:
    """Whether this channel turns the year bound into part of the expression.

    Only Web of Science does. Kept as a static answer rather than a manifest lookup:
    it is used to word a response field, and a wrong manifest path must not be able to
    break a response.
    """

    return query.channel == "webofscience"


def _has_exclusion(channel: str) -> bool:
    """Whether this channel can leave records out of a query.

    Only Web of Science carries a field for it. Deliberately a static answer rather
    than a manifest lookup: the advice is cosmetic, and a wrong manifest path should
    not be able to break a response.
    """

    return channel == "webofscience"


def _check_fields(fields: list[str] | None) -> None:
    """Reject an impossible projection before anything is spent.

    Called before the search, not after: a typo used to be discovered once the page
    had been fetched, parsed and cached, so a cold request paid for a query whose
    result it then discarded.
    """

    if not fields:
        return
    wanted = {name.strip() for name in fields if name.strip()}
    unknown = wanted - _PROJECTION_KEYS
    if unknown:
        raise ValueError(
            f"unknown field(s): {', '.join(sorted(unknown))}. "
            f"available: {', '.join(sorted(_PROJECTION_KEYS))}"
        )


def _project(records: list[dict[str, Any]], fields: list[str] | None) -> list[dict[str, Any]]:
    """Keep only the requested fields, always keeping enough to identify a record.

    `include_abstract` on 25 rows is tens of kilobytes, and most callers want a
    title, a year and a DOI. Projection is applied after serialisation so the
    derived `doc_type_unified` can be requested like any other field.
    """

    if not fields:
        return records
    wanted = {name.strip() for name in fields if name.strip()}
    if not wanted:
        return records
    _check_fields(fields)
    kept = wanted | _PROJECTION_ALWAYS
    return [{k: v for k, v in record.items() if k in kept} for record in records]


def _page_payload(
    page: Any,
    query: SearchQuery | None = None,
    fields: list[str] | None = None,
    *,
    quota_charged: int | None = None,
    quota_remaining: int | None = None,
    count_only: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "records": _project([record.to_dict() for record in page.records], fields),
        "total": page.total,
        "page": page.page,
        "page_count": page.page_count,
        # Non-zero with empty records means the local year filter removed
        # everything on this page — not that the topic has no papers that year.
        "dropped_year": page.dropped_year,
        # Top level, beside `dropped_year`, because that is where a caller looks for
        # "how much did filtering remove". The nested `filters.dropped` carries the
        # same numbers next to the thresholds that produced them; the acceptance run
        # read only the top level, found `dropped_year` and no `dropped_filter`, and
        # had to be told where the second one lived.
        "dropped_filter": page.dropped_filter,
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
    # A caller who reached for `page` on a channel that offers `exclude_ut` took the
    # more expensive route and may not know the other one exists. Say so in the answer
    # rather than only in the tool description: the choice has already been made by the
    # time a description is read again.
    if query is not None and query.page > 1 and _has_exclusion(query.channel):
        payload["advice"] = (
            f"{query.channel} can exclude records instead of turning pages: pass the UT "
            "values you already have as exclude_ut and the same query returns the ones "
            "you have not seen. Each such call is an independent request; a page turn "
            "re-submits the query and keeps one result list open."
        )
    # The price and the balance belong to every surface. They were added in the MCP
    # tool, outside this function, so the CLI silently returned neither — the fifth
    # time a field was added to one entry point and not the other.
    if quota_charged is not None:
        payload["quota_charged"] = quota_charged
    if quota_remaining is not None:
        payload["quota_remaining"] = quota_remaining
    if count_only:
        # Keep what explains the number: `total` alone cannot say whether the
        # expression failed, matched nothing, or was filtered away.
        payload["records"] = []
    return payload


def _detail_payload(
    record: dict[str, Any],
    *,
    include_abstract: bool,
    fields: list[str] | None,
    quota_charged: int | None = None,
    quota_remaining: int | None = None,
) -> dict[str, Any]:
    """Shape a detail response for either entry point.

    Exists because the CLI held its own copy of this logic and got it backwards: it
    returned the abstract when not asked and dropped it when asked. The switch lives
    here now, and both callers use it.
    """

    payload = dict(record)
    if not include_abstract:
        payload["abstract"] = None
    if quota_charged is not None:
        payload["quota_charged"] = quota_charged
    if quota_remaining is not None:
        payload["quota_remaining"] = quota_remaining
    if fields:
        payload = _project([payload], fields)[0]
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

    Only a timeout qualifies: the page was slow, not wrong. Everything else is a
    state the caller cannot change by asking again:

    - a risk block is the one case where retrying is actively harmful;
    - `BridgeError` means no host is reachable — a browser has to start or an
      extension has to reconnect, and repeating the call changes neither. This used
      to return True for it, which is the field the second review caught inviting a
      retry loop that could never succeed;
    - `BridgeAmbiguous` inherits `BridgeError`: two browsers cannot be told apart, and
      the answer does not get clearer by asking twice.
    """

    if isinstance(error, RiskBlocked):
        return False
    return isinstance(error, BridgeTimeout)


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
    # The stage a plan stopped at, when the failure knows it. Without this a caller
    # sees `wait_for failed: timeout` and cannot tell a missing query editor from a
    # result list that never rendered from a capture stream that never arrived — the
    # acceptance run had to reconstruct that from an audit log.
    stage = getattr(error, "stage", None)
    if isinstance(stage, str) and stage:
        payload["stage"] = stage
    # What the page held when a wait ran out, when the channel could describe it. A
    # `wait.capture` timeout means "no reply in time" and nothing more: no stream, an
    # unfinished stream, and a finished stream with the flag unraised are three
    # different bugs, and only the page can say which. Absent when nothing can be said.
    diagnostics = getattr(error, "diagnostics", None)
    if isinstance(diagnostics, dict) and diagnostics:
        payload["diagnostics"] = diagnostics
    # A caller that cannot act on an error will improvise. When the bridge is the
    # problem, say what the one permitted reaction is — an agent that was left to
    # guess once killed the user's browser.
    #
    # `BridgeError` counts, not only `ActionError`: "no live host" and "two browsers
    # cannot be told apart" are raised before any action runs, so they carry no
    # `bridge.` code and fell through to `_retryable` — which reported them as worth
    # retrying.
    #
    # `BridgeTimeout` is excluded on purpose: it inherits `BridgeError`, but a slow
    # page is the one transport problem that asking again can actually fix.
    bridge_problem = isinstance(error, BridgeError) and not isinstance(error, BridgeTimeout)
    bridge_problem = bridge_problem or (
        isinstance(error, ActionError) and (error.code or "").startswith("bridge.")
    )
    if bridge_problem:
        payload["remediation"] = ScholarService.BRIDGE_REMEDIATION
        payload["retryable"] = False
        payload["requires"] = "external_state_change"
    return payload


def _quota(service: ScholarService) -> int | None:
    # Brief: this runs twice per search, and the full payload is mostly constants.
    value = service.status(brief=True).get("quota_remaining")
    return value if isinstance(value, int) else None


# Tool parameter types, at module level on purpose: `from __future__ import
# annotations` turns every annotation into a string that FastMCP evaluates when it
# builds `tools/list`, and a name defined inside `build_server` is not in scope for
# that evaluation. The bounds mirror `SearchQuery.validate`, which still enforces
# them — a schema-only bound would be a claim the service never checks.
PageNumber = Annotated[
    int,
    Field(
        ge=MIN_PAGE,
        le=MAX_PAGE,
        description=(
            "Page of the site's own result list. **Reach for `exclude_ut` first on "
            "Web of Science** — see below. Use `page` when a channel has no exclusion "
            "field (CNKI), or when you need a few more records and the query is "
            "already narrow. Each turn re-submits the search and opens the next page, "
            "so it is not a way to walk a large result set."
        ),
    ),
]
PageSize = Annotated[
    int,
    Field(ge=1, le=MAX_LIMIT, description=f"Records per page, 1..{MAX_LIMIT}."),
]
FieldName = Annotated[
    str,
    Field(description="A record field to keep. `url` and the quota pair are always kept."),
]


class StrictFastMCP(FastMCP):
    """FastMCP, but an unknown parameter is an error instead of being dropped.

    The SDK builds its argument model with `ConfigDict(arbitrary_types_allowed=True)`
    and calls tools with `validate_input=False`, so `search(channle="cnki")` used the
    default channel and reported success. An agent has no way to notice that — the
    filter it thought it set simply never applied.

    Both halves are needed, and only both: rejecting in `call_tool` without declaring
    it leaves the schema lying, and declaring it in `list_tools` without enforcing it
    leaves the claim untested. The accepted keys come from the tool's own schema, so
    nothing here has to be kept in sync by hand.
    """

    async def list_tools(self) -> list[Any]:
        tools = await super().list_tools()
        for tool in tools:
            schema = tool.inputSchema
            if schema.get("type") == "object":
                schema["additionalProperties"] = False
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        tools = {tool.name: tool for tool in await self.list_tools()}
        tool = tools.get(name)
        if tool is not None:
            allowed = set(tool.inputSchema.get("properties", {}))
            unknown = sorted(set(arguments) - allowed)
            if unknown:
                # Raised, not returned: the client should treat a malformed call as a
                # malformed call, and nothing reaches the service.
                raise ValueError(
                    f"unknown parameter(s): {', '.join(unknown)}. "
                    f"{name} accepts: {', '.join(sorted(allowed))}"
                )
        return await super().call_tool(name, arguments)


def build_server(service: ScholarService) -> FastMCP:
    # FastMCP takes no `version` argument, and the handshake reported the SDK's
    # version (`1.30.0`) while `status.version` reported 0.12.x — two different
    # components answering the same question. The field lives on the inner Server.
    mcp = StrictFastMCP("wensu")
    mcp._mcp_server.version = __version__

    @mcp.tool()
    def search(
        query: str,
        channel: str = "cnki",
        sort: Literal["relevance", "date", "citation"] = "relevance",
        page: PageNumber = 1,
        year_from: int | None = None,
        year_to: int | None = None,
        source_types: list[str] | None = None,
        limit: PageSize = 20,
        include_abstract: bool = False,
        sort_by: Literal["none", "citations", "year"] = "none",
        min_citations: Annotated[int, Field(ge=0)] | None = None,
        sources_only: list[str] | None = None,
        min_impact_factor: Annotated[float, Field(ge=0)] | None = None,
        site_sort: Literal["relevance", "date", "citation"] | None = None,
        local_sort: Literal["none", "citations", "year"] | None = None,
        exclude_ut: Annotated[
            list[str] | None,
            Field(
                default=None,
                description=(
                    "Records to leave out, by UT identifier (Web of Science only). "
                    "**This is the way to go deeper on WoS**: pass the UTs you already "
                    "have and the same query returns the ones you have not seen. Each "
                    "call is an independent request, and the set shrinks predictably "
                    "(38 records, exclude 5 → total 33). `page` still exists for "
                    "channels without an exclusion field."
                ),
            ),
        ] = None,
        fields: Annotated[
            list[FieldName] | None,
            Field(
                default=None,
                description=(
                    "Keep only these keys. `url` and the quota pair are always kept, "
                    "so a projected record can still be followed."
                ),
            ),
        ] = None,
        count_only: bool = False,
    ) -> dict[str, Any]:
        """Search a channel for bibliographic records. Read-only.

        channel: "cnki" (default; Chinese literature, Chinese queries) or
        "webofscience" (English literature; also accepts a Web of Science expression
        such as TS=(ionic AND actuator) AND PY=(2021-2026) — with no year range the
        last five years are applied inside the expression).

        Returns a shortlist by default: abstracts are omitted unless
        include_abstract is true, and sort_by / min_citations / sources_only filter
        locally without any browser action. For the full record call detail(url), which
        infers the channel from the URL.

        **Whether `detail` is free depends on the channel.** A Web of Science search
        captures full records, so a following `detail` is served from the cache at no
        cost; a CNKI search captures only the list, so the first `detail` for a record
        still needs one network action. Asking twice for the same record is always
        free.

        An empty records list is a normal answer, not a failure: read `total` and
        `dropped_year` before concluding that a topic has no papers.

        **To get more records, the channel decides which lever exists.** Web of
        Science has `exclude_ut`: pass back the UT values you already have (the last
        segment of each record's `url`) and the same query returns the records you
        have not seen. Do that rather than asking for a deeper `page` — each
        exclusion call is one independent request, while each page turn re-submits the
        query and keeps a result list open. CNKI has no exclusion field, so `page` is
        how you go further there.

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

        **Which parameters cost a fetch.** The fetched page is cached as the site
        returned it, and every local view is derived from it, so these are free even
        when they change: `limit`, `include_abstract`, `sort_by` / `local_sort`,
        `min_citations`, `min_impact_factor`, `sources_only`, `fields`. These are a
        different request and cost a fetch: `query`, `channel`, `site_sort`, `page`,
        `year_from` / `year_to`, `exclude_ut`.

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
        # Both entry points validate before anything is spent: a typo in `fields` is
        # a local mistake and used to cost a full cold query before being noticed.
        try:
            _check_fields(fields)
        except ValueError as error:
            return _payload(error)
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
            exclude_ut=tuple(exclude_ut or ()),
        )
        try:
            result_page = service.search(request)
        except (RiskBlocked, ScholarSearchError) as error:
            after = _quota(service)
            charged = (before - after) if before is not None and after is not None else 0
            return _payload(error, channel=channel, quota_charged=max(0, charged))
        after = _quota(service)
        payload = _page_payload(
            result_page,
            request,
            fields,
            quota_charged=(
                max(0, before - after) if before is not None and after is not None else 0
            ),
            quota_remaining=after,
            count_only=count_only,
        )
        return payload

    @mcp.tool()
    def detail(
        url: str,
        channel: str | None = None,
        include_abstract: bool = False,
        fields: Annotated[
            list[FieldName] | None,
            Field(
                default=None,
                description=(
                    "Keep only these keys. `url` and the quota pair are always kept, "
                    "so a projected record can still be followed."
                ),
            ),
        ] = None,
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
        # `doi:…`, `https://doi.org/…` and `https://dx.doi.org/…` all name the same
        # paper. Only the bare form used to be recognised, so the others came back as
        # "no channel claims the host" — accurate, unhelpful, and easy to fix here.
        bare_doi = normalise_doi(identifier)
        is_doi = bare_doi is not None
        if bare_doi is not None:
            identifier = bare_doi
        # Before anything is fetched. `_detail_payload` raises for an unknown key, but
        # it runs after the network action — so a typo in `fields` paid for a detail
        # fetch whose result was then discarded, and in `detail_many` it aborted the
        # whole batch on the first record.
        try:
            _check_fields(fields)
        except ValueError as error:
            return _payload(error)

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
        after = _quota(service)
        return _detail_payload(
            result,
            include_abstract=include_abstract,
            fields=fields,
            quota_charged=(
                max(0, before - after) if before is not None and after is not None else 0
            ),
            quota_remaining=after,
        )

    @mcp.tool()
    def detail_many(
        urls: list[str],
        channel: str | None = None,
        include_abstract: bool = False,
        fields: Annotated[
            list[FieldName] | None,
            Field(
                default=None,
                description=(
                    "Keep only these keys on each record. `url` and the quota pair are always kept."
                ),
            ),
        ] = None,
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

        **A risk block is the exception**: it stops the batch. `detail` returns a
        `status: "blocked"` payload rather than raising, so this loop used to file it
        under `ok: true` and carry on — reporting a batch as successful while the
        site was asking the caller to stop. AGENTS.md requires stopping on a block,
        and a batch that keeps visiting after one is exactly the behaviour that rule
        exists to prevent.
        """

        results: list[dict[str, Any]] = []
        blocked: dict[str, Any] | None = None
        attempted = 0
        for url in urls:
            attempted += 1
            try:
                record = detail(url, channel, include_abstract, fields)
            except RiskBlocked as error:
                blocked = _payload(error)
                results.append({"url": url, "ok": False, "error": blocked})
                break
            except ScholarSearchError as error:
                results.append({"url": url, "ok": False, "error": _payload(error)})
                continue
            if record.get("status") == "blocked":
                blocked = record
                results.append({"url": url, "ok": False, "error": record})
                break
            if record.get("status") == "error":
                results.append({"url": url, "ok": False, "error": record})
            else:
                results.append({"url": url, "ok": True, "record": record})

        response: dict[str, Any] = {
            "results": results,
            "ok_count": sum(1 for item in results if item["ok"]),
            "failed_count": sum(1 for item in results if not item["ok"]),
            "attempted": attempted,
            "requested": len(urls),
        }
        if blocked is not None:
            # Surfaced at the top level, not only inside the per-item error: a caller
            # that reads `ok_count` alone must still see that the run was stopped.
            response["status"] = "blocked"
            response["blocked"] = blocked
            response["stopped_early"] = attempted < len(urls)
        return response

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
                # Replacing an existing file is allowed — the caller named the path —
                # but it is not silent. A fixed filename across several export runs
                # used to lose the previous batch with the response saying only
                # `written: true`, which reads as "a new file appeared".
                replaced = target.exists()
                # `newline=""` keeps the text byte-identical to what `text` holds.
                # Without it Python translates every "\n" to "\r\n" on Windows, and
                # the `bytes` field then reported 2004 for a 2054-byte file.
                with target.open("w", encoding="utf-8", newline="") as handle:
                    handle.write(text)
                # The body is deliberately omitted: it is on disk, and returning it
                # anyway would defeat the point of writing it there.
                return {
                    "written": True,
                    "overwritten": replaced,
                    "path": str(target.resolve()),
                    "format": format,
                    "records": len(typed),
                    "bytes": target.stat().st_size,
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
