"""FX rate sources (Epic FX, FX2 + ECB reconcile) — USD-base normalized, multi-source.

An ``FxSource`` yields **USD-base** observations (``rate`` = units of the currency per
1 USD, e.g. ``BRL`` ≈ 5.4). Each source declares its native quote *convention* so the
normalizer can invert a USD-*quoted* feed (e.g. a Yahoo ``EURUSD=X`` value of 1.08 → EUR
per USD 0.926) before it ever reaches storage — the F1 wrong-direction guard. Frankfurter
is natively USD-base (``?base=USD``), so it needs no inversion; the inversion path is
exercised by synthetic-payload unit tests, not a live Yahoo adapter (out of scope).

Sources, by trust tier (``SOURCE_PRECEDENCE``):
- **Frankfurter** (``frankfurter``) — primary. ECB reference rates rebased to USD server-
  side, so stored USD-base rates are *rebased*, not primary observations.
- **ECB SDMX** (``ecb``) — the ground-truth reconcile. ECB publishes EUR-base reference
  rates; this adapter rebases them to USD client-side through the EUR/USD leg, so a
  divergence vs Frankfurter (which *is* ECB, rebased) beyond rounding flags a mis-mapped
  date / bad rebase / vendor glitch (FR4b, ``sym.fx.reconcile``). ECB's ~31-currency set
  does **not** include TWD and a few exotics — those stay on the fawazahmed0 fallback.
- **fawazahmed0** (``fawazahmed0``) — breadth fallback for currencies the others drop.

When two sources hold a rate for the same ``(pair, date)``, the canonical pick is the
lowest ``SOURCE_PRECEDENCE`` (Frankfurter first). This is enforced read-side by the
``fx_source_rank`` SQL function (resolver + ``v_fx_daily``); the Python mirror below keeps
the two definitions in lockstep.
"""

from __future__ import annotations

import csv
import io
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol

import requests

# Quote conventions a source may report in.
QUOTE_PER_USD = "quote_per_usd"  # value = currency per 1 USD (what we store) — no inversion
USD_PER_QUOTE = "usd_per_quote"  # value = USD per 1 currency (e.g. EURUSD=X) — invert

# Source trust tiers (lower = preferred when sources collide on a (pair, date)). MUST mirror
# the fx_source_rank SQL function (migration fx_source_rank) — the read-side canonical pick.
SOURCE_PRECEDENCE = {"frankfurter": 10, "ecb": 20, "fawazahmed0": 30}
_UNKNOWN_RANK = 100


def source_rank(source: str) -> int:
    """Trust rank for ``source`` (lower preferred). Python mirror of ``fx_source_rank`` SQL."""
    return SOURCE_PRECEDENCE.get(source, _UNKNOWN_RANK)


class FxSourceError(Exception):
    """A source could not produce rates (transport, empty/garbled parse, bad date)."""


@dataclass(frozen=True)
class FxObservation:
    """One observed USD-base rate: ``rate`` = units of ``currency`` per 1 USD."""

    currency: str
    as_of_date: date
    rate: Decimal


def to_usd_base(value: Decimal, convention: str) -> Decimal:
    """Normalize a source value to USD-base (currency-per-USD), inverting if USD-quoted."""
    if convention == QUOTE_PER_USD:
        return value
    if convention == USD_PER_QUOTE:
        if value <= 0:
            raise FxSourceError(f"cannot invert non-positive rate {value}")
        return Decimal(1) / value
    raise FxSourceError(f"unknown quote convention {convention!r}")


class FxSource(Protocol):
    """Yields USD-base observations for ``currencies`` over ``[start, end]``."""

    SOURCE: str

    def fetch(self, currencies: Iterable[str], start: date, end: date) -> list[FxObservation]: ...


def parse_frankfurter_timeseries(payload: dict) -> list[FxObservation]:
    """Parse a Frankfurter time-series payload (``base=USD``) to USD-base observations (pure).

    Shape: ``{"base":"USD","rates":{"2024-01-02":{"BRL":4.9,...}, ...}}``. ``base`` must be
    USD (we request it); each ``rates[date][ccy]`` is already currency-per-USD.
    """
    if payload.get("base") != "USD":
        raise FxSourceError(f"expected base=USD, got {payload.get('base')!r}")
    rates = payload.get("rates")
    if not isinstance(rates, dict) or not rates:
        raise FxSourceError("Frankfurter payload has no rates (empty/garbled)")
    out: list[FxObservation] = []
    for date_str, day in rates.items():
        d = date.fromisoformat(date_str)
        for ccy, value in day.items():
            out.append(FxObservation(ccy, d, to_usd_base(Decimal(str(value)), QUOTE_PER_USD)))
    return out


class FrankfurterSource:
    """USD-base daily rates from Frankfurter (ECB-backed; rebased to USD server-side)."""

    SOURCE = "frankfurter"
    BASE_URL = "https://api.frankfurter.dev/v1"

    def __init__(
        self,
        *,
        getter: Callable[[str, dict], dict] | None = None,
        timeout: float = 25.0,
        max_retries: int = 3,
    ) -> None:
        self._getter = getter or self._http_get
        self._timeout = timeout
        self._max_retries = max_retries

    def _http_get(self, url: str, params: dict) -> dict:
        last: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = requests.get(url, params=params, timeout=self._timeout)
            except requests.RequestException as exc:
                last = exc
                time.sleep(0.5 * (attempt + 1))
                continue
            if resp.status_code != 200:
                raise FxSourceError(f"Frankfurter returned HTTP {resp.status_code} for {url}")
            return resp.json()
        raise FxSourceError(f"Frankfurter unreachable after {self._max_retries}: {last}")

    def fetch(self, currencies: Iterable[str], start: date, end: date) -> list[FxObservation]:
        symbols = sorted({c for c in currencies if c != "USD"})
        if not symbols:
            return []
        url = f"{self.BASE_URL}/{start.isoformat()}..{end.isoformat()}"
        payload = self._getter(url, {"base": "USD", "symbols": ",".join(symbols)})
        return parse_frankfurter_timeseries(payload)


def parse_fawazahmed_day(payload: dict, wanted: set[str], as_of: date) -> list[FxObservation]:
    """Parse one fawazahmed0 ``currencies/usd.json`` day to USD-base observations (pure).

    Shape: ``{"date":"2026-06-05","usd":{"twd":31.5,"brl":5.06,...}}`` — the file *is* USD-base
    (``usd[ccy]`` = ccy per 1 USD), keyed by lowercase codes. Only ``wanted`` (uppercase) codes
    are kept.
    """
    usd = payload.get("usd")
    if not isinstance(usd, dict):
        raise FxSourceError("fawazahmed0 payload missing 'usd' map")
    out: list[FxObservation] = []
    for code in wanted:
        value = usd.get(code.lower())
        if value is not None:
            out.append(FxObservation(code, as_of, to_usd_base(Decimal(str(value)), QUOTE_PER_USD)))
    return out


class FawazahmedSource:
    """USD-base daily rates from the fawazahmed0 currency-api (CC0, jsDelivr CDN, no key).

    The breadth fallback: 200+ currencies incl. ones Frankfurter/ECB drops (e.g. TWD). The
    API is **per-date** (one JSON file per day, dated package version), so a range fetch loops
    weekdays and fetches each; a missing date (404) is skipped (fail-graceful). Dated files
    resolve back to ~mid-2024 only — breadth + recent, not deep history.
    """

    SOURCE = "fawazahmed0"
    BASE_URL = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api"

    def __init__(
        self,
        *,
        getter: Callable[[str], dict | None] | None = None,
        timeout: float = 15.0,
        min_interval: float = 0.0,
    ) -> None:
        self._getter = getter or self._http_get
        self._timeout = timeout
        self._min_interval = min_interval
        self._last = 0.0

    def _http_get(self, url: str) -> dict | None:
        if self._min_interval:
            wait = self._min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
        try:
            resp = requests.get(url, timeout=self._timeout)
        except requests.RequestException as exc:
            raise FxSourceError(f"fawazahmed0 unreachable: {exc}") from exc
        if resp.status_code == 404:
            return None  # no file for this date — skip (fail-graceful)
        if resp.status_code != 200:
            raise FxSourceError(f"fawazahmed0 returned HTTP {resp.status_code} for {url}")
        return resp.json()

    def fetch(self, currencies: Iterable[str], start: date, end: date) -> list[FxObservation]:
        wanted = {c.upper() for c in currencies if c != "USD"}
        if not wanted:
            return []
        out: list[FxObservation] = []
        d = start
        while d <= end:
            if d.weekday() < 5:  # weekdays only (match the FX convention; no weekend rows)
                payload = self._getter(f"{self.BASE_URL}@{d.isoformat()}/v1/currencies/usd.json")
                if payload is not None:
                    out.extend(parse_fawazahmed_day(payload, wanted, d))
            d += timedelta(days=1)
        return out


def parse_ecb_csv(text: str) -> dict[date, dict[str, Decimal]]:
    """Parse an ECB SDMX EXR ``csvdata`` payload to raw **EUR-base** rates (pure).

    Returns ``{date: {ccy: ccy_per_eur}}`` (the native ECB direction — e.g. ``USD`` ≈ 1.09
    means 1 EUR buys 1.09 USD). Empty/header-only text → ``{}`` (a valid empty range, e.g.
    an unknown series like TWD which ECB returns as no rows — fail-graceful). A body with
    rows but no recognizable columns raises (genuinely garbled).
    """
    text = text.strip()
    if not text:
        return {}
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0]
    try:
        i_ccy = header.index("CURRENCY")
        i_date = header.index("TIME_PERIOD")
        i_val = header.index("OBS_VALUE")
    except ValueError as exc:
        raise FxSourceError(f"ECB CSV missing expected column: {exc}") from exc
    out: dict[date, dict[str, Decimal]] = {}
    for r in rows[1:]:
        if len(r) <= max(i_ccy, i_date, i_val):
            continue
        value = r[i_val].strip()
        if not value:  # ECB emits blank OBS_VALUE on non-trading days
            continue
        d = date.fromisoformat(r[i_date].strip())
        out.setdefault(d, {})[r[i_ccy].strip().upper()] = Decimal(value)
    return out


def rebase_ecb_to_usd(
    eur_base: dict[date, dict[str, Decimal]], wanted: set[str]
) -> list[FxObservation]:
    """Rebase ECB EUR-base rates to USD-base observations through the EUR/USD leg (pure).

    For each date the ``USD`` leg (USD per 1 EUR) is the pivot: a ``ccy``'s USD-base rate is
    ``(ccy per EUR) / (USD per EUR)``; ``EUR`` itself is ``1 / (USD per EUR)``. A date with
    no USD leg can't be rebased and is skipped (fail-graceful) — the resolver's as-of carry
    bridges it. Only ``wanted`` codes are emitted (USD is the base, never stored).
    """
    out: list[FxObservation] = []
    for d, day in eur_base.items():
        usd_per_eur = day.get("USD")
        if usd_per_eur is None or usd_per_eur <= 0:
            continue  # no pivot leg for this date — cannot rebase
        for ccy in wanted:
            if ccy == "USD":
                continue
            if ccy == "EUR":
                out.append(FxObservation("EUR", d, Decimal(1) / usd_per_eur))
                continue
            ccy_per_eur = day.get(ccy)
            if ccy_per_eur is None or ccy_per_eur <= 0:
                continue  # ECB doesn't cover this currency (e.g. TWD) — leave to fallback
            out.append(FxObservation(ccy, d, ccy_per_eur / usd_per_eur))
    return out


class EcbSdmxSource:
    """USD-base daily rates rebased from ECB SDMX EUR-base reference rates (the reconcile).

    ECB publishes one EUR-base series per currency (``EXR/D.{CCY}.EUR.SP00.A``); a single
    request fetches the EUR/USD pivot plus every wanted non-EUR currency, then
    ``rebase_ecb_to_usd`` folds them to USD-base. ECB's set excludes TWD and a few exotics
    (those return no rows and are left to the fawazahmed0 fallback). History reaches 1999,
    so this also corroborates Frankfurter's deep history for the currencies it covers.
    """

    SOURCE = "ecb"
    BASE_URL = "https://data-api.ecb.europa.eu/service/data/EXR"

    def __init__(
        self,
        *,
        getter: Callable[[str, dict], str] | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self._getter = getter or self._http_get
        self._timeout = timeout
        self._max_retries = max_retries

    def _http_get(self, url: str, params: dict) -> str:
        last: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = requests.get(url, params=params, timeout=self._timeout)
            except requests.RequestException as exc:
                last = exc
                time.sleep(0.5 * (attempt + 1))
                continue
            if resp.status_code != 200:
                raise FxSourceError(f"ECB SDMX returned HTTP {resp.status_code} for {url}")
            return resp.text
        raise FxSourceError(f"ECB SDMX unreachable after {self._max_retries}: {last}")

    def fetch(self, currencies: Iterable[str], start: date, end: date) -> list[FxObservation]:
        wanted = {c.upper() for c in currencies if c != "USD"}
        if not wanted:
            return []
        # Series codes: the USD pivot leg + every wanted non-EUR currency (EUR is derived
        # from the USD leg, so it needs no series of its own).
        series = {"USD"} | {c for c in wanted if c != "EUR"}
        code = "D." + "+".join(sorted(series)) + ".EUR.SP00.A"
        text = self._getter(
            f"{self.BASE_URL}/{code}",
            {"startPeriod": start.isoformat(), "endPeriod": end.isoformat(), "format": "csvdata"},
        )
        return rebase_ecb_to_usd(parse_ecb_csv(text), wanted)
