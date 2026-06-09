"""Capture the SM-6 accuracy reference fixture (Story 3.8, AR-17).

Snapshots an INDEPENDENT published return series for the benchmark names into
``tests/fixtures/accuracy_reference.json``, which ``tests/test_accuracy.py``
compares sym's ``fact_returns`` PR/TR against.

The reference is **Yahoo's own published adjusted series** — the very columns the
ingest adapter discards (``yfinance_adapter`` drops ``Adj Close`` and rebuilds
factors from explicit actions, AR-6). With ``auto_adjust=False``:

  * ``Close``      is split-adjusted only            -> price-return reference
  * ``Adj Close``  is split + dividend adjusted       -> total-return reference

Independence: Yahoo *back-adjusts* (CRSP-style, multiplying historical prices by
``∏(1 - div/close)``) whereas sym *forward-builds* from explicit split factors
(``v_prices_adjusted``) and an EXDATE_C reinvestment TRI (the loader). Same raw
price vendor, independently-computed adjustment + total-return math. A subtle
factor or reinvestment-timing bug in sym shows up as a per-window divergence
here. The window *endpoints* are shared (sym's ``base_date`` + snapshotted
calendar) so we compare like-for-like; the reference *return arithmetic* below is
reimplemented in plain float (NOT ``canonical_return``) so a bug in sym's return
formula is also caught.

This is a manual, network-touching capture (re-run to refresh the fixture after a
deliberate reference change). It is NOT part of the test suite.

Usage:  uv run python benchmark/capture_accuracy_reference.py [--as_of_date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import bisect
import json
import tomllib
from datetime import date, timedelta
from pathlib import Path

from sym.db import connect
from sym.returns.loader import _calendar_sessions
from sym.returns.windows import WINDOWS, base_date, end_date
from sym.sources.yfinance_adapter import make_yahoo_symbol_resolver

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests/fixtures/accuracy_reference.json"
SEED = REPO / "benchmark/seed_universe.toml"

# Seed categories whose names carry heavy/irregular distributions (specials,
# scrip/stock dividends, spin-offs), distress restructurings, or cross-vendor
# scaling (ADR ratio, FX, minor-unit) where Yahoo's CRSP back-adjustment and
# sym's dividend-only EXDATE_C TRI legitimately diverge by more than a few bps.
# Our reverse_split cohort (GE/C/SIRI/AIG) are all distress/restructure names
# with dividend cuts + spin-offs/split-offs, so they are CA-heavy in practice.
# Everything left — baseline, forward_split, share_class (ordinary or no
# dividend) — is "clean": the regime where sym TR and the reference agree tightly.
CA_HEAVY_CATEGORIES = frozenset(
    {"reverse_split", "special_dividend", "stock_dividend", "spin_off", "adr", "multi_currency"}
)


def _ticker_categories() -> dict[str, str]:
    data = tomllib.loads(SEED.read_text(encoding="utf-8"))
    return {s["ticker"]: s["category"] for s in data["security"] if s.get("ticker")}


def _yahoo_series(symbol: str, start: date, end: date):
    """(sorted dates, split-adj close, total-adj close) from Yahoo's published frame."""
    import yfinance as yf

    frame = yf.Ticker(symbol).history(
        start=start, end=end + timedelta(days=1), auto_adjust=False, actions=True
    )
    dates, split_adj, total_adj = [], {}, {}
    for index, row in frame.iterrows():
        d = index.date()
        dates.append(d)
        split_adj[d] = float(row["Close"])  # split-adjusted only (PR reference)
        total_adj[d] = float(row["Adj Close"])  # split + dividend (TR reference)
    dates.sort()
    return dates, split_adj, total_adj


def _on_or_before(dates: list[date], target: date) -> date | None:
    i = bisect.bisect_right(dates, target)
    return dates[i - 1] if i > 0 else None


def _ref_return(price_asof: float, price_base: float, *, annualized: bool, years: float):
    """Independent return arithmetic: cumulative ratio-1, or CAGR over years."""
    if price_base is None or price_base <= 0 or price_asof is None:
        return None
    ratio = price_asof / price_base
    if not annualized:
        return ratio - 1.0
    if years <= 0:
        return None
    return ratio ** (1.0 / years) - 1.0


def capture(as_of_date: date) -> dict:
    conn = connect()
    resolve = make_yahoo_symbol_resolver(conn)
    categories = _ticker_categories()

    subjects = conn.execute(
        """
        SELECT DISTINCT y.symbol_value AS ticker, s.composite_figi, s.mic
          FROM fact_returns f
          JOIN securities s USING (composite_figi)
          JOIN security_symbology y ON y.composite_figi = s.composite_figi
               AND y.symbol_type = 'ticker' AND y.valid_to IS NULL
         WHERE f.as_of_date = %s
         ORDER BY ticker
        """,
        (as_of_date,),
    ).fetchall()

    names: dict[str, dict] = {}
    for ticker, figi, mic in subjects:
        # SM-6 is the *curated adversarial seed* harness (calibrated per-category
        # tolerances); universe-wide correctness is `sym validate`, not this. Once the
        # universe is populated, fact_returns holds ~2k names — keep only the seed.
        if ticker not in categories:
            continue
        mic = mic.strip() if isinstance(mic, str) else mic
        symbol = resolve(figi)
        if symbol is None:
            print(f"  skip {ticker}: no Yahoo symbol")
            continue
        sessions = _calendar_sessions(conn, mic)
        start = as_of_date.replace(year=as_of_date.year - 31)
        try:
            ydates, split_adj, total_adj = _yahoo_series(symbol, start, as_of_date)
        except Exception as exc:  # noqa: BLE001 - capture tool, log and continue
            print(f"  skip {ticker} ({symbol}): {exc}")
            continue
        if not ydates:
            print(f"  skip {ticker} ({symbol}): empty Yahoo series")
            continue

        windows: dict[str, dict] = {}
        for w in WINDOWS:
            end = end_date(w, as_of_date, sessions)  # as-of for most windows; past for `period`
            base = base_date(w, as_of_date, sessions)
            if base is None or end is None:
                continue
            y_end = _on_or_before(ydates, end)
            y_base = _on_or_before(ydates, base)
            if y_end is None or y_base is None:
                continue
            years = (end - base).days / 365.25
            ann = w.annualized
            pr = _ref_return(split_adj[y_end], split_adj[y_base], annualized=ann, years=years)
            tr = _ref_return(total_adj[y_end], total_adj[y_base], annualized=ann, years=years)
            windows[w.code] = {"base": base.isoformat(), "end": end.isoformat(), "pr": pr, "tr": tr}

        category = categories.get(ticker, "baseline")
        names[ticker] = {
            "symbol": symbol,
            "category": category,
            "ca_heavy": category in CA_HEAVY_CATEGORIES,
            "windows": windows,
        }
        print(f"  {ticker:<10} {symbol:<10} {category:<16} windows={len(windows)}")

    conn.close()
    # Guard against a silent empty/near-empty capture: if seed tickers stop matching
    # `security_symbology.symbol_value` (case/suffix drift) the filter above drops
    # everything, the fixture is written empty, and the accuracy gate then passes
    # vacuously (no cells to breach). Fail loudly instead.
    captured = len(names)
    expected = len(categories)
    if captured < max(1, expected // 2):
        raise SystemExit(
            f"capture matched only {captured}/{expected} seed tickers — likely a "
            f"ticker/symbology format mismatch; refusing to write a degenerate fixture."
        )
    return {
        "as_of_date": as_of_date.isoformat(),
        "source": (
            "yfinance auto_adjust=False: Close (split-adj)=PR ref, "
            "Adj Close (split+div)=TR ref"
        ),
        "note": (
            "Independent published reference for SM-6. "
            "Re-run benchmark/capture_accuracy_reference.py to refresh."
        ),
        "names": names,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as_of_date", type=date.fromisoformat, default=None)
    args = parser.parse_args()

    as_of_date = args.as_of_date
    if as_of_date is None:
        conn = connect()
        as_of_date = conn.execute("SELECT max(as_of_date) FROM fact_returns").fetchone()[0]
        conn.close()
    print(f"Capturing SM-6 reference as of {as_of_date} ...")

    fixture = capture(as_of_date)
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {FIXTURE} ({len(fixture['names'])} names)")


if __name__ == "__main__":
    main()
