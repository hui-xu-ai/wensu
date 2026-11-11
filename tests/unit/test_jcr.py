"""The local journal-metrics database.

The reader is standard-library only, so the test builds a tiny workbook of its own rather
than depending on a spreadsheet package or on the user's 4.2 MB JCR file. Two layouts are
reproduced because the real workbook has two: the JCR sheet opens with its header, the
Chinese Academy of Sciences sheet opens with a title row.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from scholar_search.core.jcr import JcrDatabase

# ruff: noqa: E501 -- these are XML documents; wrapping them would change the bytes.
_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""


def _sheet_xml(rows: list[list[str]]) -> str:
    body: list[str] = []
    for row_index, row in enumerate(rows, start=1):
        cells: list[str] = []
        for column_index, value in enumerate(row):
            reference = f"{chr(ord('A') + column_index)}{row_index}"
            cells.append(f'<c r="{reference}" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
        body.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(body)}</sheetData></worksheet>"
    )


def build_workbook(path: Path, sheets: dict[str, list[list[str]]]) -> Path:
    """A minimal but valid `.xlsx` with inline strings, no shared-string table."""

    names = list(sheets)
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
        + "".join(
            f'<sheet name="{escape(name)}" sheetId="{index}" r:id="rId{index}"/>'
            for index, name in enumerate(names, start=1)
        )
        + "</sheets></workbook>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/'
            f'officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
            for index in range(1, len(names) + 1)
        )
        + "</Relationships>"
    )

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _ROOT_RELS)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        for index, name in enumerate(names, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _sheet_xml(sheets[name]))
    return path


@pytest.fixture()
def workbook(tmp_path: Path) -> Path:
    return build_workbook(
        tmp_path / "JCR.xlsx",
        {
            "2025JCRIF-分区": [
                [
                    "期刊名称",
                    "2024JIF",
                    "Quartile",
                    "JIF rank",
                    "2023分区",
                    "Total citation",
                    "Category",
                    "ISSN",
                    "eISSN",
                ],
                [
                    "NATURE",
                    "48.5",
                    "Q1",
                    "1/100",
                    "Q1",
                    "1000",
                    "MULTIDISCIPLINARY SCIENCES(SCIE)",
                    "0028-0836",
                    "1476-4687",
                ],
                [
                    "CA-A CANCER JOURNAL FOR CLIN",
                    "232.4",
                    "Q1",
                    "1/326",
                    "Q1",
                    "71799",
                    "ONCOLOGY(SCIE)",
                    "0007-9235",
                    "1542-4863",
                ],
                ["NO IMPACT FACTOR JOURNAL", "", "Q4", "", "", "", "SOMETHING", "1111-1111", ""],
            ],
            "2025中科学院分区表": [
                ["2025中科院分区表", "", "", ""],
                ["期刊名称", "2025分区", "Top", "Open Access"],
                ["NATURE", "1", "是", "否"],
            ],
        },
    )


def test_the_import_reads_both_sheets_and_records_the_edition(
    workbook: Path, tmp_path: Path
) -> None:
    database = JcrDatabase(tmp_path / "jcr.sqlite")
    status = database.build(workbook)
    assert status.jcr_rows == 3
    assert status.cas_rows == 1
    # The edition comes from the column header, not from the sheet name: the sheet is
    # named 2025 while its numbers are the 2024 JIF.
    assert status.edition == 2024
    assert database.status() is not None


def test_a_lookup_by_issn_returns_the_factor_and_its_edition(
    workbook: Path, tmp_path: Path
) -> None:
    database = JcrDatabase(tmp_path / "jcr.sqlite")
    database.build(workbook)
    assert database.lookup("NATURE", "0028-0836", None) == (48.5, 2024)
    # The eISSN is enough on its own.
    assert database.lookup(None, None, "1542-4863") == (232.4, 2024)


def test_a_truncated_journal_name_still_resolves_by_prefix(workbook: Path, tmp_path: Path) -> None:
    """The workbook cuts names at ~29 characters, so ISSN cannot always be the key.

    The direction that matters: the export carries the full name, the workbook carries the
    truncated one.
    """

    database = JcrDatabase(tmp_path / "jcr.sqlite")
    database.build(workbook)
    assert database.lookup("CA-A Cancer Journal for Clinicians", None, None) == (232.4, 2024)


def test_an_ambiguous_name_returns_nothing_rather_than_a_guess(tmp_path: Path) -> None:
    path = build_workbook(
        tmp_path / "amb.xlsx",
        {
            "jcr": [
                ["期刊名称", "2024JIF", "ISSN"],
                ["JOURNAL OF THINGS A", "1.0", "1111-0001"],
                ["JOURNAL OF THINGS B", "2.0", "1111-0002"],
            ]
        },
    )
    database = JcrDatabase(tmp_path / "jcr.sqlite")
    database.build(path)
    # Two rows answer the prefix, so the name path must decline.
    assert database.lookup("JOURNAL OF THINGS", None, None) is None
    # An exact name still wins over the ambiguity.
    assert database.lookup("JOURNAL OF THINGS B", None, None) == (2.0, 2024)


def test_a_journal_with_no_impact_factor_is_not_reported_as_zero(
    workbook: Path, tmp_path: Path
) -> None:
    database = JcrDatabase(tmp_path / "jcr.sqlite")
    database.build(workbook)
    assert database.lookup(None, "1111-1111", None) is None


def test_a_workbook_without_a_journal_table_is_refused(tmp_path: Path) -> None:
    path = build_workbook(tmp_path / "empty.xlsx", {"Sheet1": [["a", "b"], ["1", "2"]]})
    database = JcrDatabase(tmp_path / "jcr.sqlite")
    with pytest.raises(ValueError, match="no journal table"):
        database.build(path)


def test_a_missing_database_answers_nothing_instead_of_failing(tmp_path: Path) -> None:
    database = JcrDatabase(tmp_path / "absent.sqlite")
    assert database.status() is None
    assert database.lookup("NATURE", "0028-0836", None) is None
