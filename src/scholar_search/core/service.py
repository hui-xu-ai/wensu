"""Service facade: the only entry point transports talk to.

It owns the request lifecycle (validate → plan → execute → parse → cache) and
never exposes browser details to callers.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse

from .. import __version__
from .cache import Cache
from .contracts import (
    ActionOutcome,
    BrowserAdapter,
    Channel,
    Record,
    SearchPage,
    SearchQuery,
)
from .errors import ActionError, ChannelError, ParseError, PolicyError
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
        self._ensure_ready()
        spec, channel = self._resolve(query.channel)
        key = _key("search", spec, query)

        cached = self._cache.get(key)
        if cached is not None:
            return _page_from(cached)

        plan = channel.plan_search(query)
        outcomes = self._run(plan, spec)
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

        records = page.records
        if query.year_from is not None or query.year_to is not None:
            # The site's year control is unreliable, so filter what we fetched.
            # `total` still describes the site's result set, not the subset.
            records = tuple(
                record
                for record in records
                if record.year is not None
                and (query.year_from is None or record.year >= query.year_from)
                and (query.year_to is None or record.year <= query.year_to)
            )
        if len(records) > query.limit:
            records = records[: query.limit]
        if records is not page.records or page.page != query.page:
            page = SearchPage(
                records=records,
                total=page.total,
                page=query.page,
                page_count=page.page_count,
            )
        self._cache.set(key, _page_to(page))
        return page

    def detail(self, url: str, *, channel: str) -> Record:
        self._ensure_ready()
        spec, impl = self._resolve(channel)
        self._validate_detail_url(url, spec)

        key = _key("detail", spec, {"url": url})
        cached = self._cache.get(key)
        if cached is not None:
            return _record_from(cached)

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
