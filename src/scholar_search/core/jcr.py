"""A local journal-metrics database built from the user's own JCR workbook.

Why local, and why not shipped:

* **Licensing.** The impact factors and quartiles come from Clarivate's Journal Citation
  Reports. Redistributing that table inside a wheel is not ours to do.
* **Size.** The workbook is 4.2 MB; the two sheets hold ~22 000 journals each, and it is
  revised every year.

So the package ships the *reader*, not the data. `wensu jcr import <workbook>` turns the
user's copy into a small SQLite file under the runtime home, and re-running it after a new
release replaces the contents — which is exactly the maintenance the user asked for.

The workbook is read with the standard library (`zipfile` + `ElementTree`) rather than a
spreadsheet dependency, because this is the only place in the project that needs one and a
whole package for one import command is not a fair trade. `tests/unit/test_jcr.py` checks
the reader against `openpyxl` when it happens to be installed, so the two cannot drift
silently.

**A trap worth recording**: the journal names in the workbook are truncated to about 29
characters (`CA-A CANCER JOURNAL FOR CLIN`). Matching on the name alone therefore misses
more often than it hits, and a prefix match can be ambiguous. ISSN is the key; the name is
a fallback that refuses to guess when it cannot decide.
"""

from __future__ import annotations

import io
import re
import sqlite3
import zipfile
from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from .config import app_home

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_NAME_HEADER = "期刊名称"
_JIF_COLUMN = re.compile(r"^(\d{4})JIF$", re.I)
_QUARTILE_COLUMN = re.compile(r"^(\d{4})分区$")

MetricLookup = Callable[[str | None, str | None, str | None], "tuple[float, int] | None"]


@dataclass(frozen=True, slots=True)
class JcrStatus:
    """What is in the database, in terms a user can check against their workbook."""

    jcr_rows: int
    cas_rows: int
    edition: int | None
    source_file: str
    imported_at: str


# -- reading the workbook ----------------------------------------------------


def _column_index(reference: str) -> int:
    """`C12` -> 2. Zero-based, so a row list lines up with the header list."""

    index = 0
    for char in reference:
        if not char.isalpha():
            break
        index = index * 26 + (ord(char.upper()) - ord("A") + 1)
    return max(index - 1, 0)


def _elements(raw: bytes, tag: str) -> Iterator[ET.Element]:
    """Yield every `tag` element from a zipped XML part, one at a time.

    `iterparse` takes no `tag` filter, so the filtering is manual — and each consumed
    element is dropped along with the root's children, which is what keeps a 22 000-row
    sheet from being materialised in full.
    """

    events = ET.iterparse(io.BytesIO(raw), events=("start", "end"))
    _, root = next(events)
    for event, element in events:
        if event != "end":
            continue
        if element.tag != tag:
            continue
        yield element
        element.clear()
        root.clear()


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        raw = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    return [
        "".join(node.text or "" for node in element.iter(f"{_NS}t"))
        for element in _elements(raw, f"{_NS}si")
    ]


def _sheet_targets(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    """`[(sheet name, archive path)]` in workbook order."""

    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {relation.get("Id"): relation.get("Target", "") for relation in relationships}
    sheets: list[tuple[str, str]] = []
    for sheet in workbook.iter(f"{_NS}sheet"):
        target = targets.get(sheet.get(f"{_REL_NS}id"), "")
        if not target:
            continue
        path = target.lstrip("/")
        if not path.startswith("xl/"):
            path = f"xl/{path}"
        sheets.append((sheet.get("name") or "", path))
    return sheets


def _rows(archive: zipfile.ZipFile, path: str, shared: list[str]) -> Iterator[list[str]]:
    for element in _elements(archive.read(path), f"{_NS}row"):
        values: dict[int, str] = {}
        for cell in element.iter(f"{_NS}c"):
            reference = cell.get("r") or ""
            kind = cell.get("t")
            if kind == "inlineStr":
                text = "".join(node.text or "" for node in cell.iter(f"{_NS}t"))
            else:
                raw = cell.find(f"{_NS}v")
                text = raw.text if raw is not None and raw.text is not None else ""
                if kind == "s" and text.isdigit():
                    index = int(text)
                    text = shared[index] if index < len(shared) else ""
            if text:
                values[_column_index(reference)] = text
        if values:
            width = max(values) + 1
            yield [values.get(index, "") for index in range(width)]


def _header(rows: Iterator[list[str]]) -> tuple[list[str], Iterator[list[str]]] | None:
    """Find the header row; the two sheets put it in different places.

    The workbook's second sheet opens with a title row, so the header is not always row
    one. Rows before it are dropped, and the live iterator resumes right after it — an
    earlier version sliced the buffer and re-read the header as a data row.
    """

    for seen, row in enumerate(rows, start=1):
        if any(cell.strip() == _NAME_HEADER for cell in row):
            return row, rows
        if seen >= 5:
            return None
    return None


# -- matching ---------------------------------------------------------------


def name_key(value: str | None) -> str:
    """Fold a journal name into something two spellings can agree on."""

    if not value:
        return ""
    text = value.upper().replace("&", " AND ")
    text = re.sub(r"[^A-Z0-9 \-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _first_matching(header: list[str], pattern: re.Pattern[str]) -> int | None:
    for index, cell in enumerate(header):
        if pattern.match(cell.strip()):
            return index
    return None


def _year_of(cell: str, pattern: re.Pattern[str]) -> int | None:
    match = pattern.match(cell.strip())
    return int(match.group(1)) if match else None


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def _float(value: str) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None


class JcrDatabase:
    """The local metrics store. Cheap to construct; it opens SQLite lazily."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_path()

    # -- lifecycle ---------------------------------------------------------

    def exists(self) -> bool:
        return self.path.is_file()

    def build(self, workbook: Path) -> JcrStatus:
        """Replace the database with the contents of `workbook`."""

        jcr_rows: list[tuple[object, ...]] = []
        cas_rows: list[tuple[object, ...]] = []
        edition: int | None = None

        with zipfile.ZipFile(workbook) as archive:
            shared = _shared_strings(archive)
            for _, path in _sheet_targets(archive):
                found = _header(_rows(archive, path, shared))
                if found is None:
                    continue
                header, body = found
                columns = {cell.strip(): index for index, cell in enumerate(header)}
                name_column = columns.get(_NAME_HEADER)
                if name_column is None:
                    continue

                jif_column = _first_matching(header, _JIF_COLUMN)
                partition_column = _first_matching(header, _QUARTILE_COLUMN)

                if jif_column is not None:
                    # The JCR sheet: `Quartile` is the current JIF quartile, and a column
                    # named `<year>分区` holds the *previous* year's partition — reading
                    # that one as the current quartile would mislabel every row.
                    sheet_edition = _year_of(header[jif_column], _JIF_COLUMN)
                    edition = edition or sheet_edition
                    quartile_column = columns.get("Quartile")
                    for row in body:
                        name = _cell(row, name_column)
                        if not name:
                            continue
                        citations = _cell(row, columns.get("Total citation"))
                        jcr_rows.append(
                            (
                                _cell(row, columns.get("ISSN")),
                                _cell(row, columns.get("eISSN")),
                                name,
                                name_key(name),
                                _float(_cell(row, jif_column)),
                                _cell(row, quartile_column) or None,
                                _cell(row, columns.get("JIF rank")) or None,
                                _cell(row, partition_column) or None,
                                int(citations) if citations.isdigit() else None,
                                _cell(row, columns.get("Category")) or None,
                                sheet_edition,
                            )
                        )
                elif partition_column is not None:
                    # The Chinese Academy of Sciences sheet.
                    sheet_edition = _year_of(header[partition_column], _QUARTILE_COLUMN)
                    for row in body:
                        name = _cell(row, name_column)
                        if not name:
                            continue
                        cas_rows.append(
                            (
                                name,
                                name_key(name),
                                _cell(row, partition_column) or None,
                                _cell(row, columns.get("Top")) or None,
                                _cell(row, columns.get("Open Access")) or None,
                                sheet_edition,
                            )
                        )

        if not jcr_rows:
            raise ValueError(
                f"no journal table found in {workbook.name}: expected a sheet with a "
                f"`{_NAME_HEADER}` column and a `YYYYJIF` column"
            )

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".building")
        temporary.unlink(missing_ok=True)
        with closing(sqlite3.connect(temporary)) as connection:
            connection.executescript(
                """
                CREATE TABLE jcr (
                    issn TEXT, eissn TEXT, name TEXT, name_key TEXT,
                    jif REAL, quartile TEXT, jif_rank TEXT, prev_quartile TEXT,
                    total_citations INTEGER, category TEXT, edition INTEGER
                );
                CREATE TABLE cas (
                    name TEXT, name_key TEXT, quartile TEXT,
                    is_top TEXT, is_oa TEXT, edition INTEGER
                );
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
                CREATE INDEX jcr_issn ON jcr(issn);
                CREATE INDEX jcr_eissn ON jcr(eissn);
                CREATE INDEX jcr_name ON jcr(name_key);
                """
            )
            connection.executemany("INSERT INTO jcr VALUES (?,?,?,?,?,?,?,?,?,?,?)", jcr_rows)
            connection.executemany("INSERT INTO cas VALUES (?,?,?,?,?,?)", cas_rows)
            imported_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            connection.executemany(
                "INSERT INTO meta VALUES (?,?)",
                [
                    ("source_file", str(workbook)),
                    ("imported_at", imported_at),
                    ("edition", str(edition or "")),
                ],
            )
            connection.commit()
        temporary.replace(self.path)

        return self.status() or JcrStatus(
            jcr_rows=len(jcr_rows),
            cas_rows=len(cas_rows),
            edition=edition,
            source_file=str(workbook),
            imported_at="",
        )

    def status(self) -> JcrStatus | None:
        if not self.exists():
            return None
        with closing(sqlite3.connect(self.path)) as connection:
            meta = dict(connection.execute("SELECT key, value FROM meta"))
            counts = connection.execute("SELECT COUNT(*) FROM jcr").fetchone()
            cas = connection.execute("SELECT COUNT(*) FROM cas").fetchone()
        edition = meta.get("edition") or ""
        return JcrStatus(
            jcr_rows=int(counts[0]) if counts else 0,
            cas_rows=int(cas[0]) if cas else 0,
            edition=int(edition) if edition.isdigit() else None,
            source_file=meta.get("source_file", ""),
            imported_at=meta.get("imported_at", ""),
        )

    # -- lookup ------------------------------------------------------------

    def lookup(
        self, name: str | None, issn: str | None, eissn: str | None
    ) -> tuple[float, int] | None:
        """`(impact factor, edition year)` for a journal, or None.

        ISSN first, because the workbook's names are truncated. The name path prefers an
        exact fold and only then accepts a prefix either way round — and returns None when
        more than one journal answers, since a wrong impact factor is worse than none.
        """

        if not self.exists():
            return None
        with closing(sqlite3.connect(self.path)) as connection:
            for column, value in (("issn", issn), ("eissn", eissn)):
                if not value:
                    continue
                row = connection.execute(
                    f"SELECT jif, edition FROM jcr WHERE {column} = ? AND jif IS NOT NULL "
                    "ORDER BY edition DESC LIMIT 1",
                    (value.strip(),),
                ).fetchone()
                if row and row[0] is not None:
                    return float(row[0]), int(row[1]) if row[1] else 0

            key = name_key(name)
            if not key:
                return None
            exact = connection.execute(
                "SELECT jif, edition FROM jcr WHERE name_key = ? AND jif IS NOT NULL LIMIT 1",
                (key,),
            ).fetchone()
            if exact and exact[0] is not None:
                return float(exact[0]), int(exact[1]) if exact[1] else 0

            rows = connection.execute(
                "SELECT jif, edition, name_key FROM jcr "
                "WHERE jif IS NOT NULL AND (instr(?, name_key) = 1 OR instr(name_key, ?) = 1) "
                "LIMIT 5",
                (key, key),
            ).fetchall()
        distinct = {(row[0], row[1]) for row in rows}
        if len(distinct) == 1:
            value, edition = distinct.pop()
            return float(value), int(edition) if edition else 0
        return None

    def resolver(self) -> MetricLookup:
        """A callable shaped for `parse_bibtex.parse(metrics=...)`."""

        def resolve(
            name: str | None, issn: str | None, eissn: str | None
        ) -> tuple[float, int] | None:
            return self.lookup(name, issn, eissn)

        return resolve


def default_path() -> Path:
    return app_home() / "data" / "jcr.sqlite"
