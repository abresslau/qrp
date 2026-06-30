"""Derive-on-read curve analytics — PURE functions over a BoE curve grid (no DB/IO).

Inputs are ``{tenor_years: value_pct}`` dicts straight from the gateway (values are % per annum, the
BoE published convention). Conventions are pinned from the BoE FAQ (see MAINTENANCE.md):
**continuously compounded, annual basis** → discount factor ``DF(t) = exp(-s/100 · t)``.

Spreads/flies/asset-swaps are differences → returned in **basis points**. Breakeven is a **level** →
returned in **%** (the conventional inflation quote). A computation touching a tenor outside the
published grid returns ``None`` (never a fabricated value).
"""

from __future__ import annotations

import math

Curve = dict[float, float]  # {tenor_years: value_pct}


def interp(curve: Curve, t: float) -> float | None:
    """Linear interpolation on the published nodes (linear-on-zero-rates). None outside the grid
    (no extrapolation — a tenor BoE doesn't publish is genuinely unknown)."""
    if not curve:
        return None
    if t in curve:
        return curve[t]
    ts = sorted(curve)
    if t < ts[0] or t > ts[-1]:
        return None
    for i in range(1, len(ts)):
        if ts[i] >= t:
            t0, t1 = ts[i - 1], ts[i]
            v0, v1 = curve[t0], curve[t1]
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return None


def discount_factor(spot_pct: float, t: float) -> float:
    """Continuous-compounding discount factor for a zero/spot rate (% p.a.) at tenor ``t`` years."""
    return math.exp(-spot_pct / 100.0 * t)


def zero_rate(spot_curve: Curve, t: float) -> float | None:
    """The zero/spot rate (% p.a.) at tenor ``t``, interpolated on the published spot curve."""
    return interp(spot_curve, t)


def curve_spread(spot_curve: Curve, t_short: float, t_long: float) -> float | None:
    """A two-point curve spread (e.g. 2s10s) in **basis points**: long − short."""
    s = interp(spot_curve, t_short)
    long_ = interp(spot_curve, t_long)
    if s is None or long_ is None:
        return None
    return (long_ - s) * 100.0


def butterfly(spot_curve: Curve, t_short: float, t_mid: float, t_long: float) -> float | None:
    """A fly (e.g. 2s5s10s) in **basis points**: 2·mid − short − long (curvature)."""
    s = interp(spot_curve, t_short)
    m = interp(spot_curve, t_mid)
    long_ = interp(spot_curve, t_long)
    if s is None or m is None or long_ is None:
        return None
    return (2.0 * m - s - long_) * 100.0


def breakeven(nominal_spot: Curve, real_spot: Curve, t: float) -> float | None:
    """Implied inflation breakeven at tenor ``t`` as a **level in %**: nominal − real.

    Index-AGNOSTIC — the inflation index is whatever the real curve is linked to, named by the
    caller's label: **RPI** for the UK gilt curve (linker indexation lag — never CPI), **IPCA** for
    the BR Tesouro curve (and that BR variant is approximate — nominal/real issues mature on
    different dates, so the tenors are interpolated, not matched)."""
    n = interp(nominal_spot, t)
    r = interp(real_spot, t)
    if n is None or r is None:
        return None
    return n - r


def asset_swap_proxy(nominal_gilt_spot: Curve, ois_spot: Curve, t: float) -> float | None:
    """Asset-swap PROXY in **basis points**: gilt nominal yield − OIS at the same tenor.

    A clean par/par ASW needs the bond's cashflows (deferred bond-reference-data); this is the
    yield-level proxy, to be labelled as such."""
    g = interp(nominal_gilt_spot, t)
    o = interp(ois_spot, t)
    if g is None or o is None:
        return None
    return (g - o) * 100.0


def roll_down(spot_curve: Curve, t: float, horizon_years: float) -> float | None:
    """Roll-down in **basis points** over ``horizon_years``: spot(t) − spot(t − h).

    As time passes a t-year point becomes a (t−h)-year point; on an upward curve the yield rolls
    DOWN (a price gain). Positive = the yield falls as it rolls (favourable for a long)."""
    if horizon_years <= 0 or horizon_years >= t:
        return None
    now = interp(spot_curve, t)
    rolled = interp(spot_curve, t - horizon_years)
    if now is None or rolled is None:
        return None
    return (now - rolled) * 100.0


def carry_roll(
    spot_curve: Curve, fwd_curve: Curve, t: float, horizon_years: float
) -> dict[str, float | None]:
    """Carry + roll-down (both **bp**) over a horizon. Carry ≈ the forward's pickup over spot at the
    horizon (forward(h) − spot(t)); roll = spot(t) − spot(t−h). Returns {carry_bp, roll_bp}."""
    roll = roll_down(spot_curve, t, horizon_years)
    s = interp(spot_curve, t)
    f = interp(fwd_curve, horizon_years)
    carry = None if (s is None or f is None) else (f - s) * 100.0
    return {"carry_bp": carry, "roll_bp": roll}


def present_value(cashflows: list[tuple[float, float]], spot_curve: Curve) -> float | None:
    """PV of ``[(tenor_years, amount), ...]`` discounted on the spot curve (continuous compounding).

    None if any cashflow tenor falls outside the published grid (can't honestly discount it)."""
    total = 0.0
    for t, amt in cashflows:
        z = zero_rate(spot_curve, t)
        if z is None:
            return None
        total += amt * discount_factor(z, t)
    return total


def dv01(cashflows: list[tuple[float, float]], spot_curve: Curve) -> float | None:
    """DV01: PV change for a 1bp parallel DOWN-shift of the curve (price sensitivity per 1bp).

    Positive for a positive cashflow stream. None if the curve misses any cashflow tenor."""
    base = present_value(cashflows, spot_curve)
    if base is None:
        return None
    shifted = present_value(cashflows, {t: v - 0.01 for t, v in spot_curve.items()})  # −1bp
    if shifted is None:
        return None
    return shifted - base
