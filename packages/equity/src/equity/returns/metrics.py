"""Asset-level risk metrics — per-window volatility & Sharpe (companion to fact_returns).

For each ``(composite_figi, window_id, as_of_date)`` this computes the **annualized volatility**
and **Sharpe ratio** of the security's own daily returns over the window's ``(base, as_of]`` span —
the risk-adjusted twin of the point-to-point returns in ``fact_returns``. Volatility here is the
dispersion of the DAILY returns inside the window (NOT the single point-to-point window return), so
"1M volatility" = the stdev of the ~21 daily returns in the trailing month.

Conventions (see the story's research note):
  * **vol** = ``stddev_samp(daily) × sqrt(252)`` — annualized sample stdev (matches the existing
    ``signals.vol_1y`` definition, so the 1Y window reconciles with that factor).
  * **sharpe** = ``(mean(daily) / stddev_samp(daily)) × sqrt(252)`` with **rf = 0** (annualize the
    ratio ONCE — do NOT replicate ``backtest.score_weights``'s ``(mean×√252)/(sd×√252)`` which
    cancels to a *daily* Sharpe). A real risk-free rate is a documented future refinement.
  * Both are computed on **PR** (split-adjusted) and **TR** (dividend-reinvested) daily series; they
    differ on dividend payers.
  * ``n_obs`` (the daily-return count in the window) is stored so CONSUMERS apply their own floor —
    e.g. ``signals.vol_1y`` keeps its ≥60-obs gate downstream. Here a value needs only ``n_obs ≥ 2``
    (the sample-stdev minimum) and a positive stdev; otherwise NULL (never fabricated).

Like ``fact_returns``/``fact_price_extremes`` this is loader-written from the SAME per-figi adjusted
+ TRI series (no second price read) and carries an ``input_hash`` so the dirty-set rewrites only
moved rows. Gating is WHOLE-WINDOW (AR-9): a row is held NULL when ANY session in ``[base, end]``
(or the as-of) carries an unreviewed ``prices_review`` flag — endpoint-only gating (what
``fact_returns`` uses for its two-price returns) is insufficient for a stdev over the whole span,
which would otherwise fold a suspect interior price into a published metric. The hash is over the
REAL (pre-gate) values + the in-window flag count, so a later price revision OR a review re-dirties
even a gated row (Story 3.6). See ``compute_metric_rows`` for the exact rule and how it reconciles
with ``signals.vol_1y``.
"""

from __future__ import annotations

import bisect
import hashlib
import math
import statistics
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from equity.returns.windows import INCEPTION, WINDOWS, base_date, end_date

TRADING_DAYS = 252  # annualization factor (vol ×√252); matches signals.vol_1y
MIN_OBS = 2  # sample stdev needs ≥2 daily returns; consumers apply any stricter floor via n_obs


def metric_input_hash(
    window_id: int,
    calendar_version: int | None,
    base: date | None,
    end: date | None,
    vol_pr: float | None,
    vol_tr: float | None,
    sharpe_pr: float | None,
    sharpe_tr: float | None,
    n_obs: int,
    n_flags: int,
) -> str:
    """Stable hash of a metric row's inputs (parity with the returns/extremes hashes).

    Keyed on ``window_id`` (so two windows collapsing to the same base/end never collide), the
    calendar version + window endpoints + the computed REAL values (vol/Sharpe are functions of the
    whole in-window daily series, so hashing them re-dirties the row on ANY interior price change,
    not just an endpoint move) + ``n_obs`` + ``n_flags`` (the count of unreviewed flags in the
    window). Computed on real values even for a gated row, and ``n_flags`` re-dirties the row when a
    review changes the in-window flag set without moving the underlying prices.
    """
    payload = (
        f"{window_id}|{calendar_version}|{base}|{end}|"
        f"{vol_pr}|{vol_tr}|{sharpe_pr}|{sharpe_tr}|{n_obs}|{n_flags}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MetricRow:
    """One materialized risk-metric row (entity id added at upsert time, like ExtremeRow)."""

    window_id: int
    as_of_date: date
    vol_pr: float | None
    vol_tr: float | None
    sharpe_pr: float | None
    sharpe_tr: float | None
    n_obs: int
    input_hash: str
    gated: bool = False


def daily_returns(series: dict[date, Decimal]) -> dict[date, float]:
    """Consecutive-session simple returns from a date→price series (pure).

    ``ret[d] = price[d] / price[prev] − 1`` where ``prev`` is the immediately preceding priced
    session. The return dated ``d`` reflects the move INTO ``d``; a non-positive price breaks the
    chain (that day and the next get no return) — corrupt data never yields a fabricated return.
    """
    sessions = sorted(series)
    out: dict[date, float] = {}
    prev: Decimal | None = None
    for d in sessions:
        px = series[d]
        if prev is not None and prev > 0 and px is not None and px > 0:
            out[d] = float(px / prev) - 1.0
        prev = px
    return out


def _vol_sharpe(rets: list[float]) -> tuple[float | None, float | None]:
    """(annualized vol, annualized Sharpe rf=0) from a list of daily returns. NULL if < MIN_OBS."""
    if len(rets) < MIN_OBS:
        return None, None
    sd = statistics.stdev(rets)  # sample stdev (n−1); raises only on <2, guarded above
    if sd <= 0.0:
        return None, None
    vol = sd * math.sqrt(TRADING_DAYS)
    sharpe = (statistics.fmean(rets) / sd) * math.sqrt(TRADING_DAYS)  # rf = 0
    return vol, sharpe


def compute_metric_rows(
    figi: str,
    as_of_dates: Sequence[date],
    adj: dict[date, Decimal],
    tri: dict[date, Decimal],
    sessions: Sequence[date],
    calendar_version: int | None,
    gated_dates: Collection[date] = frozenset(),
) -> list[MetricRow]:
    """Per-window vol + Sharpe rows for one security across ``as_of_dates`` (pure).

    Volatility/Sharpe are computed from the daily returns whose session lies in ``(base, end]`` —
    base is EXCLUSIVE (the return dated ``base`` is base-1→base, outside the window). ``1D`` and any
    window with < MIN_OBS daily returns → NULL (INCEPTION windows anchor at the first priced
    session, like ``compute_return_rows``).

    **Flag handling — EXCLUDE the tainted returns, don't gate the window (a dispersion metric).**
    A daily return is TAINTED when its session, or the priced session immediately before it, carries
    an unreviewed ``prices_review`` flag (a flagged price corrupts the ratio INTO it and OUT of it).
    Tainted returns are dropped from the vol/Sharpe sample and the metric is computed over the clean
    remainder — exactly what ``signals.vol_1y`` does (`pr IS NOT NULL` on the 1D window drops the
    same set), so the 1Y window reconciles with that factor even when flags are present. This is the
    right model for TWO reasons: (a) endpoint-only gating (what ``fact_returns`` uses for a
    two-price return) would fold a suspect INTERIOR price into a published stdev; (b) whole-window
    NULLing would destroy coverage, since one partial-EOD can flag ~every name (flags are common
    here). ``n_obs`` is the CLEAN count so consumers see the effective sample. The only row that is
    gated NULL is one whose **as-of (snapshot) date** is itself flagged — the point-in-time label is
    suspect — mirroring ``fact_returns`` gating its own as-of-dated row. ``input_hash`` is over the
    real clean-day values + ``n_obs`` + the in-window flag count, so a price revision OR a review
    (which changes the tainted set → the values/counts) re-dirties even a gated row.
    """
    pr_daily = daily_returns(adj)
    tr_daily = daily_returns(tri)
    pr_sessions = sorted(pr_daily)
    tr_sessions = sorted(tr_daily)
    first_priced = min(adj) if adj else None
    flags = sorted(gated_dates)
    # Tainted return dates: session d where d or the priced session before d is an unreviewed flag.
    tainted: set[date] = set()
    if gated_dates:
        price_sessions = sorted(adj)
        for i in range(1, len(price_sessions)):
            prev, d = price_sessions[i - 1], price_sessions[i]
            if prev in gated_dates or d in gated_dates:
                tainted.add(d)
    rows: list[MetricRow] = []

    def _window_rets(
        daily: dict[date, float], sess: list[date], base: date, end: date
    ) -> list[float]:
        lo = bisect.bisect_right(sess, base)   # first session strictly after base
        hi = bisect.bisect_right(sess, end)    # one past the last session <= end
        return [daily[sess[i]] for i in range(lo, hi) if sess[i] not in tainted]

    def _flags_in(base: date, end: date) -> int:
        # count unreviewed flags in the inclusive [base, end] span (base's price feeds the first
        # in-window return; end's the last), via the sorted-flags bisect — a hash discriminator.
        return bisect.bisect_right(flags, end) - bisect.bisect_left(flags, base)

    for as_of_date in as_of_dates:
        for window in WINDOWS:
            end = end_date(window, as_of_date, sessions)
            base = (
                first_priced if window.kind == INCEPTION
                else base_date(window, as_of_date, sessions)
            )
            if base is None or end is None or base >= end:
                # Window undefined (insufficient history) or degenerate span → NULL, n_obs 0.
                gated0 = as_of_date in gated_dates
                ih = metric_input_hash(
                    window.id, calendar_version, base, end, None, None, None, None, 0, int(gated0)
                )
                rows.append(MetricRow(window.id, as_of_date, None, None, None, None, 0, ih,
                                      gated=gated0))
                continue
            # tainted returns excluded → computed over the clean remainder (matches signals.vol_1y)
            pr_rets = _window_rets(pr_daily, pr_sessions, base, end)
            tr_rets = _window_rets(tr_daily, tr_sessions, base, end)
            vol_pr, sharpe_pr = _vol_sharpe(pr_rets)
            vol_tr, sharpe_tr = _vol_sharpe(tr_rets)
            n_obs = len(pr_rets)
            gated = as_of_date in gated_dates  # only the flagged SNAPSHOT date is withheld
            ih = metric_input_hash(
                window.id, calendar_version, base, end, vol_pr, vol_tr, sharpe_pr, sharpe_tr,
                n_obs, _flags_in(base, end),
            )
            rows.append(
                MetricRow(
                    window_id=window.id,
                    as_of_date=as_of_date,
                    vol_pr=None if gated else vol_pr,
                    vol_tr=None if gated else vol_tr,
                    sharpe_pr=None if gated else sharpe_pr,
                    sharpe_tr=None if gated else sharpe_tr,
                    n_obs=n_obs,
                    input_hash=ih,
                    gated=gated,
                )
            )
    return rows
