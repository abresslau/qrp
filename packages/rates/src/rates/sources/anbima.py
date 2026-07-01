"""ANBIMA NTN-B (IPCA-linked) real-yield source adapter — the authoritative BR real curve.

ANBIMA (the Brazilian financial-markets association) publishes the daily "Mercado Secundário de
Títulos Públicos" — the official indicative secondary-market rates used for mark-to-market, more
authoritative than the Tesouro Direto RETAIL rates the ``tesouro`` adapter stores. The Tesouro
docstring flags this as the intended authoritative follow-on. Probed 2026-07-01 (free, no key):

  ``https://www.anbima.com.br/informacoes/merc-sec/arqs/ms{YYMMDD}.txt``

``@``-delimited, decimal COMMA, latin-1; a two-line title preamble then a header row
``Titulo@Data Referencia@Codigo SELIC@Data Base/Emissao@Data Vencimento@Tx. Compra@Tx. Venda@
Tx. Indicativas@PU@…``. One file per business day (weekends/holidays 404). We keep **NTN-B** rows
(IPCA-linked → the REAL curve; nominal LTN/NTN-F is left to the DI/prefixed curve, and the retail
per-issue curve stays on ``tesouro``): ``as_of_date`` = Data Referencia, ``tenor`` =
(Data Vencimento − Data Referencia)/365 (per-issue maturities, kept RAW), ``value`` = **Tx.
Indicativas** (the indicative YTM, % p.a.).

Stored under ``curve_set='anbima'`` (the authoritative reference family) so it coexists with the
``tesouro`` retail curve (``curve_set='govt'``) — the store key carries no ``source``, so a distinct
family is how two providers of the BR real curve live side by side. The file is a daily snapshot, so
history accrues forward; an explicit window loops business days. Parsing is pure; only the network
supplies the raw text.
"""

from __future__ import annotations

from datetime import date, timedelta
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .base import CurvePoint

_URL_TMPL = "https://www.anbima.com.br/informacoes/merc-sec/arqs/ms{d:%y%m%d}.txt"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
_MAX_BACK = 7  # walk back at most a week to clear a weekend/holiday when finding the latest file


class CurveLayoutError(RuntimeError):
    """The ANBIMA file layout drifted from what the probe recorded (fail loud, never mis-map)."""


def _num(cell: str) -> float | None:
    """ANBIMA decimal-comma → float; blanks/``--`` → None."""
    cell = (cell or "").strip()
    if not cell or cell == "--":
        return None
    try:
        return float(cell.replace(".", "").replace(",", ".")) if "," in cell else float(cell)
    except ValueError:
        return None


def _yyyymmdd(cell: str) -> date | None:
    cell = (cell or "").strip()
    if len(cell) != 8 or not cell.isdigit():
        return None
    return date(int(cell[:4]), int(cell[4:6]), int(cell[6:8]))


def parse_ms(text: str) -> list[CurvePoint]:
    """Parse one ANBIMA Mercado-Secundário file into BR NTN-B real-curve points. Pure (no network).

    Columns are located BY NAME off the ``Titulo@…`` header (robust to column reordering); a missing
    required column is a layout drift (fail loud). Only ``NTN-B`` rows are emitted."""
    lines = text.splitlines()
    hdr_idx = next((i for i, ln in enumerate(lines) if ln.startswith("Titulo@")), None)
    if hdr_idx is None:
        raise CurveLayoutError("no 'Titulo@…' header row found in ANBIMA file")
    cols = [c.strip() for c in lines[hdr_idx].split("@")]
    try:
        i_title = cols.index("Titulo")
        i_ref = cols.index("Data Referencia")
        i_venc = cols.index("Data Vencimento")
        i_rate = cols.index("Tx. Indicativas")
    except ValueError as exc:
        raise CurveLayoutError(f"missing expected column ({exc}); header={cols}") from None

    out: list[CurvePoint] = []
    for ln in lines[hdr_idx + 1:]:
        if not ln.strip():
            continue
        f = ln.split("@")
        if len(f) <= max(i_title, i_ref, i_venc, i_rate) or f[i_title].strip() != "NTN-B":
            continue
        ref, venc, rate = _yyyymmdd(f[i_ref]), _yyyymmdd(f[i_venc]), _num(f[i_rate])
        if ref is None or venc is None or rate is None or venc <= ref:
            continue
        tenor = round((venc - ref).days / 365, 6)
        out.append(CurvePoint("BR", "BRL", "anbima", "real", "yield", tenor, ref, rate))
    return out


def _download(d: date, *, timeout: int = 60) -> str | None:
    """Fetch one day's file; None on 404 (weekend/holiday — no file published)."""
    try:
        req = Request(_URL_TMPL.format(d=d), headers={"User-Agent": _UA})
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted ANBIMA host)
            return resp.read().decode("latin-1")
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise


class AnbimaNtnbCurveSource:
    """Fetches + parses ANBIMA NTN-B real yields. ``SOURCE`` tags every stored row."""

    SOURCE = "anbima"
    COUNTRY = "BR"
    CURRENCY = "BRL"

    def fetch(
        self, *, start_date: date | None = None, end_date: date | None = None
    ) -> list[CurvePoint]:
        end = end_date or date.today()
        if start_date is None:
            # daily tail: the latest published file at/just-before `end` (skip weekends/holidays).
            for back in range(_MAX_BACK + 1):
                text = _download(end - timedelta(days=back))
                if text is not None:
                    return parse_ms(text)
            return []
        # explicit window: one file per calendar day (404 days skipped); parse + accumulate.
        out: list[CurvePoint] = []
        d = start_date
        while d <= end:
            text = _download(d)
            if text is not None:
                out.extend(parse_ms(text))
            d += timedelta(days=1)
        return out
