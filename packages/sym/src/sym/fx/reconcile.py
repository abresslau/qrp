"""FX cross-source divergence reconcile (Epic FX, FR4b).

Compares two sources' stored USD-base rates on overlapping ``(currency, as_of_date)`` and
flags relative disagreement beyond a threshold. This was *deferred* in single-source FX2
(divergence is meaningless with one source); it lands now that ECB corroborates Frankfurter.
Frankfurter *is* ECB rebased to USD server-side, while ``EcbSdmxSource`` rebases ECB's
EUR-base rates client-side — so a divergence beyond rounding signals a mis-mapped date, a
bad rebase, or a vendor glitch rather than genuine market disagreement.

On-demand (``sym fx divergence``), not an always-on gate: it needs two sources populated, so
wiring it into ``sym validate`` would make the suite depend on the ECB backfill. Pure
``relative_divergence``/``compare`` (unit-tested DB-free) + a thin DB wrapper.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import psycopg

# Default flag threshold: 0.5% relative. Frankfurter and ECB share the same underlying ECB
# fixings, so genuine agreement is sub-rounding; 0.5% leaves headroom for rebase precision
# while still catching a real mismatch.
DEFAULT_DIVERGENCE = Decimal("0.005")


def relative_divergence(rate_a: Decimal, rate_b: Decimal) -> Decimal:
    """Relative gap of ``rate_a`` vs the reference ``rate_b``: ``abs(a / b - 1)`` (pure)."""
    if rate_b <= 0:
        raise ValueError(f"reference rate must be positive, got {rate_b}")
    return abs(rate_a / rate_b - Decimal(1))


@dataclass(frozen=True)
class Divergence:
    """One overlapping observation where two sources disagree beyond the threshold."""

    currency: str
    as_of_date: date
    rate_a: Decimal
    rate_b: Decimal
    rel: Decimal


def compare(
    rows: Iterable[tuple[str, date, Decimal, Decimal]], *, threshold: Decimal = DEFAULT_DIVERGENCE
) -> list[Divergence]:
    """Flag overlapping ``(ccy, date, rate_a, rate_b)`` rows whose relative gap exceeds
    ``threshold`` (pure). ``rate_b`` is the reference; results are worst-first."""
    flagged: list[Divergence] = []
    for ccy, d, rate_a, rate_b in rows:
        rel = relative_divergence(rate_a, rate_b)
        if rel > threshold:
            flagged.append(Divergence(ccy, d, rate_a, rate_b, rel))
    flagged.sort(key=lambda x: x.rel, reverse=True)
    return flagged


@dataclass
class DivergenceReport:
    source_a: str
    source_b: str
    threshold: Decimal
    compared: int = 0
    diverged: int = 0
    max_rel: Decimal = Decimal(0)
    worst: list[Divergence] = field(default_factory=list)


def find_divergences(
    conn: psycopg.Connection,
    *,
    source_a: str = "frankfurter",
    source_b: str = "ecb",
    threshold: Decimal = DEFAULT_DIVERGENCE,
    start: date | None = None,
    currencies: Sequence[str] | None = None,
) -> DivergenceReport:
    """Compare ``source_a`` vs ``source_b`` on every overlapping USD-base ``(ccy, date)``.

    ``source_b`` is the reference (denominator). Optionally bound by ``start`` date and a
    ``currencies`` subset. Returns counts + the worst offenders (the caller decides how many
    to print)."""
    sql = [
        "SELECT a.quote_currency, a.as_of_date, a.rate, b.rate",
        "  FROM fx_rate a JOIN fx_rate b",
        "    ON a.base_currency = 'USD' AND b.base_currency = 'USD'",
        "   AND a.quote_currency = b.quote_currency AND a.as_of_date = b.as_of_date",
        " WHERE a.source = %s AND b.source = %s",
    ]
    params: list[object] = [source_a, source_b]
    if start is not None:
        sql.append("   AND a.as_of_date >= %s")
        params.append(start)
    if currencies:
        sql.append("   AND a.quote_currency = ANY(%s)")
        params.append([c.upper() for c in currencies])
    rows = conn.execute("\n".join(sql), params).fetchall()
    flagged = compare(rows, threshold=threshold)
    return DivergenceReport(
        source_a=source_a,
        source_b=source_b,
        threshold=threshold,
        compared=len(rows),
        diverged=len(flagged),
        max_rel=flagged[0].rel if flagged else Decimal(0),
        worst=flagged,
    )
