"""Core contracts.

This module is the only interface that channels and adapters may depend on.
It contains types and signatures only: no I/O, no site knowledge, no policy
decisions. Changing anything here is an ADR-level event.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable

# --------------------------------------------------------------------------
# Action vocabulary (closed set, v1)
# --------------------------------------------------------------------------

Verb = Literal[
    "goto",
    "wait_for",
    "type",
    "click",
    "select",
    "read_html",
    "read_text",
    "scroll",
    "sleep",
]

VERBS: frozenset[str] = frozenset(
    {
        "goto",
        "wait_for",
        "type",
        "click",
        "select",
        "read_html",
        "read_text",
        "scroll",
        "sleep",
    }
)

FORBIDDEN_VERB_MARKERS: tuple[str, ...] = (
    "download",
    "upload",
    "eval",
    "script",
    "file",
    "shell",
    "exec",
)

Purpose = Literal["search", "detail", "journal", "export"]
SortOrder = Literal["relevance", "date", "citation"]
# Local post-processing of already-parsed records. It never reaches the browser,
# so ordering here costs no request — unlike the site's own sort control.
LocalSort = Literal["none", "citations", "year"]
Capability = Literal["search", "detail", "journal", "export"]


@dataclass(frozen=True, slots=True)
class Action:
    """One atomic browser operation.

    ``params`` is validated by the kernel against the verb's schema and the
    channel manifest's domain allowlist. Unknown keys are rejected.
    """

    verb: Verb
    params: Mapping[str, Any] = field(default_factory=dict)
    timeout_ms: int = 15_000
    note: str = ""


@dataclass(frozen=True, slots=True)
class Plan:
    """An ordered sequence of actions produced by a channel."""

    channel: str
    purpose: Purpose
    actions: tuple[Action, ...]


# --------------------------------------------------------------------------
# Query and record
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SearchQuery:
    text: str
    channel: str = "cnki"
    sort: SortOrder = "relevance"
    page: int = 1
    year_from: int | None = None
    year_to: int | None = None
    source_types: tuple[str, ...] = ()
    limit: int = 20
    # The four below run on records that were already parsed. Their purpose is
    # to keep a fifty-record page out of the caller's context: ask for a
    # shortlist now, pull the abstracts of the few that matter afterwards from
    # the cache, and never re-visit the site for data already in hand.
    include_abstract: bool = False
    sort_by: LocalSort = "none"
    min_citations: int | None = None
    sources_only: tuple[str, ...] = ()
    # Channel-specific and best-effort: only a channel that ships journal metrics
    # can honour it. A record whose journal has no metric is dropped, because the
    # caller is asking for high-impact venues and "unknown" is not that.
    min_impact_factor: float | None = None

    def validate(self) -> None:
        if not self.text.strip():
            raise ValueError("search text must not be empty")
        if self.page < 1:
            raise ValueError("page must be >= 1")
        if self.page > 3:
            raise ValueError("page must be <= 3 (one page turn per extra page)")
        if self.limit < 1 or self.limit > 50:
            raise ValueError("limit must be within 1..50")
        if self.year_from and self.year_to and self.year_to < self.year_from:
            raise ValueError("year_to must be >= year_from")
        if self.min_citations is not None and self.min_citations < 0:
            raise ValueError("min_citations must be >= 0")
        if self.min_impact_factor is not None and self.min_impact_factor < 0:
            raise ValueError("min_impact_factor must be >= 0")


@dataclass(slots=True)
class Record:
    """A bibliographic record. Field names are part of the public schema."""

    channel: str
    title: str
    authors: list[str] = field(default_factory=list)
    institution: str | None = None
    source: str | None = None
    year: int | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    doi: str | None = None
    abstract: str | None = None
    keywords: list[str] = field(default_factory=list)
    citations: int | None = None
    downloads: int | None = None
    url: str | None = None
    fetched_at: datetime | None = None
    doc_type: str | None = None
    # Journal metric, where the channel ships one — Web of Science does, through
    # the `jcr` block. Optional so CNKI, which has no such notion, stays valid.
    impact_factor: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "title": self.title,
            "authors": list(self.authors),
            "institution": self.institution,
            "source": self.source,
            "year": self.year,
            "volume": self.volume,
            "issue": self.issue,
            "pages": self.pages,
            "doi": self.doi,
            "abstract": self.abstract,
            "keywords": list(self.keywords),
            "citations": self.citations,
            "downloads": self.downloads,
            "impact_factor": self.impact_factor,
            "url": self.url,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "doc_type": self.doc_type,
        }


@dataclass(frozen=True, slots=True)
class SearchPage:
    records: tuple[Record, ...]
    total: int | None = None
    page: int | None = None
    page_count: int | None = None


# --------------------------------------------------------------------------
# Channel contract
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChannelManifest:
    channel: str
    site_version: str
    schema_version: int
    min_core: str
    domains: tuple[str, ...]
    verbs: tuple[str, ...]
    capabilities: tuple[str, ...]
    detail_url_prefixes: tuple[str, ...] = ()

    def validate(self) -> None:
        unknown = set(self.verbs) - VERBS
        if unknown:
            raise ValueError(f"manifest declares unknown verbs: {sorted(unknown)}")
        if not self.domains:
            raise ValueError("manifest must declare at least one domain")
        for domain in self.domains:
            if "/" in domain or ":" in domain or domain.startswith("*."):
                raise ValueError(f"domain must be a bare host name: {domain!r}")
        # `search` and `detail` are not listed as capabilities: every channel must
        # implement them, so declaring them would be a tautology. Capabilities mark
        # what is *optional* — journal metadata, export, a journal lookup — and the
        # kernel is expected to refuse a request for one that is absent.
        for cap in self.capabilities:
            if cap not in {"search", "detail", "journal", "export", "journal_metrics"}:
                raise ValueError(f"unknown capability: {cap!r}")


@runtime_checkable
class Channel(Protocol):
    """A site knowledge pack. Implementations live under channels/<name>/."""

    manifest: ChannelManifest

    def plan_search(self, query: SearchQuery) -> Plan: ...

    def parse_search(self, html: str, *, query: SearchQuery) -> SearchPage: ...

    def plan_detail(self, url: str) -> Plan: ...

    def parse_detail(self, html: str, *, url: str) -> Record: ...

    def plan_journal(self, *, issn: str, year: int, issue: str) -> Plan: ...

    def parse_journal(self, html: str, *, issn: str, year: int, issue: str) -> SearchPage: ...


# --------------------------------------------------------------------------
# Execution and adapters
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ActionOutcome:
    action: Action
    ok: bool
    data: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: int = 0
    url: str | None = None


class BrowserAdapter(Protocol):
    """Executes one action. The kernel owns sequencing, policy and risk checks."""

    name: str

    def execute(self, action: Action, *, timeout_ms: int) -> ActionOutcome: ...

    def close(self) -> None: ...


# --------------------------------------------------------------------------
# Risk
# --------------------------------------------------------------------------


class RiskSignal(StrEnum):
    CAPTCHA = "captcha"
    VERIFY_REDIRECT = "verify_redirect"
    HTTP_403 = "http_403"
    LOGIN_REDIRECT = "login_redirect"
    TEXT_MARKER = "text_marker"
    RATE_LIMITED = "rate_limited"


@dataclass(frozen=True, slots=True)
class RiskDecision:
    blocked: bool
    signal: RiskSignal | None = None
    reason: str = ""
    cooldown_until: datetime | None = None


# --------------------------------------------------------------------------
# Service surface used by transports
# --------------------------------------------------------------------------


class Service(Protocol):
    """Transport-agnostic facade. MCP tools are thin wrappers over this."""

    def search(self, query: SearchQuery) -> SearchPage: ...

    def detail(self, url: str, *, channel: str) -> Record: ...

    def journal(self, *, issn: str, year: int, issue: str, channel: str) -> SearchPage: ...

    def export(self, records: Sequence[Record], *, fmt: Literal["ris", "endnote"]) -> str: ...

    def status(self) -> Mapping[str, Any]: ...


class Transport(Protocol):
    name: str

    def serve(self, service: Service) -> None: ...
