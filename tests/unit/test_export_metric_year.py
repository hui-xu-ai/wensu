"""Export must carry an impact factor's year beside the figure, and say when it replaced a file.

Two findings from one usability report:

* the CSV had an `impact_factor` column and no `impact_factor_year`, and the Markdown
  rendered "影响因子: 29.1" alone. A figure of 29.1 sitting next to a 2026 publication
  date reads as "29.1 in 2026" — the JCR edition was 2025, and comparing journals
  across unknowable editions is exactly the mistake the year field exists to prevent.
* writing over an existing file reported only `written: true`, which reads as "a new
  file appeared". A fixed filename across several runs lost the previous batch.
"""

from __future__ import annotations

import csv
import io

from scholar_search.core.contracts import Record
from scholar_search.core.export import to_csv, to_markdown


def _record(**kwargs: object) -> Record:
    base = {
        "title": "A paper",
        "channel": "webofscience",
        "year": 2026,
        "impact_factor": 29.1,
        "impact_factor_year": 2025,
    }
    base.update(kwargs)
    return Record(**base)  # type: ignore[arg-type]


def test_csv_has_an_impact_factor_year_column() -> None:
    rows = list(csv.reader(io.StringIO(to_csv([_record()]))))
    header, body = rows[0], rows[1]

    assert "impact_factor" in header
    assert "impact_factor_year" in header, "a metric without its edition cannot be compared"
    assert body[header.index("impact_factor")] == "29.1"
    assert body[header.index("impact_factor_year")] == "2025"


def test_csv_leaves_the_year_empty_when_the_source_did_not_report_one() -> None:
    rows = list(csv.reader(io.StringIO(to_csv([_record(impact_factor_year=None)]))))
    header, body = rows[0], rows[1]
    assert body[header.index("impact_factor_year")] == "", "empty, never 0"


def test_markdown_names_the_jcr_edition() -> None:
    text = to_markdown([_record()])
    assert "影响因子: 29.1（JCR 2025）" in text


def test_markdown_says_so_when_the_edition_is_unknown() -> None:
    """Silence invites the reader to assume the publication year."""

    text = to_markdown([_record(impact_factor_year=None)])
    assert "影响因子: 29.1（JCR 年份未报告）" in text


def test_a_record_without_a_metric_prints_nothing_about_one() -> None:
    text = to_markdown([_record(impact_factor=None, impact_factor_year=None)])
    assert "影响因子" not in text
