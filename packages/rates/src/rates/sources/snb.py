"""Swiss National Bank yield-curve source adapter.

The SNB publishes "Yields on Swiss Confederation bond issues" (estimated spot rates by maturity)
as an SNB data-cube CSV. Probed 2026-06-22 (cube ``rendoblid``, monthly since 1988):

  ``https://data.snb.ch/api/cube/rendoblid/data/csv/en``

Layout (verified): a short ``key;value`` metadata preamble (``CubeId``/``PublishingDate``), a blank
line, then a data block whose header line is ``Date;D0;Value`` and whose rows are
``"<YYYY-MM-DD>";"<code>";"<value or blank>"`` — **semicolon**-delimited, double-quoted, decimal
point ``.``, and a leading UTF-8 BOM on the first line.

The ``D0`` maturity dimension carries several series; only the **Swiss Confederation spot curve** is
the sovereign govt curve we want:

  ``1J``…``9J`` = 1–9 years, ``10J0`` = 10 years (Confederation), ``15J``/``20J``/``30J``.

Deliberately EXCLUDED: ``10J1`` (German government bonds — wrong country) and the borrower-category
/ rating series (``E``/``K``/``P``/``GK``/``IKH``/``AAA``/``AA``/``A`` — not the sovereign curve).

Values are estimated ``spot`` rates in **% per annum** (can be negative). The ``Date`` is the
curve's ``as_of_date``. This module separates **parsing** (pure, testable) from **downloading**.
"""

from __future__ import annotations

import csv
from datetime import date
from urllib.request import Request, urlopen

from .base import CurvePoint

SNB_URL = "https://data.snb.ch/api/cube/rendoblid/data/csv/en"

# D0 maturity code → tenor in years. Only the Swiss Confederation spot curve; see module docstring.
MATURITY_YEARS: dict[str, float] = {
    "1J": 1.0,
    "2J": 2.0,
    "3J": 3.0,
    "4J": 4.0,
    "5J": 5.0,
    "6J": 6.0,
    "7J": 7.0,
    "8J": 8.0,
    "9J": 9.0,
    "10J0": 10.0,
    "15J": 15.0,
    "20J": 20.0,
    "30J": 30.0,
}

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) QRP-rates/0.1"


class CurveLayoutError(RuntimeError):
    """The SNB cube layout drifted from what the probe recorded (fail loud, never mis-map)."""


def _parse_date(cell: str) -> date | None:
    """``YYYY-MM-DD`` → ``date``; anything else → ``None``."""
    try:
        return date.fromisoformat(cell.strip())
    except ValueError:
        return None


def parse_csv(text: str) -> list[CurvePoint]:
    """Parse the SNB cube CSV text into curve points. Pure (no network).

    Skips the metadata preamble by scanning for the ``Date;D0;Value`` data header line, then keeps
    only the Confederation-curve maturities with a non-blank value.
    """
    lines = text.lstrip("﻿").splitlines()
    header_idx = next(
        (
            i
            for i, ln in enumerate(lines)
            if [c.strip().strip('"').lower() for c in ln.split(";")][:3]
            == ["date", "d0", "value"]
        ),
        None,
    )
    if header_idx is None:
        raise CurveLayoutError("no 'Date;D0;Value' data header line found")

    reader = csv.reader(lines[header_idx + 1 :], delimiter=";")
    out: list[CurvePoint] = []
    for row in reader:
        if len(row) < 3:
            continue
        d = _parse_date(row[0])
        tenor = MATURITY_YEARS.get(row[1].strip())
        cell = row[2].strip()
        if d is None or tenor is None or cell == "":
            continue
        try:
            value = float(cell)
        except ValueError:
            continue
        out.append(
            CurvePoint("CH", "CHF", "govt", "nominal", "spot", round(tenor, 6), d, value)
        )
    if not out:
        raise CurveLayoutError(
            "no Confederation-curve rows parsed (maturity codes may have drifted)"
        )
    return out


def _download(url: str, *, timeout: int = 120) -> str:
    req = Request(url, headers={"User-Agent": _UA})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted SNB host)
        return resp.read().decode("utf-8")


class SnbCurveSource:
    """Fetches + parses SNB Swiss Confederation spot curves. ``SOURCE`` tags every stored row."""

    SOURCE = "snb"
    COUNTRY = "CH"
    CURRENCY = "CHF"

    def fetch(
        self, *, start_date: date | None = None, end_date: date | None = None
    ) -> list[CurvePoint]:
        pts = parse_csv(_download(SNB_URL))
        if start_date is not None:
            pts = [p for p in pts if p.as_of_date >= start_date]
        if end_date is not None:
            pts = [p for p in pts if p.as_of_date <= end_date]
        return pts
