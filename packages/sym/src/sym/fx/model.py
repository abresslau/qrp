"""FX canonical-direction rule (Epic FX, FX1).

The storage invariant: one row per unordered currency pair, in a single canonical
direction. USD is the pivot (rank 0) so it is *always* the base; any non-USD cross
is ordered alphabetically (base < quote). This is the Python mirror of the inlined
``fx_rate_canonical_direction`` CHECK — used by the ingest to orient a pair before
write, and unit-tested DB-free. The SQL CHECK is the backstop.

A future non-USD pivot (e.g. EUR for the ECB reconcile) would change this rule *and*
require a migration — deliberately, not silently.
"""

from __future__ import annotations

USD = "USD"


def _rank(code: str) -> tuple[int, str]:
    """Sort key: USD first (rank 0), everything else alphabetically (rank 1)."""
    return (0, "") if code == USD else (1, code)


def canonical_pair(a: str, b: str) -> tuple[str, str]:
    """Orient an unordered pair ``{a, b}`` into the canonical ``(base, quote)``.

    USD is always the base; otherwise the alphabetically-smaller code is the base.
    Raises on a self-pair (``a == b``) — there is no rate of a currency against itself
    to store (USD/USD = 1 is injected by the derivation layer, never stored).
    """
    if a == b:
        raise ValueError(f"no self-pair rate to store: {a}/{b}")
    return (a, b) if _rank(a) < _rank(b) else (b, a)


def is_canonical_direction(base: str, quote: str) -> bool:
    """True iff ``(base, quote)`` is the legal stored direction (mirrors the SQL CHECK)."""
    if base == quote:
        return False
    if base == USD:
        return True
    return quote != USD and base < quote
