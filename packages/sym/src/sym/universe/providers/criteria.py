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

from collections.abc import Callable, Iterator
from datetime import date

import psycopg

from sym.universe.membership_diff import figi_token
from sym.universe.registry import CRITERIA, JOIN, POLL_BOUNDED, MembershipChange, register_provider

SOURCE = "criteria"


def _top_n_market_cap(conn: psycopg.Connection, as_of_date: date, n: int) -> list[str]:
    """The ``n`` largest securities by **point-in-time** market cap as of ``as_of_date``.

    Market cap is recomputed for the date — the latest raw close on/before ``as_of_date``
    times the latest shares-outstanding observation on/before ``as_of_date`` — so it is
    never stale between sparse shares observations.
    """
    rows = conn.execute(
        """
        WITH shares AS (
            SELECT DISTINCT ON (composite_figi) composite_figi, shares_outstanding
              FROM fundamentals
             WHERE as_of_date <= %s AND shares_outstanding IS NOT NULL
             ORDER BY composite_figi, as_of_date DESC
        ),
        px AS (
            SELECT DISTINCT ON (composite_figi) composite_figi, close
              FROM prices_raw
             WHERE session_date <= %s
             ORDER BY composite_figi, session_date DESC
        )
        SELECT s.composite_figi
          FROM shares s JOIN px p USING (composite_figi)
         WHERE s.shares_outstanding > 0 AND p.close > 0
         ORDER BY (s.shares_outstanding * p.close) DESC, s.composite_figi
         LIMIT %s
        """,
        (as_of_date, as_of_date, n),
    ).fetchall()
    return [r[0] for r in rows]


# Rule registry: name -> (conn, as_of_date, n) -> [composite_figi].
_RULES: dict[str, Callable[[psycopg.Connection, date, int], list[str]]] = {
    "top_n_market_cap": _top_n_market_cap,
}


class CriteriaProvider:
    """Computes membership from a rule against fundamentals; emits figi join events."""

    kind = CRITERIA

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

    def members(self, start: date, end: date) -> Iterator[MembershipChange]:
        # Evaluate the rule as-of the window end and snapshot it as joins.
        figis = _RULES[self._rule](self._conn, end, self._n)
        for figi in figis:
            yield MembershipChange(figi_token(figi), JOIN, end, SOURCE, POLL_BOUNDED)


register_provider(CRITERIA, CriteriaProvider)
