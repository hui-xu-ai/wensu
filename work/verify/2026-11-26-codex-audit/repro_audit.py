"""Offline audit probes. Synthetic inputs only; no browser or network requests.

Run with the repository .venv Python and an external SCHOLAR_SEARCH_HOME.
The JSON output records observed defects, not a regression suite for corrected code.
"""

from __future__ import annotations

import base64
import concurrent.futures
import email.encoders
import email.mime.base
import email.mime.multipart
import email.mime.text
import importlib.util
import json
import os
import socket
import sys
import tempfile
import threading
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "tests/unit")]

from scholar_search import page2md
from scholar_search.adapters.bridge.policy import validate_request
from scholar_search.core.contracts import Action, ActionOutcome, Plan
from scholar_search.core.policy import PolicyEngine
from scholar_search.core.risk import RiskGuard
from scholar_search.transports.http import load_token
from test_page_read import ARTICLE_HTML, PAYWALL_HTML, build_service, write_mhtml

DOI = "10.1002/pen.23634"
URL = f"https://onlinelibrary.wiley.com/doi/{DOI}"
FULL = f"https://onlinelibrary.wiley.com/doi/full/{DOI}"


def capture(blob: bytes, url: str = URL, title: str = "Audit article") -> dict[str, Any]:
    return {"verb": "snapshot", "data": {
        "token": "synthetic", "total": len(blob),
        "base64": base64.b64encode(blob).decode("ascii"),
        "url": url, "title": title, "captcha_visible": False,
    }}


def goto(url: str = URL, **data: Any) -> dict[str, Any]:
    return {"verb": "goto", "data": {"url": url, **data}}


def risk_signals(p: Path) -> dict[str, Any]:
    guard = RiskGuard(state_path=p / "cooldown.json")
    result = {}
    for name, url, data in [
        ("verify_redirect", "https://kns.cnki.net/verify/home", {}),
        ("login_redirect", "https://fsso.cnki.net/login", {"auth_required": True}),
        ("denied_title", URL, {"title": "Access Denied"}),
        ("http_403", URL, {"status": 403}),
        ("captcha", URL, {"captcha_visible": True}),
    ]:
        signal = guard.inspect(ActionOutcome(Action("goto", {"url": url}), True, data, url=url))
        result[name] = {"signal": signal.value if signal else None,
                        "note": getattr(guard, "last_note", None)}
    return result


def bridge_empty_scope(p: Path) -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("audit_native_main", ROOT / "native-host/main.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    seen: list[Any] = []

    class Host:
        def request(self, action: str, params: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
            seen.append(kwargs.get("domains"))
            error = validate_request({"action": action, "params": params}, kwargs.get("domains"))
            return {"ok": error is None, "error": error}

    client, server = socket.socketpair()
    client.settimeout(3)
    worker = threading.Thread(target=mod.serve_client,
        args=(server, Host(), "synthetic-token", ("kns.cnki.net",)), daemon=True)
    worker.start()
    request = {"token": "synthetic-token", "action": "goto",
               "params": {"url": "https://kns.cnki.net/"}, "domains": ["outside.invalid"]}
    client.sendall((json.dumps(request) + "\n").encode())
    reply = json.loads(client.recv(4096))
    client.close()
    worker.join(3)
    return {"requested_scope": ["outside.invalid"], "passed_to_host": seen,
            "reply": reply}


def image_boundaries(p: Path) -> dict[str, Any]:
    p.mkdir()
    source_dir = p / "input"
    source_dir.mkdir()
    source = source_dir / "article.html"
    secret = p / "synthetic-private.txt"
    secret.write_text("SYNTHETIC AUDIT SENTINEL", encoding="utf-8")
    source.write_text('<html><body><section id="s1"><h2>1. Introduction</h2>'
        '<p>Article text for an offline audit.</p><figure>'
        '<img src="../synthetic-private.txt"><figcaption>Figure 1.</figcaption>'
        '</figure></section></body></html>', encoding="utf-8")
    out = p / "converted"
    page2md.convert(source, out)
    copied = out / "assets" / secret.name
    # Windows treats backslashes in the MHTML Content-Location basename as path separators.
    malicious_location = r"https://assets.invalid/..\..\escaped.txt"
    outer = email.mime.multipart.MIMEMultipart("related")
    outer.attach(email.mime.text.MIMEText('<html><body><section id="s1"><h2>1. Introduction</h2>'
        f'<p>Synthetic article.</p><figure><img src="{malicious_location}">'
        '<figcaption>Figure 1.</figcaption></figure></section></body></html>', "html", "utf-8"))
    resource = email.mime.base.MIMEBase("image", "png")
    resource.add_header("Content-Location", malicious_location)
    resource.set_payload(b"SYNTHETIC ESCAPE")
    email.encoders.encode_base64(resource)
    outer.attach(resource)
    malicious_source = source_dir / "parts.mhtml"
    malicious_source.write_bytes(outer.as_bytes())
    page2md.convert(malicious_source, p / "mhtml-out")
    # Distinct resources with the same basename also collide silently.
    inline = {"https://one.invalid/figure.png": (b"FIRST", "figure.png"),
              "https://two.invalid/figure.png": (b"SECOND", "figure.png")}
    mapped, count, _ = page2md._localise_images(
        "![one](https://one.invalid/figure.png) ![two](https://two.invalid/figure.png)",
        source, p / "collision-out", inline)
    return {"convert_copied_outside_source": copied.is_file(),
            "copied_bytes_match": copied.read_bytes() == secret.read_bytes() if copied.exists() else False,
            "resource_wrote_outside_output": (p / "escaped.txt").is_file(),
            "same_name_resources_collide": mapped.count("assets/figure.png") == 2 and count == 2,
            "collision_kept_first_bytes": (p / "collision-out/assets/figure.png").read_bytes() == b"FIRST",
            "platform": sys.platform}


def snapshot_identity(p: Path) -> dict[str, Any]:
    p.mkdir()
    blob = write_mhtml(p / "body.mhtml", ARTICLE_HTML).read_bytes()
    service = build_service(p, [[goto(), {"verb": "sleep"},
        capture(blob, "https://pubs.acs.org/doi/10.1021/unrelated")]])
    result = service.read_page(doi=DOI)
    return {k: result.get(k) for k in ("status", "full_text", "doi", "final_url", "captured_url")}


def open_paywall(p: Path) -> dict[str, Any]:
    p.mkdir()
    blob = write_mhtml(p / "paywall.mhtml", PAYWALL_HTML).read_bytes()
    service = build_service(p, [[capture(blob)]])
    service._page_cache_put(f"https://doi.org/{DOI}", {"status": "blocked"})
    result = service.read_page(doi=DOI)
    return {k: result.get(k) for k in ("status", "full_text", "source", "quota_charged")}


def full_view_failure(p: Path, failure: str) -> dict[str, Any]:
    p.mkdir()
    landing = PAYWALL_HTML.replace("<body>", '<head><meta name="citation_fulltext_html_url" '
                                  f'content="{FULL}"></head><body>')
    blob = write_mhtml(p / "landing.mhtml", landing).read_bytes()
    failed_step = goto(FULL, status=403) if failure == "403" else goto(FULL, title="Just a moment...", halted=True)
    service = build_service(p, [[goto(), {"verb": "sleep"}, capture(blob), failed_step]])
    result = service.read_page(doi=DOI, view="full")
    used = service._policy.used_today
    return {"status": result.get("status"), "reason": result.get("reason"),
            "reported_charge": result.get("quota_charged"), "actual_charge": used,
            "cooldown_active": service._risk.cooldown_until() is not None,
            "view_applied": result.get("view_applied")}


def cached_result(p: Path) -> dict[str, Any]:
    p.mkdir()
    blob = write_mhtml(p / "body.mhtml", ARTICLE_HTML).read_bytes()
    service = build_service(p, [[goto(), {"verb": "sleep"}, capture(blob)]])
    first = service.read_page(doi=DOI)
    again = service.read_page(doi=DOI)
    return {"first_final_url": first.get("final_url"), "cached_final_url": again.get("final_url"),
            "cached_captured_url": again.get("captured_url"), "cached_judge": again.get("judge"),
            "cached_prose_words": again.get("prose_words")}


def converter_race(p: Path) -> dict[str, Any]:
    p.mkdir()
    a, b = p / "a.html", p / "b.html"
    for path, label in ((a, "ALPHA"), (b, "BETA")):
        path.write_text(f'<html><body><section id="s"><h2>1. {label}</h2>'
                        f'<p>{label} specific article content.</p></section></body></html>', encoding="utf-8")
    entered, release = threading.Event(), threading.Event()
    original = page2md.shutil.copy2

    def copy2(src: Any, dst: Any, *args: Any, **kwargs: Any) -> Any:
        if Path(src) == a:
            entered.set()
            if not release.wait(8):
                raise TimeoutError("audit thread did not release")
        return original(src, dst, *args, **kwargs)

    with patch.object(page2md.shutil, "copy2", copy2), concurrent.futures.ThreadPoolExecutor(1) as pool:
        task = pool.submit(page2md.convert, a, p / "a-out")
        assert entered.wait(8)
        try:
            page2md.convert(b, p / "b-out")
        finally:
            release.set()
        task.result(8)
    a_markdown = (p / "a-out/page.md").read_text(encoding="utf-8")
    a_index = (p / "a-out/index.json").read_text(encoding="utf-8")
    return {"alpha_page_contains_ALPHA": "ALPHA" in a_markdown,
            "alpha_index_contains_BETA": "BETA" in a_index,
            "alpha_index_contains_ALPHA": "ALPHA" in a_index}


def corrupt_quota(p: Path) -> dict[str, Any]:
    p.mkdir()
    state = p / "quota.json"
    state.write_text(json.dumps({"day": date.today().isoformat(), "used": -20, "last": None}))
    policy = PolicyEngine(state_path=state, jitter=lambda: 0)
    before = policy.remaining_today
    policy.wait_turn()
    return {"remaining_before": before, "used_after_action": policy.used_today,
            "state_error": policy.state_error}


def empty_http_token(p: Path) -> dict[str, Any]:
    p.mkdir()
    (p / "http-token").write_text("", encoding="utf-8")
    with patch.dict(os.environ, {"SCHOLAR_SEARCH_HOME": str(p)}):
        token = load_token()
    return {"empty_token_accepted": token == ""}


def url_metadata_fixture(p: Path) -> dict[str, Any]:
    from scholar_search.adapters.fixture import FixtureAdapter
    action = Action("goto", {"url": "https://doi.org/10.1002/example"})
    adapter = FixtureAdapter([goto("https://onlinelibrary.wiley.com/doi/10.1002/example")])
    outcome = adapter.execute(action, timeout_ms=1000)
    return {"outcome_url": outcome.url, "data_url": outcome.data.get("url")}


def main() -> None:
    results: dict[str, Any] = {}
    probes = {
        "risk_signals": risk_signals,
        "empty_scope_widening": bridge_empty_scope,
        "image_path_boundaries": image_boundaries,
        "capture_identity_mismatch": snapshot_identity,
        "open_tab_paywall": open_paywall,
        "full_view_403": lambda p: full_view_failure(p, "403"),
        "full_view_challenge": lambda p: full_view_failure(p, "challenge"),
        "cached_result": cached_result,
        "converter_thread_race": converter_race,
        "negative_quota": corrupt_quota,
        "empty_http_token": empty_http_token,
        "fixture_redirect_identity": url_metadata_fixture,
    }
    with tempfile.TemporaryDirectory(prefix="codex-wensu-audit-") as directory:
        root = Path(directory)
        for name, probe in probes.items():
            try:
                results[name] = probe(root / name)
            except Exception as error:
                results[name] = {"probe_error": f"{type(error).__name__}: {error}"}
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
