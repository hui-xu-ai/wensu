"""Web of Science channel implementation, site version 2026.11.

The payload handed to :meth:`parse_search` is the captured NDJSON stream, not an
HTML document. The kernel passes it through unchanged (it looks for ``html`` or
``text`` in the last read action), so the channel keeps all knowledge of the
site's wire format to itself.
"""

from __future__ import annotations

import json
import re
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
from . import parse_records, plan_search, selectors
from . import query as expression


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
class _CaptureState:
    """Summarise a capture node without parsing records out of it.

    Deliberately shallow: it counts what is there and reports the site's own declared
    count, and never decides whether a record is valid. A diagnostic that re-runs the
    parser is a second parser, and a second parser is a second thing to disagree.
    """

    selector = selectors.CAPTURE

    def describe(self, text: str) -> dict[str, object]:
        raw = text or ""
        declared = None
        match = re.search(r'"RecordsFound"\s*:\s*(\d+)', raw)
        if match is not None:
            declared = int(match.group(1))
        has_info = '"searchInfo"' in raw
        has_records = '"key"' in raw and '"records"' in raw
        lines = [line for line in raw.splitlines() if line.strip()]
        if not raw.strip():
            verdict = "no_stream"
        elif has_records:
            verdict = "records_present_not_ready"
        elif has_info:
            verdict = "metadata_only"
        else:
            verdict = "stream_started_no_records"
        return {
            "verdict": verdict,
            "bytes": len(raw),
            "lines": len(lines),
            "declared_records": declared,
            "has_search_info": has_info,
            "has_records_block": has_records,
        }


@dataclass
class WebOfScienceChannel:
    manifest: ChannelManifest

    def plan_search(self, query: SearchQuery) -> Plan:
        return plan_search.build(query)

    def plan_search_split(self, query: SearchQuery) -> tuple[Plan, Plan]:
        """Submit the search, then read it — separate so the caller can check the URL.

        A query that matches nothing never leaves the search form, so running the
        second half would reload that form and destroy the evidence. The caller
        decides, using the URL the click reported.
        """
        return (
            plan_search.build_until_click(query),
            plan_search.build_after_click(query),
        )

    def parse_search(self, html: str, *, query: SearchQuery) -> SearchPage:
        return parse_records.parse(html, query=query)

    def is_results_url(self, url: str) -> bool:
        """Whether the tab landed on a result list rather than the search form.

        `summary` is the results route. `advanced-search` means the query was
        submitted but matched nothing, so the site stayed where it was.
        """
        return "/wos/woscc/summary/" in url

    def capture_state(self) -> _CaptureState:
        """How to describe a capture that never became ready.

        Every acceptance run so far has ended at least once with
        `wait_for failed: timeout (stage wait.capture)`, and each time the only fact
        available was that it timed out. Three different failures look identical from
        there:

        * the data stream never started;
        * it started and never finished;
        * the records arrived and the readiness flag was never raised.

        Each needs a different fix, so the page is asked which one it was instead of
        the cause being assumed.
        """

        return _CaptureState()

    def is_empty_page(self, text: str) -> bool:
        """Whether the page itself says the query matched nothing."""
        return parse_records.is_empty_page(text)

    def effective_query(self, query: SearchQuery) -> str:
        """The expression this channel will actually type.

        Web of Science gets an extra `AND PY=(…)` when the caller gave no year range,
        and `PY=(2026-2026)` is collapsed to `PY=(2026)`. Neither is visible in the
        query the caller sent, so a zero-result search would otherwise be
        undiagnosable.
        """

        return expression.build(query)

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
