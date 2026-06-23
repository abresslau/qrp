"""Brazil Tesouro Direto (Tesouro Nacional) yield-curve source adapter.

Tesouro Transparente publishes "Preço e Taxa dos Títulos do Tesouro Direto" as one large CSV on its
CKAN portal (free, open). Probed 2026-06-22 — semicolon-delimited, decimal COMMA, latin-1, header:

  ``Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;PU …``

Dates are ``DD/MM/YYYY``. We keep only ``Tipo Titulo == "Tesouro Prefixado"`` — the zero-coupon
fixed-rate bullet (LTN), the clean nominal point; IPCA+ (real), Selic (floater) and the coupon
``com Juros Semestrais`` variants are dropped. Per row: ``as_of_date`` = Data Base; ``tenor`` =
(Data Vencimento − Data Base) / 365 years (per-issue maturities → non-standard tenor floats, kept
raw); ``value`` = Taxa Compra Manha (a yield in % p.a.).

The CSV is large (10M+ rows), so we stream it row-by-row rather than loading it whole. Parsing of a
single CSV row is pure (no network); the network only supplies an iterator of text lines.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Iterator
from datetime import date, datetime
from urllib.request import Request, urlopen

from .base import CurvePoint

# CKAN package + the current CSV resource (verified 2026-06-22). If the resource id 404s, the CKAN
# package_show API (``.../api/3/action/package_show?id=<PACKAGE_ID>``) lists the live resource.
PACKAGE_ID = "df56aa42-484a-4a59-8184-7676580c81e3"
RESOURCE_ID = "796d2059-14e9-44e3-80c9-2d9e30b405c1"
CSV_URL = (
    f"https://www.tesourotransparente.gov.br/ckan/dataset/{PACKAGE_ID}"
    f"/resource/{RESOURCE_ID}/download/PrecoTaxaTesouroDireto.csv"
)

PREFIXADO = "Tesouro Prefixado"  # exact match: the zero-coupon nominal bullet (LTN)
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) QRP-rates/0.1"


class CurveLayoutError(RuntimeError):
    """Tesouro's CSV layout drifted from what the probe recorded (fail loud, never mis-map)."""


def _parse_date(s: str) -> date:
    return datetime.strptime(s.strip(), "%d/%m/%Y").date()


def _parse_decimal(s: str) -> float:
    return float(s.strip().replace(".", "").replace(",", "."))


def parse_rows(rows: Iterable[dict]) -> Iterator[CurvePoint]:
    """Yield curve points from Tesouro CSV dict-rows. Pure (no network); streams lazily."""
    for row in rows:
        if row.get("Tipo Titulo") != PREFIXADO:
            continue
        rate = (row.get("Taxa Compra Manha") or "").strip()
        if not rate:
            continue
        base = _parse_date(row["Data Base"])
        maturity = _parse_date(row["Data Vencimento"])
        tenor = (maturity - base).days / 365.0
        if tenor <= 0:
            continue
        yield CurvePoint(
            "BR", "BRL", "govt", "nominal", "yield",
            round(tenor, 6), base, _parse_decimal(rate),
        )


def _stream_rows(*, timeout: int) -> Iterator[dict]:
    req = Request(CSV_URL, headers={"User-Agent": _UA})
    resp = urlopen(req, timeout=timeout)  # noqa: S310 (trusted Tesouro host)
    text = io.TextIOWrapper(resp, encoding="latin-1", newline="")
    reader = csv.DictReader(text, delimiter=";")
    expected = {"Tipo Titulo", "Data Vencimento", "Data Base", "Taxa Compra Manha"}
    missing = expected - set(reader.fieldnames or [])
    if missing:
        resp.close()
        raise CurveLayoutError(f"Tesouro CSV missing columns {missing}; got {reader.fieldnames}")
    try:
        yield from reader
    finally:
        resp.close()


class TesouroCurveSource:
    """Fetches + parses Tesouro Direto Prefixado yields. ``SOURCE`` tags every stored row."""

    SOURCE = "tesouro"
    COUNTRY = "BR"
    CURRENCY = "BRL"

    def fetch(
        self, *, start_date: date | None = None, end_date: date | None = None
    ) -> list[CurvePoint]:
        out: list[CurvePoint] = []
        for p in parse_rows(_stream_rows(timeout=300)):
            if start_date is not None and p.as_of_date < start_date:
                continue
            if end_date is not None and p.as_of_date > end_date:
                continue
            out.append(p)
        return out
