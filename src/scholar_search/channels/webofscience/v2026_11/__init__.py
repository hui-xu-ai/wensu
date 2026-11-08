"""Web of Science channel implementation, site version 2026.11.

The payload handed to :meth:`parse_search` is the captured NDJSON stream, not an
HTML document. The kernel passes it through unchanged (it looks for ``html`` or
``text`` in the last read action), so the channel keeps all knowledge of the
site's wire format to itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ....core.contracts import (
    ChannelManifest,
    Plan,
    Record,
    SearchPage,
    SearchQuery,
)
from ....core.errors import ChannelError
from . import parse_records, plan_search


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
class WebOfScienceChannel:
    manifest: ChannelManifest

    def plan_search(self, query: SearchQuery) -> Plan:
        return plan_search.build(query)

    def parse_search(self, html: str, *, query: SearchQuery) -> SearchPage:
        return parse_records.parse(html, query=query)

    def is_empty_page(self, text: str) -> bool:
        """Whether the page itself says the query matched nothing."""
        return parse_records.is_empty_page(text)

    def plan_detail(self, url: str) -> Plan:
        raise ChannelError("webofscience channel does not implement detail yet")

    def parse_detail(self, html: str, *, url: str) -> Record:
        raise ChannelError("webofscience channel does not implement detail yet")

    def plan_journal(self, *, issn: str, year: int, issue: str) -> Plan:
        raise ChannelError("webofscience channel does not implement journal listings")

    def parse_journal(self, html: str, *, issn: str, year: int, issue: str) -> SearchPage:
        raise ChannelError("webofscience channel does not implement journal listings")


def get_channel() -> WebOfScienceChannel:
    manifest = _load_manifest()
    manifest.validate()
    return WebOfScienceChannel(manifest=manifest)
