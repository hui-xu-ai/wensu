"""Installed 0.14.29 checks. Synthetic files live only in temporary directories."""
from __future__ import annotations

import argparse
import base64
import email.mime.multipart
import email.mime.text
import json
import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import scholar_search
from scholar_search import page2md
from scholar_search.adapters.bridge import BridgeAdapter
from scholar_search.adapters.fixture import FixtureAdapter
from scholar_search.bootstrap import build_service
from scholar_search.core.audit import AuditLog
from scholar_search.core.cache import Cache
from scholar_search.core.contracts import Action, Plan
from scholar_search.core.errors import ActionError, PolicyError
from scholar_search.core.planner import Planner
from scholar_search.core.policy import PolicyEngine
from scholar_search.core.publishers import publisher_for_doi
from scholar_search.core.risk import RiskGuard
from scholar_search.core.service import ScholarService, _page_spec

DOI = "10.1002/pen.23634"
URL = f"https://onlinelibrary.wiley.com/doi/{DOI}"
ARTICLE = '<html><body><section id="s"><h2>1. Introduction</h2><p>Synthetic body text.</p></section></body></html>'


def mhtml(html: str) -> bytes:
    outer = email.mime.multipart.MIMEMultipart("related")
    outer.attach(email.mime.text.MIMEText(html, "html", "utf-8"))
    return outer.as_bytes()


def capture(html: str, url: str = URL, title: str = "Article") -> dict[str, Any]:
    blob = mhtml(html)
    return {"verb": "snapshot", "data": {"token": "synthetic", "total": len(blob),
        "base64": base64.b64encode(blob).decode(), "url": url, "title": title,
        "captcha_visible": False}}


def fixture_service(p: Path, steps: list[dict[str, Any]]) -> ScholarService:
    p.mkdir(parents=True)
    clock = [0.0]
    def sleep(seconds: float) -> None:
        clock[0] += seconds
    policy = PolicyEngine(state_path=p / "state/quota.json", clock=lambda: clock[0],
                          sleeper=sleep, jitter=lambda: 0)
    risk = RiskGuard(state_path=p / "state/cooldown.json")
    audit = AuditLog(path=p / "audit.jsonl")
    return ScholarService(registry=None, adapter_factory=lambda: FixtureAdapter(steps),
        planner_factory=lambda a: Planner(a, policy, risk, audit), policy=policy,
        risk=risk, cache=Cache(path=p / "cache.sqlite3"), bridge_probe=lambda: True)


def nav(title: str = "Article") -> list[dict[str, Any]]:
    # Installed private patch has two navigations. Nothing is executed against a browser.
    return [{"verb": "goto", "data": {"url": "https://onlinelibrary.wiley.com/"}},
            {"verb": "goto", "data": {"url": URL, "title": title}}]


def offline(root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    quota_home = root / "quota"
    quota_home.mkdir()
    state = quota_home / "quota.json"
    state.write_text(json.dumps({"day": date.today().isoformat(), "used": -20}), encoding="utf-8")
    policy = PolicyEngine(state_path=state)
    refused = False
    try:
        policy.wait_turn()
    except PolicyError:
        refused = True
    result["F11"] = {"remaining": policy.remaining_today, "state_error": policy.state_error,
        "network_slot_refused": refused, "state_unchanged": json.loads(state.read_text())["used"] == -20}

    token_home = root / "token"
    token_home.mkdir()
    (token_home / "http-token").write_text("", encoding="utf-8")
    completed = subprocess.run([sys.executable, "-m", "scholar_search.cli", "serve",
        "--transport", "http", "--port", "0"],
        env={**os.environ, "SCHOLAR_SEARCH_HOME": str(token_home)},
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
    result["F12"] = {"http_start_exit": completed.returncode,
        "unusable_token_error": "unusable token" in completed.stderr,
        "empty_token_unchanged": (token_home / "http-token").stat().st_size == 0}

    doc = root / "images/doc"
    doc.mkdir(parents=True)
    outside = doc.parent / "outside.png"
    outside.write_bytes(b"SYNTHETIC OUTSIDE IMAGE")
    (doc / "inside.png").write_bytes(b"SYNTHETIC INSIDE IMAGE")
    source = doc / "article.html"
    refs = ["../outside.png", outside.as_posix(), "inside.png"]
    source.write_text('<html><body><section id="s"><h2>1. Introduction</h2><p>Synthetic paper.</p>'
        + ''.join(f'<figure><img src="{ref}"><figcaption>Figure {i}</figcaption></figure>'
                  for i, ref in enumerate(refs, 1)) + '</section></body></html>', encoding="utf-8")
    out = root / "images/output"
    meta = page2md.convert(source, out)
    copied = [p for p in (out / "assets").glob("*") if p.is_file()]
    result["F01"] = {"images_missing": meta.get("images_missing"),
        "images_copied": meta.get("images_copied"),
        "outside_bytes_copied": any(p.read_bytes() == outside.read_bytes() for p in copied),
        "inside_image_copied": (out / "assets/inside.png").is_file()}

    for label, body, snap_title in [
        ("persistent_wall", "<html><body>Verifying you are human. Just a moment.</body></html>", "Just a moment..."),
        ("transient_title", ARTICLE, "Article"),
    ]:
        service = fixture_service(root / label,
            [*nav("Just a moment..."), {"verb": "sleep"}, capture(body, title=snap_title)])
        answer = service.read_page(doi=DOI)
        result[label] = {k: answer.get(k) for k in ["status", "reason", "full_text", "mhtml_path", "quota_charged"]}

    # The prior cross-site example had no citation_doi: retain that exact boundary case.
    service = fixture_service(root / "identity_missing_metadata",
        [*nav(), {"verb": "sleep"}, capture(ARTICLE, "https://pubs.acs.org/doi/10.1021/unrelated")])
    answer = service.read_page(doi=DOI)
    result["F05_cross_site_without_metadata"] = {k: answer.get(k) for k in ["status", "reason", "full_text", "captured_url"]}

    contradicted = ARTICLE.replace('<html>', '<html><head><meta name="citation_doi" content="10.1021/unrelated"></head>')
    service = fixture_service(root / "identity_contradicted",
        [*nav(), {"verb": "sleep"}, capture(contradicted, "https://pubs.acs.org/doi/10.1021/unrelated")])
    answer = service.read_page(doi=DOI)
    result["F05_contradictory_metadata"] = {k: answer.get(k) for k in ["status", "reason", "full_text", "mhtml_path"]}

    paywall = '<html><body><h1>Article</h1><p>Purchase PDF</p></body></html>'
    service = fixture_service(root / "open_tab_paywall", [capture(paywall)])
    service._page_cache_put(f"https://doi.org/{DOI}", {"status": "blocked"})
    answer = service.read_page(doi=DOI)
    result["F06"] = {k: answer.get(k) for k in ["status", "reason", "full_text", "source", "quota_charged"]}

    full_url = f"https://onlinelibrary.wiley.com/doi/full/{DOI}"
    landing = paywall.replace('<body>', f'<head><meta name="citation_fulltext_html_url" content="{full_url}"></head><body>')
    service = fixture_service(root / "full_view_403", [*nav(), {"verb": "sleep"}, capture(landing),
        {"verb": "goto", "data": {"url": "https://onlinelibrary.wiley.com/"}},
        {"verb": "goto", "data": {"url": full_url, "status": 403}}])
    answer = service.read_page(doi=DOI, view="full")
    result["F07"] = {"status": answer.get("status"), "signal": answer.get("signal"),
        "reported_charge": answer.get("quota_charged"), "actual_charge": service._policy.used_today,
        "has_cooldown": bool(answer.get("cooldown_until"))}

    service = fixture_service(root / "full_view_snapshot_wall", [*nav(), {"verb": "sleep"}, capture(landing),
        {"verb": "goto", "data": {"url": "https://onlinelibrary.wiley.com/"}},
        {"verb": "goto", "data": {"url": full_url, "title": "Article"}},
        capture("<html>Verifying you are human. Just a moment.</html>", full_url, "Just a moment...")])
    answer = service.read_page(doi=DOI, view="full")
    result["F07_followup_snapshot_wall"] = {"status": answer.get("status"), "reason": answer.get("reason"),
        "reported_charge": answer.get("quota_charged"), "actual_charge": service._policy.used_today,
        "mhtml_path_is_null": answer.get("mhtml_path") is None}

    collision = root / "collision"
    (collision / "a").mkdir(parents=True)
    (collision / "b").mkdir()
    (collision / "a/figure.png").write_bytes(b"FIRST FIGURE")
    (collision / "b/figure.png").write_bytes(b"SECOND FIGURE")
    mapped, count, missing = page2md._localise_images(
        "![a](a/figure.png) ![b](b/figure.png)", collision / "page.html", collision / "out")
    result["F10_local_same_basename"] = {"both_refs_same_output": mapped.count("assets/figure.png") == 2,
        "copied": count, "missing": missing,
        "second_overwrote_first": (collision / "out/assets/figure.png").read_bytes() == b"SECOND FIGURE"}
    return result


def capability() -> dict[str, Any]:
    service = build_service()
    adapter = BridgeAdapter()
    publisher = publisher_for_doi("10.3390/s26041303")
    assert publisher is not None
    plan = Plan(channel="page:mdpi", purpose="probe",
        actions=(Action("goto", {"url": "https://www.mdpi.com/1424-8220/26/4/1303"}),
                 Action("wait_for", {"selector": "body", "timeout_ms": 1000})))
    before = service._policy.used_today
    cold_info = adapter.info()
    cold_rejected = False
    try:
        service._ensure_capabilities(adapter, plan)
    except ActionError as error:
        cold_rejected = error.code == "action.unsupported"
    # A deliberately nonexistent continuation token triggers protocol hello, but never captures
    # or reads a tab. It sends no request to the site and consumes no policy quota.
    handshake = adapter.execute(Action("snapshot", {"token": "audit-no-such-capture", "offset": 0}), timeout_ms=3000)
    warm_info = adapter.info()
    adapter.close()
    code = None
    executed = [0]
    original_factory = service._adapter_factory
    class Counting:
        def __init__(self) -> None:
            self.inner = original_factory()
        def pin(self) -> Any:
            return self.inner.pin()
        def info(self) -> Any:
            return self.inner.info()
        def execute(self, action: Action, *, timeout_ms: int) -> Any:
            executed[0] += 1
            # Even a broken capability gate must not turn this rejection test into a navigation.
            raise ActionError("test harness refused to send any action", verb=action.verb,
                              code="probe.execution_prevented")
        def close(self) -> None:
            self.inner.close()
    service._adapter_factory = Counting
    try:
        with service._browser_transaction():
            service._run(plan, _page_spec(publisher))
    except ActionError as error:
        code = error.code
    return {"cold_build": cold_info, "cold_gate_rejected": cold_rejected,
        "handshake_probe_error": handshake.error, "warm_build": warm_info,
        "warm_gate_code": code, "actions_executed": executed[0],
        "quota_delta": service._policy.used_today - before}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["offline", "capability"])
    args = parser.parse_args()
    assert scholar_search.__version__ == "0.14.29"
    if args.mode == "offline":
        with tempfile.TemporaryDirectory(prefix="wensu-01429-") as directory:
            result = offline(Path(directory))
    else:
        result = capability()
    private = Path(os.environ["LOCALAPPDATA"]) / "scholar-search/verification/2026-11-26-codex-0.14.29"
    private.mkdir(parents=True, exist_ok=True)
    (private / f"{args.mode}-checks.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"version": scholar_search.__version__, "checks": result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
