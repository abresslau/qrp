"""US Federal Reserve fitted-curve source — the Gürkaynak-Sack-Wright (GSW) datasets.

The Fed staff publish two daily fitted Treasury curves as CSV research datasets (no API key):

* **feds200628** — the NOMINAL Treasury zero-coupon curve, daily back to 1961. Each row carries the
  zero/spot yield (``SVENY01..30``, continuously compounded), the par yield (``SVENPY01..30``,
  coupon-equivalent) and the instantaneous forward (``SVENF01..30``) at 1..30y, plus the Svensson
  parameters (``BETA*``/``TAU*``) we ignore.
* **feds200805** — the TIPS REAL curve + inflation compensation, daily back to 1999/2003. Real zero
  (``TIPSY``), real par (``TIPSPY``), real forward (``TIPSF``) and the breakeven (``BKEVEN`` /
  ``BKEVENPY`` / ``BKEVENF``) at 2..20y.

This is materially richer than the Treasury CMT par feed (``ustreasury``): three rate types over a
nominal / real / inflation basis, 60+ years of history. We store it under ``curve_set='gsw'`` so it
coexists with the official CMT ``govt`` par curve, each row tagged ``source='fed_gsw'``.

Both files share the same layout: a multi-line preamble, then a header row starting ``Date,``, then
one row per business day. ``NA`` cells (a tenor with no history, or a holiday) are skipped, never
invented. Parsing is pure/testable (no network); downloading is separate, mirroring the BoE/Treasury
adapters. ``rates`` is a peer package — no import from ``macro``.
"""

from __future__ import annotations

import csv
import math
import re
from datetime import date
from urllib.request import Request, urlopen

from .base import CurvePoint

_BASE = "https://www.federalreserve.gov/data/yield-curve-tables/{file}.csv"
NOMINAL_FILE = "feds200628"
TIPS_FILE = "feds200805"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) QRP-rates/0.1"

# (column-name prefix, basis, rate_type). The trailing integer is the tenor in YEARS (all GSW
# maturities are whole years: 1..30 nominal, 2..20 TIPS). Each prefix is matched as `^PREFIX\d+$`
# so SVENY/SVENPY/SVENF (and the BKEVEN family) never collide, and the special one-year-forward /
# 5y5y columns (SVEN1F*, BKEVEN1F*, TIPS5F5, …) are excluded — they aren't `^PREFIX\d+$`.
_SPECS_NOMINAL: list[tuple[str, str, str]] = [
    ("SVENY", "nominal", "spot"),
    ("SVENPY", "nominal", "par"),
    ("SVENF", "nominal", "forward"),
]
_SPECS_TIPS: list[tuple[str, str, str]] = [
    ("TIPSY", "real", "spot"),
    ("TIPSPY", "real", "par"),
    ("TIPSF", "real", "forward"),
    ("BKEVEN", "inflation", "spot"),
    ("BKEVENPY", "inflation", "par"),
    ("BKEVENF", "inflation", "forward"),
]


def parse_gsw(csv_text: str, specs: list[tuple[str, str, str]]) -> list[CurvePoint]:
    """Parse one GSW CSV into curve points. Pure (no network).

    ``specs`` maps a column-name prefix to (basis, rate_type); the trailing integer is the tenor in
    years. The header is the first line beginning ``Date,`` (a preamble precedes it). Blank/``NA``/
    non-finite cells are skipped per (day, tenor), never invented.
    """
    lines = csv_text.splitlines()
    try:
        hi = next(i for i, line in enumerate(lines) if line.startswith("Date,"))
    except StopIteration:
        return []
    reader = csv.reader(lines[hi:])
    header = next(reader, None)
    if not header:
        return []
    # column index -> (basis, rate_type, tenor) for the columns we keep
    colmap: dict[int, tuple[str, str, float]] = {}
    for j, name in enumerate(header):
        for prefix, basis, rate_type in specs:
            m = re.match(rf"^{prefix}(\d+)$", name.strip())
            if m:
                colmap[j] = (basis, rate_type, float(int(m.group(1))))
                break
    try:
        date_idx = header.index("Date")
    except ValueError:
        return []

    out: list[CurvePoint] = []
    for row in reader:
        if len(row) <= date_idx:
            continue
        try:
            d = date.fromisoformat(row[date_idx].strip()[:10])
        except ValueError:
            continue
        for j, (basis, rate_type, tenor) in colmap.items():
            if j >= len(row):
                continue
            raw = row[j].strip()
            if not raw or raw.upper() == "NA":
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            if not math.isfinite(value):
                continue
            out.append(
                CurvePoint("US", "USD", "gsw", basis, rate_type, round(tenor, 6), d, value)
            )
    return out


def _download(url: str, *, timeout: int = 180) -> bytes:
    req = Request(url, headers={"User-Agent": _UA})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted federalreserve.gov host)
        return resp.read()


class FedGswCurveSource:
    """Fetches the Fed GSW nominal + TIPS fitted curves. ``SOURCE`` tags every stored row."""

    SOURCE = "fed_gsw"
    COUNTRY = "US"
    CURRENCY = "USD"

    def fetch(
        self, *, start_date: date | None = None, end_date: date | None = None
    ) -> list[CurvePoint]:
        pts: list[CurvePoint] = []
        pts.extend(parse_gsw(_download(_BASE.format(file=NOMINAL_FILE)).decode("utf-8", "replace"),
                             _SPECS_NOMINAL))
        pts.extend(parse_gsw(_download(_BASE.format(file=TIPS_FILE)).decode("utf-8", "replace"),
                             _SPECS_TIPS))
        if start_date is not None:
            pts = [p for p in pts if p.as_of_date >= start_date]
        if end_date is not None:
            pts = [p for p in pts if p.as_of_date <= end_date]
        return pts
