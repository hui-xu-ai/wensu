"""Service facade: the only entry point transports talk to.

It owns the request lifecycle (validate → plan → execute → parse → cache) and
never exposes browser details to callers.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse

from .. import __version__
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
from .export import to_endnote, to_ris
from .planner import Planner
from .policy import PolicyEngine
from .registry import ChannelRegistry, ChannelSpec
from .risk import RiskGuard


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
    ) -> None:
        self._registry = registry
        self._adapter_factory = adapter_factory
        self._planner_factory = planner_factory
        self._policy = policy
        self._cache = cache
        self._status_provider = status_provider or (lambda: {})
        self._risk = risk

    def _ensure_ready(self) -> None:
        if self._risk is not None:
            self._risk.ensure_ready()

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
            return _page_from(cached)

        self._ensure_ready()

        splitter = getattr(channel, "plan_search_split", None)
        if splitter is not None:
            head, tail = splitter(query)
            heads = self._run(head, spec)
            landed, moved = _click_landing(heads)
            is_results = getattr(channel, "is_results_url", None)
            # Only a click that reported a URL change can be judged. If the tab never
            # moved, the query matched nothing; if we have no URL at all (older
            # extension), fall through to the normal path rather than guessing.
            if moved and landed and is_results is not None and not is_results(landed):
                empty = SearchPage(
                    records=(), total=0, page=None, empty_reason="no_match"
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
                        records=(), total=0, page=None, empty_reason="no_match"
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
        # Only records that already carry their own detail are seeded. A CNKI
        # list row has a title and a URL but no abstract — caching it would make
        # a later detail(url) answer with strictly less than the detail page
        # would, which is worse than not caching at all.
        for record in page.records:
            if record.url and record.abstract:
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
        self._cache.set(key, _page_to(page))
        return page

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
        page = impl.parse_journal(_html(self._run(plan, spec)), issn=issn, year=year, issue=issue)
        self._cache.set(key, _page_to(page))
        return page

    def export(self, records: Sequence[Record], *, fmt: Literal["ris", "endnote"]) -> str:
        if fmt == "ris":
            return to_ris(records)
        if fmt == "endnote":
            return to_endnote(records)
        raise ValueError(f"unsupported export format: {fmt!r}")

    def status(self) -> dict[str, Any]:
        return dict(self._status_provider())

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

    def _run(self, plan: Any, spec: ChannelSpec) -> tuple[ActionOutcome, ...]:
        adapter = self._adapter_factory()
        planner = self._planner_factory(adapter)
        if self._risk is None:
            self._risk = getattr(planner, "risk", None)
        try:
            outcomes = planner.run(plan, spec.manifest)
        finally:
            adapter.close()
        for outcome in outcomes:
            if not outcome.ok:
                raise ActionError(
                    f"{outcome.action.verb} failed: {outcome.error or 'unknown'}",
                    verb=outcome.action.verb,
                    code=outcome.error or "action.failed",
                )
        return outcomes

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
    }


def _page_from(payload: dict[str, Any]) -> SearchPage:
    return SearchPage(
        records=tuple(_record_from(item) for item in payload["records"]),
        total=payload.get("total"),
        page=payload.get("page"),
        page_count=payload.get("page_count"),
    )


def _record_from(payload: dict[str, Any]) -> Record:
    data = dict(payload)
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
    """Where the tab was after the click, and whether it actually moved.

    Both matter: a URL with no movement means the site stayed put (nothing matched),
    while no URL at all means the extension did not report one and nothing can be
    concluded.
    """

    for outcome in outcomes:
        if outcome.action.verb != "click":
            continue
        data = outcome.data
        if not isinstance(data, dict):
            continue
        url = data.get("url")
        moved = bool(data.get("url_changed"))
        return (url if isinstance(url, str) and url else None), moved
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
