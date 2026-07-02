"""DB gateway for the portfolios module.

Writes ONLY to the QRP-own `qrp` schema (its own `qrp` database under the DB-per-package
topology); reads sym (securities, symbology, names, fact_returns, return_window) read-only
over a separate connection. Never mutates sym. Cross-package reads — security labels and the
weight×return PnL — are assembled IN-APP (the qrp weights and the sym returns live in
different databases), not via a cross-database SQL join. Weights resolve to sym_id at upload;
unresolved identifiers are reported, never fabricated.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import psycopg


def read_latest_weights(
    conn: psycopg.Connection, portfolio_id: int
) -> tuple[date | None, dict[str, Decimal]]:
    """The latest stored weight vector for a portfolio — THE weights read.

    Returns ``(as_of_date | None, {composite_figi: Decimal weight})``. This is
    the cross-package seam (Story A.1): other modules (analytics) consume
    weights through THIS function so the `portfolio_weight` SQL has exactly one
    owner. Decimals as stored — representation is the consumer's choice.
    ONE statement — date selection and row fetch share a snapshot, so a
    concurrent weight write can't yield a torn vector.
    """
    rows = conn.execute(
        "SELECT as_of_date, composite_figi, weight FROM portfolio.portfolio_weight "
        "WHERE portfolio_id = %s AND as_of_date = ("
        "  SELECT max(as_of_date) FROM portfolio.portfolio_weight WHERE portfolio_id = %s"
        ")",
        (portfolio_id, portfolio_id),
    ).fetchall()
    if not rows:
        return None, {}
    return rows[0][0], {figi: weight for _, figi, weight in rows}


def read_weight_history(
    conn: psycopg.Connection, portfolio_id: int
) -> list[tuple[date, dict[str, Decimal]]]:
    """The FULL effective-dated weight history, ascending — the time-series seam.

    Returns ``[(as_of_date, {composite_figi: Decimal weight}), …]`` oldest first.
    Consumers apply a step function: for a date ``d`` the effective vector is the
    last one with ``as_of_date <= d`` (Story Q5.2/Q4.5 — analytics' effective-dated
    weighting). Like :func:`read_latest_weights`, the `portfolio_weight` SQL has
    exactly one owner (Story A.1) and ONE statement returns everything — a
    concurrent write can't yield a torn vector.
    """
    rows = conn.execute(
        "SELECT as_of_date, composite_figi, weight FROM portfolio.portfolio_weight "
        "WHERE portfolio_id = %s ORDER BY as_of_date",
        (portfolio_id,),
    ).fetchall()
    history: list[tuple[date, dict[str, Decimal]]] = []
    for as_of_date, figi, weight in rows:
        if not history or history[-1][0] != as_of_date:
            history.append((as_of_date, {}))
        history[-1][1][figi] = weight
    return history


def read_portfolio_terms(
    conn: psycopg.Connection, portfolio_id: int
) -> tuple[Decimal | None, str] | None:
    """The portfolio's PnL terms ``(notional | None, base_currency)``, or None if absent.

    The notional is the operator-stated reference amount (in base_currency) that
    expresses cumulative time-weighted return as money — NULL means PnL is served in
    return space only (FR-15 definition, Story Q5.2).
    """
    row = conn.execute(
        "SELECT notional, base_currency FROM portfolio.portfolio WHERE portfolio_id = %s",
        (portfolio_id,),
    ).fetchone()
    if row is None:
        return None
    return row[0], row[1]


def portfolio_exists(conn: psycopg.Connection, portfolio_id: int) -> bool:
    """Whether the portfolio row exists — lets consumers tell a nonexistent
    portfolio (404) apart from an existing one with no weights yet (empty)."""
    row = conn.execute(
        "SELECT 1 FROM portfolio.portfolio WHERE portfolio_id = %s",
        (portfolio_id,),
    ).fetchone()
    return row is not None


class DbPortfolioGateway:
    def __init__(
        self,
        conn: psycopg.Connection,
        sym_conn: psycopg.Connection | None = None,
        equity_conn: psycopg.Connection | None = None,
    ) -> None:
        self._conn = conn      # qrp DB — portfolio / portfolio_weight (read + write)
        self._sym = sym_conn   # sym package — securities / labels (read-only)
        self._equity = equity_conn  # equity package — fact_returns (PnL), read-only
        self._conn.autocommit = True  # portfolios are small interactive writes

    def _labels(self, figis: list[str]) -> tuple[dict, dict]:
        """Ticker + name for ``figis`` from the sym package, merged in-app (cross-package read)."""
        if not self._sym or not figis:
            return {}, {}
        tickers = dict(
            self._sym.execute(
                "SELECT DISTINCT ON (composite_figi) composite_figi, symbol_value "
                "FROM security_symbology WHERE composite_figi = ANY(%s) AND symbol_type = 'ticker' "
                "ORDER BY composite_figi, (valid_to IS NULL) DESC, valid_from DESC",
                (figis,),
            ).fetchall()
        )
        names = dict(
            self._sym.execute(
                "SELECT DISTINCT ON (composite_figi) composite_figi, name "
                "FROM security_names WHERE composite_figi = ANY(%s) "
                "ORDER BY composite_figi, (valid_to IS NULL) DESC, valid_from DESC",
                (figis,),
            ).fetchall()
        )
        return tickers, names

    # ---- clients (FR-13) ----
    def _resolve_client(self, name: str) -> int | None:
        """Resolve a client by name, creating it if new (deduped by name). Blank -> None."""
        name = (name or "").strip()
        if not name:
            return None
        row = self._conn.execute(
            "INSERT INTO portfolio.client (name) VALUES (%s) "
            "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING client_id",
            (name,),
        ).fetchone()
        return int(row[0])

    def create_client(self, name: str) -> int:
        cid = self._resolve_client(name)
        if cid is None:
            raise ValueError("client name must be non-empty")
        return cid

    def clients(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT c.client_id, c.name, c.created_at, count(p.portfolio_id) AS n_portfolios
              FROM portfolio.client c
              LEFT JOIN portfolio.portfolio p USING (client_id)
             GROUP BY c.client_id, c.name, c.created_at
             ORDER BY c.name
            """
        ).fetchall()
        return [
            {"client_id": cid, "name": n, "created_at": ca.isoformat() if ca else None,
             "n_portfolios": np}
            for cid, n, ca, np in rows
        ]

    # ---- portfolios ----
    def create(
        self, name: str, client: str = "", base_currency: str = "USD",
        notional: float | None = None,
    ) -> int:
        client_id = self._resolve_client(client)  # FR-13: link to a first-class Client
        row = self._conn.execute(
            "INSERT INTO portfolio.portfolio (name, client_id, base_currency, notional) "
            "VALUES (%s, %s, %s, %s) RETURNING portfolio_id",
            (name, client_id, base_currency, notional),
        ).fetchone()
        return int(row[0])

    def set_notional(self, pid: int, notional: float | None) -> bool:
        """Set or clear the PnL reference notional. Returns False for an unknown portfolio."""
        row = self._conn.execute(
            "UPDATE portfolio.portfolio SET notional = %s WHERE portfolio_id = %s "
            "RETURNING portfolio_id",
            (notional, pid),
        ).fetchone()
        return row is not None

    def list(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT p.portfolio_id, p.name, coalesce(c.name, '') AS client, p.base_currency,
                   p.created_at,
                   count(w.composite_figi) AS n_weights,
                   count(DISTINCT w.as_of_date) AS n_snapshots,
                   count(w.composite_figi) FILTER (
                       WHERE w.as_of_date = (
                           SELECT max(as_of_date) FROM portfolio.portfolio_weight w2
                            WHERE w2.portfolio_id = p.portfolio_id
                       )
                   ) AS n_holdings,
                   max(w.as_of_date) AS latest_as_of_date
              FROM portfolio.portfolio p
              LEFT JOIN portfolio.client c ON c.client_id = p.client_id
              LEFT JOIN portfolio.portfolio_weight w USING (portfolio_id)
             GROUP BY p.portfolio_id, p.name, c.name, p.base_currency, p.created_at
             ORDER BY p.created_at DESC
            """
        ).fetchall()
        # n_weights = total stored weight rows across all history; n_holdings = positions at the
        # latest snapshot; n_snapshots = distinct as_of dates. The UI shows holdings-at-latest so the
        # count isn't conflated with history (a 100-name backtest over 12 months has n_weights=1200).
        return [
            {
                "portfolio_id": pid,
                "name": name,
                "client": client,
                "base_currency": ccy,
                "created_at": ca.isoformat() if ca else None,
                "n_weights": n,
                "n_snapshots": ns,
                "n_holdings": nh,
                "latest_as_of_date": la.isoformat() if la else None,
            }
            for pid, name, client, ccy, ca, n, ns, nh, la in rows
        ]

    def get(self, pid: int, as_of_date: date | None = None) -> dict | None:
        """Portfolio detail. ``as_of_date`` picks a stored historical vector (Q4.5);
        None means the latest. An as_of_date with no stored vector raises ValueError —
        the caller asked for a vector that does not exist, not an empty portfolio."""
        meta = self._conn.execute(
            "SELECT p.portfolio_id, p.name, coalesce(c.name, '') AS client, p.base_currency, "
            "p.notional, p.created_at FROM portfolio.portfolio p "
            "LEFT JOIN portfolio.client c ON c.client_id = p.client_id "
            "WHERE p.portfolio_id = %s",
            (pid,),
        ).fetchone()
        if not meta:
            return None
        dates = [
            d.isoformat()
            for (d,) in self._conn.execute(
                "SELECT DISTINCT as_of_date FROM portfolio.portfolio_weight "
                "WHERE portfolio_id = %s ORDER BY as_of_date DESC",
                (pid,),
            ).fetchall()
        ]
        latest = dates[0] if dates else None
        shown = latest
        if as_of_date is not None:
            if as_of_date.isoformat() not in dates:
                raise ValueError(f"no weight vector stored for {as_of_date.isoformat()}")
            shown = as_of_date.isoformat()
        weights: list[dict] = []
        if shown:
            wrows = self._conn.execute(
                "SELECT composite_figi, weight FROM portfolio.portfolio_weight "
                "WHERE portfolio_id = %s AND as_of_date = %s ORDER BY weight DESC",
                (pid, shown),
            ).fetchall()
            figis = [r[0] for r in wrows]
            tickers, names = self._labels(figis)  # enrich from the sym package, in-app
            weights = [
                {"figi": f, "ticker": tickers.get(f, f), "name": names.get(f), "weight": float(w)}
                for f, w in wrows
            ]
        # Net = signed sum (directional tilt); gross = abs sum (leverage). Computed from the
        # SHOWN vector so they track the as-of picker and stay consistent with the holdings table.
        # None when no vector is in scope (don't fabricate a 0 for an empty portfolio).
        net_exposure = sum(w["weight"] for w in weights) if shown else None
        gross_exposure = sum(abs(w["weight"]) for w in weights) if shown else None
        # Long = Σ positive weight; short = Σ |negative weight| (a positive magnitude). Net =
        # long − short; gross = long + short. L/S ratio is the consumer's (long / short).
        long_exposure = sum(w["weight"] for w in weights if w["weight"] > 0) if shown else None
        short_exposure = sum(-w["weight"] for w in weights if w["weight"] < 0) if shown else None
        return {
            "portfolio_id": meta[0],
            "name": meta[1],
            "client": meta[2],
            "base_currency": meta[3],
            "notional": float(meta[4]) if meta[4] is not None else None,
            "created_at": meta[5].isoformat() if meta[5] else None,
            "as_of_dates": dates,
            "latest_as_of_date": latest,
            "shown_as_of_date": shown,
            "net_exposure": net_exposure,
            "gross_exposure": gross_exposure,
            "long_exposure": long_exposure,
            "short_exposure": short_exposure,
            "weights": weights,
        }

    # ---- weights ----
    def _resolve_figi(self, ident: str) -> str | None:
        ident = ident.strip()
        if not ident:
            return None
        direct = self._sym.execute(
            "SELECT composite_figi FROM securities WHERE composite_figi = %s", (ident,)
        ).fetchone()
        if direct:
            return direct[0]
        row = self._sym.execute(
            "SELECT composite_figi FROM security_symbology WHERE symbol_type = 'ticker' "
            "AND upper(symbol_value) = upper(%s) "
            "ORDER BY (valid_to IS NULL) DESC, valid_from DESC LIMIT 1",
            (ident,),
        ).fetchone()
        return row[0] if row else None

    def upload_weights(self, pid: int, as_of_date: date, items: list[tuple[str, float]]) -> dict:
        """Store a weight VECTOR for a date — replace semantics.

        Re-uploading a date REPLACES that date's whole vector (transactional
        delete-then-insert): a corrected upload that drops a name must not leave the
        stale row merged in — every historical vector now feeds the time-weighted
        series (Q5.2), so a ghost holding would corrupt returns silently. Identifiers
        that resolve to nothing are reported, never stored; if NOTHING resolves the
        existing vector is left untouched (a typo'd upload must not erase real data).
        """
        resolved: list[tuple[str, float]] = []
        unresolved: list[str] = []
        for ident, weight in items:
            figi = self._resolve_figi(ident)  # resolved against the sym package
            if not figi:
                unresolved.append(ident)
                continue
            resolved.append((figi, weight))
        if not resolved:
            return {"stored": 0, "unresolved": unresolved, "as_of_date": as_of_date.isoformat()}
        with self._conn.transaction():  # autocommit=True -> this is a real transaction
            self._conn.execute(
                "DELETE FROM portfolio.portfolio_weight "
                "WHERE portfolio_id = %s AND as_of_date = %s",
                (pid, as_of_date),
            )
            for figi, weight in resolved:
                self._conn.execute(
                    "INSERT INTO portfolio.portfolio_weight "
                    "(portfolio_id, as_of_date, composite_figi, weight) "
                    "VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (portfolio_id, as_of_date, composite_figi) "
                    "DO UPDATE SET weight = EXCLUDED.weight",
                    (pid, as_of_date, figi, weight),
                )
        return {
            "stored": len(resolved),
            "unresolved": unresolved,
            "as_of_date": as_of_date.isoformat(),
        }

    # ---- returns (snapshot attribution view) ----
    def returns(self, pid: int, window_code: str) -> dict:
        """Current-holdings attribution SNAPSHOT — NOT the time-weighted return.

        Applies the LATEST weight vector to sym's precomputed window returns: "what
        did the names I hold today do over this window, weighted as I hold them now".
        Useful for attribution; wrong as portfolio performance the moment weights
        changed mid-window. The portfolio's true time-weighted Return + PnL over its
        effective-dated history is analytics' ``returns`` block (Story Q5.2). The
        ``semantics`` response field states this.
        """
        as_of_date = self._conn.execute(
            "SELECT max(as_of_date) FROM portfolio.portfolio_weight WHERE portfolio_id = %s", (pid,)
        ).fetchone()[0]
        # return_window is a sym reference table; resolve the window id from the sym package.
        # An unknown code is the caller's error — no silent YTD fallback.
        wrow = self._sym.execute(
            "SELECT window_id, code FROM return_window WHERE code = %s", (window_code,)
        ).fetchone()
        if not wrow:
            raise ValueError(f"unknown return window {window_code!r}")
        window_id, window = wrow
        empty = {"window": window, "as_of_date": None, "returns_as_of_date": None,
                 "semantics": "snapshot_attribution",
                 "constituents": [], "n_constituents": 0,
                 "n_with_return": 0, "total_weight": 0.0, "covered_weight": 0.0,
                 "portfolio_return": None, "portfolio_return_normalized": None}
        if as_of_date is None:
            return empty

        wrows = self._conn.execute(
            "SELECT composite_figi, weight FROM portfolio.portfolio_weight "
            "WHERE portfolio_id = %s AND as_of_date = %s",
            (pid, as_of_date),
        ).fetchall()
        figis = [r[0] for r in wrows]
        # weight×return is a cross-database join — assemble in-app: returns + labels from sym.
        # Pin every constituent to ONE returns date so the summed portfolio return never blends
        # as-of dates — but to the latest BROADLY-COMPLETE date, NOT the bare max: the newest
        # as_of is often a sparse "today" (only the markets that have closed so far), and pinning
        # to it would drop every constituent whose market's latest session is a day behind. Pick
        # the most recent date that >=90% of the covered members reach (scoped to THESE figis, so
        # it's a tiny grouped scan, not a full fact_returns aggregate).
        ret_date = self._equity.execute(
            """
            WITH per_day AS (
                SELECT as_of_date, count(*) AS n
                  FROM fact_returns
                 WHERE composite_figi = ANY(%s) AND window_id = %s AND pr IS NOT NULL
                 GROUP BY as_of_date
            )
            SELECT max(as_of_date) FROM per_day
             WHERE n >= 0.9 * (SELECT max(n) FROM per_day)
            """,
            (figis, window_id),
        ).fetchone()[0]
        # ``pr IS NOT NULL`` in BOTH the date pin and the lookup: an AR-9-gated row (a real row whose pr
        # is withheld pending price review) must not win the broadly-complete-date pin nor populate the
        # map — else the latest date can be all-gated and 97/100 constituents read null. Falls back to the
        # last date with actual returns (mirrors portfolios-live-returns-fix's skip-null rule).
        pr_map = (
            dict(
                self._equity.execute(
                    "SELECT composite_figi, pr FROM fact_returns "
                    "WHERE composite_figi = ANY(%s) AND window_id = %s AND as_of_date = %s "
                    "AND pr IS NOT NULL",
                    (figis, window_id, ret_date),
                ).fetchall()
            )
            if ret_date is not None
            else {}
        )
        tickers, _ = self._labels(figis)

        total_w = covered_w = port_ret = 0.0
        n_with_return = 0
        constituents = []
        for figi, weight in wrows:
            w = float(weight)
            total_w += w
            pr = pr_map.get(figi)
            contrib = None
            if pr is not None:
                covered_w += abs(w)  # GROSS present — long-only == net; dollar-neutral stays > 0
                contrib = w * float(pr)
                port_ret += contrib
                n_with_return += 1
            constituents.append(
                {"ticker": tickers.get(figi, figi), "weight": w,
                 "ret": float(pr) if pr is not None else None, "contribution": contrib}
            )
        constituents.sort(
            key=lambda x: abs(x["contribution"]) if x["contribution"] is not None else -1,
            reverse=True,
        )
        return {
            "window": window,
            "as_of_date": as_of_date.isoformat(),
            "returns_as_of_date": ret_date.isoformat() if ret_date is not None else None,
            "semantics": "snapshot_attribution",
            "n_constituents": len(wrows),
            "n_with_return": n_with_return,
            "total_weight": total_w,
            "covered_weight": covered_w,
            "portfolio_return": port_ret if covered_w > 0 else None,
            "portfolio_return_normalized": (port_ret / covered_w) if covered_w > 0 else None,
            "constituents": constituents,
        }
