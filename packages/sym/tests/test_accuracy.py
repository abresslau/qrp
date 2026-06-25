"""SM-6 returns-accuracy harness (Story 3.8, AR-17).

Compares sym's materialized ``fact_returns`` PR/TR against an INDEPENDENT
published reference series (Yahoo's own split-adjusted ``Close`` = PR, and
split+dividend-adjusted ``Adj Close`` = TR — the columns the ingest adapter
discards) across all return windows for the ~50 benchmark seed names. The reference is
captured into ``tests/fixtures/accuracy_reference.json`` by
``benchmark/capture_accuracy_reference.py``; re-run that to refresh it.

This is the SM-6 regression gate on every returns-engine change
(``v_prices_adjusted``, factor derivation, the ``fact_returns`` loader, or the
window definitions). It needs the populated database; it skips cleanly when the
DB or the benchmark data is absent (so the DB-free suite stays green in CI),
which means **it must be run against a populated DB before shipping a
returns-engine change** — that is the gate.

Tolerance policy (per-window, and SM-C2: tolerances are NOT widened to force a
pass — the loose bands below are a *definitional* gap, and PR carries precision
where TR cannot):

  * **PR — strict, every window, every name (`PR_TOL_BPS`).** Both series are
    split-adjusted only, so this is exactly apples-to-apples. Empirically the
    divergence is ~0; this single assertion validates the whole split-factor +
    view + window-anchoring path, which is the dominant silent-corruption risk.
  * **TR — strict where the two TR *definitions* coincide (`TR_TOL_BPS`):**
    clean names (ordinary/no dividend) on non-annualized windows (1D..1Y). This
    is the reinvestment-timing gate the architecture called for.
  * **TR — loose sanity bound elsewhere (`TR_SANITY_BPS`):** corporate-action-
    heavy names, and all multi-year annualized windows. sym reinvests cash
    dividends gross on the ex-date (EXDATE_C); Yahoo back-adjusts CRSP-style and
    its Adj Close omits the spin-offs / specials / scrip those names carry, so
    the gap compounds (and annualization amplifies it). PR remains the precision
    anchor for these names; this bound only catches gross corruption (a missed
    split, a 10x, a sign flip). Divergences are printed for inspection.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest
from equity.returns.windows import BY_CODE

FIXTURE = Path(__file__).resolve().parent / "fixtures/accuracy_reference.json"

PR_TOL_BPS = 10.0  # strict: all windows, all names (observed max ~0.0)
TR_TOL_BPS = 15.0  # strict: clean names, non-annualized windows (observed max ~3.0)
TR_SANITY_BPS = 2500.0  # loose: definitional-gap regime; catches only gross corruption

BPS = 1e-4


def _connect():
    try:
        from sym.db import connect

        return connect()
    except Exception:  # noqa: BLE001 - any config/connection failure -> skip the gate
        return None


def _equity_connect():
    try:
        from equity.db import connect

        return connect()
    except Exception:  # noqa: BLE001 - fact_returns moved to the equity DB; skip the gate if down
        return None


@pytest.fixture(scope="module")
def reference() -> dict:
    if not FIXTURE.exists():
        pytest.skip("accuracy reference fixture not captured")
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# Yahoo symbol suffix -> operating MIC, so a benchmark name resolves to its own
# listing even when the same ticker exists on another exchange (e.g. MC = LVMH on
# XPAR AND Moelis on XNYS once index universes are populated). No suffix -> a US
# listing. This keeps the harness pinned to the *intended* benchmark security.
_SUFFIX_MIC = {
    "KS": "XKRX", "HK": "XHKG", "TW": "XTAI", "T": "XTKS", "AX": "XASX",
    "L": "XLON", "MC": "XMAD", "PA": "XPAR", "SW": "XSWX", "DE": "XETR",
}
_US_MICS = ("XNYS", "XNAS", "XASE", "ARCX")


def _resolve_benchmark_figi(sym_map: dict, ticker: str, symbol: str) -> str | None:
    """Resolve a benchmark (ticker, Yahoo-symbol) to its figi by ticker + exchange."""
    _, sep, suffix = symbol.rpartition(".")
    if sep and suffix.upper() in _SUFFIX_MIC:
        return sym_map.get((ticker, _SUFFIX_MIC[suffix.upper()]))
    for mic in _US_MICS:
        if (ticker, mic) in sym_map:
            return sym_map[(ticker, mic)]
    return None


@pytest.fixture(scope="module")
def sym_returns(reference) -> dict:
    """{ticker: {window_code: (pr, tr)}} from fact_returns at the fixture's as_of_date."""
    conn = _connect()
    eq_conn = _equity_connect()  # fact_returns lives in the equity DB now
    if conn is None or eq_conn is None:
        pytest.skip("database unavailable")
    try:
        as_of_date = reference["as_of_date"]
        sym_map = {
            (sv, (mic or "").strip()): figi
            for sv, mic, figi in conn.execute(
                "SELECT symbol_value, mic, composite_figi FROM security_symbology "
                "WHERE symbol_type = 'ticker' AND valid_to IS NULL"
            ).fetchall()
        }
        id_to_code = {w.id: code for code, w in BY_CODE.items()}
        out: dict[str, dict[str, tuple]] = {}
        for ticker, info in reference["names"].items():
            figi = _resolve_benchmark_figi(sym_map, ticker, info.get("symbol", ticker))
            if figi is None:
                continue
            rows = eq_conn.execute(
                "SELECT window_id, pr, tr FROM fact_returns "
                "WHERE composite_figi = %s AND as_of_date = %s",
                (figi, as_of_date),
            ).fetchall()
            if rows:
                out[ticker] = {id_to_code[wid]: (pr, tr) for wid, pr, tr in rows}
        if not out:
            pytest.skip("benchmark names not present in fact_returns")
        return out
    except psycopg.Error:
        pytest.skip("fact_returns not available")
    finally:
        eq_conn.close()
        conn.close()


def _diffs(reference, sym_returns):
    """Yield (ticker, code, ca_heavy, annualized, pr_diff_bps, tr_diff_bps)."""
    for ticker, info in reference["names"].items():
        sym = sym_returns.get(ticker)
        if sym is None:
            continue
        for code, ref in info["windows"].items():
            if code not in sym:
                continue
            spr, str_ = sym[code]
            pr_diff = (
                abs(float(spr) - ref["pr"]) / BPS
                if ref["pr"] is not None and spr is not None
                else None
            )
            tr_diff = (
                abs(float(str_) - ref["tr"]) / BPS
                if ref["tr"] is not None and str_ is not None
                else None
            )
            yield ticker, code, info["ca_heavy"], BY_CODE[code].annualized, pr_diff, tr_diff


def _is_long_cumulative(code: str) -> bool:
    """Cumulative (non-annualized) multi-year or since-inception window.

    These are **report-only** (excluded from both the strict-clean and sanity gates):
    - For CLEAN names, correct reinvestment matches Yahoo tightly (~0.1% even at 30Y), but
      the small relative residual is still tens–hundreds of bps in absolute terms once a
      return is several hundred % — above the strict-clean band.
    - For CA-heavy names (ADR / multi-currency / special-distribution), the gap vs Yahoo's
      USD Adj Close is genuinely UNBOUNDED at long cumulative horizons (currency translation
      + omitted distributions compound over decades, e.g. HSBA/30Y ~1481%) — no fixed bps
      ceiling is meaningful.
    PR (asserted on every window) is the precision anchor here, and the dividend-reinvestment
    *basis* bug class is locked by a deterministic unit test (test_dividend_reinvested_on_
    split_consistent_basis), so report-only does not hide it.
    """
    w = BY_CODE[code]
    return not w.annualized and ((w.years is not None and w.years >= 2) or w.kind == "inception")


def test_price_return_matches_published_series(reference, sym_returns):
    """PR vs Yahoo split-adjusted close — strict, every window, all names (AC #1)."""
    breaches = [
        f"{t}/{code}: {pr:.1f}bps"
        for t, code, _ca, _ann, pr, _tr in _diffs(reference, sym_returns)
        if pr is not None and pr > PR_TOL_BPS
    ]
    assert breaches == [], f"PR exceeds {PR_TOL_BPS}bps vs published split-adj close: {breaches}"


def test_total_return_matches_published_series_clean(reference, sym_returns):
    """TR vs Yahoo Adj Close — strict where the TR definitions coincide.

    Clean (ordinary/no-dividend) names on non-annualized windows (1D..1Y): this
    is the reinvestment-timing gate. Tolerance is NOT widened (SM-C2).
    """
    breaches = [
        f"{t}/{code}: {tr:.1f}bps"
        for t, code, ca_heavy, annualized, _pr, tr in _diffs(reference, sym_returns)
        if tr is not None
        and not ca_heavy
        and not annualized
        and not _is_long_cumulative(code)
        and tr > TR_TOL_BPS
    ]
    assert breaches == [], f"clean TR exceeds {TR_TOL_BPS}bps vs published Adj Close: {breaches}"


def test_total_return_sanity_bound(reference, sym_returns, capsys):
    """TR loose sanity bound for the definitional-gap regime (CA-heavy / multi-year).

    Not a precision gate (PR carries precision for these names); catches only
    gross corruption. Prints the divergences so a maintainer sees regressions.
    """
    rows, breaches = [], []
    for t, code, ca_heavy, annualized, _pr, tr in _diffs(reference, sym_returns):
        long_cum = _is_long_cumulative(code)
        if tr is None or (not ca_heavy and not annualized and not long_cum):
            continue  # the strict-clean cells are gated by the test above
        rows.append((tr, t, code))
        # Assert the BOUNDED definitional-gap regime only (annualized per-year rates +
        # CA-heavy short windows). Cumulative multi-year / since-inception TR is UNBOUNDED
        # for CA-heavy names -- currency-translation (ADR vs local line) and special-
        # distribution gaps vs Yahoo's USD Adj Close compound over decades (e.g. HSBA/30Y
        # ~1481%), so no fixed ceiling is meaningful -> report-only. PR is the precision
        # anchor for these, and the dividend-reinvestment *basis* bug class (the GE 8x
        # inflation) is locked deterministically by test_dividend_reinvested_on_split_
        # consistent_basis in test_loader.py -- not by this Yahoo-tolerance band.
        if not long_cum and tr > TR_SANITY_BPS:
            breaches.append(f"{t}/{code}: {tr:.1f}bps")
    with capsys.disabled():
        for tr, t, code in sorted(rows, reverse=True)[:12]:
            print(f"  TR gap {t:<8} {code:<8} {tr:8.1f}bps")
    assert breaches == [], f"TR exceeds gross-corruption ceiling {TR_SANITY_BPS}bps: {breaches}"


def test_all_windows_are_covered(reference):
    """Every window appears in the reference for at least one name (all 28)."""
    covered = {code for info in reference["names"].values() for code in info["windows"]}
    missing = {code for code in BY_CODE} - covered
    # The since-inception windows anchor on the calendar floor (~1990), which predates
    # the reference's 31y Yahoo window, so their base never resolves in the fixture.
    assert missing <= {"SI_ANN", "SI"}, f"windows never exercised by the harness: {missing}"
