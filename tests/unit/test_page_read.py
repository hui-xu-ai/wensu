"""Page reading: the curated publisher list, the "is the article here" probe, and the
`page_read` flow (ADR 0019)."""

from __future__ import annotations

import base64
import email.mime.multipart
import email.mime.text
from pathlib import Path

import pytest

from scholar_search.adapters.fixture import FixtureAdapter
from scholar_search.core.cache import Cache
from scholar_search.core.pageprobe import classify_mhtml
from scholar_search.core.params import validate_params
from scholar_search.core.planner import Planner
from scholar_search.core.policy import PolicyEngine
from scholar_search.core.publishers import (
    PUBLISHERS,
    publisher_domains,
    publisher_for_doi,
    publisher_for_host,
)
from scholar_search.core.risk import RiskGuard
from scholar_search.core.service import ScholarService, _page_full_text, _page_next
from support import FakeChannel, StubRegistry, make_manifest

ARTICLE_HTML = """<!DOCTYPE html><html><body>
<h1>A paper</h1>
<section id="s1"><h2>1. Introduction</h2><p>Text.</p></section>
<section id="s2"><h2>2. Results</h2><p>More text.</p></section>
<section id="s3"><h2>3. Conclusions</h2><p>Done.</p></section>
</body></html>"""

PAYWALL_HTML = """<!DOCTYPE html><html><body><h1>A paper</h1>
<p>Purchase PDF</p><p>Get access</p></body></html>"""

# Same shell, but with no sign-in prompt at all: this is a page that is still painting,
# which is what a capture taken right after the load event sees.
UNRENDERED_HTML = """<!DOCTYPE html><html><body><h1>A paper</h1>
<section id="u1"><h2>Highlights</h2><p>Short teaser.</p></section>
<section id="u2"><h2>Abstract</h2><p>Some abstract text.</p></section>
</body></html>"""
# `<section id=…>`, so counting those wrappers called it a full article (0.12.58, real run).
# What it does not have is the article's own numbering.
ABSTRACT_HTML = """<!DOCTYPE html><html><body>
<h1>A paper</h1>
<section id="a1"><h2>Highlights</h2><p>Short teaser.</p></section>
<section id="a2"><h2>Abstract</h2><p>Some abstract text.</p></section>
<section id="a3"><div class="section-title">Model description</div><p>Snippet.</p></section>
<section id="a4"><div class="section-title">Conclusions</div><p>Snippet.</p></section>
<section id="a5"><div class="section-title">Recommended articles</div><p>Others.</p></section>
<section id="a6"><p>Sign in to view the full text.</p></section>
</body></html>"""


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def build_service(tmp_path: Path, scripts: list[list[dict[str, object]]]) -> ScholarService:
    clock = FakeClock()
    policy = PolicyEngine(clock=clock.time, sleeper=clock.sleep, state_path=tmp_path / "quota.json")
    risk = RiskGuard(state_path=tmp_path / "cooldown.json")
    from scholar_search.core.audit import AuditLog

    audit = AuditLog(path=tmp_path / "audit.jsonl")

    def factory() -> FixtureAdapter:
        return FixtureAdapter(scripts.pop(0))

    return ScholarService(
        registry=StubRegistry(FakeChannel(manifest=make_manifest(), records=[])),  # type: ignore[arg-type]
        adapter_factory=factory,
        planner_factory=lambda adapter: Planner(adapter, policy, risk, audit),
        policy=policy,
        cache=Cache(path=tmp_path / "cache.sqlite3"),
        bridge_probe=lambda: True,
    )


def write_mhtml(path: Path, html: str) -> Path:
    part = email.mime.text.MIMEText(html, "html", "utf-8")
    outer = email.mime.multipart.MIMEMultipart("related")
    outer.attach(part)
    path.write_bytes(outer.as_bytes())
    return path


def test_view_full_follows_the_pages_own_fulltext_url(tmp_path: Path) -> None:
    """A landing page that shows only the abstract often names the view that has the body.

    ACS lands on `/jacsat/article/…` with the Abstract tab active and injects the article only in
    its full-text view (2026-11-26 report P1-4). The address comes from the page's own
    `<meta name="citation_fulltext_html_url">`, so no per-publisher template table is needed.
    """

    landing = (
        "<!DOCTYPE html><html><head>"
        '<meta name="citation_fulltext_html_url" content="https://pubs.acs.org/doi/full/10.1021/jacs.6c13448"/>'
        "</head><body><h1>A paper</h1>"
        '<section id="a1"><h2>Abstract</h2><p>Short teaser only, no body.</p></section>'
        "</body></html>"
    )
    full = (
        "<!DOCTYPE html><html><body><h1>A paper</h1>"
        '<section id="s1"><h2>1. Introduction</h2><p>Body text a reader came for.</p></section>'
        "</body></html>"
    )
    landing_blob = write_mhtml(tmp_path / "landing.mhtml", landing).read_bytes()
    full_blob = write_mhtml(tmp_path / "full.mhtml", full).read_bytes()

    def reply(blob: bytes, url: str, title: str) -> dict[str, object]:
        return {
            "verb": "snapshot",
            "data": {
                "token": "t1",
                "total": len(blob),
                "base64": base64.b64encode(blob).decode("ascii"),
                "url": url,
                "title": title,
                "captcha_visible": False,
            },
        }

    service = build_service(
        tmp_path,
        [
            [
                {"verb": "goto", "data": {"url": "https://doi.org/10.1021/jacs.6c13448"}},
                {"verb": "sleep", "data": {"ms": 1}},
                reply(landing_blob, "https://pubs.acs.org/doi/10.1021/jacs.6c13448", "A paper"),
                # the abstract page triggers one extra look at the same tab
                {"verb": "sleep", "data": {"ms": 1_500}},
                reply(landing_blob, "https://pubs.acs.org/doi/10.1021/jacs.6c13448", "A paper"),
                {
                    "verb": "goto",
                    "data": {"url": "https://pubs.acs.org/doi/full/10.1021/jacs.6c13448"},
                },
                reply(full_blob, "https://pubs.acs.org/doi/full/10.1021/jacs.6c13448", "A paper"),
            ]
        ],
    )

    result = service.read_page(doi="10.1021/jacs.6c13448", view="full")

    assert result["status"] == "ok", result
    assert result["view_applied"] is True, result
    assert result["fulltext_url"] == "https://pubs.acs.org/doi/full/10.1021/jacs.6c13448"
    # Two navigations ran; the captures are free.
    assert result["quota_charged"] == 2, result


def test_the_default_view_navigates_once_even_when_the_page_names_a_fulltext_url(
    tmp_path: Path,
) -> None:
    """Opt-in, because the second look costs a navigation."""

    landing = (
        "<!DOCTYPE html><html><head>"
        '<meta name="citation_fulltext_html_url" content="https://pubs.acs.org/doi/full/x"/>'
        "</head><body><h1>A paper</h1>"
        '<section id="a1"><h2>Abstract</h2><p>Short teaser only, no body.</p></section>'
        "</body></html>"
    )
    blob = write_mhtml(tmp_path / "landing.mhtml", landing).read_bytes()
    service = build_service(
        tmp_path,
        [
            [
                {"verb": "goto", "data": {"url": "https://doi.org/10.1021/jacs.6c13448"}},
                {"verb": "sleep", "data": {"ms": 1}},
                {
                    "verb": "snapshot",
                    "data": {
                        "token": "t1",
                        "total": len(blob),
                        "base64": base64.b64encode(blob).decode("ascii"),
                        "url": "https://pubs.acs.org/doi/10.1021/jacs.6c13448",
                        "title": "A paper",
                        "captcha_visible": False,
                    },
                },
                {"verb": "sleep", "data": {"ms": 1_500}},
                {
                    "verb": "snapshot",
                    "data": {
                        "token": "t1",
                        "total": len(blob),
                        "base64": base64.b64encode(blob).decode("ascii"),
                        "url": "https://pubs.acs.org/doi/10.1021/jacs.6c13448",
                        "title": "A paper",
                        "captcha_visible": False,
                    },
                },
            ]
        ],
    )

    result = service.read_page(doi="10.1021/jacs.6c13448")

    assert result["status"] == "no_html", result
    assert result["view_applied"] is False, result
    assert result["quota_charged"] == 1, result


def test_a_capture_that_names_another_doi_is_not_this_articles_answer(tmp_path: Path) -> None:
    """The tab can move between the navigation and the snapshot (audit F05).

    Two different articles on the same publisher look identical to a `status: ok` check, so the
    page's own `citation_doi` decides. Contradictory evidence is a failure the caller can read,
    not a success it has to notice.
    """

    other = (
        '<html><head><meta name="citation_doi" content="10.1002/anie.201102901"/></head>'
        '<body><h1>Another paper</h1><section id="s1"><h2>1. Introduction</h2>'
        "<p>Body text of a different article.</p></section></body></html>"
    )
    blob = write_mhtml(tmp_path / "other.mhtml", other).read_bytes()
    service = build_service(
        tmp_path,
        [
            [
                {
                    "verb": "goto",
                    "data": {"url": "https://onlinelibrary.wiley.com/doi/10.1002/pen.23634"},
                },
                {"verb": "sleep", "data": {"ms": 1}},
                {
                    "verb": "snapshot",
                    "data": {
                        "token": "t1",
                        "total": len(blob),
                        "base64": base64.b64encode(blob).decode("ascii"),
                        "url": "https://onlinelibrary.wiley.com/doi/10.1002/anie.201102901",
                        "title": "Another paper",
                        "captcha_visible": False,
                    },
                },
            ]
        ],
    )

    result = service.read_page(doi="10.1002/pen.23634")

    assert result["status"] == "no_page", result
    assert result["reason"] == "capture_mismatch", result
    assert result["declared_doi"] == "10.1002/anie.201102901", result
    assert result["full_text"] is False, result
    assert not list(tmp_path.rglob("page.mhtml")), "another article's bytes must not be kept"


def test_doi_prefixes_map_to_the_right_publisher() -> None:
    assert publisher_for_doi("10.1016/j.cej.2023.145123").name == "elsevier"  # type: ignore[union-attr]
    assert publisher_for_doi("https://doi.org/10.1038/s41586-024-00001-0").name == "nature"  # type: ignore[union-attr]
    # 《物理化学学报》 was answered `unsupported_site` (2026-11-26 report P2-9).
    assert publisher_for_doi("10.3866/PKU.WHXB201912007").name == "pku-whxb"  # type: ignore[union-attr]
    assert publisher_for_doi("10.9999/unknown") is None


def test_hosts_match_subdomains_only() -> None:
    assert publisher_for_host("www.sciencedirect.com").name == "elsevier"  # type: ignore[union-attr]
    assert publisher_for_host("sciencedirect.com").name == "elsevier"  # type: ignore[union-attr]
    # `notsciencedirect.com` must not pass: the matcher is `host == domain or endswith(.domain)`
    assert publisher_for_host("notsciencedirect.com") is None


def test_every_publisher_is_https_and_deduplicated() -> None:
    hosts = publisher_domains()

    assert len(hosts) == len(set(hosts))
    assert all("://" not in host for host in hosts)
    assert all(publisher.domains and "." in publisher.domains[0] for publisher in PUBLISHERS)


def test_probe_accepts_a_full_text_page(tmp_path: Path) -> None:
    result = classify_mhtml(write_mhtml(tmp_path / "ok.mhtml", ARTICLE_HTML))

    assert result["status"] == "ok"
    assert result["sections"] == 3


def test_probe_reports_a_paywall_page(tmp_path: Path) -> None:
    result = classify_mhtml(write_mhtml(tmp_path / "paywall.mhtml", PAYWALL_HTML))

    assert result["status"] == "no_html"
    assert result["reason"] == "paywall"
    assert result["paywall_hits"] >= 2


def test_probe_rejects_an_abstract_page_that_wraps_sections(tmp_path: Path) -> None:
    """摘要页也有 `<section id=…>` 外壳：判据必须是"有没有编号文章标题"。"""

    result = classify_mhtml(write_mhtml(tmp_path / "abstract.mhtml", ABSTRACT_HTML))

    assert result["sections"] >= 3  # 外壳很多，正是误判来源
    assert result["headings"] == 0
    assert result["status"] == "no_html"
    assert result["reason"] == "paywall"


def test_next_does_not_blame_the_readers_permissions() -> None:
    """`no_html` used to advise "ask the user to sign in" for every reason.

    2026-11-26 report: a site that only offers a PDF, and a page that simply has no HTML body,
    were both reported as "no institutional access". The advice must say *not read*, and name
    the routes that actually exist.
    """

    for reason in ("paywall", "abstract_only", "pdf_only"):
        hint = _page_next({"status": "no_html", "reason": reason})
        assert "sign in" not in hint.lower(), hint
        assert "no access" in hint, hint  # named only as the thing this is not
        assert "pdf_url" in hint, hint
        assert len(hint) <= 300, hint
    assert "page2md" in _page_next({"status": "ok", "reason": ""})


def test_full_text_is_the_field_to_branch_on() -> None:
    """One field answers the question the caller actually asked."""

    read = _page_full_text({"status": "ok"})
    assert read["full_text"] is True
    assert "full_text_reason" not in read

    for status, reason in (
        ("no_html", "paywall"),
        ("no_html", "pdf_only"),
        ("no_html", "abstract_only"),
        ("unsupported_site", "no curated publisher matches"),
        ("blocked", "challenge"),
    ):
        answered = _page_full_text({"status": status, "reason": reason})
        assert answered["full_text"] is False, answered
        assert answered["full_text_reason"] == reason, answered
        # The older fields are untouched: existing callers must not break.
        assert answered["status"] == status

    # A payload with no reason still names something.
    assert _page_full_text({"status": "blocked"})["full_text_reason"] == "blocked"


def test_a_pdf_only_landing_page_says_pdf_only(tmp_path: Path) -> None:
    """A site that offers only the PDF is neither an abstract nor a permission problem."""

    html = (
        "<!DOCTYPE html><html><body><h1>A paper</h1>"
        '<p><a href="https://example.org/article.pdf">Download PDF</a></p></body></html>'
    )
    result = classify_mhtml(write_mhtml(tmp_path / "pdfonly.mhtml", html))

    assert result["status"] == "no_html", result
    assert result["reason"] == "pdf_only", result
    assert str(result["pdf_url"]).endswith(".pdf"), result


def test_a_paywall_answer_points_at_a_file_it_actually_wrote(tmp_path: Path) -> None:
    """Report L32: a `no_html` answer carried a byte count and a path, and `page2md` found no file.

    Paywall / abstract captures *are* kept — they are what `page2md` can still summarise — so the
    path must name a file that exists. (The byte count describes the bridge reply, before
    `<script>` stripping, which is why it is never compared to the file size.)
    """

    paywall = write_mhtml(tmp_path / "paywall.mhtml", PAYWALL_HTML).read_bytes()
    service = build_service(
        tmp_path,
        [
            [
                {
                    "verb": "goto",
                    "data": {"url": "https://onlinelibrary.wiley.com/doi/10.1002/pen.23634"},
                },
                {"verb": "sleep", "data": {"ms": 1}},
                {
                    "verb": "snapshot",
                    "data": {
                        "token": "t1",
                        "total": len(paywall),
                        "base64": base64.b64encode(paywall).decode("ascii"),
                        "url": "https://onlinelibrary.wiley.com/doi/10.1002/pen.23634",
                        "title": "A paper",
                        "captcha_visible": False,
                    },
                },
            ]
        ],
    )

    result = service.read_page(doi="10.1002/pen.23634")

    assert result["status"] == "no_html", result
    assert result["full_text"] is False, result
    assert result["mhtml_path"], result
    assert Path(str(result["mhtml_path"])).is_file(), result


def test_page_read_takes_a_second_look_when_the_body_is_still_rendering(tmp_path: Path) -> None:
    """第一次抓到的是还没渲染出来的摘要（无 paywall 提示）：同一页再看一次，不问用户。"""

    abstract = write_mhtml(tmp_path / "unrendered.mhtml", UNRENDERED_HTML).read_bytes()
    full = write_mhtml(tmp_path / "full.mhtml", ARTICLE_HTML).read_bytes()
    scripts: list[list[dict[str, object]]] = [
        [
            {
                "verb": "goto",
                "data": {"url": "https://www.sciencedirect.com/science/article/pii/X"},
            },
            {"verb": "sleep", "data": {"ms": 1_200}},
            {
                "verb": "snapshot",
                "data": {
                    "token": "t1",
                    "total": len(abstract),
                    "base64": base64.b64encode(abstract).decode("ascii"),
                    "url": "https://www.sciencedirect.com/science/article/pii/X",
                    "title": "A paper",
                    "captcha_visible": False,
                },
            },
            {"verb": "sleep", "data": {"ms": 1_500}},
            {
                "verb": "snapshot",
                "data": {
                    "token": "t2",
                    "total": len(full),
                    "base64": base64.b64encode(full).decode("ascii"),
                    "url": "https://www.sciencedirect.com/science/article/pii/X",
                    "title": "A paper",
                    "captcha_visible": False,
                },
            },
        ]
    ]
    service = build_service(tmp_path, scripts)

    result = service.read_page(doi="10.1016/j.cej.2023.145123")

    assert result["status"] == "ok"
    assert result["headings"] >= 1


def test_page_read_deep_links_without_a_front_page_warm_up(tmp_path: Path) -> None:
    """发布版只做一步深链：计划里不得出现任何预热式导航（0.13.7 起）。

    私有版要恢复时只需把两行 Action 补回去；`goto` 的 `open`/`close`/`wait` 参数仍在，
    所以恢复不需要改扩展。
    """

    service = build_service(tmp_path, [[]])  # 事务会先钉一个 adapter
    seen: list[object] = []

    def fake_run(plan: object, spec: object) -> tuple[object, ...]:
        seen.append(plan)
        raise RuntimeError("stop here")

    service._run = fake_run  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        service.read_page(doi="10.1016/j.cej.2023.145123")

    # The navigation is its own plan: what `goto` returns decides whether anything else may
    # run at all (a wall must stop the tool, ADR 0004). This fake raises on that first plan,
    # so exactly one is observed — and it has to be the deep link alone.
    assert len(seen) == 1, seen
    first = seen[0]
    actions = first.actions  # type: ignore[attr-defined]
    assert [action.verb for action in actions] == ["goto"]
    assert actions[0].params["url"] == "https://doi.org/10.1016/j.cej.2023.145123"
    assert "open" not in actions[0].params, "发布版不得出现预热式导航"
    assert "https://www.sciencedirect.com/" not in str(actions)


def test_goto_accepts_the_transient_tab_parameters() -> None:
    assert validate_params("goto", {"url": "https://www.sciencedirect.com/", "open": "new"}) is None
    assert validate_params("goto", {"url": "https://doi.org/10/x", "close": "disposable"}) is None
    assert validate_params("goto", {"url": "https://doi.org/10/x", "dwell_ms": 250}) is None
    assert validate_params("goto", {"url": "https://doi.org/10/x", "open": "everywhere"})
    assert validate_params("goto", {"url": "https://doi.org/10/x", "close": "all"})
    assert validate_params("goto", {"url": "https://doi.org/10/x", "dwell_ms": 9_000})
    assert validate_params("goto", {"url": "https://doi.org/10/x", "dwell_ms": True})


def test_page_read_refuses_an_unsupported_doi_without_opening_anything(tmp_path: Path) -> None:
    service = build_service(tmp_path, [])

    result = service.read_page(doi="10.9999/whatever")

    assert result["status"] == "unsupported_site"
    assert "publishers" in result


def test_page_read_deep_links_then_classifies(tmp_path: Path) -> None:
    payload = write_mhtml(tmp_path / "source.mhtml", ARTICLE_HTML).read_bytes()
    scripts: list[list[dict[str, object]]] = [
        [
            {
                "verb": "goto",
                "data": {"url": "https://www.sciencedirect.com/science/article/pii/X"},
            },
            # 正文是渲染出来的：内核在抓之前会等一次（0.12.59 真实链路：不等只抓到 Highlight）。
            {"verb": "sleep", "data": {"ms": 1_200}},
            {
                "verb": "snapshot",
                "data": {
                    "token": "t1",
                    "total": len(payload),
                    "base64": base64.b64encode(payload).decode("ascii"),
                    "url": "https://www.sciencedirect.com/science/article/pii/X",
                    "title": "A paper",
                    "captcha_visible": False,
                },
            },
        ]
    ]
    service = build_service(tmp_path, scripts)

    result = service.read_page(doi="10.1016/j.cej.2023.145123")

    assert result["status"] == "ok"
    assert result["publisher"] == "elsevier"
    # The kernel writes the page itself; there is no download folder in the way.
    assert str(result["mhtml_path"]).endswith("page.mhtml")
    assert Path(str(result["mhtml_path"])).is_file()
    # One `goto` costs one unit; the capture costs nothing (policy.py: NETWORK_VERBS only).
    assert result["quota_charged"] == 1, result
    assert result["quota_reason"] == "navigate", result
    assert "page2md" in str(result["next"])
