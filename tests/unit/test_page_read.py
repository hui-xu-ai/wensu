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
from scholar_search.core.service import ScholarService, _page_next
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


def test_doi_prefixes_map_to_the_right_publisher() -> None:
    assert publisher_for_doi("10.1016/j.cej.2023.145123").name == "elsevier"  # type: ignore[union-attr]
    assert publisher_for_doi("https://doi.org/10.1038/s41586-024-00001-0").name == "nature"  # type: ignore[union-attr]
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
    assert all(publisher.homepage.startswith("https://") for publisher in PUBLISHERS)


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


def test_next_asks_the_user_to_sign_in_instead_of_retrying() -> None:
    paywall = _page_next({"status": "no_html", "reason": "paywall"})
    abstract = _page_next({"status": "no_html", "reason": "abstract_only"})
    ok = _page_next({"status": "ok", "reason": ""})

    for hint in (paywall, abstract):
        assert "sign in" in hint
        assert "ask the user" in hint
        assert "page_read again" in hint
        assert "Do not retry" in hint
    assert "page2md" in ok


def test_page_read_takes_a_second_look_when_the_body_is_still_rendering(tmp_path: Path) -> None:
    """第一次抓到的是还没渲染出来的摘要（无 paywall 提示）：同一页再看一次，不问用户。"""

    abstract = write_mhtml(tmp_path / "unrendered.mhtml", UNRENDERED_HTML).read_bytes()
    full = write_mhtml(tmp_path / "full.mhtml", ARTICLE_HTML).read_bytes()
    scripts: list[list[dict[str, object]]] = [
        [
            {"verb": "goto", "data": {"url": "https://www.sciencedirect.com/"}},
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


def test_page_read_touches_the_home_page_in_a_throwaway_tab(tmp_path: Path) -> None:
    """首页只"碰一下"：新开的临时标签页由下一次 goto 关掉，最后只留文章页那一张。"""

    service = build_service(tmp_path, [[]])  # 事务会先钉一个 adapter
    seen: list[object] = []

    def fake_run(plan: object, spec: object) -> tuple[object, ...]:
        seen.append(plan)
        raise RuntimeError("stop here")  # 只看计划，不真的跑

    service._run = fake_run  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        service.read_page(doi="10.1016/j.cej.2023.145123")

    actions = seen[0].actions  # type: ignore[attr-defined]
    assert actions[0].verb == "goto"
    assert actions[0].params["open"] == "new"
    assert actions[0].params["url"] == "https://www.sciencedirect.com/"
    assert actions[0].params["dwell_ms"] == 600, "首页与空白页之间固定 0.6s"
    assert actions[1].verb == "goto"
    assert actions[1].params["close"] == "disposable"
    assert actions[1].params["url"] == "https://doi.org/10.1016/j.cej.2023.145123"


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


def test_page_read_navigates_home_then_article_and_classifies(tmp_path: Path) -> None:
    payload = write_mhtml(tmp_path / "source.mhtml", ARTICLE_HTML).read_bytes()
    scripts: list[list[dict[str, object]]] = [
        [
            {"verb": "goto", "data": {"url": "https://www.sciencedirect.com/"}},
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
    assert result["quota_charged"] == 2
    assert "page2md" in str(result["next"])
