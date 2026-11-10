"""Service facade: the only entry point transports talk to.

It owns the request lifecycle (validate → plan → execute → parse → cache) and
never exposes browser details to callers.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, suppress
from dataclasses import replace
from datetime import datetime
from typing import Any, ClassVar, Literal
from urllib.parse import urlparse

from .. import __version__
from ..adapters.bridge import BridgeAdapter
from .cache import Cache
from .contracts import (
    Action,
    ActionOutcome,
    BrowserAdapter,
    Channel,
    Plan,
    Record,
    SearchPage,
    SearchQuery,
)
from .errors import ActionError, ChannelError, ParseError, PolicyError, ScholarSearchError
from .export import to_csv, to_endnote, to_markdown, to_ris
from .locking import interprocess_lock
from .planner import Planner
from .policy import PolicyEngine
from .registry import ChannelRegistry, ChannelSpec
from .risk import RiskGuard


class _BrowserTransaction:
    """The browser lock plus the adapter that lock protects.

    A context manager rather than a bare `interprocess_lock` call so the two things
    that must move together — the lock, and the host the transaction is pinned to —
    are acquired and released in one place.
    """

    __slots__ = ("_lock", "_service")

    def __init__(self, service: ScholarService) -> None:
        self._service = service
        self._lock = interprocess_lock(service._policy.state_dir / "browser.lock", timeout_s=180.0)

    def __enter__(self) -> None:
        self._lock.__enter__()
        self._service._transaction_depth += 1
        try:
            # Fail here, not halfway through: a profile that is explicitly requested
            # but not running must not silently fall back to another browser.
            self._service._pin_transaction_host()
        except BaseException:
            self._service._transaction_depth -= 1
            self._lock.__exit__(None, None, None)
            raise
        return None

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._service._transaction_depth -= 1
        if self._service._transaction_depth == 0:
            self._service._close_pinned()
        self._lock.__exit__(exc_type, exc, tb)  # type: ignore[arg-type]


class ScholarService:
    def __init__(
        self,
        registry: ChannelRegistry,
        adapter_factory: Callable[[], BrowserAdapter],
        *,
        planner_factory: Callable[[BrowserAdapter], Planner],
        policy: PolicyEngine,
        cache: Cache,
        status_provider: Callable[[], dict[str, Any]] | None = None,
        risk: RiskGuard | None = None,
        bridge_probe: Callable[[], bool] | None = None,
    ) -> None:
        self._registry = registry
        self._adapter_factory = adapter_factory
        self._planner_factory = planner_factory
        self._policy = policy
        self._cache = cache
        self._status_provider = status_provider or (lambda: {})
        # Injectable so tests that use a stub adapter are not blocked by a real
        # bridge probe. Resolved lazily so a monkeypatched `BridgeAdapter.probe`
        # still takes effect — binding it at construction time froze the reference.
        self._bridge_probe = bridge_probe or (lambda: BridgeAdapter.probe())
        self._risk = risk
        # Pinned for the duration of a browser transaction so a search cannot submit
        # to one host and read from another. Depth guards re-entry.
        self._pinned_adapter: Any = None
        self._transaction_depth = 0

    def _ensure_ready(self) -> None:
        if self._risk is not None:
            self._risk.ensure_ready()

    def _browser_transaction(self) -> AbstractContextManager[None]:
        """Hold the shared browser for a whole request, not one plan at a time.

        A split search submits, then reads. Between those two calls the planner's
        `plan.lock` is released, so a second request can submit in the gap and the
        first one then reads *its* results — silently, and cached under the first
        request's key. The lock has to span the request, which means it cannot be the
        planner's: that one is taken inside every `_run`, and re-entering it would
        deadlock. This is a separate file for that reason.

        The transaction also pins one adapter. Without that, each `_run` re-discovers
        a host, and a browser that dies mid-search is simply replaced by whichever
        other host answers — the search then returns another profile's page. Pinning
        means the failure surfaces as a bridge error instead.

        The cost is contention, not latency: a lone request holds this lock for
        exactly as long as it already held the browser. A second request waits, which
        is what "the policy layer serialises network actions" already promised.
        """

        return _BrowserTransaction(self)

    # -- public surface -------------------------------------------------

    def search(self, query: SearchQuery) -> SearchPage:
        query.validate()
        spec, channel = self._resolve(query.channel)
        # Refuse a filter the channel cannot honour rather than silently returning
        # unfiltered records: a caller that asked for high-impact venues and got
        # everything back has no way to notice.
        if (
            query.min_impact_factor is not None
            and "journal_metrics" not in spec.manifest.capabilities
        ):
            raise ScholarSearchError(
                f"channel {query.channel!r} does not report journal metrics, "
                "so min_impact_factor cannot be applied"
            )
        key = _key("search", spec, query)

        cached = self._cache.get(key)
        if cached is not None:
            # A cache hit sends nothing to the site, so a cooldown should not hide
            # it: the cooldown exists to stop traffic, not to withhold data already
            # retrieved. Checking readiness first made it do the latter.
            return replace(_page_from(cached), cache_hit=True)

        self._ensure_ready()

        # Everything from here to the parsed page depends on the browser showing the
        # page this request navigated to. Held across the split, so the submit and the
        # read belong to the same owner.
        with self._browser_transaction():
            return self._search_locked(query, spec, channel, key)

    def _search_locked(
        self, query: SearchQuery, spec: ChannelSpec, channel: Any, key: str
    ) -> SearchPage:
        splitter = getattr(channel, "plan_search_split", None)
        if splitter is not None:
            head, tail = splitter(query)
            heads = self._run(head, spec)
            landed, settled = _click_landing(heads)
            is_results = getattr(channel, "is_results_url", None)
            # A click that overran the extension's 2 s race returns
            # `navigation_expected: true` and **no url**. Treating "no url" as "no
            # problem" skipped this guard entirely, and the next step then reloaded the
            # search form.
            #
            # But it cannot be treated as a failure either, which is what the first
            # attempt at this did: it required `settled` and reported "the query may
            # not have started" on a real Web of Science search that had already
            # spent three quota points and did run. WoS's submit control never reports
            # going busy, so that condition was always true for the one channel that
            # most needs the split path.
            #
            # So an unconfirmed landing is carried forward rather than judged: the
            # tail plan reads the page, and the caller sees what is actually there. If
            # the click really did nothing, the read returns the form and the parse
            # fails visibly instead of being pre-empted by a guess.
            #
            # The one thing that must not happen is reloading the *search form*: a
            # reload there re-runs the query against nothing and wastes a round. When
            # the landing is unknown, the tail is still run — but the reload is
            # skipped only if the URL proves it is a form, which is exactly what
            # `is_results` decides below.
            if landed is None and not settled:
                # Nothing was confirmed. Carry on without asserting either outcome;
                # the tail plan reads whatever is on screen.
                pass
            # The click waits for the site to finish, so this URL is the final state,
            # not a sample taken mid-flight. A tab on anything other than a results
            # route means the query matched nothing: that is where the "no results"
            # answer lives, and reloading it would erase the evidence.
            if landed and is_results is not None and not is_results(landed):
                if not settled:
                    # The button never went busy, so the site may never have started
                    # the query at all. Reporting "no results" here would hide a
                    # failed click behind a confident answer.
                    raise ActionError(
                        "click did not start a query (the submit control never became busy)",
                        verb="click",
                        code="click.not_started",
                    )
                empty = SearchPage(
                    records=(),
                    total=0,
                    page=None,
                    empty_reason="no_match",
                    query_effective=self._effective_query(channel, query),
                )
                self._cache.set(key, _page_to(empty))
                return empty
            outcomes = heads + self._run(tail, spec)
        else:
            plan = channel.plan_search(query)
            try:
                outcomes = self._run(plan, spec)
            except ActionError:
                # Channels without a splittable plan can still say "nothing matched"
                # by their own wording; ask the page before calling it a failure.
                if self._looks_empty(channel, spec):
                    empty = SearchPage(
                        records=(),
                        total=0,
                        page=None,
                        empty_reason="no_match",
                        query_effective=self._effective_query(channel, query),
                    )
                    self._cache.set(key, _page_to(empty))
                    return empty
                raise
        html = _html(outcomes)
        fixer = getattr(channel, "sort_fix", None)
        for _ in range(2):
            if fixer is None:
                break
            fix_plan = fixer(query, html)
            if fix_plan is None:
                break
            outcomes = self._run(fix_plan, spec)
            html = _html(outcomes)
        page = channel.parse_search(html, query=query)

        # Seed the detail cache before any filtering happens. A caller that wants
        # five records now may want the abstract of the twelfth one later, and
        # fetching it from the site would cost a browser action for data we have
        # already parsed and are about to throw away.
        #
        # The test is not "has an abstract". A CNKI list row is a title and a link, so
        # caching it would make a later detail(url) answer with strictly less than the
        # detail page holds — worse than not caching. A Web of Science row is a full
        # record minus the abstract, so caching it is not a downgrade. Gating on the
        # abstract made a WoS paper *without* one unreachable: not cached, and that
        # channel implements no detail plan to fall back to.
        seeds = spec.manifest.search_seeds_detail
        for record in page.records:
            if not record.url:
                continue
            if seeds or record.abstract:
                self._cache.set(_key("detail", spec, {"url": record.url}), record.to_dict())

        records = page.records
        dropped_year = 0
        if query.year_from is not None or query.year_to is not None:
            # The site's year control is unreliable, so filter what we fetched.
            # `total` still describes the site's result set, not the subset — and a
            # page filtered to nothing does NOT mean the topic has no papers in that
            # year. A caller that reads an empty page as "no literature" draws a
            # wrong conclusion, so the number dropped is counted and reported.
            before = records
            records = tuple(
                record
                for record in records
                if record.year is not None
                and (query.year_from is None or record.year >= query.year_from)
                and (query.year_to is None or record.year <= query.year_to)
            )
            dropped_year = len(before) - len(records)
        records = _narrow(records, query)
        if len(records) > query.limit:
            records = records[: query.limit]
        if not query.include_abstract:
            # An abstract is roughly 85% of a record's context cost. Dropping it
            # is what keeps a fifty-record page affordable; `detail(url)` serves
            # the full record from the cache seeded above, with no second visit.
            records = tuple(replace(record, abstract=None) for record in records)
        if records is not page.records:
            # Never overwrite this with `query.page`. Doing so reported "page 2"
            # even when the site had served page 1, which made a failed page turn
            # invisible: the caller saw success and a page number it asked for.
            # What lands here is whatever the channel actually observed.
            page = replace(page, records=records)
        if dropped_year:
            page = replace(page, dropped_year=dropped_year)
            # The site had results and this page lost all of them to the year
            # filter. Reporting `empty_reason: null` there left the caller to work it
            # out from `dropped_year == total` — and one concluded "this topic has no
            # literature" when the years simply did not match.
            if not records and page.empty_reason is None:
                page = replace(page, empty_reason="all_dropped_by_year")
        # What the channel actually typed. A bare keyword becomes `SU='…'` on CNKI,
        # and Web of Science appends `AND PY=(…)` when no year range was given — so
        # the query that ran is often not the query the caller sent, and a
        # zero-result answer is otherwise undiagnosable.
        effective = getattr(channel, "effective_query", None)
        if effective is not None and page.query_effective is None:
            # A channel that cannot describe its query is not an error: the field
            # stays None and the response is still complete without it.
            with suppress(ChannelError, ValueError):
                page = replace(page, query_effective=effective(query))
        self._cache.set(key, _page_to(page))
        # `channel` is untyped here (it is whatever the plugin module exposes), so
        # `parse_search` returns Any. Narrow it once, at the exit.
        result: SearchPage = page
        return result

    def channel_for_url(self, url: str) -> str | None:
        """Which channel owns this URL, judged by the manifests' domain lists.

        `detail(url)` used to default to CNKI, so passing back a URL that `search`
        had just returned for Web of Science was refused by the policy layer that
        had just allowed it. The caller has no way to know it must also pass
        `channel` — the tool description never said so. Deriving it from the URL the
        tool itself produced keeps search → detail a closed loop.
        """

        host = urlparse(url).hostname or ""
        host = host.lower()
        for spec in self._registry.discover():
            for domain in spec.manifest.domains:
                value = domain.lower()
                if host == value or host.endswith(f".{value}"):
                    return spec.name
        return None

    def detail_by_doi(self, doi: str, *, channel: str | None = None) -> Record:
        """Look a record up by DOI and return its full detail.

        CNKI detail URLs are hundreds of characters of encrypted signature (the only
        parameter is `v=`), so handing them back verbatim is easy to truncate. A DOI
        is short, stable and already present in every record.

        Resolving costs one search, because the detail page is only reachable by its
        URL — there is no separate DOI-to-page endpoint. That is the honest price of
        not requiring the signature string back.

        Lives here rather than in the MCP layer so the CLI cannot drift from the
        tool: that divergence has already cost three fields.
        """

        target = channel
        if target is None:
            lowered = doi.casefold()
            # CNKI's own DOIs use the j.cnki / d.cnki namespaces; anything else is
            # assumed to be a Web of Science-indexed DOI.
            target = "cnki" if ("j.cnki." in lowered or "d.cnki." in lowered) else "webofscience"

        expression = f"DOI='{doi}'" if target == "cnki" else f'DO=("{doi}")'
        page = self.search(
            SearchQuery(
                text=expression,
                channel=target,
                limit=1,
                include_abstract=True,
                # A DOI identifies one record; appending an unrequested time window
                # would exclude older papers for no reason. The WoS query builder
                # adds `PY=(last five years)` whenever no year is given, and the
                # `detail` contract says a bare DOI works — so the window is widened
                # here rather than left implicit. 1900 is a floor no real DOI falls
                # below; it only exists to suppress the default.
                year_from=1900 if target == "webofscience" else None,
            )
        )
        if not page.records:
            raise ChannelError(f"no record found for DOI {doi!r} on channel {target!r}")
        record = page.records[0]
        if not record.url:
            raise ChannelError(f"the record for {doi!r} carries no detail URL")
        return self.detail(record.url, channel=target)

    def detail(self, url: str, *, channel: str) -> Record:
        spec, impl = self._resolve(channel)
        self._validate_detail_url(url, spec)

        key = _key("detail", spec, {"url": url})
        cached = self._cache.get(key)
        if cached is not None:
            # Serving a cached record costs the site nothing, so the cooldown does
            # not apply: it exists to stop traffic, not to withhold data that was
            # already retrieved. Checking it first made a cooldown withhold records
            # the user already had.
            return _record_from(cached)

        self._ensure_ready()
        # Same transaction as `search`. A detail fetch navigates the shared tab, so it
        # must not run while a split search is between its submit and its read: the
        # search would then read the detail page. A review reproduced exactly that,
        # with the detail page's title stored under the search's cache key.
        with self._browser_transaction():
            record = impl.parse_detail(_html(self._run(impl.plan_detail(url), spec)), url=url)
        self._cache.set(key, record.to_dict())
        return record

    def journal(self, *, issn: str, year: int, issue: str, channel: str) -> SearchPage:
        self._ensure_ready()
        spec, impl = self._resolve(channel)
        if "journal" not in spec.manifest.capabilities:
            raise ChannelError(f"channel {channel!r} does not support journal listings")
        key = _key("journal", spec, {"issn": issn, "year": year, "issue": issue})

        cached = self._cache.get(key)
        if cached is not None:
            return _page_from(cached)

        plan = impl.plan_journal(issn=issn, year=year, issue=issue)
        with self._browser_transaction():
            page = impl.parse_journal(
                _html(self._run(plan, spec)), issn=issn, year=year, issue=issue
            )
        self._cache.set(key, _page_to(page))
        result: SearchPage = page
        return result

    def export(
        self,
        records: Sequence[Record],
        *,
        fmt: Literal["ris", "endnote", "markdown", "csv"],
    ) -> str:
        if fmt == "ris":
            return to_ris(records)
        if fmt == "endnote":
            return to_endnote(records)
        if fmt == "markdown":
            return to_markdown(records)
        if fmt == "csv":
            return to_csv(records)
        raise ValueError(f"unsupported export format: {fmt!r}")

    def status(self, *, brief: bool = False) -> dict[str, Any]:
        """Session state. `brief` returns only what a health check needs."""

        provider: Any = self._status_provider
        try:
            return dict(provider(brief=brief))
        except TypeError:
            # Providers written before `brief` existed take no argument.
            return dict(provider())

    # -- internals ------------------------------------------------------

    def _resolve(self, name: str) -> tuple[ChannelSpec, Channel]:
        spec = self._registry.select(name)
        return spec, self._registry.load(name, spec.site_version)

    def _validate_detail_url(self, url: str, spec: ChannelSpec) -> None:
        self._policy.check_url(url, spec.manifest.domains)
        path = urlparse(url).path
        prefixes = spec.manifest.detail_url_prefixes
        if prefixes and not any(path.startswith(prefix) for prefix in prefixes):
            raise PolicyError(f"detail URL path is not allowed: {path}", rule="url.detail_path")

    # The permitted reaction to a missing bridge, as data. `bootstrap` fills in the
    # diagnosis (profile running or not) and names the command; this is the fallback
    # for callers that only see the error payload.
    BRIDGE_REMEDIATION: ClassVar[dict[str, object]] = {
        "diagnosis": "the browser extension is not connected",
        "next_action": "browser_start",
        "command": "wensu browser start",
        "human_step_required": False,
        "note": "If a browser is already using the profile, click the wensu icon in "
        "that window instead. Never start, stop, reload or kill browser processes.",
    }

    def _effective_query(self, channel: Any, query: SearchQuery) -> str | None:
        """What the channel will actually type, or None if it cannot say.

        Used on **every** exit path, including the early returns for "nothing
        matched". Those were the one place it mattered most — a zero-result answer
        is exactly when a caller needs to see the expression that produced it — and
        they were the one place it was missing.
        """

        hook = getattr(channel, "effective_query", None)
        if hook is None:
            return None
        with suppress(ChannelError, ValueError):
            produced = hook(query)
            return produced if isinstance(produced, str) else None
        return None

    def _ensure_bridge(self) -> None:
        """Fail before spending quota if no extension is listening.

        The reservation happens inside `planner.run`, so a dead bridge used to cost
        one quota point per attempt while being unable to succeed. Checking first is
        free: `probe` only reads the endpoint file and tries the socket.
        """

        if self._bridge_probe():
            return
        raise ActionError(
            "no live native host found: the browser extension is not connected",
            verb="goto",
            code="bridge.not_ready",
        )

    def _run(self, plan: Any, spec: ChannelSpec) -> tuple[ActionOutcome, ...]:
        self._ensure_bridge()
        # An adapter created here would re-discover a host for every plan. Inside one
        # search that is two discoveries, and if the browser picked at submit time
        # disappears before the read, the second discovery happily selects a
        # *different* profile — so the search completes with another browser's page.
        # A review reproduced exactly that. The transaction pins one adapter instead.
        adapter = self._transaction_adapter()
        planner = self._planner_factory(adapter)
        if self._risk is None:
            self._risk = getattr(planner, "risk", None)
        try:
            outcomes = planner.run(plan, spec.manifest)
        except ActionError as error:
            # A bridge failure means the request never left the machine, so the
            # reservation taken for it paid for something that did not happen. The
            # probe above cannot close this window by itself: the host can die
            # between the probe and the call, and it did — a search charged one
            # point and then reported `no live native host found`.
            if (error.code or "").startswith("bridge.") and self._policy is not None:
                self._policy.refund()
            raise
        finally:
            # Closing is the transaction's job when it owns the adapter: the next
            # plan in the same search has to reach the same host.
            self._release_transaction_adapter()
        for outcome in outcomes:
            if not outcome.ok:
                raise ActionError(
                    f"{outcome.action.verb} failed: {outcome.error or 'unknown'}",
                    verb=outcome.action.verb,
                    code=outcome.error or "action.failed",
                )
        return outcomes

    def _pin_transaction_host(self) -> None:
        """Choose the host for this transaction, once, and refuse if it is ambiguous.

        Runs at the start of the transaction instead of at each `_run`. A host that
        disappears later is an error, not an invitation to pick another one: the
        caller asked for a specific browser, and answering with a different one is
        worse than answering with nothing.
        """

        adapter = self._adapter_factory()
        self._pinned_adapter = adapter
        # `BridgeAdapter` raises at this point when candidates cannot be told apart.
        probe = getattr(adapter, "pin", None)
        if callable(probe):
            probe()

    def _transaction_adapter(self) -> Any:
        """The adapter for this browser transaction, created once.

        Outside a transaction (`_transaction_depth == 0`) this behaves as before:
        one adapter per plan, closed by that plan.
        """

        if self._transaction_depth > 0:
            if self._pinned_adapter is None:
                self._pinned_adapter = self._adapter_factory()
            return self._pinned_adapter
        self._pinned_adapter = self._adapter_factory()
        return self._pinned_adapter

    def _release_transaction_adapter(self) -> None:
        if self._transaction_depth > 0:
            return
        self._close_pinned()

    def _close_pinned(self) -> None:
        if self._pinned_adapter is not None:
            with suppress(Exception):
                self._pinned_adapter.close()
            self._pinned_adapter = None

    def _looks_empty(self, impl: Channel, spec: ChannelSpec) -> bool:
        """Ask the page whether the query matched nothing.

        Run only after a readiness wait timed out. A zero-result search sends no
        data stream on either site, so the wait can never succeed — without this
        probe every empty search surfaced as `wait_for failed: timeout`, which costs
        quota and tells the caller nothing. `read_text` is not a network verb, so the
        probe itself is free.
        """

        checker = getattr(impl, "is_empty_page", None)
        if checker is None:
            return False
        probe = Plan(
            channel=spec.name,
            purpose="probe",
            actions=(Action("read_text", {"selector": "body", "mode": "text"}),),
        )
        try:
            outcomes = self._run(probe, spec)
        except ActionError:
            return False
        for outcome in outcomes:
            if outcome.action.verb == "read_text" and isinstance(outcome.data, dict):
                text = outcome.data.get("text")
                if isinstance(text, str) and checker(text):
                    return True
        return False


# -- cache serialisation ---------------------------------------------------


def _key(kind: str, spec: ChannelSpec, payload: Any) -> str:
    raw = json.dumps(
        {
            "kind": kind,
            "v": __version__,
            "channel": spec.name,
            "site": spec.site_version,
            "q": payload,
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"{kind}:{spec.name}:{spec.site_version}:{digest}"


def _page_to(page: SearchPage) -> dict[str, Any]:
    return {
        "records": [record.to_dict() for record in page.records],
        "total": page.total,
        "page": page.page,
        "page_count": page.page_count,
        # Cached so a repeated search answers the same question the first one did.
        # Without it a cached zero-result page reported `query_effective: null`
        # while the identical live call reported the expression — the field was
        # present or absent depending on a cache hit.
        "query_effective": page.query_effective,
        "empty_reason": page.empty_reason,
        "dropped_year": page.dropped_year,
    }


def _page_from(payload: dict[str, Any]) -> SearchPage:
    return SearchPage(
        records=tuple(_record_from(item) for item in payload["records"]),
        total=payload.get("total"),
        page=payload.get("page"),
        page_count=payload.get("page_count"),
        query_effective=payload.get("query_effective"),
        empty_reason=payload.get("empty_reason"),
        dropped_year=payload.get("dropped_year") or 0,
    )


def _record_from(payload: dict[str, Any]) -> Record:
    data = dict(payload)
    # Derived from `doc_type` when the record was serialised; not a constructor
    # field, so it must be dropped before rebuilding.
    data.pop("doc_type_unified", None)
    fetched = data.get("fetched_at")
    if isinstance(fetched, str):
        data["fetched_at"] = datetime.fromisoformat(fetched)
    return Record(**data)


def _narrow(records: Sequence[Record], query: SearchQuery) -> tuple[Record, ...]:
    """Apply the local filters and ordering — none of these touch the browser.

    A missing citation count is *kept* rather than dropped: some result views do
    not ship one at all, and an empty page would read as "no such papers" when
    the truth is "not measured".
    """

    narrowed = tuple(records)
    if query.min_citations is not None:
        narrowed = tuple(
            record
            for record in narrowed
            if record.citations is None or record.citations >= query.min_citations
        )
    if query.sources_only:
        wanted = tuple(source.casefold() for source in query.sources_only)
        narrowed = tuple(
            record
            for record in narrowed
            if record.source and any(want in record.source.casefold() for want in wanted)
        )
    if query.sort_by == "citations":
        return tuple(sorted(narrowed, key=lambda record: record.citations or 0, reverse=True))
    if query.sort_by == "year":
        return tuple(sorted(narrowed, key=lambda record: record.year or 0, reverse=True))
    return narrowed


def _click_landing(outcomes: Sequence[ActionOutcome]) -> tuple[str | None, bool]:
    """Where the tab was after the click, and whether the site acknowledged it.

    `settled` is the extension's report that the submit control went busy and came
    back — the site ran the query. A URL that never moved while `settled` is false
    means the click most likely did nothing, which must not be reported as an empty
    result.
    """

    for outcome in outcomes:
        if outcome.action.verb != "click":
            continue
        data = outcome.data
        if not isinstance(data, dict):
            continue
        url = data.get("url")
        settled = bool(data.get("settled"))
        return (url if isinstance(url, str) and url else None), settled
    return None, False


def _html(outcomes: Sequence[ActionOutcome]) -> str:
    """Return the page payload of the last read action.

    Usually an HTML document. A channel that captures a network stream reads it
    through ``read_text`` instead and receives plain text here — from the
    kernel's point of view both are "the page".
    """

    for outcome in reversed(outcomes):
        for key in ("html", "text"):
            value = outcome.data.get(key)
            if isinstance(value, str) and value:
                return value
    raise ParseError("plan produced no page payload")
