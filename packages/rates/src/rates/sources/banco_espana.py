"""Banco de España (ES) government yield-curve source adapter.

The Banco de España Statistical Bulletin publishes daily Spanish government secondary-market
yields as a wide CSV (table ti_1_3, "Tipos de interés del mercado secundario"). Probed
2026-07-01 — daily since 1987, latest ~T-2 business days:

  ``https://www.bde.es/webbe/es/estadisticas/compartido/datos/csv/ti_1_3.csv``

This replaces the single monthly ECB Maastricht 10y point with a real daily curve. Layout
(verified): **Latin-1 (ISO-8859-1)**, comma-delimited, double-quoted, decimal POINT, missing =
``"_"``. A metadata header block precedes the data:

  Row 0 ``"CÓDIGO DE LA SERIE",<code per column>``   — the stable per-series code (we map on this)
  Row 1 ``"NÚMERO SECUENCIAL",…``                     — sequence id (ignored)
  Row 2 ``"ALIAS DE LA SERIE","TI_1_3.1",…``          — positional alias (NOT used; positions drift)
  Row 3 ``"DESCRIPCIÓN DE LA SERIE",…``               — Spanish description
  Rows 4-6: UNIDADES (Porcentaje) / FRECUENCIA (DIARIA)
  Rows 7+: ``"DD MES YYYY", v0, v1, …``               — Spanish date + % p.a. per column

We keep ONLY the clean constant-maturity **government** tenors (Letras del Tesoro 6m/1y; Bonos y
Obligaciones del Estado 3y/5y/10y/15y), mapped by their stable CÓDIGO. Range series ("1 a 3 meses",
"más de 2 años", …), the discontinued "más de 1 año", and the AIAF private-fixed-income columns
(``D_KG8SZ*``) are deliberately excluded (never mis-map a range/private series onto a tenor).

This module separates **parsing** (pure, testable, no network) from **downloading**.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from urllib.request import Request, urlopen

from .base import CurvePoint

BDE_TI13_URL = "https://www.bde.es/webbe/es/estadisticas/compartido/datos/csv/ti_1_3.csv"

# Stable CÓDIGO → tenor in years. Only clean constant-maturity Spanish govt secondary-market yields
# (Letras del Tesoro + Bonos y Obligaciones del Estado no segregados). Verified 2026-07-01.
CODE_TENORS: dict[str, float] = {
    "D_DTES00S7": 0.5,    # Letras del Tesoro, 6 meses
    "D_DTES00U7": 1.0,    # Letras del Tesoro, 1 año
    "D_G0B1F0ZN": 3.0,    # Bonos y Obligaciones, 3 años
    "D_G0B1F0ZO": 5.0,    # Bonos y Obligaciones, 5 años
    "D_G0B1F0ZP": 10.0,   # Bonos y Obligaciones, 10 años
    "D_G0B1F0ZQ": 15.0,   # Bonos y Obligaciones, 15 años
}

# Spanish month abbreviations (uppercased) → month number.
_MONTHS: dict[str, int] = {
    "ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12,
}

_CODE_LABEL = "CÓDIGO DE LA SERIE"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) QRP-rates/0.1"


class CurveLayoutError(RuntimeError):
    """The BdE CSV layout drifted from what the probe recorded (fail loud, never mis-map)."""


def _parse_es_date(cell: str) -> date | None:
    """``"DD MES YYYY"`` (Spanish month abbr) → date; anything else → None."""
    parts = cell.strip().strip('"').split()
    if len(parts) != 3:
        return None
    try:
        day = int(parts[0])
        month = _MONTHS.get(parts[1].strip().upper()[:3])
        year = int(parts[2])
    except ValueError:
        return None
    if month is None:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_csv(text: str) -> list[CurvePoint]:
    """Parse the BdE ti_1_3 wide CSV into ES govt nominal yield points. Pure (no network)."""
    rows = list(csv.reader(io.StringIO(text)))
    code_row = next(
        (r for r in rows[:10] if r and r[0].strip().strip('"') == _CODE_LABEL),
        None,
    )
    if code_row is None:
        raise CurveLayoutError(f"no '{_CODE_LABEL}' header row found in the first 10 rows")
    # column index → tenor for the codes we recognise.
    col_tenors = [
        (j, CODE_TENORS[code.strip()])
        for j, code in enumerate(code_row)
        if j >= 1 and code.strip() in CODE_TENORS
    ]
    if not col_tenors:
        raise CurveLayoutError(f"no known BdE govt series codes in {code_row}")
    out: list[CurvePoint] = []
    for r in rows:
        if not r:
            continue
        d = _parse_es_date(r[0])
        if d is None:
            continue
        for j, tenor in col_tenors:
            if j >= len(r):
                continue
            cell = r[j].strip().strip('"')
            if cell in ("", "_"):
                continue
            try:
                value = float(cell)
            except ValueError:
                continue
            out.append(
                CurvePoint("ES", "EUR", "govt", "nominal", "yield", round(tenor, 6), d, value)
            )
    return out


def _download(url: str, *, timeout: int = 120) -> str:
    req = Request(url, headers={"User-Agent": _UA})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted BdE host)
        return resp.read().decode("latin-1")


class BancoEspanaCurveSource:
    """Fetches + parses the BdE daily Spanish govt curve. ``SOURCE`` tags every stored row."""

    SOURCE = "banco_espana"
    COUNTRY = "ES"
    CURRENCY = "EUR"

    def fetch(
        self, *, start_date: date | None = None, end_date: date | None = None
    ) -> list[CurvePoint]:
        pts = parse_csv(_download(BDE_TI13_URL))
        if start_date is not None:
            pts = [p for p in pts if p.as_of_date >= start_date]
        if end_date is not None:
            pts = [p for p in pts if p.as_of_date <= end_date]
        return pts
