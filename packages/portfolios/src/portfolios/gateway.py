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
        "SELECT as_of_date, composite_figi, weight FROM portfolios.portfolio_weight "
        "WHERE portfolio_id = %s AND as_of_date = ("
        "  SELECT max(as_of_date) FROM portfolios.portfolio_weight WHERE portfolio_id = %s"
        ")",
        (portfolio_id, portfolio_id),
    ).fetchall()
    if not rows:
        return None, {}
    return rows[0][0], {figi: weight for _, figi, weight in rows}


def portfolio_exists(conn: psycopg.Connection, portfolio_id: int) -> bool:
    """Whether the portfolio row exists — lets consumers tell a nonexistent
    portfolio (404) apart from an existing one with no weights yet (empty)."""
    row = conn.execute(
        "SELECT 1 FROM portfolios.portfolio WHERE portfolio_id = %s",
        (portfolio_id,),
    ).fetchone()
    return row is not None


class DbPortfolioGateway:
    def __init__(self, conn: psycopg.Connection, sym_conn: psycopg.Connection | None = None) -> None:
        self._conn = conn      # qrp DB — portfolio / portfolio_weight (read + write)
        self._sym = sym_conn   # sym package — securities / labels / fact_returns (read-only)
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
            "INSERT INTO portfolios.client (name) VALUES (%s) "
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
              FROM portfolios.client c
              LEFT JOIN portfolios.portfolio p USING (client_id)
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
    def create(self, name: str, client: str = "", base_currency: str = "USD") -> int:
        client_id = self._resolve_client(client)  # FR-13: link to a first-class Client
        row = self._conn.execute(
            "INSERT INTO portfolios.portfolio (name, client_id, base_currency) VALUES (%s, %s, %s) "
            "RETURNING portfolio_id",
            (name, client_id, base_currency),
        ).fetchone()
        return int(row[0])

    def list(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT p.portfolio_id, p.name, coalesce(c.name, '') AS client, p.base_currency,
                   p.created_at,
                   count(w.composite_figi) AS n_weights,
                   max(w.as_of_date) AS latest_as_of_date
              FROM portfolios.portfolio p
              LEFT JOIN portfolios.client c ON c.client_id = p.client_id
              LEFT JOIN portfolios.portfolio_weight w USING (portfolio_id)
             GROUP BY p.portfolio_id, p.name, c.name, p.base_currency, p.created_at
             ORDER BY p.created_at DESC
            """
        ).fetchall()
        return [
            {
                "portfolio_id": pid,
                "name": name,
                "client": client,
                "base_currency": ccy,
                "created_at": ca.isoformat() if ca else None,
                "n_weights": n,
                "latest_as_of_date": la.isoformat() if la else None,
            }
            for pid, name, client, ccy, ca, n, la in rows
        ]

    def get(self, pid: int) -> dict | None:
        meta = self._conn.execute(
            "SELECT p.portfolio_id, p.name, coalesce(c.name, '') AS client, p.base_currency, "
            "p.created_at FROM portfolios.portfolio p "
            "LEFT JOIN portfolios.client c ON c.client_id = p.client_id "
            "WHERE p.portfolio_id = %s",
            (pid,),
        ).fetchone()
        if not meta:
            return None
        dates = [
            d.isoformat()
            for (d,) in self._conn.execute(
                "SELECT DISTINCT as_of_date FROM portfolios.portfolio_weight "
                "WHERE portfolio_id = %s ORDER BY as_of_date DESC",
                (pid,),
            ).fetchall()
        ]
        latest = dates[0] if dates else None
        weights: list[dict] = []
        if latest:
            wrows = self._conn.execute(
                "SELECT composite_figi, weight FROM portfolios.portfolio_weight "
                "WHERE portfolio_id = %s AND as_of_date = %s ORDER BY weight DESC",
                (pid, latest),
            ).fetchall()
            figis = [r[0] for r in wrows]
            tickers, names = self._labels(figis)  # enrich from the sym package, in-app
            weights = [
                {"figi": f, "ticker": tickers.get(f, f), "name": names.get(f), "weight": float(w)}
                for f, w in wrows
            ]
        return {
            "portfolio_id": meta[0],
            "name": meta[1],
            "client": meta[2],
            "base_currency": meta[3],
            "created_at": meta[4].isoformat() if meta[4] else None,
            "as_of_dates": dates,
            "latest_as_of_date": latest,
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
        stored = 0
        unresolved: list[str] = []
        for ident, weight in items:
            figi = self._resolve_figi(ident)  # resolved against the sym package
            if not figi:
                unresolved.append(ident)
                continue
            self._conn.execute(
                "INSERT INTO portfolios.portfolio_weight (portfolio_id, as_of_date, composite_figi, weight) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (portfolio_id, as_of_date, composite_figi) DO UPDATE SET weight = EXCLUDED.weight",
                (pid, as_of_date, figi, weight),
            )
            stored += 1
        return {"stored": stored, "unresolved": unresolved, "as_of_date": as_of_date.isoformat()}

    # ---- returns / PnL engine ----
    def returns(self, pid: int, window_code: str) -> dict:
        as_of_date = self._conn.execute(
            "SELECT max(as_of_date) FROM portfolios.portfolio_weight WHERE portfolio_id = %s", (pid,)
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
                 "constituents": [], "n_constituents": 0,
                 "n_with_return": 0, "total_weight": 0.0, "covered_weight": 0.0,
                 "portfolio_return": None, "portfolio_return_normalized": None}
        if as_of_date is None:
            return empty

        wrows = self._conn.execute(
            "SELECT composite_figi, weight FROM portfolios.portfolio_weight "
            "WHERE portfolio_id = %s AND as_of_date = %s",
            (pid, as_of_date),
        ).fetchall()
        figis = [r[0] for r in wrows]
        # weight×return is a cross-database join — assemble in-app: returns + labels from sym.
        # Pin every constituent to ONE returns date (the latest available for this window) so
        # the summed portfolio return never blends returns as-of different dates.
        ret_date = self._sym.execute(
            "SELECT max(as_of_date) FROM fact_returns "
            "WHERE composite_figi = ANY(%s) AND window_id = %s",
            (figis, window_id),
        ).fetchone()[0]
        pr_map = (
            dict(
                self._sym.execute(
                    "SELECT composite_figi, pr FROM fact_returns "
                    "WHERE composite_figi = ANY(%s) AND window_id = %s AND as_of_date = %s",
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
                covered_w += w
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
            "n_constituents": len(wrows),
            "n_with_return": n_with_return,
            "total_weight": total_w,
            "covered_weight": covered_w,
            "portfolio_return": port_ret if covered_w > 0 else None,
            "portfolio_return_normalized": (port_ret / covered_w) if covered_w > 0 else None,
            "constituents": constituents,
        }
