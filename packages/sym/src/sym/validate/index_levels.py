"""Index-level source reconciliation — does our stored close match the vendor's official close?

`sym validate` proper is DB-internal (deterministic, runs in the EOD pipeline). This check is the
complement: a *live* reconciliation that re-fetches each index's official close from the
source and compares it to the latest level we stored. It exists because the daily OHLC *candle*
close a bulk history pull returns can differ from the settled official close for some symbols
(notably Yahoo ``^BVSP`` / IBOVESPA, whose unsettled current-day candle lags its official close) —
a small divergence no internal check can see. Divergence is graded in basis points: a tiny gap is
a warn (vendor noise), a large one a fail (a real data break). Network-dependent, so it lives behind
its own ``sym index-reconcile`` command rather than the EOD gate.
"""

from __future__ import annotations

from dataclasses import dataclass

from sym.validate.results import CheckResult

# Default tolerances. FP round-tripping (e.g. 7500.580078125 vs 7500.58) is <0.01 bps, so 5 bps is a
# comfortable floor for "materially different"; 50 bps (0.50%) is a clear data break.
DEFAULT_WARN_BPS = 5.0
DEFAULT_FAIL_BPS = 50.0


@dataclass(frozen=True)
class StoredLevel:
    """The latest index level we hold, keyed to its source symbol for reconciliation."""

    sym_id: int
    name: str
    symbol: str  # the source symbol (e.g. "^BVSP")
    last_date: str  # ISO date of the stored latest session
    level: float


@dataclass(frozen=True)
class OfficialQuote:
    """The source's official close for an index (the settled value, not the candle)."""

    date: str | None  # ISO date the official close belongs to
    price: float | None


def reconcile_index_levels(
    stored: list[StoredLevel],
    quotes: dict[str, OfficialQuote | None],
    *,
    warn_bps: float = DEFAULT_WARN_BPS,
    fail_bps: float = DEFAULT_FAIL_BPS,
) -> CheckResult:
    """Compare each stored latest level against the source's official close (PURE — no I/O).

    Only same-date pairs are reconciled: if the source's official close is for a *newer* session
    than what we hold, that's a freshness signal (warn: the board is behind), not a fidelity gap.
    A missing quote warns (couldn't verify). Divergence ≥ ``fail_bps`` fails; ≥ ``warn_bps`` warns.
    """
    failures: list[str] = []
    warnings: list[str] = []
    checked = 0
    for s in stored:
        q = quotes.get(s.symbol)
        if q is None or q.price is None:
            warnings.append(f"{s.name} ({s.symbol}): no official quote to reconcile against")
            continue
        if q.date is not None and q.date != s.last_date:
            warnings.append(
                f"{s.name} ({s.symbol}): stored latest {s.last_date} but source official is "
                f"{q.date} — the stored series is behind the source"
            )
            continue
        checked += 1
        if not s.level or not q.price:
            failures.append(f"{s.name} ({s.symbol}) {s.last_date}: non-positive level/quote")
            continue
        bps = abs(s.level / q.price - 1.0) * 10_000.0
        if bps >= fail_bps:
            failures.append(
                f"{s.name} ({s.symbol}) {s.last_date}: stored {s.level:g} vs official "
                f"{q.price:g} ({bps:.1f} bps)"
            )
        elif bps >= warn_bps:
            warnings.append(
                f"{s.name} ({s.symbol}) {s.last_date}: stored {s.level:g} vs official "
                f"{q.price:g} ({bps:.1f} bps)"
            )
    return CheckResult.from_items(
        "index_level_fidelity",
        checked=checked,
        failures=failures,
        warnings=warnings,
        detail=(
            f"stored latest index close vs source official "
            f"(warn>={warn_bps:g}bps, fail>={fail_bps:g}bps)"
        ),
    )


def gather_latest_index_levels(conn) -> list[StoredLevel]:
    """The latest stored level per Yahoo-sourced index (the reconciliation universe).

    MSCI aggregates carry an ``msci`` xref (different source/endpoint) and are skipped — they'd need
    their own reconciliation against the MSCI service.
    """
    rows = conn.execute(
        """
        WITH ranked AS (
            SELECT sym_id, session_date, level,
                   row_number() OVER (PARTITION BY sym_id ORDER BY session_date DESC) AS rn
              FROM index_levels
        )
        SELECT i.sym_id, i.name,
               (SELECT value FROM instrument_xref x
                 WHERE x.sym_id = i.sym_id AND x.source = 'yahoo' LIMIT 1) AS yahoo,
               r.session_date, r.level
          FROM instrument i
          JOIN ranked r ON r.sym_id = i.sym_id AND r.rn = 1
         WHERE i.kind = 'index'
        """
    ).fetchall()
    return [
        StoredLevel(sid, name, sym, d.isoformat(), float(lv))
        for sid, name, sym, d, lv in rows
        if sym
    ]


def check_index_level_fidelity(
    conn,
    source,
    *,
    warn_bps: float = DEFAULT_WARN_BPS,
    fail_bps: float = DEFAULT_FAIL_BPS,
) -> CheckResult:
    """Gather stored latest levels + the source's official quotes, then reconcile (I/O wrapper).

    A per-symbol fetch failure becomes a missing quote (a warn), never aborting the whole check.
    """
    stored = gather_latest_index_levels(conn)
    quotes: dict[str, OfficialQuote | None] = {}
    for s in stored:
        if s.symbol in quotes:
            continue
        try:
            iso, price = source.official_quote(s.symbol)
            quotes[s.symbol] = OfficialQuote(iso, price)
        except Exception:  # noqa: BLE001 — a vendor failure is a missing quote, not a crash
            quotes[s.symbol] = None
    return reconcile_index_levels(stored, quotes, warn_bps=warn_bps, fail_bps=fail_bps)
