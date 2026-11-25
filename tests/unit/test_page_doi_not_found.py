"""A DOI that does not resolve is not an abstract-only page and not a paywall.

Acceptance run 2026-11-25: `page_read(doi: "10.1016/j.snb.2026.000001")` — a DOI the tester
made up — came back as

    {"status": "no_html", "reason": "abstract_only", "title": "Error: DOI Not Found",
     "quota_charged": 2, "mhtml_path": "…\\page.mhtml"}

with the advice "this browser is not signed in to the publisher: ask the user to sign in".
Three things were wrong (P6 in the report): the reason was misdiagnosed, so the advice sent
the user to sign in for a DOI that does not exist; 267 KB of the publisher's error page was
kept as if it were the article; and the capture price was charged for a page that was never
captured.
"""

from __future__ import annotations

from pathlib import Path

from test_page_read import write_mhtml

from scholar_search.core.pageprobe import classify_mhtml
from scholar_search.core.service import _page_next

# Elsevier's answer to a DOI it cannot resolve. Nothing else on the page — that is the whole
# point: no section wrappers, no numbering, no sign-in prompt, so every "is this the article"
# rule answers no and the old classifier fell through to `abstract_only`.
DOI_ERROR_HTML = """<!DOCTYPE html><html><head><title>Error: DOI Not Found</title></head>
<body><div class="error-page"><h1>Error: DOI Not Found</h1>
<p>The DOI you requested could not be found.</p></div></body></html>"""

# The same shell with a real (but paywalled) article: this must keep `paywall`, because it is
# a session problem and the advice to sign in is the right one.
PAYWALL_HTML = """<!DOCTYPE html><html><head><title>A paper</title></head><body>
<h1>A paper</h1><p>Purchase PDF</p><p>Get access</p></body></html>"""


def test_a_doi_that_does_not_resolve_has_its_own_reason(tmp_path: Path) -> None:
    probe = classify_mhtml(write_mhtml(tmp_path / "error.mhtml", DOI_ERROR_HTML))

    assert probe["status"] == "no_html"
    assert probe["reason"] == "doi_not_found", probe


def test_the_error_page_title_is_the_signal(tmp_path: Path) -> None:
    probe = classify_mhtml(write_mhtml(tmp_path / "error2.mhtml", DOI_ERROR_HTML))

    assert "DOI Not Found" in str(probe["title"]), probe


def test_a_paywall_keeps_its_own_reason(tmp_path: Path) -> None:
    probe = classify_mhtml(write_mhtml(tmp_path / "paywall.mhtml", PAYWALL_HTML))

    assert probe["reason"] == "paywall", probe


def test_the_hint_points_at_the_doi_not_at_signing_in() -> None:
    hint = _page_next({"status": "no_html", "reason": "doi_not_found"})

    assert "sign in" not in hint, hint
    assert "DOI" in hint, hint
    # `page_read` answers are budgeted at 300 chars per string (test_response_budget.py).
    assert len(hint) <= 300, len(hint)
