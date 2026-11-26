"""Service facade: the only entry point transports talk to.

It owns the request lifecycle (validate → plan → execute → parse → cache) and
never exposes browser details to callers.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import time
import uuid
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, suppress
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Literal
from urllib.parse import urlparse

from .. import __version__
from ..adapters.bridge import BridgeAdapter
from .cache import Cache
from .config import browser_state_dir
from .contracts import (
    Action,
    ActionOutcome,
    BrowserAdapter,
    Channel,
    ChannelManifest,
    Plan,
    Record,
    SearchPage,
    SearchQuery,
)
from .errors import (
    ActionError,
    ChannelError,
    ParseError,
    PolicyError,
    RiskBlocked,
    ScholarSearchError,
)
from .export import to_csv, to_endnote, to_markdown, to_ris
from .locking import interprocess_lock
from .page_nav import article_navigation
from .pageprobe import challenge_in_title, citation_doi, citation_fulltext_url, classify_mhtml
from .planner import Planner
from .policy import NETWORK_VERBS, PolicyEngine
from .publishers import PUBLISHERS, Publisher, publisher_for_doi, publisher_for_host
from .registry import ChannelRegistry, ChannelSpec
from .risk import RISK_TITLE_MARKERS, RiskGuard

# How long one slice of a result-list wait may be when the channel can also be asked what the
# page says. It is the price of noticing "the site already answered" late: on the happy path
# nothing changes (the first slice succeeds), and a slow-but-real page pays one free read per
# slice. Measured 2026-11-25: the alert is not in the DOM when the click returns, so a single
# check right after the click finds nothing and the refusal still costs the whole budget.
ANSWER_SLICE_MS = 1_200
# Article bodies paint after the load event; a capture taken too early holds only the
# highlights. Both waits are clamped by the extension to 3 s per action.
_ARTICLE_SETTLE_MS = 1_200
_SECOND_LOOK_MS = 1_500


def _classify_saved(saved: dict[str, Any], *, url: str = "") -> dict[str, Any]:
    """Probe whatever the capture wrote; a missing file is `not_written`, never `ok`."""

    path = Path(str(saved.get("path") or ""))
    if path.is_file():
        return classify_mhtml(path, url=url)
    return {
        "status": "no_html",
        "reason": "not_written",
        "sections": 0,
        "headings": 0,
        "paywall_hits": 0,
    }


def _still_rendering(probe: dict[str, Any]) -> bool:
    """No article body **and** no sign-in prompt: the page is late, not closed.

    A challenge wall (`blocked` / `challenge`) is never a late page: the second snapshot
    would be a second fetch of the wall, which ADR 0004 forbids.
    """

    return (
        probe.get("status") == "no_html"
        and probe.get("reason") in {"abstract_only", "paywall"}
        and not probe.get("headings")
        # A blocking marker means the body is behind a wall, so no amount of waiting helps;
        # a soft one ("institutional access") is printed on pages that are still painting.
        and not probe.get("blocking_hits")
    )


def _page_next(probe: dict[str, Any]) -> str:
    """What the caller should do next, in the state the page was actually in.

    A paywall or an abstract-only page is almost always a *session* problem: the page was
    opened without the reader's institutional access. Telling the caller to "offer the PDF
    route" hides the one action that fixes it — ask the user to sign in, then read again.
    A challenge wall is different: it is the *site* asking for a person, so the user has to
    finish it in the browser, and nothing may be fetched until then. The tool never retries
    by itself (ADR 0004).
    """

    status = probe.get("status")
    reason = probe.get("reason")
    if status == "ok":
        return "call `page2md` with this `mhtml_path` (0 quota, runs inside the server)"
    if status == "blocked":
        return (
            "the publisher challenged this browser and the tab is already on it: ask the user to "
            "finish the check in that window, then call `page_read` again — a solved wall is read "
            "from the open tab at 0 quota. `snapshot` is also free but captures whichever tab is "
            "in front."
        )
    if status == "no_html" and reason == "doi_not_found":
        return (
            "the DOI did not resolve: the publisher answered with its own 'no such DOI' page, so "
            "nothing was kept and only the navigation is charged (1 unit). Check the identifier "
            "itself — a mistyped or not-yet-indexed DOI lands here; signing in will not change it."
        )
    if status == "no_html" and reason in {"paywall", "abstract_only", "pdf_only"}:
        return (
            "no full text on this page, which is not the same as no access: the site may want a "
            "subscription, may publish only a PDF, or may not serve the article as HTML. Use "
            "`pdf_url` when it is present, or read it from another source."
        )
    return "no full text on the page: offer the PDF route instead"


def _network_actions(actions: Sequence[Action]) -> int:
    """How many of these actions the policy would bill: one unit per network verb that runs."""

    return sum(1 for action in actions if action.verb in NETWORK_VERBS)


def _page_stage(payload: dict[str, Any]) -> str:
    """Which step the read stopped at: `cache|navigate|wall|capture|identity|publish`.

    Derived from the answer's own fields, so every exit is covered without each exit having to
    remember to label itself — the failure mode this field exists to prevent.
    """

    if payload.get("cached"):
        return "cache"
    status = str(payload.get("status") or "")
    reason = str(payload.get("reason") or "")
    if status == "blocked" or reason == "challenge":
        return "wall"
    if reason in {"capture_mismatch", "unverified_capture"}:
        return "identity"
    if status == "unsupported_site":
        return "navigate"
    # A navigation that never confirmed sits at `navigate`, not at a render it never reached.
    if status == "timeout" or reason == "navigation_unconfirmed":
        return "navigate"
    if status == "ok":
        return "publish" if payload.get("mhtml_path") else "capture"
    if status == "no_page":
        return "navigate"
    return "capture" if payload.get("mhtml_path") else "render"


def _page_terminal(payload: dict[str, Any]) -> str:
    """One word for how the read ended, so a caller branches on it instead of on a status.

    `ok` — the body was read; `partial` — a page was read but not the article's body;
    `blocked` — a human has to act; `timeout` / `no_page` / `unsupported_site` as they say.
    """

    status = str(payload.get("status") or "")
    reason = str(payload.get("reason") or "")
    code = str(payload.get("code") or "")
    if status == "ok":
        return "ok"
    if status == "blocked" or "RISK_" in code:
        # `verification_timeout` is the only "we asked and waited" outcome; a wait that could not
        # run at all (`gate_wait_unavailable`) stays `blocked` — a build problem, not a slow click.
        return "timeout" if reason == "verification_timeout" else "blocked"
    if "timeout" in reason or "timeout" in code.casefold():
        return "timeout"
    # A navigation the bridge gave up on: the tab may still land, so this is a timeout, not "a
    # page without a body" (ADR 0030, second slice).
    if status == "timeout" or reason == "navigation_unconfirmed":
        return "timeout"
    if status == "unsupported_site":
        return "unsupported_site"
    if status == "no_page":
        return "no_page"
    return "partial"


def _page_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    """What was observed, quoted rather than summarised — the answer to "why did it stop?"."""

    evidence: dict[str, Any] = {}
    for key in (
        "title",
        "captured_url",
        "final_url",
        "declared_doi",
        "identity",
        "prose_words",
        "sections",
        "navigation_attempts",
        "tab_id",
        "navigation_id",
    ):
        value = payload.get(key)
        if value not in (None, "", 0):
            evidence[key] = value
    return evidence


def _page_full_text(payload: dict[str, Any]) -> dict[str, Any]:
    """Say whether the full text was actually read, in a field worth branching on.

    `status` / `reason` keep their meanings — `no_html` still covers every "no article body"
    case — but a caller that only reads them cannot tell a paywall from a PDF-only landing page
    from a site that never serves HTML (2026-11-26 report: all three were reported as "no
    institutional access"). `full_text` answers the one question that was actually asked.
    """

    if str(payload.get("status") or "") == "ok":
        return {**payload, "full_text": True}
    reason = str(payload.get("reason") or payload.get("status") or "").strip()
    return {**payload, "full_text": False, "full_text_reason": reason or "unknown"}


def _charged_units(outcomes: Sequence[ActionOutcome]) -> int:
    """What the policy actually billed: one unit per network action that ran.

    The answer used to say `1` for every wall, while a read that navigates through the
    publisher's home page first runs two `goto`s and is billed two (measured 2026-11-26: the
    answer said 1, the quota dropped by 2, and `audit.jsonl` held two `goto` lines).
    """

    return sum(1 for outcome in outcomes if outcome.action.verb in NETWORK_VERBS) or 1


@dataclass(frozen=True)
class _FollowResult:
    """What one full-text follow-up did: its actions, its risk state, its capture.

    Every field is reported, because the caller has to be able to tell "the second look found
    nothing" from "the site refused and the ledger was charged" (audit 2026-11-26, F07).
    """

    outcomes: Sequence[ActionOutcome]
    saved: dict[str, Any] | None = None
    probe: dict[str, Any] | None = None
    final_url: str = ""
    blocked: dict[str, Any] | None = None
    charged: int = 0


def _page_cached_payload(
    cached: dict[str, Any], identifier: str, publisher: Publisher, target: str
) -> dict[str, Any]:
    """The answer for a page that is already on disk — one shape, used by both call sites.

    Idempotent on purpose: the page is already captured, so navigating again could only replace
    a good capture with whatever the publisher serves now. The verdict travels with the capture:
    an answer that drops `captured_url`, `judge` or `prose_words` forces the caller to trust it,
    and filling `final_url` with the *requested* address hides where the page actually was
    (audit F13).
    """

    return {
        "status": "ok",
        "cached": True,
        "doi": identifier,
        "publisher": publisher.name,
        "final_url": str(cached.get("final_url") or target),
        "captured_url": str(cached.get("captured_url") or ""),
        "reason": str(cached.get("reason") or ""),
        "prose_words": cached.get("prose_words"),
        "judge": cached.get("judge"),
        "capture_sha256": cached.get("capture_sha256"),
        "mhtml_path": str(cached.get("mhtml_path") or ""),
        "bytes": cached.get("bytes"),
        "headings": cached.get("headings"),
        "title": str(cached.get("title") or ""),
        "quota_charged": 0,
        "quota_reason": "cache_hit",
        "next": _page_next({"status": "ok"}),
    }


_DOI_IN_URL = re.compile(r"10\.\d{4,9}/[^\s?#'\"]+", re.IGNORECASE)


def _is_home_page(url: str) -> bool:
    """Is this the site's front page rather than an article (no path, or one bare segment)?"""

    path = urlparse(url).path or "/"
    return path in {"", "/"} or len([part for part in path.split("/") if part]) <= 0


def _page_identity(captured_url: str, declared_doi: str, identifier: str) -> tuple[bool, str]:
    """(refused, evidence) — is this capture the article that was asked for?

    Three strengths of evidence, because publisher attribution is not article identity (audit
    2026-11-26, R31-03: a Wiley request answered with another Wiley DOI passed on the host alone):

    * `declared` — the page prints the DOI that was asked for;
    * `url` — the address carries that DOI;
    * `publisher_only` — neither, but nothing contradicts it either: ScienceDirect addresses an
      article by PII and a legitimate page can hold no DOI anywhere, so silence is not proof of
      the wrong article;
    * `mismatch` — the page prints or carries a *different* DOI, which is positive proof that it
      is another article, and the only case that refuses.
    """

    wanted = identifier.casefold()
    if declared_doi:
        return (False, "declared") if declared_doi.casefold() == wanted else (True, "mismatch")
    found = _DOI_IN_URL.search(captured_url or "")
    if found:
        matched = found.group(0).casefold().startswith(wanted)
        return (False, "url") if matched else (True, "mismatch")
    return (False, "publisher_only")


def _page_evidence_site(url: str, publisher: Publisher, identifier: str) -> bool:
    """Is `url` the page this read asked for — the same publisher, or one carrying the DOI?

    A wall is evidence about *a page*. A challenge title seen on some other tab, or on an earlier
    navigation of the same read, says nothing about this DOI: measured 2026-11-26 (report L26),
    asking for an RSC DOI answered with the `science.org` URL of whatever tab was in front.
    """

    text = (url or "").strip()
    if not text:
        return False
    if identifier and identifier.casefold() in text.casefold():
        return True
    found = publisher_for_host(urlparse(text).hostname or "")
    return found is not None and found.name == publisher.name


# How much of the title survives in the directory name. A person reads these folder names in a
# file manager, so the readable part matters — but it is exactly the *prefix* that used to collide.
_PAGE_SLUG_CHARS = 60
# How long an unpublished (staged) capture may sit in `pages/.probe/` before it is swept.
_PROBE_TTL_S = 3600.0
# Which rule set produced a cached verdict. Bump it whenever the classifier or the wall rules
# change meaning: entries stamped with an older value are not served, so a fix takes effect
# without asking the reader to clear anything. Pre-existing entries carry no stamp at all.
_PAGE_JUDGE_REV = 2
# How long a person gets to clear a verification page, and how often the extension looks at the
# tab title while waiting (ADR 0027). Both are action parameters, not verbs.
_GATE_WAIT_MS = 10_000
_GATE_POLL_MS = 2_000
# How far a cache timestamp may sit in the future before it is treated as corrupt rather than as
# a small clock difference between two machines (audit F13).
_CLOCK_SKEW_S = 300.0


def _page_meta(saved: dict[str, Any]) -> dict[str, str]:
    """The two facts a capture's folder name is built from."""

    return {
        "url": str(saved.get("url") or ""),
        "title": str(saved.get("title") or ""),
    }


def _page_slug_for(identifier: str, meta: dict[str, str]) -> str:
    """Folder name for an article: its DOI when there is one, else the old title+hash rule.

    `10.1021/jacs.6c13448` → `10.1021_jacs.6c13448`. A DOI is stable, readable and unique, which
    is everything a folder name needs; the URL-hash rule stays for pages that have no DOI (a
    landing page read by URL) and for captures written by older builds.
    """

    doi = (identifier or "").strip().casefold()
    if doi.startswith("10.") and "/" in doi:
        slug = re.sub(r"[^a-z0-9._-]+", "_", doi.replace("/", "_")).strip("_")
        if slug:
            return slug[:120]
    return _page_dir_slug(meta)


def _page_dir_slug(meta: dict[str, str]) -> str:
    """Directory name for one capture: readable title prefix, then a hash that makes it unique.

    The name used to be the title cut at 80 characters, so two papers in the same series landed in
    one folder and the second capture overwrote the first (P9, 2026-11-25:
    `…Proximity-Sensing-and`). The hash comes from the URL, which is what actually identifies the
    article — and a page with no usable title (`page`, or a title the rule strips entirely, as CJK
    titles are) still gets a directory of its own.
    """

    title = meta.get("title") or meta.get("url") or "page"
    readable = re.sub(r"[^A-Za-z0-9._-]+", "-", title)[:_PAGE_SLUG_CHARS].strip("-") or "page"
    digest = hashlib.sha1((meta.get("url") or title).encode("utf-8")).hexdigest()[:8]
    return f"{readable}-{digest}"


def _page_spec(publisher: Publisher) -> ChannelSpec:
    """A manifest-shaped view of one publisher, so the planner can run against it.

    The planner needs a manifest for the domain scope and the verb list; page reading
    has no channel package, so it borrows both from the curated publisher entry.
    `doi.org` is in scope because a DOI is resolved there before the publisher is
    known; the resolver only ever redirects to a domain that is on the same list.
    """

    manifest = ChannelManifest(
        channel=f"page:{publisher.name}",
        site_version="v1",
        schema_version=1,
        min_core=__version__,
        domains=(*publisher.hosts(), "doi.org"),
        verbs=("goto", "read_html", "wait_for", "sleep", "snapshot", "await_gate_clear"),
        capabilities=(),
    )
    return ChannelSpec(name=manifest.channel, site_version="v1", manifest=manifest, package="")


# A page snapshot moves a few megabytes through the browser's own write path. The host
# rejects any deadline above 15 s (`policy.deadline`), so this is the ceiling too.
SNAPSHOT_TIMEOUT_MS = 15_000
# One chunk per round trip; the extension sends at most this many bytes per reply.
MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024

_SCRIPT_BLOCK = re.compile(rb"<script\b[^>]*>.*?</script\s*>", re.IGNORECASE | re.DOTALL)
_SCRIPT_TAG = re.compile(rb"<script\b[^>]*/?>", re.IGNORECASE)


def _strip_scripts(payload: bytes) -> bytes:
    """Remove script blocks from the stored capture.

    An MHTML file is rendered by whatever opens it, and a publisher page is full of
    third-party script. The reader only needs the markup, so the stored copy carries none —
    that also makes the file safe to hand to another tool.
    """

    without_blocks = _SCRIPT_BLOCK.sub(b"", payload)
    return _SCRIPT_TAG.sub(b"", without_blocks)


class _BrowserTransaction:
    """The browser lock plus the adapter that lock protects.

    A context manager rather than a bare `interprocess_lock` call so the two things
    that must move together — the lock, and the host the transaction is pinned to —
    are acquired and released in one place.
    """

    __slots__ = ("_lock", "_service")

    def __init__(self, service: ScholarService) -> None:
        self._service = service
        self._lock = interprocess_lock(service._browser_lock_path(), timeout_s=180.0)

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


def _home_from_state_dir(state_dir: Path) -> Path:
    """Best guess at the home that owns *state_dir*, for callers that do not pass one.

    `build_service` passes `app_home()` explicitly; this fallback keeps hand-built services (and
    the test helpers) working. The convention is `<home>/state/<file>`, and a state directory not
    named `state` *is* the home — guessing its parent instead put every test's captures one level
    too high, where they were shared.
    """

    path = Path(state_dir)
    return path.parent if path.name == "state" else path


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
        home_dir: Path | None = None,
    ) -> None:
        self._registry = registry
        self._adapter_factory = adapter_factory
        self._planner_factory = planner_factory
        self._policy = policy
        self._cache = cache
        # Where this home keeps its documents: the page cache, `pages/` and the last-job marker.
        # Deliberately **not** derived from `policy.state_path`: since ADR 0029 that path is the
        # machine-scoped quota file, and deriving documents from it moved every capture into the
        # shared browser directory — two homes then read and overwrote each other's articles
        # (P5 retest 2026-11-27, F41-01). Falls back to the policy file's parent so existing
        # callers and tests keep their layout; `build_service` passes `app_home()` explicitly.
        self._home_dir = (
            Path(home_dir) if home_dir is not None else _home_from_state_dir(policy.state_dir)
        )
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
        # A record range is read out of the site's export file (Web of Science) or by
        # turning its result pages (CNKI), so only a channel that declares an envelope can
        # honour it. Saying so is better than quietly returning the fifty-record page the
        # caller explicitly asked to go past.
        span = query.records_span
        cap = int(getattr(channel, "record_range_max", 0) or 0)
        if span is not None:
            if cap <= 0:
                raise ScholarSearchError(
                    f"channel {query.channel!r} cannot read a record range: it reads the "
                    "result page, not an export file. Use page/limit there, or ask "
                    "webofscience."
                )
            if span[0] != 1 and getattr(channel, "record_range_starts_at_one", False):
                raise ScholarSearchError(
                    f"channel {query.channel!r} reads a range from the first record only: it "
                    f"turns pages rather than jumping to record {span[0]}. Ask for "
                    f"records_from=1, or use page/limit."
                )
            if span[1] - span[0] + 1 > cap:
                raise ScholarSearchError(
                    f"channel {query.channel!r} reads at most {cap} records per call "
                    f"(asked for {span[1] - span[0] + 1}); read the next range instead"
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
            tail_outcomes: tuple[ActionOutcome, ...] | None = None
            if landed and is_results is not None and not is_results(landed):
                if not settled:
                    # The URL has not moved *yet*. It used to be judged here, right after the
                    # click, and the plan therefore had to buy the site time by asking the
                    # extension to wait for the submit button to come back — a transition
                    # this site never makes, so it burned 10 s to protect a check that runs
                    # in microseconds (2026-11-24). Run the tail first instead: it waits for
                    # the result list, which is the site's own "the query ran" signal. If the
                    # page still is not a results route afterwards, the click did nothing.
                    tail_outcomes = self._run_tail(channel, spec, tail)
                    if tail_outcomes is None:
                        return self._empty_result(query, channel, key)
                    proof = _last_url(tail_outcomes) or landed
                    if not is_results(proof):
                        raise ActionError(
                            "click did not start a query (the result list never appeared)",
                            verb="click",
                            code="click.not_started",
                        )
                    landed = proof
                else:
                    return self._empty_result(query, channel, key)
            if tail_outcomes is None:
                tail_outcomes = self._run_tail(channel, spec, tail)
                if tail_outcomes is None:
                    return self._empty_result(query, channel, key)
            outcomes = heads + tail_outcomes
        else:
            plan = channel.plan_search(query)
            try:
                outcomes = self._run(plan, spec)
            except ActionError as error:
                # Only a failure to see the *result list* can be the site refusing to run the
                # query. A capture timeout has its own diagnostics probe and must keep it: an
                # extra `read_text` here would spend the step that probe needs.
                refusal, nothing_matched = (
                    self._site_diagnosis(channel, spec)
                    if error.stage == "wait.result-list"
                    else (None, False)
                )
                # A record range asks for N pages; a result set smaller than the range has
                # no next page, and the turn then fails with `not_found`. That is not a
                # failed search: the first page is already on screen, so read it and answer
                # with what exists rather than throwing away a good page.
                if query.records_span is not None and error.stage == "click.page-turn":
                    outcomes = self._run(
                        Plan(
                            channel=query.channel,
                            purpose="search",
                            actions=(Action("read_html", timeout_ms=4_000),),
                        ),
                        spec,
                    )
                # Channels without a splittable plan can still say "nothing matched" — or
                # "your expression is wrong" — in their own wording; ask the page once
                # before calling it a failure.
                elif refusal or nothing_matched:
                    if refusal:
                        raise ChannelError(
                            f"the site refused this query (query.rejected): {refusal}"
                        ) from None
                    return self._empty_result(query, channel, key)
                else:
                    raise
        # An export-capable channel has no read action in its plan — the payload is a file —
        # so demanding a page payload here would fail before the file is even looked at.
        html = "" if getattr(channel, "parse_export", None) is not None else _html(outcomes)
        fixer = getattr(channel, "sort_fix", None)
        for _ in range(2):
            if fixer is None:
                break
            fix_plan = fixer(query, html)
            if fix_plan is None:
                break
            outcomes = self._run(fix_plan, spec)
            html = _html(outcomes)
        page = self._read_result(channel, outcomes, query)

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

    def _read_result(
        self,
        channel: Channel,
        outcomes: Sequence[ActionOutcome],
        query: SearchQuery,
    ) -> SearchPage:
        """Turn what the plan produced into records, whichever way the channel reads.

        A channel that can only be read through an export file declares `parse_export`;
        the file path arrives in the click's reply, so nothing else in the kernel has to
        know that this path exists. When such a channel reports no file, that is a
        failure, not an empty result — reading the (empty) page instead would report
        "no records found" for a run that never got any.
        """

        parse_export = getattr(channel, "parse_export", None)
        if parse_export is None:
            pages = [channel.parse_search(item, query=query) for item in _payloads(outcomes)]
            if not pages:
                raise ParseError("plan produced no page payload")
            return pages[0] if len(pages) == 1 else _merge_pages(pages)

        download = next(
            (
                outcome.data.get("download")
                for outcome in outcomes
                if isinstance(outcome.data, dict) and isinstance(outcome.data.get("download"), dict)
            ),
            None,
        )
        path = download.get("path") if isinstance(download, dict) else None
        if not isinstance(path, str) or not path:
            seen = next(
                (
                    outcome.data.get("download_seen")
                    for outcome in outcomes
                    if isinstance(outcome.data, dict) and outcome.data.get("download_seen")
                ),
                None,
            )
            detail = ""
            if isinstance(seen, list) and seen:
                detail = (
                    " [saw "
                    + "; ".join(
                        f"{item.get('why')}:{item.get('filename') or item.get('url') or '?'}"
                        for item in seen[:3]
                        if isinstance(item, dict)
                    )
                    + "]"
                )
            raise ActionError(
                "the export click produced no file: the browser reported no completed "
                "BibTeX download for this tab" + detail,
                verb="click",
                code="export.missing",
                stage="action.click",
            )
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            raise ActionError(
                f"the export file could not be read ({error.__class__.__name__})",
                verb="click",
                code="export.unreadable",
                stage="action.click",
            ) from error
        page: SearchPage = parse_export(text, query=query)
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

    # A captured article is reused for this long instead of navigating again. Re-navigating
    # is what turned a good capture into a challenge page (2026-11-24 report, D1/D2), and it
    # is also the only reason a second look at the same DOI cost another two quota points.
    _PAGE_CACHE_TTL_S = 3600.0
    # How long "this URL hit a wall" is remembered. Long enough to cover "the reader is
    # clicking through the challenge right now", short enough that a later attempt is not
    # second-guessed by a stale marker.
    _PAGE_WALL_TTL_S = 300.0

    def _page_cache_path(self) -> Path:
        # Home-scoped on purpose: a capture belongs to the home that took it, not to the browser
        # (F41-01). Two homes sharing a quota file must not share their articles.
        return self._home_dir / "state" / "page-read.json"

    def _page_cache_get(self, url: str) -> dict[str, Any] | None:
        """A capture of this URL that is still on disk, still fresh and still judged the same."""

        try:
            payload = json.loads(self._page_cache_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        entry = payload.get(url) if isinstance(payload, dict) else None
        if not isinstance(entry, dict) or entry.get("status", "ok") != "ok":
            return None
        # The fingerprint is the *rule set* that produced the verdict, not the page's state:
        # entries written before it existed cannot be checked, so they are not served. Nothing
        # is deleted — a later read simply navigates again and writes a stamped entry.
        if entry.get("judge") != _PAGE_JUDGE_REV:
            return None
        if not Path(str(entry.get("mhtml_path") or "")).is_file():
            return None
        # The entry quotes the bytes it judged. A later capture of the same article replaces that
        # one file (one article, one file), so a digest that no longer matches means this entry
        # describes a file that is gone: navigating again is cheaper than serving a verdict about
        # bytes nobody has (audit 2026-11-26, R31-04).
        digest = entry.get("capture_sha256")
        if isinstance(digest, str) and digest:
            try:
                actual = hashlib.sha256(Path(str(entry["mhtml_path"])).read_bytes()).hexdigest()
            except OSError:
                return None
            if actual != digest:
                return None
        stamp = float(entry.get("at") or 0.0)
        # A timestamp in the future (or not a finite number) is a corrupt entry, not a fresh one:
        # subtracting it yields a negative age, so the entry would live forever (audit F13).
        if not math.isfinite(stamp) or stamp > time.time() + _CLOCK_SKEW_S:
            return None
        if time.time() - stamp > self._PAGE_CACHE_TTL_S:
            return None
        return entry

    def _page_cache_walled(self, url: str) -> bool:
        """Did this exact URL meet a verification wall recently?

        A wall is remembered as a marker rather than a capture: it has no file, it expires on
        its own (`_PAGE_WALL_TTL_S`), and its only job is to make the *next* attempt look at
        the tab the person is on before navigating — they may have solved the challenge by
        hand, and navigating again is what replaces a body already on screen.
        """

        try:
            payload = json.loads(self._page_cache_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        entry = payload.get(url) if isinstance(payload, dict) else None
        if not isinstance(entry, dict) or entry.get("status") != "blocked":
            return False
        return time.time() - float(entry.get("at") or 0.0) <= self._PAGE_WALL_TTL_S

    def _page_cache_put(self, url: str, payload: dict[str, Any]) -> None:
        """Best effort: a cache that cannot be written must never fail a read."""

        target = self._page_cache_path()
        try:
            stored: dict[str, Any] = {}
            if target.is_file():
                existing = json.loads(target.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    stored = existing
            stored[url] = {
                # `blocked` entries are markers, not captures: no file, and `_page_cache_get`
                # refuses them (only `ok` can be served as a capture).
                "status": payload.get("status") or "ok",
                "mhtml_path": payload.get("mhtml_path"),
                "bytes": payload.get("bytes"),
                "headings": payload.get("headings"),
                "title": payload.get("title"),
                # What the verdict was made of. Without it a later read cannot tell "this page
                # was judged by a 3,700-word body" from "it was judged by a shell" — and the
                # 2026-11-26 report showed exactly that: a capture that read as an abstract kept
                # being served for an hour after the reader could see the article.
                "judge": _PAGE_JUDGE_REV,
                "reason": payload.get("reason"),
                "prose_words": payload.get("prose_words"),
                "final_url": payload.get("final_url"),
                "captured_url": payload.get("captured_url"),
                # The exact bytes this verdict describes. A later capture of the same article
                # replaces that one file, and the digest is how `_page_cache_get` notices
                # (audit 2026-11-26, R31-04).
                "capture_sha256": payload.get("capture_sha256"),
                "at": time.time(),
            }
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
        except (OSError, ValueError):
            return

    @staticmethod
    def _page_goto_params(target: str) -> dict[str, Any]:
        """The `goto` that opens an article, carrying the gate markers worth stopping for.

        A verification interstitial never fires the load event, so `waitComplete` sits out its
        whole budget on a page that is already final: measured 12.12 s on Wiley (2026-11-25),
        for an answer the title had given away in about a second. Handing the markers to the
        extension lets it end the wait as soon as one of them persists (ADR 0025).

        The lists come from `core/risk.py`, which is where a wall is decided — the extension
        treats them as opaque strings and never learns what a gate page is. Passing a copy of
        the *values* is deliberate: the extension gets no second opinion to drift from, and the
        kernel's own `RiskGuard` and `challenge_in_title` still make the call.
        """

        return {
            "url": target,
            # Empty on purpose: a URL that merely contains `captcha` is not a challenge (ACS hops
            # through such a URL and lands on the article, and the tab title we saw was the article
            # itself — 2026-11-25). Only a gate *title* stops the wait; the kernel no longer trips
            # on URL markers either.
            "halt_url_markers": [],
            "halt_titles": list(RISK_TITLE_MARKERS),
        }

    def _await_gate_clear(self, publisher: Publisher, spec: ChannelSpec) -> dict[str, Any]:
        """Bring the working tab to the person and wait, bounded, for the gate to go away.

        The one thing this function asks of a human is a click. It runs a single action that
        issues no request — the extension polls the tab's title (ADR 0027) — so waiting costs no
        quota; if the title never clears the read still stops (`verification_timeout`) and the
        batch layer skips this publisher.
        """

        try:
            outcomes = self._run(
                Plan(
                    channel=f"page:{publisher.name}",
                    purpose="detail",
                    actions=(
                        Action(
                            "await_gate_clear",
                            {
                                "halt_titles": list(RISK_TITLE_MARKERS),
                                "halt_url_markers": [],
                                "timeout_ms": _GATE_WAIT_MS,
                                "poll_ms": _GATE_POLL_MS,
                            },
                            timeout_ms=_GATE_WAIT_MS + 5_000,
                        ),
                    ),
                ),
                spec,
            )
        except (ActionError, ScholarSearchError, RiskBlocked) as error:
            # The wait did not run. Saying "the person did not clear it in ten seconds" here would
            # be a lie that hides a protocol fault: the P5 acceptance saw `verification_timeout`
            # on a read whose whole life was 3.3 s and which executed no wait at all
            # (2026-11-26, F33-02). The failure keeps its own name and code.
            return {
                "cleared": False,
                "ran": False,
                "title": "",
                "url": "",
                "reason": getattr(error, "code", "") or type(error).__name__,
            }
        last = outcomes[-1].data if outcomes and isinstance(outcomes[-1].data, dict) else {}
        return {
            "cleared": last.get("cleared") is True,
            "ran": True,
            "title": str(last.get("title") or ""),
            "url": str(last.get("url") or ""),
            "reason": str(last.get("reason") or ""),
        }

    def _follow_fulltext(self, url: str, publisher: Publisher, spec: ChannelSpec) -> _FollowResult:
        """One navigation to the page's own full-text view.

        Called only for an explicit `view="full"`, only when the first capture held no body, and
        only when the page named a different address for it. Everything it did is reported back —
        the risk state, the actions that ran, and whether the second look produced the article.

        A swallowed `RiskBlocked` used to lose both the stop and the charge, so the answer said
        `no_html` while the shared ledger had paid for a navigation and the site had cooled down
        (audit 2026-11-26, F07). A refusal is now its own outcome, not "no benefit".
        """

        actions = article_navigation(self, url, publisher)
        try:
            outcomes = self._run(
                Plan(
                    channel=f"page:{publisher.name}",
                    purpose="detail",
                    actions=actions,
                ),
                spec,
            )
        except RiskBlocked as blocked:
            # One navigation ran before the planner stopped — or two, when the warmup patch adds
            # a front page. Counting the plan is honest; the old constant `1` under-reported the
            # private shape (retest 2026-11-26, F07).
            return _FollowResult(
                outcomes=(),
                blocked=dict(blocked.to_payload()),
                charged=getattr(blocked, "charged", _network_actions(actions)),
            )
        final_url = outcomes[-1].url or url
        last = outcomes[-1].data if isinstance(outcomes[-1].data, dict) else {}
        title = last.get("title") if isinstance(last.get("title"), str) else ""
        if last.get("halted") is not False and challenge_in_title(str(title)):
            return _FollowResult(outcomes=outcomes, final_url=final_url)
        saved = self._snapshot_locked(tab="work")
        if saved.get("status") == "blocked":
            return _FollowResult(outcomes=outcomes, saved=saved, final_url=final_url)
        probe = _classify_saved(saved, url=final_url)
        return _FollowResult(
            outcomes=outcomes,
            saved=saved,
            probe=probe,
            final_url=final_url,
        )

    def read_page(
        self, *, url: str = "", doi: str = "", refresh: bool = False, view: str = "landing"
    ) -> dict[str, Any]:
        """`_read_page`, plus the one field a caller should branch on: `full_text`.

        The 2026-11-26 report found the same `status: "no_html"` standing for a paywall, a
        PDF-only landing page and a site that never serves HTML — and the advice built on it told
        the reader they had no institutional access. `full_text` says what actually happened; the
        older `status` / `reason` keep their meanings so existing callers do not break.

        `refresh` skips the capture cache and navigates again. It is explicit and off by default
        because navigating again is what replaced a good capture with a wall once already
        (2026-11-24, report D1/D2).

        `view="full"` follows the page's own `citation_fulltext_html_url` one extra time when the
        landing page holds no body. It costs a navigation, so it is off by default; `view_applied`
        says whether the second look produced the article.

        `job_id`, `terminal`, `stage` and `evidence` are what a caller reads to know *where* the
        read stopped, instead of inferring it from a status string: `stage` names the step
        (`navigate`/`wall`/`render`/`capture`/`identity`/`publish`) and `evidence` quotes what was
        actually observed at that step.
        """

        job_id = uuid.uuid4().hex[:12]
        answer = self._read_page(url=url, doi=doi, refresh=refresh, view=view)
        answer["job_id"] = job_id
        answer["stage"] = _page_stage(answer)
        answer["evidence"] = _page_evidence(answer)
        answer["terminal"] = _page_terminal(answer)
        self._note_job(answer)
        return _page_full_text(answer)

    def warm_up(self, targets: Sequence[str]) -> dict[str, Any]:
        """Open one article per publisher in a kept tab, for the person to click through.

        A verification page is per-site and short-lived: clearing it once for a publisher is what
        lets the batch that follows read that publisher's articles without asking again. Each
        target costs one navigation (a `goto`) and one site visit, so the caller is told exactly
        that before it happens, and the tabs are left in place (ADR 0028) — a later navigation
        blanks its own transient tabs, and these are not among them.
        """

        opened: list[dict[str, Any]] = []
        charged = 0
        with self._browser_transaction():
            for raw in targets:
                target = str(raw or "").strip()
                if not target:
                    continue
                identifier = target if target.startswith("10.") else ""
                url = (
                    target
                    if target.startswith(("http://", "https://"))
                    else (f"https://doi.org/{identifier}" if identifier else "")
                )
                publisher = publisher_for_doi(identifier) if identifier else None
                if publisher is None and url:
                    publisher = publisher_for_host(urlparse(url).hostname or "")
                if publisher is None or not url:
                    opened.append({"target": target, "ok": False, "reason": "unsupported_site"})
                    continue
                spec = _page_spec(publisher)
                try:
                    outcomes = self._run(
                        Plan(
                            channel=f"page:{publisher.name}",
                            purpose="detail",
                            actions=(
                                Action(
                                    "goto",
                                    {
                                        "url": url,
                                        "open": "new",
                                        "keep": True,
                                        "wait": "load",
                                    },
                                ),
                            ),
                        ),
                        spec,
                    )
                except RiskBlocked as error:
                    # A refusal ends the whole warm-up: the cooldown that came with it blocks the
                    # remaining targets anyway, and a caller that only saw per-target `ok: false`
                    # went on to the batch believing the publishers were cleared (P5 acceptance
                    # 2026-11-26, F33-03).
                    charged += getattr(error, "charged", 1)
                    opened.append(
                        {
                            "target": target,
                            "publisher": publisher.name,
                            "ok": False,
                            "reason": error.signal,
                        }
                    )
                    return {
                        "status": "blocked",
                        "signal": error.signal,
                        "cooldown_until": error.cooldown_until,
                        "opened": opened,
                        "not_attempted": [
                            str(item)
                            for item in targets[targets.index(raw) + 1 :]
                            if str(item or "").strip()
                        ],
                        "quota_charged": charged,
                        "quota_reason": "challenge",
                        "next": (
                            "the site refused a warm-up navigation: stop here, do not run the "
                            "batch, and tell the user which publisher cooled down."
                        ),
                    }
                except (ActionError, ScholarSearchError) as error:
                    opened.append(
                        {
                            "target": target,
                            "publisher": publisher.name,
                            "ok": False,
                            "reason": getattr(error, "code", "") or "action_failed",
                        }
                    )
                    continue
                cost = _charged_units(outcomes)
                charged += cost
                last = outcomes[-1].data if outcomes and isinstance(outcomes[-1].data, dict) else {}
                landing = str(last.get("url") or url)
                opened.append(
                    {
                        "target": target,
                        "publisher": publisher.name,
                        # Warm-up is per *subdomain*, not per publisher: measured 2026-11-26, a
                        # Wiley warm-up on `4spepublications…` did not cover an article on
                        # `scijournals…`. Reporting where each tab actually landed is what lets a
                        # caller group the batch by that host instead of by the publisher name.
                        "landing_host": urlparse(landing).hostname or "",
                        "landing_url": landing,
                        "ok": True,
                        "quota_charged": cost,
                    }
                )
        return {
            "status": "ok",
            "opened": opened,
            "quota_charged": charged,
            "quota_reason": "navigate",
            "next": (
                "ask the user to solve any verification page in these tabs, then run the batch: "
                "each of these publishers is cleared for a while."
            ),
        }

    def _read_page(
        self, *, url: str = "", doi: str = "", refresh: bool = False, view: str = "landing"
    ) -> dict[str, Any]:
        """Open the article a reader asked for, then say what is on it.

        One navigation: the article URL is opened directly — a deep link, the
        same thing a reader who pasted the URL would do. Nothing is clicked and nothing is
        typed; only `goto` and `sleep` are used, so a page that challenges the browser ends
        as `blocked` / `challenge` and the human solves it in the browser (ADR 0004).

        Answers with `status: "ok"` and the saved path when the page holds the article,
        `status: "no_html"` with a `reason` when it holds only a preview or a PDF, and
        `status: "unsupported_site"` when the DOI leads to a publisher this build does not
        visit (ADR 0019).
        """

        target = (url or "").strip()
        identifier = (doi or "").strip()
        publisher = publisher_for_doi(identifier) if identifier else None
        if publisher is None and target:
            host = urlparse(target).hostname or ""
            publisher = publisher_for_host(host)
        if publisher is None:
            return {
                "status": "unsupported_site",
                "reason": f"no curated publisher matches {identifier or target!r}",
                "doi": identifier,
                "url": target,
                "quota_charged": 0,
                "quota_reason": "unsupported_site",
                "publishers": [item.name for item in PUBLISHERS],
            }
        if not target:
            # DOIs are case-insensitive, and two spellings used to be two entries — one blocked
            # marker and one capture, neither protecting the other (measured 2026-11-26: the same
            # DOI sat in `page-read.json` twice, differing only in case).
            target = f"https://doi.org/{identifier.casefold()}"

        cached = None if refresh else self._page_cache_get(target)
        if cached is not None:
            return _page_cached_payload(cached, identifier, publisher, target)

        spec = _page_spec(publisher)
        # The navigation is its own plan, because what it returns decides whether anything
        # else may happen at all: on a wall (ADR 0004) the tool must not sleep, capture or
        # look again. The title arrives with the `goto` reply, so this check is free.
        with self._browser_transaction():
            # Asked again, now that the lock is held. The check above ran before the lock, so a
            # second request for the same page could queue behind the first and, once inside,
            # navigate all over again: two readers, four units, neither answer `cached`
            # (measured 2026-11-26, offline concurrency test).
            if not refresh:
                arrived = self._page_cache_get(target)
                if arrived is not None:
                    return _page_cached_payload(arrived, identifier, publisher, target)
            # The one tab this read touches without navigating it itself is the tab in front,
            # so the look happens *under the browser lock*: doing it outside let another read
            # navigate the shared tab in between, and the answer carried that article's URL
            # (2026-11-26 report L26/L27: an RSC DOI answered with a `science.org` page).
            if self._page_cache_walled(target):
                # This URL hit a wall recently. Before navigating again — which is what replaces
                # a body the reader already captured — look at the tab the person is on: if they
                # solved the challenge by hand, the article is right there and `snapshot` costs
                # nothing and issues no request (ADR 0018/0022).
                open_tab = self._snapshot_locked(tab="active")
                # Only the page this read is about can carry its verdict: the tab in front may
                # be another article, another site, or last night's challenge page.
                if open_tab.get("status") == "blocked" and _page_evidence_site(
                    str(open_tab.get("url") or ""), publisher, identifier
                ):
                    return {
                        "status": "blocked",
                        "reason": "challenge",
                        "signal": "title:active-tab",
                        "doi": identifier,
                        "publisher": publisher.name,
                        "final_url": open_tab.get("url") or target,
                        "mhtml_path": None,
                        "bytes": 0,
                        "quota_charged": 0,
                        "quota_reason": "open_tab",
                        "next": _page_next({"status": "blocked", "reason": "challenge"}),
                    }
                reuse = bool(identifier) and identifier in str(open_tab.get("url") or "")
                if not reuse and identifier and open_tab.get("path"):
                    # ACS (and friends) keep the DOI out of the landing URL, so a substring test
                    # can never match there and a page the reader already has on screen was
                    # re-navigated — two units, and often another challenge (measured 2026-11-26).
                    # The page's own `citation_doi` is a positive identity, not a guess.
                    reuse = (
                        citation_doi(Path(str(open_tab["path"]))).casefold()
                        == identifier.casefold()
                    )
                if reuse:
                    # Identity is not content: a page whose DOI matches can still be a paywall
                    # or an abstract (audit 2026-11-26, F06). The classifier the navigation path
                    # uses decides here too, so `full_text` means the same thing on both paths.
                    probe_tab = _classify_saved(open_tab, url=str(open_tab.get("url") or ""))
                    published, capture_sha256 = self._publish_page(
                        Path(str(open_tab.get("path") or "")),
                        _page_meta(open_tab),
                        identifier or str(open_tab.get("url") or ""),
                    )
                    return {
                        **probe_tab,
                        "source": "open-tab",
                        "doi": identifier,
                        "publisher": publisher.name,
                        "final_url": open_tab.get("url"),
                        "captured_url": str(open_tab.get("url") or ""),
                        "mhtml_path": str(published),
                        "capture_sha256": capture_sha256,
                        "bytes": open_tab.get("bytes"),
                        "title": open_tab.get("title"),
                        # It was already open: nothing was navigated, nothing was charged.
                        "quota_charged": 0,
                        "quota_reason": "open_tab",
                        "view_applied": False,
                        "fulltext_url": None,
                        "next": _page_next(probe_tab),
                    }
                # Not the article: that capture was a guess, so it must not become a file.
                with suppress(OSError):
                    Path(str(open_tab.get("path") or "")).unlink()

            navigation_actions = article_navigation(self, target, publisher)
            try:
                outcomes = self._run(
                    Plan(
                        channel=f"page:{publisher.name}",
                        purpose="detail",
                        # One navigation to the article, built in one place (ADR 0025).
                        actions=navigation_actions,
                    ),
                    spec,
                )
            except RiskBlocked as blocked:
                # The wall was named by the `goto` outcome itself (gate title / captcha /
                # verify redirect), so the planner stopped before the next action: nothing
                # was captured, nothing was written (ADR 0004). Remembered so the next
                # attempt looks at the reader's own tab first instead of navigating again.
                self._page_cache_put(target, {"status": "blocked", "title": target})
                return {
                    **blocked.to_payload(),
                    "doi": identifier,
                    "publisher": publisher.name,
                    "final_url": target,
                    "mhtml_path": None,
                    "bytes": 0,
                    # What actually ran, reported by the planner: a plan of two navigations whose
                    # first was refused used one unit, not two (audit 2026-11-26, R31-06).
                    "quota_charged": getattr(
                        blocked, "charged", _network_actions(navigation_actions)
                    ),
                    "quota_reason": "challenge",
                    "next": _page_next({"status": "blocked", "reason": "challenge"}),
                }
            except ActionError as error:
                # A navigation the bridge gave up on is not a navigation that did not happen: the
                # tab may land after the caller has been told "timeout". Say so instead of letting
                # the error escape as if nothing was in flight (ADR 0030, second slice).
                code = getattr(error, "code", "") or "navigation_failed"
                unconfirmed = "timeout" in code
                return {
                    "status": "timeout" if unconfirmed else "error",
                    "reason": "navigation_unconfirmed" if unconfirmed else code,
                    "stage": "navigate",
                    "doi": identifier,
                    "publisher": publisher.name,
                    "final_url": target,
                    "mhtml_path": None,
                    "bytes": 0,
                    "unconfirmed": unconfirmed,
                    "error": str(error),
                    "quota_charged": 0,
                    "quota_reason": "unknown",
                    "next": (
                        "the navigation was not confirmed: the tab may still land. Check "
                        "`status.browser_busy` (and the tab) before asking again — a second "
                        "navigation while this one is in flight is what makes captures "
                        "untrustworthy."
                        if unconfirmed
                        else "the navigation failed before it was issued: ask again."
                    ),
                }
            final_url = outcomes[-1].url or target
            # Only the last navigation's title can be this page's title. With two `goto`s (the
            # warmup patch) the first one belongs to another page, and an empty title means the
            # page was still painting when the extension read it — that is "no evidence yet",
            # not "look at an earlier page" (measured 2026-11-26, T0 1a).
            last = outcomes[-1].data if isinstance(outcomes[-1].data, dict) else {}
            wall_title = last.get("title") if isinstance(last.get("title"), str) else ""
            marker = challenge_in_title(str(wall_title))
            if marker and last.get("halted") is False:
                # The extension times the gate title for 1.5 s and reports `halted`. A title that
                # did not persist is an interstitial on its way out — the ACS one clears itself in
                # ~40 s (live 2026-11-26) — so the capture decides instead of the title.
                marker = None
            if marker and not _page_evidence_site(
                str(last.get("url") or final_url), publisher, identifier
            ):
                marker = None
            if marker:
                # The title is a claim about the tab at the instant `goto` returned, not a
                # verdict about the page: measured 2026-11-26, ACS answered 「请稍候…」 and the
                # article itself was on screen minutes later. A person can clear it in one click,
                # so ask them — the window comes to the front and the extension watches the title
                # for ten seconds (ADR 0027). Cleared means the article is there; not cleared
                # means this read stops, and a batch skips the publisher (plan 2026-11-26 §三).
                self._page_cache_put(target, {"status": "blocked", "title": wall_title})
                gate = self._await_gate_clear(publisher, spec)
                if not gate["cleared"]:
                    # Two different failures, two different names: "the wait ran and the person
                    # did not clear it" versus "the wait could not run at all".
                    waited = bool(gate.get("ran"))
                    return {
                        "status": "blocked",
                        "reason": "verification_timeout" if waited else "gate_wait_unavailable",
                        "signal": f"title:{marker}",
                        "doi": identifier,
                        "publisher": publisher.name,
                        "final_url": gate["url"] or final_url,
                        "mhtml_path": None,
                        "bytes": 0,
                        "title": gate["title"] or wall_title,
                        "action_required": "manual_verification",
                        "waited": waited,
                        "wait_reason": gate["reason"],
                        "quota_charged": _charged_units(outcomes),
                        "quota_reason": "challenge",
                        "next": (
                            "the verification page did not clear in ten seconds: solve it in the "
                            "browser, then ask again (or call `snapshot` yourself once you have), "
                            "or skip this publisher for now."
                            if waited
                            else (
                                "the wait for the verification page could not run "
                                f"({gate['reason']}): a tool/build problem, not a slow click — "
                                "check `status` for the running worker and its capabilities."
                            )
                        ),
                    }
            # Publisher article bodies render after the load event: capturing straight after
            # `goto` returned 1.8 KB of "Highlights" from a ScienceDirect article page that
            # was fully accessible (0.12.59, real run after signing in).
            self._run(
                Plan(
                    channel=f"page:{publisher.name}",
                    purpose="detail",
                    actions=(Action("sleep", {"ms": _ARTICLE_SETTLE_MS}),),
                ),
                spec,
            )
            saved = self._snapshot_locked(tab="work")
            probe = _classify_saved(saved, url=final_url)
            if _still_rendering(probe):
                # No article body, but also no sign-in prompt: the page is still painting,
                # not paywalled. One bounded second look, same page, same quota.
                self._run(
                    Plan(
                        channel=f"page:{publisher.name}",
                        purpose="detail",
                        actions=(Action("sleep", {"ms": _SECOND_LOOK_MS}),),
                    ),
                    spec,
                )
                retry = self._snapshot_locked(tab="work")
                retry_probe = _classify_saved(retry, url=final_url)
                if retry_probe.get("status") == "ok":
                    # The second look wins, so the first one is inspection debris: delete it
                    # rather than leave a copy of an older render next to the article.
                    with suppress(OSError):
                        Path(str(saved.get("path") or "")).unlink()
                    saved, probe = retry, retry_probe
            readable = Path(str(saved.get("path") or ""))
            if saved.get("status") == "blocked" or probe.get("status") == "blocked":
                # The site asked for a person (extension-level challenge or the probe's own
                # marker match). Nothing more may be fetched; the captured bytes were
                # discarded by `_snapshot_locked`, so there is no file to point at.
                self._page_cache_put(target, {"status": "blocked", "title": saved.get("title")})
                stored = saved.get("path")
                return {
                    **(probe if probe.get("status") == "blocked" else {}),
                    **saved,
                    "doi": identifier,
                    "publisher": publisher.name,
                    "final_url": final_url,
                    "mhtml_path": str(stored) if stored else None,
                    "quota_charged": _charged_units(outcomes),
                    "quota_reason": "challenge",
                    "next": _page_next({"status": "blocked", "reason": "challenge"}),
                }

            # A landing page that shows only the abstract often carries the address of the view
            # that holds the body (`citation_fulltext_html_url`) — ACS lands on
            # `/jacsat/article/…` and injects the body only on "Full Text" (2026-11-26 report
            # P1-4). This is opt-in because it costs another navigation: a caller that wants the
            # body asks for `view="full"` and pays for the second look.
            view_applied = False
            fulltext_declared = ""
            # Only worth a second navigation when the first capture held no body: a page that
            # already has the article is not improved by following another address (audit F07).
            if view == "full" and probe.get("status") != "ok" and readable.is_file():
                fulltext_declared = citation_fulltext_url(readable)
                if fulltext_declared and fulltext_declared != final_url:
                    follow = self._follow_fulltext(fulltext_declared, publisher, spec)
                    # Counted whether or not it helped: the ledger was charged for what ran.
                    outcomes = (*outcomes, *follow.outcomes)
                    if follow.blocked is not None or (
                        isinstance(follow.saved, dict) and follow.saved.get("status") == "blocked"
                    ):
                        # The site refused during the follow-up — either the planner raised, or
                        # the snapshot itself recognized the wall. Both are a stop, and folding
                        # the second one into "no benefit" reported the initial paywall instead
                        # (retest 2026-11-26, §3).
                        payload = dict(follow.blocked or {})
                        payload.setdefault("status", "blocked")
                        payload.setdefault("reason", "challenge")
                        payload.setdefault("action_required", "manual_verification")
                        return {
                            **payload,
                            "doi": identifier,
                            "publisher": publisher.name,
                            "final_url": follow.final_url or final_url,
                            "fulltext_url": fulltext_declared,
                            "view_applied": False,
                            "mhtml_path": None,
                            "bytes": 0,
                            "quota_charged": _charged_units(outcomes) + follow.charged,
                            "quota_reason": "challenge",
                            "next": _page_next({"status": "blocked", "reason": "challenge"}),
                        }
                    if follow.probe is not None and follow.probe.get("status") == "ok":
                        assert follow.saved is not None
                        saved, probe = follow.saved, follow.probe
                        final_url = follow.final_url or final_url
                        readable = Path(str(saved.get("path") or ""))
                        view_applied = True

            # Identity of the capture, not just of the request: the tab can move between the
            # navigation and the snapshot. Two pieces of evidence, and the order matters — the
            # address the capture came from is checked first, `citation_doi` is the extra
            # confirmation (retest 2026-11-26, §补充 F05: a Wiley request answered with an ACS
            # page and no DOI metadata still came back `ok`).
            declared = citation_doi(readable) if readable.is_file() else ""
            captured_url = str(saved.get("url") or "")
            refused, identity = _page_identity(captured_url, declared, identifier)
            if declared and declared.casefold() != identifier.casefold():
                refused = True
            # A publisher that answers a deep link with its home page is not showing a partial
            # article: the P5 acceptance got 192 words of an ACS home page reported as
            # `abstract_only`, which reads like "this article has no body". Judging the address is
            # cheap and says what actually happened (2026-11-26).
            landing_home = identity == "publisher_only" and _is_home_page(captured_url)
            # ADR 0030, second slice: did this capture follow the navigation this read issued?
            # `match` / `mismatch` / `absent` — absence is not a failure, because a worker from an
            # older build (or a build the user assembled) does not report it; a *mismatch* is.
            capture_nav = str(saved.get("navigation_id") or "")
            # The navigation the capture **followed**, which is the last one this read issued, not
            # the first. A plan of two `goto`s (the private navigation patch: publisher front page,
            # then the article) issued two ids; the snapshot records the tab's most recent one, and
            # taking the first id here rejected a perfectly good capture on a real read
            # (2026-11-27, `10.3390/s26041303`, `capture_navigation: mismatch`).
            read_nav = next(
                (
                    str(outcome.data.get("navigation_id"))
                    for outcome in reversed(outcomes)
                    if isinstance(outcome.data, dict) and outcome.data.get("navigation_id")
                ),
                "",
            )
            if not capture_nav or not read_nav:
                capture_navigation = "absent"
            elif capture_nav == read_nav:
                capture_navigation = "match"
            else:
                capture_navigation = "mismatch"
                # A tab the reader moved, or a navigation this read did not issue: either way the
                # bytes are not the page we asked for.
                refused = True
            if refused or landing_home:
                with suppress(OSError):
                    readable.unlink()
                reason = (
                    "capture_mismatch"
                    if refused and capture_navigation != "mismatch"
                    else "unverified_capture"
                    if refused
                    else "landing_home"
                )
                self._page_cache_put(target, {"status": "blocked", "title": reason})
                return {
                    "status": "no_page",
                    "reason": reason,
                    "doi": identifier,
                    "publisher": publisher.name,
                    "final_url": final_url,
                    "declared_doi": declared,
                    "captured_url": captured_url,
                    "tab_id": saved.get("tab_id"),
                    "navigation_id": capture_nav or None,
                    "capture_navigation": capture_navigation,
                    "mhtml_path": None,
                    "bytes": 0,
                    "quota_charged": _charged_units(outcomes),
                    "quota_reason": "navigate",
                    "next": (
                        "the capture followed a different navigation than the one this read "
                        "issued (ADR 0030): ask again — something moved the tab."
                        if capture_navigation == "mismatch"
                        else (
                            "the captured page is not this article (its address or its own DOI "
                            "says so): ask again — the browser tab moved between the navigation "
                            "and the capture."
                        )
                        if refused
                        else (
                            "the publisher answered with its home page instead of the article "
                            "(no DOI anywhere on it): ask again, or pass the article's own URL."
                        )
                    ),
                }

            # Publish the one capture this answer describes: `pages/<doi>/page.mhtml`, written
            # once and atomically. Everything up to here worked on staged bytes, so a read that
            # looked twice or glanced at the reader's tab leaves no half-described file behind
            # (audit 2026-11-26, R31-04).
            published, capture_sha256 = self._publish_page(readable, _page_meta(saved), identifier)
            readable = published

            result = {
                **probe,
                "doi": identifier,
                "publisher": publisher.name,
                "final_url": final_url,
                # What was actually captured, so a caller can check it instead of trusting it:
                # the tab can move between the navigation and the snapshot.
                "captured_url": str(saved.get("url") or ""),
                # Which rule set produced this verdict — the same stamp a cache hit reports, so
                # the two answers are comparable (audit F13).
                "judge": _PAGE_JUDGE_REV,
                # How strongly the capture was tied to this article: `declared` (the page prints
                # the DOI), `url` (the address carries it) or `publisher_only` (nothing
                # contradicts it, nothing confirms it). A caller that needs article identity can
                # treat `publisher_only` as "unconfirmed" instead of guessing (audit R31-03).
                "identity": identity,
                "mhtml_path": str(readable),
                # Which tab and which navigation produced this capture (ADR 0030).
                "tab_id": last.get("tab_id"),
                "navigation_id": read_nav or None,
                "capture_navigation": capture_navigation,
                # Which bytes this answer is about. A later capture of the same article replaces
                # the file, so an answer that quotes a digest can be checked instead of trusted.
                "capture_sha256": capture_sha256,
                "bytes": int(saved.get("bytes") or 0),
                "title": str(saved.get("title") or probe.get("title") or ""),
                # Billed per navigation, measured: `snapshot` is not in `NETWORK_VERBS` and is
                # free, so the old flat 2 over-quoted every direct read (measured 2026-11-26 on
                # the live ledger and in `policy.py:354`).
                "quota_charged": _charged_units(outcomes),
                "quota_reason": "navigate",
                "view_applied": view_applied,
                "fulltext_url": fulltext_declared or None,
                "next": _page_next(probe),
            }
            if probe.get("status") == "ok":
                self._page_cache_put(target, result)
            elif probe.get("reason") == "doi_not_found":
                # There is no article here, so the capture is discarded instead of becoming a
                # file a caller could mistake for one, and only the navigation is reported.
                with suppress(OSError):
                    readable.unlink()
                result["mhtml_path"] = None
                result["bytes"] = 0
                result["quota_charged"] = _charged_units(outcomes)
                result["quota_reason"] = "navigate"
            return result

    def _collect_chunks(self, adapter: Any, first: dict[str, Any]) -> bytes:
        """Assemble the capture from base64 chunks the extension hands out on request."""

        token = str(first.get("token") or "")
        total = int(first.get("total") or 0)
        if not token or total <= 0:
            raise ActionError(
                "the extension sent no page data",
                verb="snapshot",
                code="snapshot.empty",
                stage="snapshot",
            )
        if total > MAX_SNAPSHOT_BYTES:
            raise ActionError(
                f"the page is {total} bytes, larger than the {MAX_SNAPSHOT_BYTES}-byte cap",
                verb="snapshot",
                code="snapshot.too_large",
                stage="snapshot",
            )

        buffer = bytearray()
        chunk = str(first.get("base64") or "")
        while True:
            if chunk:
                buffer.extend(base64.b64decode(chunk))
            if len(buffer) >= total:
                break
            follow_up = adapter.execute(
                Action("snapshot", {"token": token, "offset": len(buffer)}),
                timeout_ms=SNAPSHOT_TIMEOUT_MS,
            )
            if not follow_up.ok:
                raise ActionError(
                    f"the page could not be read back ({follow_up.error or 'action.failed'})",
                    verb="snapshot",
                    code=follow_up.error or "snapshot.chunk",
                    stage="snapshot",
                )
            chunk = str(dict(follow_up.data).get("base64") or "")
            if not chunk:
                raise ActionError(
                    "the extension stopped sending data mid-page",
                    verb="snapshot",
                    code="snapshot.chunk",
                    stage="snapshot",
                )
        return bytes(buffer[:total])

    def browser_busy(self) -> bool:
        """Is another read holding the browser right now?

        `page_read` is one call that runs a whole plan, and a caller has no way to see whether the
        previous call is still inside it — which is exactly the reader the timeout story needs
        (P5 acceptance 2026-11-26: "the AI cannot tell whether the last action finished"). The
        lock already knows: if it cannot be taken without waiting, a plan is in flight.
        """

        path = self._browser_lock_path()
        try:
            with interprocess_lock(path, timeout_s=0.0):
                return False
        except (ScholarSearchError, OSError):
            return True

    def last_job(self) -> dict[str, Any] | None:
        """The last finished read, for a caller that wants to know how the previous one ended."""

        path = self._last_job_path()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def _last_job_path(self) -> Path:
        # The writer and `status`'s reader must agree on one path, and it is the home's: "how did
        # the last read end" is about this caller's work, not about the browser's shared ledger
        # (F41-03).
        return self._home_dir / "state" / "last-job.json"

    def _note_job(self, answer: dict[str, Any]) -> None:
        """Remember how this read ended. Best effort: a state file must never fail a read."""

        record = {
            key: answer.get(key)
            for key in (
                "job_id",
                "terminal",
                "stage",
                "status",
                "reason",
                "doi",
                "publisher",
                "quota_charged",
                "capture_sha256",
            )
            if answer.get(key) not in (None, "")
        }
        record["finished_at"] = time.time()
        try:
            path = self._last_job_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        except (OSError, ValueError):
            return

    def _browser_lock_path(self) -> Path:
        """The lock that serialises the browser — machine-scoped, not per-home (ADR 0029)."""

        return browser_state_dir() / "browser.lock"

    def _stage_page(self, payload: bytes, meta: dict[str, str]) -> Path:
        """Write a captured page into `pages/.probe/`: inspection, not storage.

        Every `snapshot` used to write the article's own `page.mhtml`, so one read that looked
        twice — or a look at the reader's own tab — left bytes behind that no verdict described
        (audit 2026-11-26, R31-04). Staged bytes have no identity yet; the one capture the answer
        refers to is published, once, by `_publish_page`.
        """

        staged_dir = self._home_dir / "pages" / ".probe"
        staged_dir.mkdir(parents=True, exist_ok=True)
        # Inspection left-behinds are not storage: a capture nobody published (the first look
        # that a second look replaced, the reader's own tab) is deleted as it happens, and this
        # sweep covers the ones a crashed run left behind.
        for stale in staged_dir.glob("*.mhtml"):
            try:
                if time.time() - stale.stat().st_mtime > _PROBE_TTL_S:
                    stale.unlink()
            except OSError:
                continue
        body = _strip_scripts(payload)
        name = f"{time.time_ns()}-{hashlib.sha256(body).hexdigest()[:8]}.mhtml"
        target = staged_dir / name
        target.write_bytes(body)
        return target

    def _publish_page(
        self, staged: Path, meta: dict[str, str], identifier: str
    ) -> tuple[Path, str]:
        """Publish *one* capture under `pages/<doi-or-slug>/page.mhtml`, atomically.

        The DOI is the article's identity, so it names the folder (`10.1021_jacs.6c13448`) and a
        later capture of the same article replaces that one file — one article, one file. The
        rename is atomic so a reader never sees half a capture, and the returned digest is what
        an answer and the cache quote when they say which bytes they describe.
        """

        target = self._home_dir / "pages" / _page_slug_for(identifier, meta) / "page.mhtml"
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(staged.read_bytes()).hexdigest()
        os.replace(staged, target)
        return target, digest

    def page2md(self, *, mhtml_path: str, out_dir: str = "") -> dict[str, Any]:
        """Turn a saved article page into Markdown: local, free, and no shell involved.

        This is the last link of "read the paper", and it used to be a command line only —
        so any session whose shell could not be provisioned lost the whole chain after the
        page had already been captured (`docs/publishing.md` §2, 2026-11-24 report D3/D7).
        The converter ships inside this package, so it can be called in-process.
        """

        from .. import page2md as converter

        source = Path(mhtml_path).expanduser()
        if not source.is_file():
            raise FileNotFoundError(f"no such saved page: {source}")
        if source.suffix.lower() not in {".html", ".htm", ".mhtml", ".mht"}:
            raise ValueError("expected a saved .html or .mhtml page")
        target = Path(out_dir).expanduser() if out_dir else source.parent / "md"
        meta = converter.convert(source, target)
        return {
            "status": "ok",
            "page_md": str(target / "page.md"),
            "index_json": str(target / "index.json"),
            "bytes_md": meta.get("bytes_md"),
            "engine": meta.get("engine"),
            "math_engine": meta.get("math_engine"),
            "math_failed": meta.get("math_failed"),
            "warnings": meta.get("warnings") or [],
        }

    def snapshot(self) -> dict[str, Any]:
        """Save the page the user has open as MHTML, next to the other snapshots.

        No channel is involved and no request is issued (ADR 0018): `pageCapture` reads
        the tab the user is already looking at and the browser's download manager writes
        the file, so nothing is charged to the quota and no domain scope applies.
        """

        with self._browser_transaction():
            saved = self._snapshot_locked()
            if saved.get("path"):
                # An explicit `snapshot` is a capture the caller asked for, so it is published
                # under the article folder its own metadata implies (no DOI is known here).
                published, digest = self._publish_page(
                    Path(str(saved["path"])), _page_meta(saved), ""
                )
                return {**saved, "path": str(published), "capture_sha256": digest}
            return saved

    def _snapshot_locked(self, *, tab: str = "active") -> dict[str, Any]:
        """`snapshot` without taking the browser lock — for a caller already holding it.

        The bytes travel as base64 chunks over the bridge and the *kernel* writes the file.
        Going through the browser's download manager was the first design and it does not
        work: Edge's file-reputation check holds every `.mhtml` download behind a
        "may harm your device" prompt, which surfaces as a `未确认 NNNN.crdownload` that
        never completes (ADR 0018, amendment 2).
        """

        self._ensure_bridge()
        adapter = self._transaction_adapter()
        action = Action("snapshot", {"tab": tab}) if tab != "active" else Action("snapshot")
        first = adapter.execute(action, timeout_ms=SNAPSHOT_TIMEOUT_MS)
        if not first.ok:
            if str(first.error or "").startswith("policy."):
                # `snapshot` reads "the tab the user is looking at", and a browser tab is not
                # always a web page — `edge://settings`, a blank new tab, the downloads list.
                # Reporting `policy.url_scheme` for that is a policy error where the honest
                # answer is "there is no page here".
                return {
                    "status": "no_page",
                    "code": first.error,
                    "retryable": True,
                    "hint": (
                        "the tab you are on is not a web page (browser-internal or blank): "
                        "open the article in this window, then ask again."
                    ),
                }
            raise ActionError(
                f"the page could not be saved ({first.error or 'action.failed'})",
                verb="snapshot",
                code=first.error or "action.failed",
                stage="snapshot",
            )
        data = dict(first.data)
        meta = {
            "url": str(data.get("url") or ""),
            "title": str(data.get("title") or ""),
        }
        payload = self._collect_chunks(adapter, data)
        # A wall is decided here, before the bytes reach the disk: saving one would leave a
        # file that looks like an article, overwrite nothing useful, and invite a caller to
        # convert 73 KB of "please wait" into Markdown (2026-11-24, report D1/D2).
        wall = data.get("captcha_visible") is True or challenge_in_title(meta["title"])
        if wall:
            marker = challenge_in_title(meta["title"]) or "captcha_visible"
            return {
                "status": "blocked",
                "reason": "challenge",
                "signal": f"title:{marker}" if marker != "captcha_visible" else marker,
                "code": "RISK_CAPTCHA",
                "retryable": False,
                "path": None,
                "bytes": 0,
                "discarded_bytes": len(payload),
                **meta,
                "hint": (
                    "the tab is showing a human-verification challenge, so nothing was "
                    "saved: solve it in the browser yourself, then ask again — do not retry "
                    "automatically."
                ),
            }
        staged = self._stage_page(payload, meta)

        result: dict[str, Any] = {
            "path": str(staged),
            "bytes": len(payload),
            **meta,
        }
        # ADR 0030: which tab and which navigation these bytes came from. Dropped here once, and
        # the capture then looked "absent" no matter what the worker reported.
        if isinstance(data.get("tab_id"), int):
            result["tab_id"] = data["tab_id"]
        if isinstance(data.get("navigation_id"), str) and data["navigation_id"]:
            result["navigation_id"] = data["navigation_id"]
        return result

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

    def _ensure_capabilities(self, adapter: Any, plan: Any) -> None:
        """Refuse a verb the connected build does not advertise — before any navigation.

        The gate is only possible when the extension says what it can serve. Until now the
        handshake carried nothing but a protocol number, so a plan could ask for a verb the
        content script was never injected for and learn about it one navigation too late (audit
        2026-11-26, F08). A build that advertises nothing — or an adapter that cannot be asked,
        like the fixture — leaves this check silent on purpose: refusing every plan because the
        peer is old would be worse than the risk.
        """

        describe = getattr(adapter, "info", None)
        if describe is None:
            return
        try:
            info = describe()
        except (ActionError, ScholarSearchError, OSError):
            info = {}
        if not isinstance(info, dict):
            info = {}
        universal = info.get("capabilities")
        planned = tuple(getattr(plan, "actions", ()) or ())
        first_verb = planned[0].verb if planned else "goto"
        if not isinstance(universal, list) or not universal:
            # Unknown is not permission. The first version of this gate returned here, so a plan
            # asking for `wait_for` on a publisher page ran, navigated, spent a quota point and
            # only then timed out (retest 2026-11-26, §2). Refusing costs nothing and says what
            # to do; the `handshake` field distinguishes "not yet answered" from "old worker".
            handshake = str(info.get("handshake") or "")
            if handshake == "timeout":
                raise ActionError(
                    "the browser extension has not answered the handshake, so it cannot be "
                    "asked what it supports: reload the extension, then try again",
                    verb=first_verb,
                    code="bridge.handshake",
                )
            raise ActionError(
                "the running browser extension does not advertise what it supports (it is older "
                "than this build): reload the extension, then try again",
                verb=first_verb,
                code="action.unsupported",
            )
        advertised = {str(item) for item in universal}
        # The DOM verbs need `content/actions.js`, which the manifest injects into the two
        # channels' domains only. A publisher page gets the universal set and nothing else — this
        # is the check whose absence let `wait_for` be requested on ACS (audit F08).
        channel_capabilities = info.get("channel_capabilities")
        channel_name = str(getattr(plan, "channel", ""))
        if not channel_name.startswith("page:") and isinstance(channel_capabilities, list):
            advertised |= {str(item) for item in channel_capabilities}
        missing = [
            action.verb for action in getattr(plan, "actions", ()) if action.verb not in advertised
        ]
        if not missing:
            return
        raise ActionError(
            f"the connected browser extension cannot run {sorted(set(missing))} on this page "
            f"(it advertises {sorted(advertised)}): reload the extension, then try again",
            verb=missing[0],
            code="action.unsupported",
        )

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
        self._ensure_capabilities(adapter, plan)
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
                    self._failure_message(outcome, index, plan),
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
    def _failure_message(cls, outcome: ActionOutcome, index: int, plan: Any) -> str:
        """`<verb> failed: <error>` plus where it happened and what the page was.

        The step count is against the **plan**, not against the actions that ran. It
        used to be `len(outcomes)`, which for a plan that died on its second action
        read `step 2/2` — indistinguishable from a two-action plan, and it sent one
        investigation looking for a small plan that did not exist.
        """

        stage = cls._stage_of(outcome, index)
        total = len(plan.actions)
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
        # The channel's own wording for why it could not reach the page. A bare
        # `content_not_ready` covers "no such tab", "the document is not there yet" and
        # "the script is there but its channel closed"; only the extension can say
        # which, and one investigation was spent guessing between them.
        if isinstance(outcome.data, dict):
            reason = outcome.data.get("reason")
            if isinstance(reason, str) and reason.strip():
                message = f"{message} [{reason.strip()[:160]}]"
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

    def _empty_result(self, query: SearchQuery, channel: Any, key: str) -> SearchPage:
        """The site's own "nothing matched" answer, cached like any other page.

        A zero-hit search is not a failure: the actions that ran were really sent, and "the
        expression matches nothing" is a true answer about it (2026-11-25: two legal zero-hit
        expressions were reported as refused expressions instead).
        """

        empty = SearchPage(
            records=(),
            total=0,
            page=None,
            empty_reason="no_match",
            query_effective=self._effective_query(channel, query),
        )
        self._cache.set(key, _page_to(empty))
        return empty

    def _run_tail(
        self, impl: Channel, spec: ChannelSpec, tail: Plan
    ) -> tuple[ActionOutcome, ...] | None:
        """Run the part of a split plan that reads the result, translating a refusal.

        A bad expression is answered with an alert instead of a result list, so this wait can
        only time out. The site says what is wrong in a sentence; reporting that is the
        difference between "your expression is invalid" and "nothing happened" (measured
        2026-11-24: `TS=(ionic OR electroactive) AND actuator` → 「布尔运算符的使用无效」).

        `None` means the site said the expression matched nothing. That is an answer, not a
        failure: the caller renders it as an empty page instead of an error.

        **The wait is taken in slices when the channel names an alert container.** The alert is
        not in the DOM when the click returns — measured 2026-11-25: one look right after the
        click passed in 2 ms with nothing there, and the refusal still cost 10.8 s of waiting
        for a result list that was never coming. Between slices the page is asked what it says,
        so whichever of "results are up" and "the site answered" happens first wins. Both polls
        are reads, so a slice costs a round trip and no quota.
        """

        alert_selector = getattr(impl, "alert_selector", None)
        first = tail.actions[0] if tail.actions else None
        polls_between_slices = (
            isinstance(alert_selector, str)
            and bool(alert_selector)
            and first is not None
            and first.verb == "wait_for"
        )
        if not polls_between_slices:
            return self._tail_once(impl, spec, tail)
        assert first is not None  # narrowed by `polls_between_slices`
        deadline = time.monotonic() + max(1, first.timeout_ms) / 1000
        last: ActionError | None = None
        while True:
            left_ms = int((deadline - time.monotonic()) * 1000)
            if left_ms <= 0:
                break
            slice_ms = min(ANSWER_SLICE_MS, left_ms)
            sliced = replace(
                first,
                params={**first.params, "timeout_ms": slice_ms},
                timeout_ms=slice_ms + 1_000,
            )
            try:
                return self._run(replace(tail, actions=(sliced, *tail.actions[1:])), spec)
            except ActionError as error:
                if error.stage != "wait.result-list":
                    raise
                last = error
            refusal, nothing_matched = self._site_diagnosis(impl, spec)
            if refusal is not None:
                raise ChannelError(
                    f"the site refused this query (query.rejected): {refusal}"
                ) from None
            if nothing_matched:
                return None
        if last is not None:
            raise last
        raise ActionError(
            "the result list never appeared",
            verb="wait_for",
            code="timeout",
            stage="wait.result-list",
        )

    def _tail_once(
        self, impl: Channel, spec: ChannelSpec, tail: Plan
    ) -> tuple[ActionOutcome, ...] | None:
        """The whole tail in one go, then one look at the page when the wait failed."""

        try:
            return self._run(tail, spec)
        except ActionError as error:
            # Only "the result list never appeared" can be the site refusing the query. An
            # export that produced no file is a different failure with its own message, and it
            # must not spend a step on a probe that cannot describe it.
            if error.stage != "wait.result-list":
                raise
            refusal, nothing_matched = self._site_diagnosis(impl, spec)
            if refusal is not None:
                raise ChannelError(
                    f"the site refused this query (query.rejected): {refusal}"
                ) from None
            if nothing_matched:
                return None
            raise

    def _site_diagnosis(self, impl: Channel, spec: ChannelSpec) -> tuple[str | None, bool]:
        """One free look at the page: was the expression refused, or did it match nothing?

        Both answers need the same `read_text` (not a network verb, so free), and asking twice
        would spend two actions on a failure path — the older tests caught exactly that.

        * a refusal is the site's own sentence ("布尔运算符的使用无效…"); before this probe the
          caller was told the result list never appeared, which is true and useless;
        * "no results" is not a refusal: both render the same alert, so the wording decides.
          When the channel names that alert, no wording list is needed at all — an alert that
          does not refuse the expression *is* the zero-hit notice — and that is what makes it
          work on a localized UI, where the empty wording is a sentence nobody has captured
          (2026-11-25: a Chinese zero-hit page was reported as a refused expression, quoting
          the search form's help panel, because the English-only wording list matched nothing
          and the whole page was read instead of the alert).
        """

        refusal_checker = getattr(impl, "query_error", None)
        empty_checker = getattr(impl, "is_empty_page", None)
        if refusal_checker is None and empty_checker is None:
            return (None, False)
        # `inner` is rendered text, so the alert container the site keeps in the DOM while it
        # is not showing anything reads as empty rather than as a message.
        alert_selector = getattr(impl, "alert_selector", None)
        if isinstance(alert_selector, str) and alert_selector:
            probe_action = Action("read_text", {"selector": alert_selector, "mode": "inner"})
        else:
            probe_action = Action("read_text", {"selector": "body", "mode": "text"})
        probe = Plan(
            channel=spec.name,
            purpose="probe",
            actions=(probe_action,),
        )
        try:
            outcomes = self._run(probe, spec)
        except ActionError:
            return (None, False)
        text = ""
        for outcome in outcomes:
            if outcome.action.verb == "read_text" and isinstance(outcome.data, dict):
                candidate = outcome.data.get("text")
                if isinstance(candidate, str):
                    text = candidate
        if not text.strip():
            return (None, False)
        if refusal_checker is not None:
            message = refusal_checker(text)
            if isinstance(message, str) and message.strip():
                return (message.strip(), False)
        if isinstance(alert_selector, str) and alert_selector:
            return (None, True)
        if empty_checker is not None and empty_checker(text):
            return (None, True)
        return (None, False)


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
    # Before any filter and before `limit`: what the fetch actually brought back. `total` is
    # the site's claim; the two together say whether a screen was read or the result set is
    # exhausted (2026-11-26 report P2-7).
    fetched = page.fetched if page.fetched is not None else len(records)
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
    span = query.records_span
    if span is not None:
        # A range names how many records the caller wants, and it overrides `limit` (which
        # defaults to 20). Trim to the contract: a page-turn channel can hand back more than
        # the span because its grid keeps filling while the plan runs — a 150-record range
        # returned 170 rows (measured 2026-11-22).
        records = records[: span[1] - span[0] + 1]
    elif len(records) > query.limit:
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
    return replace(
        page,
        returned=len(records),
        # What the fetch itself brought back, before the filters above and before `limit`.
        fetched=fetched,
        # "Is there more at the site than this fetch brought back?" Measured live 2026-11-24:
        # `limit: 3` against `total: 50` answered `truncated: false`, because the fetch had
        # pulled all 50 and only the *answer* was trimmed. The old test compared the answer to
        # `total`, so any local filter (a year range on a 20-record page with a 45-hit site)
        # also reported `truncated: true` and told the caller to go fetch what they already had
        # (2026-11-26 report P2-7). It compares the *fetch* now, and says `None` when the channel
        # never learnt the site's total.
        truncated=(
            False
            if query.records_span is not None
            else (None if page.total is None else fetched < page.total)
        ),
    )


def _last_url(outcomes: Sequence[ActionOutcome]) -> str | None:
    """The most recent URL any action reported, for judging where the tab ended up."""

    for outcome in reversed(outcomes):
        data = outcome.data if isinstance(outcome.data, dict) else {}
        candidate = outcome.url or data.get("url")
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


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
        # Two ways the extension reports that the click was taken: the control went busy and
        # came back (`settled`, the old "enabled" wait), or the tab's URL moved (`url_changed`,
        # the cheaper wait that WoS actually answers — 2026-11-24). Either is proof the site
        # started the query.
        settled = bool(data.get("settled")) or bool(data.get("url_changed"))
        return (url if isinstance(url, str) and url else None), settled
    return None, False


def _payloads(outcomes: Sequence[ActionOutcome]) -> list[str]:
    """Every page payload the plan produced, oldest first.

    A plan normally reads once. A record range on a channel without an export file reads
    per page instead (CNKI: turn, read, turn, read), and the pages have to be merged
    rather than silently keeping only the last one.
    """

    found: list[str] = []
    for outcome in outcomes:
        for key in ("html", "text"):
            value = outcome.data.get(key)
            if isinstance(value, str) and value:
                found.append(value)
                break
    return found


def _merge_pages(pages: Sequence[SearchPage]) -> SearchPage:
    """Join several pages of one range read into a single answer.

    A record that appears on two pages (the grid re-ordered between turns) is kept once, by
    `url` — the identifier both channels carry. `total` and `page_count` come from the first
    page that reports them: every page carries the same site-wide numbers, and the first one
    is as good as any.
    """

    records: list[Record] = []
    seen: set[str] = set()
    for page in pages:
        for record in page.records:
            marker = record.url or f"{record.title}|{record.year}"
            if marker in seen:
                continue
            seen.add(marker)
            records.append(record)
    first = pages[0]
    return replace(
        first,
        records=tuple(records),
        dropped_year=sum(page.dropped_year for page in pages),
        empty_reason=first.empty_reason if not records else None,
    )


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
