"""Bundesbank German (DE) yield-curve source adapter.

The Bundesbank publishes the estimated term structure of interest rates for listed Federal
securities (``Börsennotierte Bundeswertpapiere``) fitted by the **Svensson** method — daily
**spot** rates per residual maturity, back to 1997-08-01. Probed 2026-06-23 against the
statistics REST API (BBSIS dataflow), which is reachable in-env.

One request with the maturity dimension left blank returns ALL tenors as a single wide
``BBK_STD_DATA`` CSV::

    https://api.statistiken.bundesbank.de/rest/data/BBSIS/
      D.I.ZST.ZI.EUR.S1311.B.A604..R.A.A._Z._Z.A?format=csv   (Accept: text/csv)

CSV shape (semicolon-delimited, UTF-8 BOM, latin German decimals):

  - Row 0: series keys — one value column ``BBSIS.…`` plus a paired ``…_FLAGS`` column per tenor.
  - Row 1: German titles, each carrying the tenor as ``… / 0,5 Jahr(e) RLZ / …`` (RLZ = residual
    maturity). This label is the authoritative tenor source (the opaque maturity code in the key
    is not parsed).
  - Rows 2–8: metadata (Dezimalstellen, Einheit=Prozent, ``Stand vom`` …).
  - Rows 9+: ``<YYYY-MM-DD>; v0; flag0; v1; flag1; …`` — values in **% p.a.** with a comma decimal
    (negatives occur); missing cells are ``.`` (flag ``Kein Wert vorhanden``).

The grid is 0.5y then every integer year 1y…30y (31 tenors). ``as_of_date`` is the date in
column A — the curve's own date, never the ingest date.

This module separates **parsing** (pure, testable, no network) from **downloading**.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date
from urllib.request import Request, urlopen

from .base import CurvePoint

BBSIS_URL = (
    "https://api.statistiken.bundesbank.de/rest/data/BBSIS/"
    "D.I.ZST.ZI.EUR.S1311.B.A604..R.A.A._Z._Z.A?format=csv"
)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) QRP-rates/0.1"

# "… / 0,5 Jahr(e) RLZ / …" → tenor in years (German comma decimal).
_TENOR_RE = re.compile(r"([0-9]+(?:,[0-9]+)?)\s*Jahr", re.IGNORECASE)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class CurveLayoutError(RuntimeError):
    """Bundesbank's CSV layout drifted from what the probe recorded (fail loud, never mis-map)."""


def _to_float(cell: str) -> float | None:
    """German numeric cell → float, or None for blank/missing (``.``) / non-numeric."""
    s = cell.strip().replace(",", ".")
    if not s or s == ".":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_csv(text: str) -> list[CurvePoint]:
    """Parse the wide BBK_STD_DATA CSV into DE govt spot curve points. Pure (no network).

    The tenor for each value column is read from the German title row; only columns whose title
    yields a numeric ``Jahr(e)`` tenor are kept (the paired ``_FLAGS`` columns carry no tenor and
    are skipped). Rows whose first cell is not an ISO date are metadata and ignored.
    """
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    if len(rows) < 10:
        raise CurveLayoutError(f"expected header + data rows, got only {len(rows)} rows")
    keys, titles = rows[0], rows[1]

    # Map each value column index → tenor (years), driven by the title label.
    col_tenor: list[tuple[int, float]] = []
    for j, key in enumerate(keys):
        if not key.startswith("BBSIS") or key.endswith("_FLAGS"):
            continue
        title = titles[j] if j < len(titles) else ""
        m = _TENOR_RE.search(title)
        if not m:
            continue
        col_tenor.append((j, float(m.group(1).replace(",", "."))))
    if not col_tenor:
        raise CurveLayoutError("no tenor-bearing value columns found in the title row")

    out: list[CurvePoint] = []
    for row in rows:
        if not row or not _DATE_RE.match(row[0].strip()):
            continue
        as_of = date.fromisoformat(row[0].strip())
        for j, tenor in col_tenor:
            if j >= len(row):
                continue
            value = _to_float(row[j])
            if value is None:
                continue
            out.append(
                CurvePoint(
                    "DE", "EUR", "govt", "nominal", "spot", round(tenor, 6), as_of, value
                )
            )
    return out


def _download(url: str, *, timeout: int = 120) -> bytes:
    req = Request(url, headers={"User-Agent": _UA, "Accept": "text/csv"})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted Bundesbank host)
        return resp.read()


class BundesbankCurveSource:
    """Fetches + parses the Bundesbank DE govt (Svensson spot) curve. ``SOURCE`` tags rows."""

    SOURCE = "bundesbank"
    COUNTRY = "DE"
    CURRENCY = "EUR"

    def fetch(
        self, *, start_date: date | None = None, end_date: date | None = None
    ) -> list[CurvePoint]:
        text = _download(BBSIS_URL).decode("utf-8-sig")
        pts = parse_csv(text)
        if start_date is not None:
            pts = [p for p in pts if p.as_of_date >= start_date]
        if end_date is not None:
            pts = [p for p in pts if p.as_of_date <= end_date]
        return pts
