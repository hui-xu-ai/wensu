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
        key = _key("search", spec, _site_signature(channel, query))

        cached = self._cache.get(key)
        if cached is not None:
            # A cache hit sends nothing to the site, so a cooldown should not hide
            # it: the cooldown exists to stop traffic, not to withhold data already
            # retrieved. Checking readiness first made it do the latter.
            #
            # The cached page is the site's raw answer, so the caller's own view —
            # sort, filters, limit, abstract — is applied here, at no cost.
            stored = _page_from(cached)
            if _cache_can_answer(stored, query):
                return replace(_present(stored, query), cache_hit=True)

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
        # Cache the page **as the site returned it**, before any local filtering.
        # That is what makes the local view free: the same fetched page can be
        # re-sorted, re-filtered and re-projected as often as the caller likes.
        # Caching the narrowed page is why changing `local_sort` used to trigger a
        # whole new search and charge for it.
        self._cache.set(key, _page_to(page))
        # `channel` is untyped here (it is whatever the plugin module exposes), so
        # `parse_search` returns Any. Narrow it once, at the exit.
        result: SearchPage = _present(page, query)
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
        # Deliberately not "the browser extension is not connected". A
        # `bridge.timeout` says only that an action got no reply in time; the
        # connection, the content script in that tab, and the page itself are all
        # candidates, and the acceptance run that hit this had `bridge_ready: true`
        # immediately before and after. Asserting one cause sent the user to restart
        # a browser that was already working.
        "diagnosis": "the browser did not answer one action in time",
        "next_action": "bring_the_tab_forward",
        "command": "wensu status",
        "human_step_required": True,
        "note": "Check `bridge_ready` first. If it is true, the connection is fine and "
        "the tab itself stopped answering — bring that window to the foreground, or "
        "click the wensu icon in it, and retry. Only run `wensu browser start` when "
        "`bridge_ready` is false. Never start, stop, reload or kill browser processes "
        "that are already running.",
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
        for index, outcome in enumerate(outcomes):
            if not outcome.ok:
                stage = self._stage_of(outcome, index)
                raise ActionError(
                    self._failure_message(outcome, index, outcomes),
                    verb=outcome.action.verb,
                    code=outcome.error or "action.failed",
                    stage=stage,
                    diagnostics=self._diagnose_failure(stage, spec),
                )
        return outcomes

    def _diagnose_failure(self, stage: str, spec: ChannelSpec) -> dict[str, Any] | None:
        """What the page looked like when a wait ran out — read locally, charged nothing.

        `wait.capture` has timed out in every acceptance run so far, and each time the
        only fact available was "it timed out". Three different situations produce that
        symptom: the stream never started, the stream started and never finished, or the
        records arrived and the readiness flag did not. They need different fixes, and
        guessing which one it was is how a diagnosis turns into a wrong instruction.

        **This must never raise.** It runs while a real `ActionError` is being built, so
        anything escaping here replaces the failure the caller needs to see with a
        diagnostic about it. The first version did exactly that: it read `.selector` off
        the bound method `capture_state` instead of calling it first, so a capture
        timeout became `AttributeError: 'function' object has no attribute 'selector'`
        and the timeout, the stage and the quota charge were all lost. Hence the broad
        catch below, which is deliberate and not a shortcut.
        """

        if stage != "wait.capture":
            return None
        try:
            impl = self._registry.load(spec.name, spec.site_version)
            factory = getattr(impl, "capture_state", None)
            if factory is None:
                return None
            # A channel may expose either the descriptor itself or a factory for it.
            descriptor = factory() if callable(factory) else factory
            selector = getattr(descriptor, "selector", None)
            describe = getattr(descriptor, "describe", None)
            if not isinstance(selector, str) or not callable(describe):
                return None
            probe = Plan(
                channel=spec.name,
                purpose="probe",
                actions=(Action("read_text", {"selector": selector, "mode": "text"}),),
            )
            outcomes = self._run(probe, spec)
            for outcome in outcomes:
                data = outcome.data
                text = data.get("text") if isinstance(data, dict) else data
                if outcome.ok and isinstance(text, str):
                    described = describe(text)
                    if isinstance(described, dict):
                        return described
        except Exception:
            # Deliberate: a diagnostic must never mask the failure it describes.
            # Anything raised here replaces a `bridge.timeout` that carries the stage
            # and the quota charge with an error about the diagnostic itself.
            return None
        return None

    @staticmethod
    def _stage_of(outcome: ActionOutcome, index: int) -> str:
        """A short, content-free label for where a plan stopped.

        Three different waits in one Web of Science search all failed as
        `wait_for failed: timeout`: the query editor not appearing, the result list not
        rendering, and the capture stream never arriving. A caller reading the public
        error could not tell them apart and had to reconstruct the sequence from an
        audit log — the acceptance run did exactly that.

        The label names the *kind* of thing that was waited for, never the selector
        itself: which elements a channel uses is implementation detail, and on some
        paths the selector is derived from page content.
        """

        params = outcome.action.params or {}
        if outcome.action.verb == "wait_for":
            selector = str(params.get("selector", ""))
            if selector.startswith("#wensu-") or "capture" in selector:
                return "wait.capture"
            if "textarea" in selector or "input" in selector or "SearchInput" in selector:
                return "wait.query-input"
            return "wait.result-list"
        if outcome.action.verb == "click":
            return "click.submit" if index < 6 else "click.page-turn"
        if outcome.action.verb == "goto":
            return "navigate.reload" if params.get("reload") else "navigate.open"
        if outcome.action.verb in {"type", "select"}:
            return "input.fill"
        return f"action.{outcome.action.verb}"

    @classmethod
    def _failure_message(
        cls, outcome: ActionOutcome, index: int, outcomes: Sequence[ActionOutcome]
    ) -> str:
        """`<verb> failed: <error>` plus where it happened and what had succeeded.

        The step index and the stage make the public error self-describing: "step 9
        of 12, waiting for the capture stream" is actionable; "wait_for failed:
        timeout" is not.
        """

        stage = cls._stage_of(outcome, index)
        total = len(outcomes)
        message = (
            f"{outcome.action.verb} failed: {outcome.error or 'unknown'} "
            f"(step {index + 1}/{total}, stage {stage})"
        )
        # A refused navigation says `goto failed: policy.domain`, and the one thing a
        # caller needs is *where* it was sent instead. The acceptance run that hit this
        # could only see a cooldown timestamp, and had to reconstruct the cause from an
        # audit line that did not carry the host either.
        url = outcome.url or ""
        if not url and isinstance(outcome.data, dict):
            nested = outcome.data.get("url")
            url = nested if isinstance(nested, str) else ""
        if url:
            host = urlparse(url).hostname
            if host:
                message = f"{message} [reached {host}]"
        return message

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
        "dropped_filter": page.dropped_filter,
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
        dropped_filter=payload.get("dropped_filter") or 0,
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


def normalise_doi(identifier: str) -> str | None:
    """The bare DOI inside whatever the caller typed, or None if it is not a DOI.

    A DOI arrives in at least four spellings, and only one of them used to be
    recognised:

        10.1002/adma.74981
        doi:10.1002/adma.74981
        https://doi.org/10.1002/adma.74981
        https://dx.doi.org/10.1002/adma.74981

    The last three were reported as `UNKNOWN_CHANNEL` with "no channel claims the
    host" — true but useless: the host is a resolver, not a publisher, and the thing
    the caller has *is* the identifier. Naming the fix is the whole job here, so the
    prefix is stripped rather than diagnosed.

    Returns None for anything that is not a DOI, so a URL keeps going to the channel
    that owns it.
    """

    value = identifier.strip()
    lowered = value.lower()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
    ):
        if lowered.startswith(prefix):
            value = value[len(prefix) :]
            break
    else:
        if lowered.startswith("doi:"):
            value = value[4:]
    value = value.strip()
    if value.lower().startswith("10.") and "/" in value:
        return value
    return None


def _site_signature(channel: Any, query: SearchQuery) -> Any:
    """A stable digest of the actions this channel would run for this query.

    Deciding "which parameters are site-facing" by hand was a mistake that cost two
    rounds. The first version put the whole query in the cache key, so re-sorting a
    page in hand re-ran the search. The second version kept only a hand-picked list —
    and got it wrong for CNKI in both directions at once:

    * `limit` was excluded, but CNKI's plan **does** differ above 20 (it switches the
      site's page size), so a cached 20-record page answered a later `limit: 50` with
      20 records and `cache_hit: true`;
    * `year_from`/`year_to` were kept, but CNKI filters locally only, so adding a year
      cost a full 14 s re-search for an identical site request.

    Both are the same mistake: guessing what the channel will do. So stop guessing —
    build the plan and hash it. Whatever the plan does is, by definition, what the site
    is asked to do; anything not in the plan cannot change the fetch.

    The fallback matters: a query the channel refuses to plan (an out-of-range page, an
    unknown field code) still needs a key, and collapsing every such query into one
    entry would let a later valid query read a page it never fetched. Falling back to
    the whole query is conservative and correct.
    """

    try:
        splitter = getattr(channel, "plan_search_split", None)
        declared: Any = getattr(channel, "volatile_url_params", frozenset())
        volatile = (
            frozenset(declared)
            if isinstance(declared, (set, frozenset, tuple, list))
            else frozenset()
        )
        plans: tuple[Any, ...]
        if splitter is not None:
            head, tail = splitter(query)
            plans = (head, tail)
        else:
            plans = (channel.plan_search(query),)
        # The stripped text rides along with the plan. A channel is supposed to put the
        # expression into a `type` action, and both of ours do — but "supposed to" is
        # the kind of assumption that produced the two bugs above. Including the
        # question makes the identity correct even for a channel that sends it some
        # other way.
        #
        # Stripped, not raw: surrounding whitespace produces byte-identical plans and
        # this repository's own acceptance run paid for a control query that differed
        # only by leading and trailing spaces.
        #
        # Sleep durations are dropped. `settle(jitter(...))` picks a random pause on
        # every call, so hashing it made two identical queries hash differently and the
        # cache never hit at all. A pause is pacing, not content: it cannot change what
        # the site is asked.
        #
        # URL parameters the channel declares as navigation nonces are dropped for the
        # same reason. CNKI appends `&t=<epoch ms>`, which made every call a new
        # identity — identical requests a second apart each paid 3 quota for the same
        # page.
        return [
            query.text.strip(),
            [
                [action.verb, _content_of(action, volatile)]
                for plan in plans
                for action in plan.actions
            ],
        ]
    except (ChannelError, ValueError, AttributeError, TypeError):
        return {"fallback": dict(_site_fields(query))}


def _content_of(action: Action, volatile_url_params: frozenset[str]) -> dict[str, Any]:
    """The part of an action that decides what the site is asked.

    Two kinds of parameter are removed:

    * `sleep.ms` — `settle(jitter(...))` picks a pause per call, so hashing it makes two
      identical queries hash differently and the cache never hits. A pause is pacing.
    * URL query parameters the channel declares as navigation nonces. CNKI appends
      `&t=<epoch ms>` to force a real page load; hashing it made every single call a
      new identity, so CNKI never reused a cached page at all — identical requests a
      second apart each paid 3 quota for the same page.

    The second is a declaration by the channel, not a guess here: only the code that
    writes the nonce knows it is not a search term.
    """

    params = dict(action.params or {})
    if action.verb == "sleep":
        params.pop("ms", None)
    url = params.get("url")
    if volatile_url_params and isinstance(url, str) and "?" in url:
        head, _, tail = url.partition("?")
        fragment = ""
        if "#" in tail:
            tail, _, fragment = tail.partition("#")
            fragment = f"#{fragment}"
        kept = [
            pair
            for pair in tail.split("&")
            if pair and pair.split("=", 1)[0] not in volatile_url_params
        ]
        params["url"] = f"{head}?{'&'.join(kept)}{fragment}" if kept else f"{head}{fragment}"
    return params


def _cache_can_answer(cached: SearchPage, query: SearchQuery) -> bool:
    """Whether a cached page actually holds what this call asked for.

    A page the site returned short is still a valid cache entry — it is what happened.
    But serving 20 records to a request for 50, while `total` says 128 exist, reports a
    truncated list as the answer. The signature usually prevents this by making the two
    requests different; this is the belt to that braces, because a channel that uses one
    plan for both sizes would otherwise reintroduce it.
    """

    held = len(cached.records)
    if held >= query.limit:
        return True
    if cached.total is None:
        # Nothing said how many exist, so nothing proves more do. Refusing here would
        # disable caching for any channel that never reports a total, and the short
        # list plus a null `total` already tells the caller not to assume completeness.
        return True
    if (
        cached.page is not None
        and cached.page_count is not None
        and cached.page >= cached.page_count
    ):
        # A last page is legitimately short. The guard below would otherwise re-fetch
        # it every time, because 128 records over three pages of 50 leaves 28 on the
        # final page and a request for 50 there can never be satisfied.
        return True
    return cached.total <= held


def _narrow(records: Sequence[Record], query: SearchQuery) -> tuple[tuple[Record, ...], int]:
    """Apply the local filters and ordering — none of these touch the browser.

    A missing citation count is **dropped**, not kept. Keeping it meant
    `min_citations: 1000` returned a paper whose citation count was unknown, which a
    caller reads as "this paper has at least 1000 citations" — a claim the data does
    not support. Recall was the old argument, but an unverifiable record is not
    recall, it is a wrong answer with a plausible shape. The number dropped is
    reported so the caller can see the cost.

    Same for the impact-factor threshold: a journal without a metric cannot be shown
    to clear a bar, so it does not clear it.
    """

    narrowed = tuple(records)
    if query.min_citations is not None:
        threshold = query.min_citations
        narrowed = tuple(
            record
            for record in narrowed
            if record.citations is not None and record.citations >= threshold
        )
    if query.min_impact_factor is not None:
        floor = query.min_impact_factor
        narrowed = tuple(
            record
            for record in narrowed
            if record.impact_factor is not None and record.impact_factor >= floor
        )
    if query.sources_only:
        wanted = tuple(source.casefold() for source in query.sources_only)
        narrowed = tuple(
            record
            for record in narrowed
            if record.source and any(want in record.source.casefold() for want in wanted)
        )
    dropped = len(records) - len(narrowed)
    if query.sort_by == "citations":
        by_citations = sorted(narrowed, key=lambda record: record.citations or 0, reverse=True)
        return tuple(by_citations), dropped
    if query.sort_by == "year":
        by_year = sorted(narrowed, key=lambda record: record.year or 0, reverse=True)
        return tuple(by_year), dropped
    return narrowed, dropped


def _site_fields(query: SearchQuery) -> dict[str, Any]:
    """The part of a query that decides what the site is asked.

    Everything else — `limit`, `include_abstract`, `sort_by`, `local_sort`,
    `min_citations`, `min_impact_factor`, `sources_only` — acts on a page already in
    hand. They used to be part of the cache key, so asking the *same* question and
    merely re-sorting what came back sent a second full search: 24 s and 4 quota for
    a list the caller was already holding. A user report measured exactly that, and
    the "local sorting is free" line in the tool description was false as a result.

    `exclude_ut` stays: it is part of the expression typed into the site.
    `year_from`/`year_to` stay: on Web of Science they become `PY=(…)`.
    """

    return {
        "text": query.text,
        "channel": query.channel,
        "sort": query.sort,
        "page": query.page,
        "year_from": query.year_from,
        "year_to": query.year_to,
        "source_types": query.source_types,
        "exclude_ut": query.exclude_ut,
    }


def _present(page: SearchPage, query: SearchQuery) -> SearchPage:
    """Apply the caller's view to a page — identical for a fresh or a cached fetch.

    One function for both paths, because keeping them separate is how the cached
    answer and the live answer drift apart.
    """

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
    records, dropped_filter = _narrow(records, query)
    if len(records) > query.limit:
        records = records[: query.limit]
    if not query.include_abstract:
        # An abstract is roughly 85% of a record's context cost. Dropping it
        # is what keeps a fifty-record page affordable; `detail(url)` serves
        # the full record from the cache seeded above, with no second visit.
        records = tuple(replace(record, abstract=None) for record in records)

    page = replace(page, records=records, dropped_year=dropped_year, dropped_filter=dropped_filter)
    # The site had results and this page lost all of them. Reporting
    # `empty_reason: null` there left the caller to work it out from the counters —
    # and one concluded "this topic has no literature" when the filters simply did
    # not match. Which filter emptied the page matters: a year range is a different
    # mistake from a citation threshold.
    if not records and page.empty_reason is None:
        if dropped_year:
            page = replace(page, empty_reason="all_dropped_by_year")
        elif dropped_filter:
            page = replace(page, empty_reason="all_dropped_by_filter")
    return page


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
