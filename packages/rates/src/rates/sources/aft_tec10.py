"""Agence France Trésor (FR) daily TEC-10 nominal 10y benchmark source adapter.

France's full nominal government curve is not published as a free daily multi-tenor feed (Banque de
France discontinued its daily OAT curve 2024-07-10; MTS is commercial; Webstat's API needs a key).
But AFT publishes, **daily**, the **CNO-TEC-10** — the yield-to-maturity of a notional 10-year OAT,
linearly interpolated from the two secondary-market OATs straddling the exact 10y point (source: MTS
France). It is *the* French 10y nominal reference. Probed 2026-07-01:

  ``https://www.aft.gouv.fr/en/today-tec-10-index``
  → HTML containing e.g. "TEC 10 index on Wednesday 01 July 2026: 3.65%"

This supersedes the ECB Maastricht 10y (monthly) for FR nominal — a single **daily** 10y point at
``basis='nominal'``, ``rate_type='yield'``, ``tenor=10``. It is NOT a fitted curve (one benchmark
point), and the page carries **today's value only** — there is no bulk-history file, so history
accrues forward one business day per run (the OAT€i real/breakeven and the ECB's stored monthly
history remain for the past). Parsing (pure, testable) is separated from the network fetch.
"""

from __future__ import annotations

import re
import time
from datetime import date
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .base import CurvePoint

_TEC10_URL = "https://www.aft.gouv.fr/en/today-tec-10-index"
_TENOR = 10.0
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) QRP-rates/0.1"

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
# "TEC 10 index on Wednesday 01 July 2026: 3.65%"  (weekday name skipped; day/month/year + value)
_TEC10_RE = re.compile(
    r"TEC\s*10\s*index\s+on\s+\w+\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})"
    r"\s*:\s*([\d.,]+)\s*%",
    re.IGNORECASE,
)


class CurveLayoutError(RuntimeError):
    """The AFT TEC-10 page layout drifted from the probe (fail loud, never mis-map)."""


def parse_tec10(html: str) -> CurvePoint:
    """Parse the AFT 'today TEC 10 index' page into one FR nominal 10y point. Pure (no network)."""
    m = _TEC10_RE.search(html)
    if not m:
        raise CurveLayoutError("could not find the 'TEC 10 index on <date>: <value>%' line")
    day, month_name, year, raw_val = m.groups()
    month = _MONTHS.get(month_name.lower())
    if month is None:
        raise CurveLayoutError(f"unrecognised month name {month_name!r} in the TEC-10 line")
    d = date(int(year), month, int(day))
    value = float(raw_val.replace(",", "."))  # /en/ renders a dot; be robust to a comma
    return CurvePoint("FR", "EUR", "govt", "nominal", "yield", _TENOR, d, value)


class AftTec10CurveSource:
    """Fetches + parses the AFT daily TEC-10 (FR nominal 10y). ``SOURCE`` tags every stored row."""

    SOURCE = "aft_tec10"
    COUNTRY = "FR"
    CURRENCY = "EUR"

    def fetch(
        self, *, start_date: date | None = None, end_date: date | None = None
    ) -> list[CurvePoint]:
        # AFT intermittently 403s under rapid access — retry a few times with linear backoff so a
        # transient block doesn't drop the day (the loader's attempt-all would otherwise skip FR).
        html: str | None = None
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                req = Request(_TEC10_URL, headers={"User-Agent": _UA})
                with urlopen(req, timeout=120) as resp:  # noqa: S310 (trusted AFT host)
                    html = resp.read().decode("utf-8", "ignore")
                break
            except HTTPError as exc:
                last_err = exc
                time.sleep(2 * (attempt + 1))
        if html is None:
            raise last_err or CurveLayoutError("AFT TEC-10 page unreachable")
        pt = parse_tec10(html)
        # The page carries a single day; honour an explicit window (both inclusive) if given.
        if start_date is not None and pt.as_of_date < start_date:
            return []
        if end_date is not None and pt.as_of_date > end_date:
            return []
        return [pt]
