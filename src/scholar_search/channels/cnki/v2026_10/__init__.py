"""CNKI channel implementation, site version 2026.10."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup

from ....core.contracts import (
    Action,
    ChannelManifest,
    Plan,
    Record,
    SearchPage,
    SearchQuery,
)
from ....core.errors import ChannelError
from . import parse_detail, parse_search, plan_detail, plan_search
from .selectors import SEARCH_READY, SORT


def _load_manifest() -> ChannelManifest:
    raw = json.loads((Path(__file__).parent.parent / "manifest.json").read_text("utf-8"))
    return ChannelManifest(
        channel=raw["channel"],
        site_version=raw["site_version"],
        schema_version=int(raw["schema_version"]),
        min_core=str(raw["min_core"]),
        domains=tuple(raw["domains"]),
        verbs=tuple(raw["verbs"]),
        capabilities=tuple(raw["capabilities"]),
        detail_url_prefixes=tuple(raw.get("detail_url_prefixes", ())),
    )


@dataclass
class CnkiChannel:
    manifest: ChannelManifest

    # The channel declares the navigation nonce it appends, so the kernel can hash
    # this channel's plan without hashing a millisecond timestamp. Declared here
    # rather than guessed there: only the code that writes `&t=…` knows it is a
    # cache-buster and not a search term.
    volatile_url_params = plan_search.VOLATILE_URL_PARAMS

    def plan_search(self, query: SearchQuery) -> Plan:
        return plan_search.build(query)

    def parse_search(self, html: str, *, query: SearchQuery) -> SearchPage:
        return parse_search.parse(html, query)

    def is_empty_page(self, text: str) -> bool:
        """Whether the page itself says the query matched nothing."""
        return parse_search.is_empty_page(text)

    def effective_query(self, query: SearchQuery) -> str:
        """The expression this channel will actually type.

        A bare keyword is wrapped as `SU='…'`; anything carrying a field code passes
        through. Reporting it lets a caller see why a search matched nothing — the
        text it sent is not the text the site matched against.
        """

        return plan_search.effective_expression(query.text)

    def sort_fix(self, query: SearchQuery, html: str) -> Plan | None:
        """Return a corrective plan when the grid ended up ascending."""

        selector = SORT.get(query.sort)
        if selector is None or query.sort == "relevance":
            return None
        node = BeautifulSoup(html, "lxml").select_one(selector)
        if node is None:
            return None
        classes = [str(item).upper() for item in (node.get("class") or [])]
        if "ASC" not in classes:
            return None
        return Plan(
            channel="cnki",
            purpose="search",
            actions=(
                Action(
                    "click",
                    {"selector": selector},
                    timeout_ms=plan_search.CLICK_TIMEOUT_MS,
                ),
                plan_search.settle(1_500),
                Action(
                    "wait_for",
                    {
                        "selector": SEARCH_READY,
                        "timeout_ms": plan_search.FILTER_WAIT_MS,
                    },
                    timeout_ms=plan_search.FILTER_WAIT_MS + plan_search.WAIT_REPLY_MARGIN_MS,
                ),
                Action("read_html", timeout_ms=plan_search.READ_TIMEOUT_MS),
            ),
        )

    def plan_detail(self, url: str) -> Plan:
        return plan_detail.build(url)

    def parse_detail(self, html: str, *, url: str) -> Record:
        return parse_detail.parse(html, url)

    def plan_journal(self, *, issn: str, year: int, issue: str) -> Plan:
        raise ChannelError("cnki channel does not implement journal listings yet")

    def parse_journal(self, html: str, *, issn: str, year: int, issue: str) -> SearchPage:
        raise ChannelError("cnki channel does not implement journal listings yet")


def get_channel() -> CnkiChannel:
    manifest = _load_manifest()
    manifest.validate()
    return CnkiChannel(manifest=manifest)
