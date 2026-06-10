"""Criteria (rules-based screen) universe provider — Story U5.2.

A *function-evaluating* provider: instead of reading a published membership, it
**computes** ``members(date) = {s : rule(s, date)}`` against the fundamentals input
(U5.1), and emits the result as ``join`` change-events (``figi:`` tokens) at the
evaluation date. Snapshotting the computed screen into the event log makes a
criteria universe point-in-time queryable and reproducible like any other.

The provider needs DB access to evaluate, so it is constructed with a connection
(``refresh_universe`` injects it). The MVP rule is ``top_n_market_cap``; more rules
slot into ``_RULES`` without touching the membership pipeline.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import psycopg

from sym.universe.membership_diff import figi_token
from sym.universe.registry import CRITERIA, JOIN, POLL_BOUNDED, MembershipChange, register_provider

SOURCE = "criteria"


# A market-cap input older than this is too stale to rank against live names (a
# delisted mega-cap's final close must not compete with current prices forever).
MAX_INPUT_AGE_DAYS = 400


def _top_n_market_cap(conn: psycopg.Connection, as_of_date: date, n: int) -> list[str]:
    """The ``n`` largest securities by **USD market cap** as of ``as_of_date``.

    Ranks ``fundamentals.market_cap_usd`` (maintained by ``recompute_market_cap_usd``)
    rather than ``shares × raw close``: raw closes mix currencies (and pence-quoted
    listings) in one ordering, which is meaningless for a cross-listed screen. The
    latest observation on/before ``as_of_date`` is used, bounded by
    ``MAX_INPUT_AGE_DAYS`` so dead names age out of the screen.
    """
    rows = conn.execute(
        """
        SELECT composite_figi FROM (
            SELECT DISTINCT ON (composite_figi) composite_figi, market_cap_usd
              FROM fundamentals
             WHERE as_of_date <= %s
               AND as_of_date > %s::date - %s
               AND market_cap_usd IS NOT NULL AND market_cap_usd > 0
             ORDER BY composite_figi, as_of_date DESC
        ) latest
         ORDER BY market_cap_usd DESC, composite_figi
         LIMIT %s
        """,
        (as_of_date, as_of_date, MAX_INPUT_AGE_DAYS, n),
    ).fetchall()
    return [r[0] for r in rows]


# Rule registry: name -> (conn, as_of_date, n) -> [composite_figi].
_RULES: dict[str, Callable[[psycopg.Connection, date, int], list[str]]] = {
    "top_n_market_cap": _top_n_market_cap,
}


class CriteriaProvider:
    """Computes membership from a rule against fundamentals; emits figi join events."""

    kind = CRITERIA
    # Full current-membership token set from the last evaluation (U3.5): a criteria
    # screen IS the complete current set by construction — leaver-diff-safe.
    last_snapshot_tokens: set[str] | None = None

    def __init__(
        self,
        conn: psycopg.Connection | None = None,
        rule: str = "top_n_market_cap",
        n: int = 1000,
        **_: object,
    ) -> None:
        if conn is None:
            raise ValueError("CriteriaProvider requires a database connection to evaluate")
        if rule not in _RULES:
            raise ValueError(f"unknown criteria rule {rule!r} (known: {sorted(_RULES)})")
        self._conn = conn
        self._rule = rule
        self._n = int(n)

    def members(self, start: date, end: date) -> list[MembershipChange]:
        # Evaluate the rule as-of the window end and snapshot it as joins. An
        # empty evaluation declares NO snapshot (None, not an empty set) — mass
        # leaves must never be derived from an empty screen result.
        # EAGER, not a generator: the reset + declaration must happen at CALL
        # time, or a reader consulting last_snapshot_tokens before consuming
        # the members would see the previous evaluation's snapshot.
        self.last_snapshot_tokens = None
        figis = _RULES[self._rule](self._conn, end, self._n)
        tokens = [figi_token(figi) for figi in figis]
        self.last_snapshot_tokens = set(tokens) or None
        return [MembershipChange(token, JOIN, end, SOURCE, POLL_BOUNDED) for token in tokens]


register_provider(CRITERIA, CriteriaProvider)
