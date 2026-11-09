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

# `probe` is a read-only look at the page after a readiness wait timed out, used to
# tell "the query matched nothing" apart from "the capture failed". It never clicks
# or navigates, so it costs no quota.
Purpose = Literal["search", "detail", "journal", "export", "probe"]
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


# The bounds a query must satisfy. Defined once so the MCP tool schema and
# `SearchQuery.validate` cannot disagree: the schema used to advertise no bounds at
# all, so a caller only discovered the range by failing a call.
MIN_PAGE = 1
MAX_PAGE = 3
MAX_LIMIT = 50


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
        if self.page < MIN_PAGE:
            raise ValueError(f"page must be >= {MIN_PAGE}")
        if self.page > MAX_PAGE:
            raise ValueError(f"page must be <= {MAX_PAGE} (one page turn per extra page)")
        if self.limit < 1 or self.limit > MAX_LIMIT:
            raise ValueError(f"limit must be within 1..{MAX_LIMIT}")
        if self.year_from and self.year_to and self.year_to < self.year_from:
            raise ValueError("year_to must be >= year_from")
        if self.min_citations is not None and self.min_citations < 0:
            raise ValueError("min_citations must be >= 0")
        if self.min_impact_factor is not None and self.min_impact_factor < 0:
            raise ValueError("min_impact_factor must be >= 0")


# One vocabulary for document type, shared by every channel.
#
# Each site names the same thing differently: CNKI calls a journal paper `journal`,
# Web of Science calls it `article`, and WoS also has `proceedings` where CNKI says
# `conference`. Comparing `doc_type` across channels was therefore comparing words,
# not concepts. The channel's own value is preserved; this mapping adds a second
# field so a caller can filter uniformly without knowing which site answered.
DOC_TYPE_UNIFIED = {
    "journal": "article",
    "article": "article",
    "review": "review",
    "proceedings": "conference",
    "conference": "conference",
    "thesis": "thesis",
    "dissertation": "thesis",
    "book": "book",
    "newspaper": "newspaper",
    "patent": "patent",
}


def unify_doc_type(value: str | None) -> str | None:
    """Map a channel's document type onto the shared vocabulary."""

    if value is None:
        return None
    return DOC_TYPE_UNIFIED.get(value.strip().lower(), "other")


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
            # The channel's own vocabulary is kept above; this is the cross-channel
            # one. A caller comparing `doc_type` across channels would otherwise be
            # comparing "journal" with "article" — the same thing under two names.
            "doc_type_unified": unify_doc_type(self.doc_type),
        }


@dataclass(frozen=True, slots=True)
class SearchPage:
    records: tuple[Record, ...]
    total: int | None = None
    page: int | None = None
    page_count: int | None = None
    # How many records the local year filter removed from this page. Non-zero with
    # an empty `records` means "nothing on THIS page matched", not "the topic has no
    # papers that year" — a distinction a caller cannot otherwise make, and one that
    # has already produced a wrong conclusion in practice.
    dropped_year: int = 0
    # Set when the channel proved the query matched nothing. Without it an empty
    # page is indistinguishable from a capture failure or a filter that removed
    # everything, all three of which look like `records: []`.
    empty_reason: str | None = None
    # True when this answer came from the cache, so nothing was spent. Without it a
    # caller cannot tell a free repeat from a charged search.
    cache_hit: bool = False
    # The expression that actually went to the site, when it differs from what the
    # caller typed. A bare keyword becomes `SU='…'` on CNKI, and Web of Science
    # appends `AND PY=(…)` when no year range was given. Without this echo, a
    # zero-result search gives the caller nothing to diagnose: the query it sent is
    # not the query that ran.
    query_effective: str | None = None


# --------------------------------------------------------------------------
# Channel contract
# --------------------------------------------------------------------------


# Which record fields a channel may declare support for. Deliberately a closed set:
# an unknown key is a typo that would silently never be reported to callers.
FIELD_SUPPORT_KEYS = frozenset({"abstract", "keywords", "doi", "volume", "pages", "paging"})


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
    # Which record fields this channel can actually fill. A list row on CNKI has a
    # title, authors and a year but no abstract, keywords or DOI — that is a
    # property of the site, not a bug. Declaring it lets a caller choose a different
    # channel or accept the gap, instead of asking for `include_abstract` and
    # silently receiving nulls.
    field_support: Mapping[str, bool] = field(default_factory=dict)
    # The same question for the *detail* endpoint, which often knows more than the
    # list row does. CNKI's search rows carry no abstract, yet its detail page holds
    # the complete one; declaring only `field_support` told a caller that CNKI
    # "cannot do abstracts", which is false at the endpoint they would use.
    detail_field_support: Mapping[str, bool] = field(default_factory=dict)

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
        for name in (*self.field_support, *self.detail_field_support):
            if name not in FIELD_SUPPORT_KEYS:
                raise ValueError(f"unknown field_support entry: {name!r}")


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
