"""Japan Ministry of Finance JGB yield-curve source adapter.

The MoF publishes daily JGB (Japanese Government Bond) benchmark interest rates as a single CSV
covering the full history since 1974 (Open data). Probed 2026-06-22:

  ``.../historical/jgbcme_all.csv`` — one row per business day; ``Date`` plus benchmark tenors
  ``1Y,2Y,…,10Y,15Y,20Y,25Y,30Y,40Y`` (the grid has widened over the decades, so early dates carry
  blanks/``-`` for tenors not yet issued).

Layout (verified):

  Row 0: ``Interest Rate,,,,,…,(Unit : %)``  — a banner, skipped.
  Row 1: ``Date,1Y,2Y,3Y,…``                — the tenor header.
  Row 2+: ``1974/9/24,10.327,9.362,…,-,-``  — dates as ``YYYY/M/D``; ``-``/blank = no data.

Values are market ``yield`` quotes in **% per annum**. The date in column A is the curve's
``as_of_date``. This module separates **parsing** (pure, testable) from **downloading**.
"""

from __future__ import annotations

import csv
from datetime import date
from urllib.request import Request, urlopen

from .base import CurvePoint

MOF_JGB_URL = (
    "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/"
    "historical/jgbcme_all.csv"
)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) QRP-rates/0.1"


class CurveLayoutError(RuntimeError):
    """The MoF CSV layout drifted from what the probe recorded (fail loud, never mis-map)."""


def _parse_tenor(label: str) -> float | None:
    """``"1Y"``/``"10Y"`` (or a bare ``"1"``) → years as float; non-tenor labels → ``None``."""
    s = label.strip().upper().rstrip("Y").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _parse_date(cell: str) -> date | None:
    """``YYYY/M/D`` (zero-padding optional) → ``date``; anything else → ``None``."""
    parts = cell.strip().split("/")
    if len(parts) != 3:
        return None
    try:
        y, m, d = (int(p) for p in parts)
        return date(y, m, d)
    except ValueError:
        return None


def parse_csv(text: str) -> list[CurvePoint]:
    """Parse the MoF JGB CSV text into curve points. Pure (no network)."""
    rows = list(csv.reader(text.splitlines()))
    header_idx = next(
        (i for i, r in enumerate(rows[:10]) if r and r[0].strip().lower() == "date"),
        None,
    )
    if header_idx is None:
        raise CurveLayoutError("no 'Date' header row found in the first 10 rows")
    header = rows[header_idx]
    tenor_cols = [(j, _parse_tenor(lbl)) for j, lbl in enumerate(header) if j >= 1]
    tenor_cols = [(j, t) for j, t in tenor_cols if t is not None]
    if not tenor_cols:
        raise CurveLayoutError("no numeric tenors in the 'Date' header row")

    out: list[CurvePoint] = []
    for r in rows[header_idx + 1 :]:
        if not r:
            continue
        d = _parse_date(r[0])
        if d is None:
            continue
        for j, tenor in tenor_cols:
            if j >= len(r):
                continue
            cell = r[j].strip()
            if cell in ("", "-"):
                continue
            try:
                value = float(cell)
            except ValueError:
                continue
            out.append(
                CurvePoint("JP", "JPY", "govt", "nominal", "yield", round(tenor, 6), d, value)
            )
    return out


def _download(url: str, *, timeout: int = 120) -> str:
    req = Request(url, headers={"User-Agent": _UA})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted MoF host)
        return resp.read().decode("utf-8")


class MofJgbCurveSource:
    """Fetches + parses MoF JGB yield curves. ``SOURCE`` tags every stored row."""

    SOURCE = "mof_jp"
    COUNTRY = "JP"
    CURRENCY = "JPY"

    def fetch(
        self, *, start_date: date | None = None, end_date: date | None = None
    ) -> list[CurvePoint]:
        pts = parse_csv(_download(MOF_JGB_URL))
        if start_date is not None:
            pts = [p for p in pts if p.as_of_date >= start_date]
        if end_date is not None:
            pts = [p for p in pts if p.as_of_date <= end_date]
        return pts
