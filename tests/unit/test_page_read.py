"""Page reading: the curated publisher list, the "is the article here" probe, and the
`page_read` flow (ADR 0019)."""

from __future__ import annotations

import base64
import email.mime.multipart
import email.mime.text
from pathlib import Path

from scholar_search.adapters.fixture import FixtureAdapter
from scholar_search.core.cache import Cache
from scholar_search.core.pageprobe import classify_mhtml
from scholar_search.core.planner import Planner
from scholar_search.core.policy import PolicyEngine
from scholar_search.core.publishers import (
    PUBLISHERS,
    publisher_domains,
    publisher_for_doi,
    publisher_for_host,
)
from scholar_search.core.risk import RiskGuard
from scholar_search.core.service import ScholarService
from support import FakeChannel, StubRegistry, make_manifest

ARTICLE_HTML = """<!DOCTYPE html><html><body>
<h1>A paper</h1>
<section id="s1"><h2>1. Introduction</h2><p>Text.</p></section>
<section id="s2"><h2>2. Results</h2><p>More text.</p></section>
<section id="s3"><h2>3. Conclusions</h2><p>Done.</p></section>
</body></html>"""

PAYWALL_HTML = """<!DOCTYPE html><html><body><h1>A paper</h1>
<p>Purchase PDF</p><p>Get access</p></body></html>"""


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
