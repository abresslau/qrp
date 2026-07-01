"""Reserve Bank of Australia Government-bond-yield source adapter (statistical table F2).

The RBA publishes table F2 "Capital Market Yields – Government Bonds" as a CSV. Probed 2026-06-22:

  ``https://www.rba.gov.au/statistics/tables/csv/f2-data.csv``

Layout: a block of metadata header rows (``Title`` / ``Description`` / ``Frequency`` / ``Type`` /
``Units`` / ``Source`` / ``Publication date`` / ``Series ID`` …) then daily data rows. The first
column is the date (``DD-Mon-YYYY``). The Australian Government nominal benchmark columns are
identified by their ``Series ID`` (``FCMYGBAG<n>D`` for n in 2/3/5/10) and their ``Title``
("Australian Government <n> year bond"). The indexed-bond column (``FCMYGBAGID``,
"indexed bonds, interpolated, 10 years maturity") is the **real** 10y point — emitted with
``basis='real'`` so the nominal−real breakeven derives on read.

This module separates **parsing** (pure, no network) from **downloading**.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from urllib.request import Request, urlopen

from .base import CurvePoint

RBA_URL = "https://www.rba.gov.au/statistics/tables/csv/f2-data.csv"

# Australian Government benchmark series ID → (basis, tenor in years). Nominal 2/3/5/10y +
# the interpolated 10y indexed (real) bond yield.
SERIES_SPECS: dict[str, tuple[str, float]] = {
    "FCMYGBAG2D": ("nominal", 2.0),
    "FCMYGBAG3D": ("nominal", 3.0),
    "FCMYGBAG5D": ("nominal", 5.0),
    "FCMYGBAG10D": ("nominal", 10.0),
    "FCMYGBAGID": ("real", 10.0),  # indexed bonds, interpolated 10y → the real point
}

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) QRP-rates/0.1"
_DATE_RE = re.compile(r"^\d{1,2}-[A-Za-z]{3}-\d{4}$")


class CurveLayoutError(RuntimeError):
    """RBA's F2 layout drifted from what the probe recorded (fail loud, never mis-map)."""


def _parse_date(cell: str) -> date | None:
    cell = cell.strip()
    if not _DATE_RE.match(cell):
        return None
    return datetime.strptime(cell, "%d-%b-%Y").date()


def parse_csv(text: str) -> list[CurvePoint]:
    """Parse F2 CSV text into nominal AU Government yield points. Pure (no network)."""
    rows = list(csv.reader(io.StringIO(text)))
    sid_row = next(
        (r for r in rows if r and r[0].strip() == "Series ID"),
        None,
    )
    if sid_row is None:
        raise CurveLayoutError("no 'Series ID' header row found in F2 CSV")
    # column index → (basis, tenor), for the columns whose Series ID we recognise.
    col_specs = [
        (j, *SERIES_SPECS[sid.strip()])
        for j, sid in enumerate(sid_row)
        if j >= 1 and sid.strip() in SERIES_SPECS
    ]
    if not col_specs:
        raise CurveLayoutError(f"no known AU Govt series IDs in {sid_row}")
    out: list[CurvePoint] = []
    for r in rows:
        if not r:
            continue
        d = _parse_date(r[0])
        if d is None:
            continue
        for j, basis, tenor in col_specs:
            if j >= len(r):
                continue
            v = r[j].strip()
            if not v:
                continue
            out.append(
                CurvePoint("AU", "AUD", "govt", basis, "yield", tenor, d, float(v))
            )
    return out


def _download(url: str, *, timeout: int = 120) -> str:
    req = Request(url, headers={"User-Agent": _UA})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted RBA host)
        return resp.read().decode("utf-8-sig", errors="replace")


class RbaCurveSource:
    """Fetches + parses RBA F2 Australian Government yields. ``SOURCE`` tags every stored row."""

    SOURCE = "rba"
    COUNTRY = "AU"
    CURRENCY = "AUD"

    def fetch(
        self, *, start_date: date | None = None, end_date: date | None = None
    ) -> list[CurvePoint]:
        pts = parse_csv(_download(RBA_URL))
        if start_date is not None:
            pts = [p for p in pts if p.as_of_date >= start_date]
        if end_date is not None:
            pts = [p for p in pts if p.as_of_date <= end_date]
        return pts
