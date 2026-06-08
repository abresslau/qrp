"""MSCI index-level file importer (Benchmark epic fast-follow).

MSCI indexes (e.g. MSCI World Net Total Return) are not on Yahoo and have no FIGI,
so their level series are loaded from a **downloaded MSCI export** (the EOD
index-data search yields CSV/Excel). This parses that file into ``(date, level)``
and upserts it into ``index_levels`` under the index's existing ``sym_id`` —
resolved from the ``msci`` cross-reference (or created on first import). Immutable
(ON CONFLICT DO NOTHING), source-tagged ``msci``.

MSCI exports vary (metadata preamble, a ``Date`` header, an index-value column,
thousands separators, several date formats); the row parser tolerates all of these.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import psycopg

from sym.identity.instrument import INDEX, SRC_MSCI, ensure_instrument, sym_id_for

_DATE_FORMATS = ("%Y-%m-%d", "%b %d, %Y", "%d %b %Y", "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%Y")


def _parse_date(value: str) -> date | None:
    value = (value or "").strip().strip('"')
    if not value:
        return None
    head = value.split()[0]  # tolerate Excel 'YYYY-MM-DD 00:00:00'
    try:
        return date.fromisoformat(head)
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _parse_level(value: str) -> Decimal | None:
    value = (value or "").strip().strip('"').replace(",", "").replace(" ", "")
    if not value:
        return None
    try:
        level = Decimal(value)
    except InvalidOperation:
        return None
    return level if level > 0 else None


def _is_date_header(cell: str) -> bool:
    return (cell or "").strip().strip('"').lower() in ("date", "as of date", "asofdate")


def parse_msci_rows(rows: Sequence[Sequence[str]]) -> list[tuple[date, Decimal]]:
    """Parse MSCI export rows into a (date, level) series (pure).

    Skips the metadata preamble to the ``Date`` header row, takes the date column
    and the first other column with a parseable numeric value as the level. Rows
    that don't parse to (date, level) are skipped (footer notes, blanks).
    """
    header_idx = None
    date_col = 0
    for i, row in enumerate(rows):
        for j, cell in enumerate(row):
            if _is_date_header(str(cell)):
                header_idx, date_col = i, j
                break
        if header_idx is not None:
            break
    if header_idx is None:
        return []

    out: list[tuple[date, Decimal]] = []
    for row in rows[header_idx + 1 :]:
        if date_col >= len(row):
            continue
        d = _parse_date(str(row[date_col]))
        if d is None:
            continue
        level = next(
            (lv for k, cell in enumerate(row) if k != date_col and (lv := _parse_level(str(cell)))),
            None,
        )
        if level is not None:
            out.append((d, level))
    return out


def read_rows(path: str | Path) -> list[list[str]]:
    """Read an MSCI export (.csv or .xls/.xlsx) into rows of string cells."""
    p = Path(path)
    if p.suffix.lower() in (".xls", ".xlsx"):
        import pandas as pd

        df = pd.read_excel(p, header=None, dtype=object)
        return [[("" if c is None else str(c)) for c in row] for row in df.values.tolist()]
    text = p.read_text(encoding="utf-8-sig")
    return [list(r) for r in csv.reader(io.StringIO(text))]


@dataclass
class MsciImportSummary:
    sym_id: int
    parsed: int = 0
    written: int = 0


def load_msci_file(
    conn: psycopg.Connection,
    path: str | Path,
    *,
    msci_code: str,
    name: str | None = None,
    currency_code: str | None = None,
) -> MsciImportSummary:
    """Import an MSCI level file for the index identified by ``msci_code``.

    The instrument is resolved from its ``msci`` xref; if absent and ``name`` is
    given, it is created (kind=index) with the ``msci`` xref. Levels are
    immutable-upserted into ``index_levels`` tagged ``source='msci'``.
    """
    conn.autocommit = True
    sym_id = sym_id_for(conn, SRC_MSCI, msci_code)
    if sym_id is None:
        if not name:
            raise ValueError(
                f"no instrument for msci code {msci_code!r}; pass name (+ currency) to create it"
            )
        sym_id = ensure_instrument(
            conn, INDEX, name=name, currency_code=currency_code, xrefs={SRC_MSCI: msci_code}
        )
    series = parse_msci_rows(read_rows(path))
    written = 0
    for d, level in series:
        row = conn.execute(
            """
            INSERT INTO index_levels (sym_id, session_date, level, source)
            VALUES (%s, %s, %s, 'msci')
            ON CONFLICT (sym_id, session_date) DO NOTHING
            RETURNING sym_id
            """,
            (sym_id, d, level),
        ).fetchone()
        if row is not None:
            written += 1
    return MsciImportSummary(sym_id=sym_id, parsed=len(series), written=written)
