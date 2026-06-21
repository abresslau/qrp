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
import json
import re
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import psycopg

from sym.identity.instrument import INDEX, SRC_MSCI, ensure_instrument, sym_id_for

_DATE_FORMATS = ("%Y-%m-%d", "%b %d, %Y", "%d %b %Y", "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%Y")

# --- direct MSCI EOD pull (getLevelDataForGraph) -------------------------------------------------
# MSCI's public End-of-Day Index Data Search calls this same endpoint — free, published EOD index
# levels, used as intended. Pull POLITELY (backfill + occasional top-up, NOT a tight poller);
# redistribution or commercial/high-frequency use needs an MSCI licence. Tagged source='msci'.
_MSCI_GRAPH_URL = "https://app2.msci.com/products/service/index/indexmaster/getLevelDataForGraph"
# The free endpoint refuses dates earlier than this ("Calculation date cannot be earlier than
# 19970101"). True since-inception (1969/1987) is the LICENSED product — never imply we have it.
MSCI_HISTORY_FLOOR = date(1997, 1, 1)
# Public return-variant identifiers → MSCI's getLevelDataForGraph variant codes.
_VARIANT_CODES = {"PR": "STRD", "NR": "NETR", "GR": "GRTR"}


def variant_code(variant: str) -> str:
    """Map a public variant id (PR/NR/GR) to MSCI's graph code (STRD/NETR/GRTR)."""
    code = _VARIANT_CODES.get((variant or "").strip().upper())
    if code is None:
        raise ValueError(f"unknown variant {variant!r}; expected one of {sorted(_VARIANT_CODES)}")
    return code


def msci_xref_value(msci_code: str, variant: str) -> str:
    """The `msci` xref value for a (code, variant) — variant-encoded so PR/NR/GR of one index
    resolve to DISTINCT instruments (the per-row `variant` dimension was dropped from index_levels;
    each published series is its own instrument, like ^GSPC vs ^SP500TR)."""
    return f"{msci_code}:{variant_code(variant)}"


def parse_msci_graph_json(payload: object) -> list[tuple[date, Decimal]]:
    """Parse a getLevelDataForGraph JSON payload into a (date, level) series (pure).

    Raises ``ValueError`` on an MSCI error payload (it returns an ``error_code`` such as ``" 100"``)
    so we never write partial garbage. ``calc_date`` is an int ``YYYYMMDD``; ``level_eod`` a float.
    Non-positive / missing levels are dropped; the series is returned ascending by date.
    """
    if not isinstance(payload, dict):
        raise ValueError("MSCI response was not a JSON object")
    err = payload.get("error_code")
    # A present, non-empty, non-"0" error_code is a real error. "0"/0 is the common success
    # sentinel some APIs send alongside valid data — don't treat it as a failure.
    if err is not None and str(err).strip() not in ("", "0"):
        msg = str(payload.get("error_message") or "").strip()
        raise ValueError(f"MSCI error {str(err).strip()}: {msg}")
    levels = (payload.get("indexes") or {}).get("INDEX_LEVELS") or []
    out: list[tuple[date, Decimal]] = []
    for row in levels:
        cd, lv = row.get("calc_date"), row.get("level_eod")
        if cd is None or lv is None:
            continue
        try:
            d = datetime.strptime(str(cd), "%Y%m%d").date()
            level = Decimal(str(lv))
        except (ValueError, InvalidOperation):
            continue
        if level > 0:
            out.append((d, level))
    out.sort(key=lambda t: t[0])
    return out


def _default_fetch_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (QRP sym/benchmarks)"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - fixed MSCI https host
        return json.loads(resp.read().decode("utf-8"))


def fetch_msci_levels(
    *,
    msci_code: str,
    variant: str,
    currency: str = "USD",
    start_date: date = MSCI_HISTORY_FLOOR,
    end_date: date | None = None,
    _fetch_json: Callable[[str], object] = _default_fetch_json,
) -> list[tuple[date, Decimal]]:
    """Fetch an MSCI index level series directly from the public EOD graph endpoint.

    ``variant`` is PR/NR/GR. ``start_date`` is clamped to :data:`MSCI_HISTORY_FLOOR` (the free
    endpoint's floor). ``_fetch_json`` is injectable for testing. Raises ``ValueError`` on an MSCI
    error payload; lets network errors (``urllib.error.URLError``) propagate to the caller.
    """
    end_date = end_date or date.today()
    start_date = max(start_date, MSCI_HISTORY_FLOOR)
    params = {
        "currency_symbol": currency,
        "index_variant": variant_code(variant),
        "start_date": start_date.strftime("%Y%m%d"),
        "end_date": end_date.strftime("%Y%m%d"),
        "data_frequency": "DAILY",
        "baseValue": "false",
        "index_codes": msci_code,
    }
    url = f"{_MSCI_GRAPH_URL}?{urllib.parse.urlencode(params)}"
    return parse_msci_graph_json(_fetch_json(url))


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
    value = (value or "").strip().strip('"').replace(" ", "")
    if not value:
        return None
    # European decimal-comma format ('1.234,56'): stripping commas as thousands
    # separators would corrupt the level 100x — convert it explicitly instead.
    if re.fullmatch(r"\d{1,3}(\.\d{3})*,\d+", value):
        value = value.replace(".", "").replace(",", ".")
    else:
        value = value.replace(",", "")  # plain thousands separators ('1,234.56')
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
    variant: str | None = None,
    name: str | None = None,
    currency_code: str | None = None,
) -> MsciImportSummary:
    """Import an MSCI level file for the index identified by ``msci_code``.

    When ``variant`` (PR/NR/GR) is given the instrument is resolved from the SAME variant-encoded
    ``msci`` xref ``<code>:<VARIANT>`` that ``load_msci_pull`` uses — so a file import and a direct
    pull of the same series land on ONE instrument (no bare-code duplicate). Omitting ``variant``
    keeps the legacy bare-code behaviour. If absent and ``name`` is given, the instrument is created
    (kind=index). Levels are immutable-upserted into ``index_levels`` tagged ``source='msci'``.
    """
    conn.autocommit = True
    xref_value = msci_xref_value(msci_code, variant) if variant else msci_code
    sym_id = sym_id_for(conn, SRC_MSCI, xref_value)
    if sym_id is None:
        if not name:
            raise ValueError(
                f"no instrument for msci xref {xref_value!r}; pass name (+ currency) to create it"
            )
        sym_id = ensure_instrument(
            conn, INDEX, name=name, currency_code=currency_code, xrefs={SRC_MSCI: xref_value}
        )
    series = parse_msci_rows(read_rows(path))
    return _upsert_levels(conn, sym_id, series)


def _upsert_levels(
    conn: psycopg.Connection, sym_id: int, series: Sequence[tuple[date, Decimal]]
) -> MsciImportSummary:
    """Immutable upsert of a (date, level) series into index_levels (source='msci')."""
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


def load_msci_pull(
    conn: psycopg.Connection,
    *,
    msci_code: str,
    variant: str,
    currency: str = "USD",
    name: str | None = None,
    start_date: date = MSCI_HISTORY_FLOOR,
    end_date: date | None = None,
    _fetch: Callable[..., list[tuple[date, Decimal]]] = fetch_msci_levels,
) -> MsciImportSummary:
    """Pull an MSCI index level series directly from MSCI and upsert it into ``index_levels``.

    The instrument is resolved from its variant-encoded ``msci`` xref (``<code>:<VARIANT>``); if
    absent and ``name`` is given, it is created (kind=index) with that xref + currency. Levels are
    immutable-upserted tagged ``source='msci'`` (same path as the file importer). Each (index,
    variant) is a distinct instrument. Returns at most :data:`MSCI_HISTORY_FLOOR`-onward history.
    """
    conn.autocommit = True
    xref_value = msci_xref_value(msci_code, variant)
    sym_id = sym_id_for(conn, SRC_MSCI, xref_value)
    if sym_id is None:
        if not name:
            raise ValueError(
                f"no instrument for msci xref {xref_value!r}; pass name (+ currency) to create it"
            )
        sym_id = ensure_instrument(
            conn, INDEX, name=name, currency_code=currency, xrefs={SRC_MSCI: xref_value}
        )
    series = _fetch(
        msci_code=msci_code, variant=variant, currency=currency,
        start_date=start_date, end_date=end_date,
    )
    return _upsert_levels(conn, sym_id, series)
