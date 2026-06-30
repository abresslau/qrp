"""Brazil Tesouro Direto (Tesouro Nacional) yield-curve source adapter.

Tesouro Transparente publishes "Preço e Taxa dos Títulos do Tesouro Direto" as one large CSV on its
CKAN portal (free, open). Probed 2026-06-22/06-30 — semicolon-delimited, decimal COMMA, latin-1:

  ``Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;PU …``

Dates are ``DD/MM/YYYY``. We map each ``Tipo Titulo`` to its curve **basis** (see ``TITLE_BASIS``):
the nominal curve from ``Tesouro Prefixado`` (LTN, zero-coupon, short) + ``… com Juros Semestrais``
(NTN-F, coupon, the long end); the **real** curve from ``Tesouro IPCA+`` (NTN-B Principal) + ``IPCA+
com Juros Semestrais`` (NTN-B, long → ~2055/60). ``Tesouro Selic`` (LFT overnight floater — not a
fixed-term yield) and ``IGPM+`` (NTN-C, a different/legacy inflation index) are deliberately
**excluded** (``EXCLUDED_TITLES``); the retail accumulation annuities ``Educa+``/``Renda+`` are
**deferred** (``DEFERRED_TITLES`` — IPCA-linked but their Data Vencimento is a final-payment date,
not a bullet maturity); any unmapped/new title is skipped (logged once), never mis-mapped. Per row:
``as_of_date`` = Data Base; ``tenor`` = (Data Vencimento − Data Base) / 365 years (per-issue
maturities → non-standard tenor floats, kept RAW, not fitted);
``value`` = Taxa Compra Manha, the per-issue **yield-to-maturity** in % p.a. (NOT a bootstrapped
zero/spot — coupon NTN-F/NTN-B YTMs are stored raw and labelled ``rate_type='yield'``, and the
nominal−real breakeven derived from them is approximate, since nominal and real issues mature on
different dates; the authoritative fitted curve is ANBIMA's ETTJ — a documented follow-on).

The CSV is large (10M+ rows), so we stream it row-by-row rather than loading it whole. Parsing of a
single CSV row is pure (no network); the network only supplies an iterator of text lines.
"""

from __future__ import annotations

import csv
import io
import logging
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

# Exact ``Tipo Titulo`` → curve ``basis``. Coupon ("com Juros Semestrais") variants carry the long
# end. Strings verified against the live CSV (probe 2026-06-30 — 8 distinct title types). The real
# curve is the bullet/coupon NTN-B family (Tesouro IPCA+); see ``DEFERRED_TITLES`` for the retail
# accumulation products held out of v1.
TITLE_BASIS: dict[str, str] = {
    "Tesouro Prefixado": "nominal",                       # LTN — zero-coupon nominal bullet (short)
    "Tesouro Prefixado com Juros Semestrais": "nominal",  # NTN-F — coupon nominal (long, ~10y)
    "Tesouro IPCA+": "real",                              # NTN-B Principal — zero real (mid)
    "Tesouro IPCA+ com Juros Semestrais": "real",        # NTN-B — coupon real (long → 2055/60)
}

# Dedup priority when two issues land on the SAME (as_of_date, basis, tenor) — and they do: an LTN
# and an NTN-F both mature Jan-1 (2027/2029/2031 overlap), an NTN-B Principal and an NTN-B coupon
# both on May/Aug-15. They'd collide on the store PK (country,curve_set,basis,rate_type,tenor,
# as_of_date), and a last-writer-wins upsert would non-deterministically keep one (their YTMs differ
# ~10-20bp from the coupon effect). Keep the ZERO-COUPON bullet (LTN / NTN-B Principal) — the
# cleaner spot/zero proxy — and let the coupon issue populate only tenors no bullet covers (long).
# Lower number = preferred.
TITLE_PRIORITY: dict[str, int] = {
    "Tesouro Prefixado": 0,                       # LTN zero-coupon — preferred at shared tenors
    "Tesouro Prefixado com Juros Semestrais": 1,  # NTN-F coupon — extends the nominal long end
    "Tesouro IPCA+": 0,                           # NTN-B Principal zero-coupon — preferred
    "Tesouro IPCA+ com Juros Semestrais": 1,      # NTN-B coupon — extends the real long end
}

# Deliberately excluded (documented; never mapped to a basis): a floater is not a term-yield point,
# and IGP-M is a different (legacy/illiquid) inflation index — out of scope for the IPCA real curve.
EXCLUDED_TITLES: frozenset[str] = frozenset({
    "Tesouro Selic",                       # LFT — overnight floater (Taxa Compra ≈ 0)
    "Tesouro IGPM+ com Juros Semestrais",  # NTN-C — IGP-M indexed (legacy)
})

# Held out of v1 (real in nature, but NOT clean curve nodes): the retail accumulation products quote
# an IPCA+ real rate, but their ``Data Vencimento`` is a final-annuity-PAYMENT date (Renda+ pays out
# over ~20y, Educa+ over 5y) rather than a bullet maturity — so it isn't comparable to an NTN-B
# yield-to-maturity, and the implied tenor runs past the store's 60y bound. The proper real curve is
# the NTN-B family above; admitting these is a documented follow-on (needs a tenor-bound widening +
# an annuity-aware tenor, not a raw final-payment date). Skipped quietly (known, not "unmapped").
DEFERRED_TITLES: frozenset[str] = frozenset({
    "Tesouro Educa+",                      # IPCA-linked retail education annuity (5y payout)
    "Tesouro Renda+ Aposentadoria Extra",  # IPCA-linked retail retirement annuity (~20y payout)
})

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) QRP-rates/0.1"
_log = logging.getLogger(__name__)


class CurveLayoutError(RuntimeError):
    """Tesouro's CSV layout drifted from what the probe recorded (fail loud, never mis-map)."""


def _parse_date(s: str) -> date:
    return datetime.strptime(s.strip(), "%d/%m/%Y").date()


def _parse_decimal(s: str) -> float:
    return float(s.strip().replace(".", "").replace(",", "."))


def parse_rows(rows: Iterable[dict]) -> Iterator[CurvePoint]:
    """Yield curve points from Tesouro CSV dict-rows, one per (as_of_date, basis, tenor).

    Each ``Tipo Titulo`` is mapped to its ``basis`` via ``TITLE_BASIS``; ``EXCLUDED_TITLES``
    (Selic/IGP-M), ``DEFERRED_TITLES`` (Educa+/Renda+) and any unmapped/new title are skipped — the
    first sighting of an unmapped title is logged once so a new Tesouro product surfaces, never
    mis-mapped onto a curve. A malformed row (blank/absent Data Base or Data Vencimento) is skipped,
    never allowed to abort the stream.

    The INPUT iterator is consumed lazily (the 10M-row CSV is never materialized); only the few
    thousand KEPT points are buffered, so that issues colliding on (as_of_date, basis, tenor) — an
    LTN and an NTN-F maturing the same day, an NTN-B Principal and coupon — can be de-duplicated to
    the preferred (zero-coupon) issue (``TITLE_PRIORITY``) rather than non-deterministically
    overwriting each other on the store PK. Network-free / pure (fixed input → fixed output set)."""
    seen_unknown: set[str] = set()
    # (as_of_date, basis, tenor) -> (priority, CurvePoint); keep the lowest-priority (zero-coupon).
    best: dict[tuple[date, str, float], tuple[int, CurvePoint]] = {}
    for row in rows:
        title = (row.get("Tipo Titulo") or "").strip()
        basis = TITLE_BASIS.get(title)
        if basis is None:
            known_skip = title in EXCLUDED_TITLES or title in DEFERRED_TITLES
            if title and not known_skip and title not in seen_unknown:
                seen_unknown.add(title)
                _log.info("tesouro: skipping unmapped Tipo Titulo %r (not in TITLE_BASIS)", title)
            continue
        rate = (row.get("Taxa Compra Manha") or "").strip()
        db = (row.get("Data Base") or "").strip()
        dv = (row.get("Data Vencimento") or "").strip()
        if not rate or not db or not dv:
            continue
        try:
            base = _parse_date(db)
            maturity = _parse_date(dv)
        except ValueError:
            continue  # malformed date cell — skip the row, never abort the whole stream
        tenor = (maturity - base).days / 365.0
        if tenor <= 0:
            continue
        t = round(tenor, 6)
        key = (base, basis, t)
        prio = TITLE_PRIORITY[title]
        existing = best.get(key)
        if existing is None or prio < existing[0]:
            best[key] = (prio, CurvePoint(
                "BR", "BRL", "govt", basis, "yield", t, base, _parse_decimal(rate),
            ))
    for _prio, point in best.values():
        yield point


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
    """Fetches + parses Tesouro Direto yields — nominal (LTN/NTN-F) + real (NTN-B).

    ``SOURCE`` tags every stored row. Per-issue YTMs kept raw (``rate_type='yield'``); the breakeven
    is derived on read (nominal − real, approximate — non-matched tenors). The retail accumulation
    annuities (Educa+/Renda+) are deferred — see ``DEFERRED_TITLES``."""

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
