"""DB-backed reads for the sym module (Overview Q2.1 + Universe heat map Q2.6/FR-23).

Reads sym's tables/views directly (read/trigger posture; no writes). Every figure is a live
read of sym — nothing mocked.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone

import psycopg

from qrp_api.modules.sym import quotes as quotes_mod
from qrp_api.modules.sym.freshness import AreaFreshness, classify
from qrp_api.modules.sym.quotes import QuoteSourceUnreachable


def _as_text(v) -> str | None:
    """Render a JSONB/dict column as a compact string (review_queue.source_input is JSONB)."""
    if v is None or isinstance(v, str):
        return v
    return json.dumps(v, default=str, separators=(",", ":"))

# Curated short/medium windows for the heat-map selector (subset of return_window codes).
HEATMAP_WINDOWS = ["1D", "WTD", "MTD", "QTD", "YTD", "1M", "3M", "6M", "1Y"]
DEFAULT_HEATMAP_WINDOW = "1D"
# Bound the LIVE heatmap fan-out (Story QH.9): one external quote per representative issuer, so a
# huge universe could fire hundreds of requests at Yahoo (rate-limit risk). Sized so the flagship
# S&P 500 (~633 issuers after share-class collapse) AND the S&P 400 fit; only the largest (S&P 600,
# ~838) is over — those use an EOD window. Over-cap is a 422 (with a clear message), never an
# unbounded fan-out.
LIVE_HEATMAP_MAX = 700


@dataclass(frozen=True)
class LastRun:
    run_id: str | None
    mode: str | None
    status: str | None
    started_at: datetime | None
    finished_at: datetime | None
    rows_written: int | None


@dataclass(frozen=True)
class SymOverview:
    securities: int
    universes: int
    priced_securities: int
    priced_at_latest: int
    latest_session: date | None
    freshness: list[AreaFreshness]
    last_run: LastRun | None


@dataclass(frozen=True)
class UniverseRef:
    universe_id: str
    name: str
    members_resolved: int


def _scalar(conn: psycopg.Connection, sql: str, params: tuple = ()):
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


class DbSymGateway:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def healthy(self) -> bool:
        try:
            self._conn.execute("SELECT 1")
            return True
        except psycopg.Error:
            return False

    def overview(self) -> SymOverview:
        c = self._conn
        securities = _scalar(c, "SELECT count(*) FROM securities")
        universes = _scalar(c, "SELECT count(*) FROM universe")
        # securities that have ANY price bar — an index-only EXISTS semi-join (rides the
        # prices_raw PK), not a count(DISTINCT) over all 13M rows (which took ~5s). Equivalent
        # because prices_raw.composite_figi is FK'd to securities (no orphan price figis).
        priced = _scalar(
            c,
            "SELECT count(*) FROM securities s "
            "WHERE EXISTS (SELECT 1 FROM prices_raw p WHERE p.composite_figi = s.composite_figi)",
        )
        latest_session = _scalar(c, "SELECT max(session_date) FROM prices_raw")
        # How many securities actually have a bar on the newest session — exposes the gap
        # when a recent load only refreshed a sub-universe (e.g. nasdaq100) and the rest lag.
        priced_at_latest = (
            _scalar(
                c,
                "SELECT count(DISTINCT composite_figi) FROM prices_raw WHERE session_date = %s",
                (latest_session,),
            )
            if latest_session is not None
            else 0
        )
        # The latest session at which the universe is BROADLY priced (>=90% of a full-load
        # day). The prices area's freshness keys off THIS, not max(session_date) — otherwise
        # one fresh sub-universe makes prices report "0 days behind / ok" while most of the
        # universe is days stale (the max-is-fresh-masks-the-laggards trap).
        coverage_session = _scalar(
            c,
            """
            WITH per_day AS (
                SELECT session_date, count(DISTINCT composite_figi) AS n
                  FROM prices_raw
                 WHERE session_date >= (SELECT max(session_date) FROM prices_raw) - 90
                 GROUP BY session_date
            )
            SELECT max(session_date) FROM per_day
             WHERE n >= 0.9 * (SELECT max(n) FROM per_day)
            """,
        )

        area_as_of = {
            "prices": coverage_session,
            "returns": _scalar(c, "SELECT max(as_of_date) FROM fact_returns"),
            "fx": _scalar(c, "SELECT max(as_of_date) FROM fx_rate"),
            "fundamentals": _scalar(c, "SELECT max(as_of_date) FROM fundamentals"),
        }
        prices_coverage = (
            f"{priced_at_latest}/{priced} at {latest_session}" if latest_session else None
        )
        freshness = [
            classify(a, d, latest_session, coverage=(prices_coverage if a == "prices" else None))
            for a, d in area_as_of.items()
        ]

        row = c.execute(
            "SELECT run_id, mode, status, started_at, finished_at, rows_written "
            "FROM pipeline_run_log ORDER BY started_at DESC NULLS LAST LIMIT 1"
        ).fetchone()
        last_run = LastRun(str(row[0]), row[1], row[2], row[3], row[4], row[5]) if row else None

        return SymOverview(
            securities=securities,
            universes=universes,
            priced_securities=priced,
            priced_at_latest=priced_at_latest,
            latest_session=latest_session,
            freshness=freshness,
            last_run=last_run,
        )

    def universes(self) -> list[UniverseRef]:
        rows = self._conn.execute(
            """
            SELECT u.universe_id, u.name,
                   count(*) FILTER (WHERE r.resolution_status = 'resolved') AS resolved
              FROM universe u
              LEFT JOIN universe_member_resolution r USING (universe_id)
             GROUP BY u.universe_id, u.name
             ORDER BY resolved DESC, u.universe_id
            """
        ).fetchall()
        return [UniverseRef(uid, name, resolved) for uid, name, resolved in rows]

    def universe_coverage(self) -> list[dict]:
        """Per-universe coverage of prices / returns / fundamentals, judged by PER-MEMBER
        recency — not presence at a single global session, because markets close at different
        times (a member a day behind its market's close is not "missing"). Index-bounded:
        per-figi max() over a recent window (rides the fact-table PKs), never a full-table
        count(DISTINCT)/group-by-date over the 13.5M-row prices_raw (the Overview 125s trap).
        Returns/fundamentals: returns restricted to ONE window_id (fact_returns has ~28 per
        figi/date); fundamentals judged on a wider window (low cadence — quarterly)."""
        c = self._conn
        latest = _scalar(c, "SELECT max(session_date) FROM prices_raw")
        if latest is None:
            return []
        one_win = _scalar(c, "SELECT min(window_id) FROM return_window")
        rows = c.execute(
            """
            WITH members AS (
                SELECT universe_id, composite_figi FROM universe_member_resolution
                 WHERE resolution_status = 'resolved'
            ),
            px AS (SELECT composite_figi, max(session_date) d FROM prices_raw
                    WHERE session_date >= %(latest)s - 14 GROUP BY composite_figi),
            rt AS (SELECT composite_figi, max(as_of_date) d FROM fact_returns
                    WHERE window_id = %(w)s AND as_of_date >= %(latest)s - 14 GROUP BY composite_figi),
            fn AS (SELECT composite_figi, max(as_of_date) d FROM fundamentals
                    WHERE as_of_date >= %(latest)s - 180 GROUP BY composite_figi)
            SELECT m.universe_id, u.name, count(*) AS total,
                   count(*) FILTER (WHERE px.d >= %(latest)s - 7) AS px_cov, max(px.d) AS px_latest,
                   count(*) FILTER (WHERE rt.d >= %(latest)s - 7) AS rt_cov, max(rt.d) AS rt_latest,
                   count(fn.d) AS fn_cov, max(fn.d) AS fn_latest
              FROM members m
              JOIN universe u ON u.universe_id = m.universe_id
              LEFT JOIN px ON px.composite_figi = m.composite_figi
              LEFT JOIN rt ON rt.composite_figi = m.composite_figi
              LEFT JOIN fn ON fn.composite_figi = m.composite_figi
             GROUP BY m.universe_id, u.name
             ORDER BY total DESC, m.universe_id
            """,
            {"latest": latest, "w": one_win},
        ).fetchall()

        def _layer(cov: int, total: int, latest_d) -> dict:
            status = "missing" if cov == 0 else "partial" if cov < total else "ok"
            return {
                "covered": cov,
                "total": total,
                "latest_date": latest_d.isoformat() if latest_d else None,
                "status": status,
            }

        return [
            {
                "universe_id": uid,
                "name": name,
                "members_resolved": total,
                "prices": _layer(pxc, total, pxl),
                "returns": _layer(rtc, total, rtl),
                "fundamentals": _layer(fnc, total, fnl),
            }
            for uid, name, total, pxc, pxl, rtc, rtl, fnc, fnl in rows
        ]

    def return_windows(self) -> list[tuple[str, str]]:
        """Curated (code, label) windows for the heat-map selector, in HEATMAP_WINDOWS order."""
        rows = self._conn.execute(
            "SELECT code, label FROM return_window WHERE code = ANY(%s)", (HEATMAP_WINDOWS,)
        ).fetchall()
        by_code = {code: label for code, label in rows}
        return [(c, by_code[c]) for c in HEATMAP_WINDOWS if c in by_code]

    def heatmap(self, universe_id: str, window_code: str) -> dict:
        """Universe constituents sized by market cap (USD), colored by return over a window,
        grouped by GICS sector. Constituents missing market cap are excluded but counted;
        missing return -> null (neutral); missing sector -> 'Unclassified'. All live reads."""
        c = self._conn
        uname = _scalar(
            c, "SELECT name FROM universe WHERE universe_id = %s", (universe_id,)
        )
        if uname is None:
            raise LookupError(f"universe {universe_id!r} not found")
        wrow = c.execute(
            "SELECT window_id, code FROM return_window WHERE code = %s", (window_code,)
        ).fetchone()
        if not wrow:
            # No silent fallback: an unknown code is the caller's error (the router's Query
            # default already supplies DEFAULT_HEATMAP_WINDOW when none is requested).
            raise ValueError(f"unknown return window {window_code!r}")
        window_id, window = wrow

        rows = c.execute(
            """
            SELECT r.composite_figi AS figi,
                   coalesce(tk.symbol_value, s.composite_figi) AS ticker,
                   coalesce(sn.name, s.composite_figi) AS name,
                   coalesce(g.sector_name, 'Unclassified') AS sector,
                   g.industry_name AS industry,
                   f.market_cap_usd,
                   f.market_cap_lcy,
                   f.currency_code,
                   px.close AS price,
                   fr.pr AS ret,
                   isin.symbol_value AS isin
              FROM universe_member_resolution r
              JOIN securities s ON s.composite_figi = r.composite_figi
              LEFT JOIN LATERAL (
                  SELECT market_cap_usd, market_cap_lcy, currency_code FROM fundamentals f2
                   WHERE f2.composite_figi = r.composite_figi AND f2.market_cap_usd IS NOT NULL
                   ORDER BY as_of_date DESC LIMIT 1
              ) f ON TRUE
              LEFT JOIN LATERAL (
                  SELECT close FROM prices_raw p2
                   WHERE p2.composite_figi = r.composite_figi
                   ORDER BY session_date DESC LIMIT 1
              ) px ON TRUE
              LEFT JOIN LATERAL (
                  SELECT pr FROM fact_returns x
                   WHERE x.composite_figi = r.composite_figi AND x.window_id = %s
                   ORDER BY as_of_date DESC LIMIT 1
              ) fr ON TRUE
              LEFT JOIN LATERAL (
                  SELECT sector_name, industry_name FROM gics_scd g2
                   WHERE g2.composite_figi = r.composite_figi
                   ORDER BY (g2.valid_to IS NULL) DESC, g2.valid_from DESC LIMIT 1
              ) g ON TRUE
              LEFT JOIN LATERAL (
                  SELECT name FROM security_names z
                   WHERE z.composite_figi = r.composite_figi
                   ORDER BY (z.valid_to IS NULL) DESC, z.valid_from DESC LIMIT 1
              ) sn ON TRUE
              LEFT JOIN LATERAL (
                  SELECT symbol_value FROM security_symbology y
                   WHERE y.composite_figi = r.composite_figi AND y.symbol_type = 'ticker'
                   ORDER BY (y.valid_to IS NULL) DESC, y.valid_from DESC LIMIT 1
              ) tk ON TRUE
              LEFT JOIN LATERAL (
                  SELECT symbol_value FROM security_symbology yi
                   WHERE yi.composite_figi = r.composite_figi AND yi.symbol_type = 'isin'
                   ORDER BY (yi.valid_to IS NULL) DESC, yi.valid_from DESC LIMIT 1
              ) isin ON TRUE
             WHERE r.universe_id = %s AND r.resolution_status = 'resolved'
            """,
            (window_id, universe_id),
        ).fetchall()

        # Collapse share classes to one tile per issuer (ISIN CUSIP-issuer prefix, chars 3-8;
        # fallback to the security's own FIGI). sym stores TOTAL shares on each class row, so
        # each class ~ the whole-company cap -> take the largest-cap class as the representative
        # (summing would double-count given that data). See the per-class-shares caveat.
        groups: dict[str, dict] = {}
        missing_mcap = 0
        with_mcap = 0
        for figi, ticker, name, sector, industry, mcap, mcap_lcy, currency, price, ret, isin in rows:
            if mcap is None:
                missing_mcap += 1
                continue
            with_mcap += 1
            issuer = isin[2:8] if isin and len(isin) >= 8 else f"figi:{figi}"
            cell = {
                "ticker": ticker,
                "name": name,
                "sector": sector,
                "industry": industry,
                "market_cap_usd": float(mcap),
                "market_cap_lcy": float(mcap_lcy) if mcap_lcy is not None else None,
                "currency": currency,
                "price": float(price) if price is not None else None,
                "ret": float(ret) if ret is not None else None,
            }
            cur = groups.get(issuer)
            if cur is None or cell["market_cap_usd"] > cur["market_cap_usd"]:
                groups[issuer] = cell
        cells = sorted(groups.values(), key=lambda x: x["market_cap_usd"], reverse=True)

        return {
            "universe_id": universe_id,
            "universe_name": uname,
            "window": window,
            "members_resolved": len(rows),
            "shown": len(cells),
            "missing_mcap": missing_mcap,
            "merged_share_classes": with_mcap - len(cells),
            "cells": cells,
        }

    def live_heatmap(self, universe_id: str, *, now: float | None = None) -> dict:
        """LIVE recolor of the universe treemap (Story QH.9): the SAME constituents / market-cap
        sizing / share-class collapse as ``heatmap``, but each cell's return is a LIVE return
        (``live_price / previousClose - 1``) from the QH.2 quote source, fanned out concurrently.
        Per-cell ``freshness``; map-level ``as_of`` (most-recent priced), worst ``freshness``, and
        ``priced``/``total`` coverage. Quotes are fetched externally and NEVER persisted.
        Raises LookupError (404), ValueError (422 over-cap), QuoteSourceUnreachable (503 when the
        provider is wholly unreachable). Uncovered issuers render neutral (``ret`` = None)."""
        c = self._conn
        uname = _scalar(c, "SELECT name FROM universe WHERE universe_id = %s", (universe_id,))
        if uname is None:
            raise LookupError(f"universe {universe_id!r} not found")

        rows = c.execute(
            """
            SELECT r.composite_figi AS figi,
                   coalesce(tk.symbol_value, s.composite_figi) AS ticker,
                   s.mic AS mic,
                   coalesce(sn.name, s.composite_figi) AS name,
                   coalesce(g.sector_name, 'Unclassified') AS sector,
                   g.industry_name AS industry,
                   f.market_cap_usd,
                   f.market_cap_lcy,
                   f.currency_code,
                   isin.symbol_value AS isin
              FROM universe_member_resolution r
              JOIN securities s ON s.composite_figi = r.composite_figi
              LEFT JOIN LATERAL (
                  SELECT market_cap_usd, market_cap_lcy, currency_code FROM fundamentals f2
                   WHERE f2.composite_figi = r.composite_figi AND f2.market_cap_usd IS NOT NULL
                   ORDER BY as_of_date DESC LIMIT 1
              ) f ON TRUE
              LEFT JOIN LATERAL (
                  SELECT sector_name, industry_name FROM gics_scd g2
                   WHERE g2.composite_figi = r.composite_figi
                   ORDER BY (g2.valid_to IS NULL) DESC, g2.valid_from DESC LIMIT 1
              ) g ON TRUE
              LEFT JOIN LATERAL (
                  SELECT name FROM security_names z
                   WHERE z.composite_figi = r.composite_figi
                   ORDER BY (z.valid_to IS NULL) DESC, z.valid_from DESC LIMIT 1
              ) sn ON TRUE
              LEFT JOIN LATERAL (
                  SELECT symbol_value FROM security_symbology y
                   WHERE y.composite_figi = r.composite_figi AND y.symbol_type = 'ticker'
                   ORDER BY (y.valid_to IS NULL) DESC, y.valid_from DESC LIMIT 1
              ) tk ON TRUE
              LEFT JOIN LATERAL (
                  SELECT symbol_value FROM security_symbology yi
                   WHERE yi.composite_figi = r.composite_figi AND yi.symbol_type = 'isin'
                   ORDER BY (yi.valid_to IS NULL) DESC, yi.valid_from DESC LIMIT 1
              ) isin ON TRUE
             WHERE r.universe_id = %s AND r.resolution_status = 'resolved'
            """,
            (universe_id,),
        ).fetchall()

        # Same issuer-collapse as the EOD heatmap (one tile per issuer, largest-cap class), but
        # carry the representative's figi/mic/ticker so we can build its Yahoo symbol.
        groups: dict[str, dict] = {}
        missing_mcap = 0
        with_mcap = 0
        for figi, ticker, mic, name, sector, industry, mcap, mcap_lcy, currency, isin in rows:
            if mcap is None:
                missing_mcap += 1
                continue
            with_mcap += 1
            issuer = isin[2:8] if isin and len(isin) >= 8 else f"figi:{figi}"
            rep = {
                "ticker": ticker, "name": name, "sector": sector, "industry": industry,
                "market_cap_usd": float(mcap),
                "market_cap_lcy": float(mcap_lcy) if mcap_lcy is not None else None,
                "currency": currency, "price": None, "ret": None, "freshness": "unavailable",
                "_mic": mic,
            }
            cur = groups.get(issuer)
            if cur is None or rep["market_cap_usd"] > cur["market_cap_usd"]:
                groups[issuer] = rep
        reps = sorted(groups.values(), key=lambda x: x["market_cap_usd"], reverse=True)

        if len(reps) > LIVE_HEATMAP_MAX:
            raise ValueError(
                f"universe too large for a live heatmap ({len(reps)} issuers > {LIVE_HEATMAP_MAX}); "
                "use a smaller universe or an EOD window"
            )

        now = quotes_mod.now_epoch() if now is None else now
        sym_by_id = {id(rep): quotes_mod.yahoo_symbol_for(rep["ticker"], rep["_mic"]) for rep in reps}
        symbols = [s for s in sym_by_id.values() if s]
        batch = quotes_mod.fetch_quotes_batch(symbols) if symbols else {}

        priced = 0
        any_delayed = False
        newest_epoch: int | None = None  # the most-recent priced mark (QH.9): `as_of` should track
        cells: list[dict] = []           # the freshest data point, not be pinned by one stale name
        for rep in reps:
            ysym = sym_by_id[id(rep)]
            q = batch.get(ysym) if ysym else None
            if q is not None:
                lr = quotes_mod.live_return(q.price, q.prev_close)
                if lr is not None:
                    fresh, _ = quotes_mod.classify_freshness(q.quote_epoch, now)
                    rep["price"] = q.price
                    rep["ret"] = lr
                    rep["freshness"] = fresh
                    priced += 1
                    any_delayed = any_delayed or fresh == "delayed"
                    if q.quote_epoch is not None:
                        newest_epoch = (
                            q.quote_epoch if newest_epoch is None else max(newest_epoch, q.quote_epoch)
                        )
            rep.pop("_mic", None)
            cells.append(rep)

        return {
            "universe_id": universe_id,
            "universe_name": uname,
            "window": "LIVE",
            "members_resolved": len(rows),
            "shown": len(cells),
            "missing_mcap": missing_mcap,
            "merged_share_classes": with_mcap - len(cells),
            "as_of": (
                datetime.fromtimestamp(newest_epoch, tz=timezone.utc).isoformat()
                if newest_epoch is not None else None
            ),
            "freshness": ("unavailable" if priced == 0 else "delayed" if any_delayed else "live"),
            "priced": priced,
            "total": len(cells),
            "cells": cells,
        }

    _SEC_FROM = """
          FROM securities s
          LEFT JOIN LATERAL (
              SELECT symbol_value FROM security_symbology y
               WHERE y.composite_figi = s.composite_figi AND y.symbol_type = 'ticker'
               ORDER BY (y.valid_to IS NULL) DESC, y.valid_from DESC LIMIT 1
          ) tk ON TRUE
          LEFT JOIN LATERAL (
              SELECT name FROM security_names z
               WHERE z.composite_figi = s.composite_figi
               ORDER BY (z.valid_to IS NULL) DESC, z.valid_from DESC LIMIT 1
          ) sn ON TRUE
    """

    def securities(
        self, q: str | None, limit: int, offset: int, universe: str | None = None
    ) -> dict:
        """Paged list of securities — optionally searched (ticker/name/FIGI) and/or filtered
        to one universe's resolved members. Both filters apply to the count + rows alike."""
        c = self._conn
        conds: list[str] = []
        params: list = []
        if q:
            conds.append(
                "(upper(coalesce(tk.symbol_value, '')) LIKE %s"
                " OR upper(coalesce(sn.name, '')) LIKE %s"
                " OR s.composite_figi LIKE %s)"
            )
            # Escape LIKE metacharacters in the user's query: a bare '%' would match
            # everything and '_' would wildcard single characters.
            esc = q.upper().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like = f"%{esc}%"
            params += [like, like, like]
        if universe:
            conds.append(
                "EXISTS (SELECT 1 FROM universe_member_resolution r "
                "WHERE r.universe_id = %s AND r.composite_figi = s.composite_figi "
                "AND r.resolution_status = 'resolved')"
            )
            params.append(universe)
        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        total = c.execute(
            f"SELECT count(*) {self._SEC_FROM} {where}", params
        ).fetchone()[0]
        # Enrichment joins live HERE (the rows query) only — NOT in `_SEC_FROM`, which the
        # count(*) + search WHERE share. Keeping them off `_SEC_FROM` means the per-row price/
        # fundamentals/gics laterals run only for the LIMITed page, not for every counted row.
        rows = c.execute(
            f"""
            SELECT s.composite_figi,
                   coalesce(tk.symbol_value, s.composite_figi) AS ticker,
                   sn.name, s.mic, s.currency_code, s.status,
                   px.close, px.volume, px.session_date,
                   fu.market_cap_usd, ex.country, ex.country_iso, gx.sector_name
            {self._SEC_FROM}
            LEFT JOIN exchange ex ON ex.mic = s.mic
            LEFT JOIN LATERAL (
                SELECT close, volume, session_date FROM prices_raw p
                 WHERE p.composite_figi = s.composite_figi
                 ORDER BY p.session_date DESC LIMIT 1
            ) px ON TRUE
            LEFT JOIN LATERAL (
                SELECT market_cap_usd FROM fundamentals f
                 WHERE f.composite_figi = s.composite_figi
                 ORDER BY f.as_of_date DESC LIMIT 1
            ) fu ON TRUE
            LEFT JOIN LATERAL (
                SELECT sector_name FROM gics_scd g
                 WHERE g.composite_figi = s.composite_figi
                 ORDER BY (g.valid_to IS NULL) DESC, g.valid_from DESC LIMIT 1
            ) gx ON TRUE
            {where}
            ORDER BY tk.symbol_value NULLS LAST, s.composite_figi
            LIMIT %s OFFSET %s
            """,
            [*params, limit, offset],
        ).fetchall()
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "rows": [
                {
                    "figi": figi,
                    "ticker": ticker,
                    "name": name,
                    "mic": mic,
                    "currency": currency,
                    "status": status,
                    "price": float(close) if close is not None else None,
                    "volume": int(volume) if volume is not None else None,
                    "session_date": session_date.isoformat() if session_date else None,
                    "market_cap_usd": float(mcap) if mcap is not None else None,
                    "country": country,
                    "country_iso": country_iso,
                    "sector": sector,
                }
                for (
                    figi, ticker, name, mic, currency, status,
                    close, volume, session_date, mcap, country, country_iso, sector,
                ) in rows
            ],
        }

    def quotes(self, figis: list[str], *, now: float | None = None) -> list[dict]:
        """Live/delayed quotes for ``figis`` — fetched externally, NEVER persisted.

        Resolves each figi to (ticker, mic) -> Yahoo symbol, fetches a snapshot, and computes a
        live return vs the quote's OWN previous close (no sym price read needed). A figi with no
        Yahoo mapping, or one the source has no data for, comes back ``freshness='unavailable'``
        (price null) — a per-symbol miss is not a request failure. If EVERY attempted symbol
        fails with a network error the whole source is unreachable -> raise
        ``QuoteSourceUnreachable`` (the router maps it to the honest 503 envelope). Writes nothing.
        """
        now = quotes_mod.now_epoch() if now is None else now
        rows = self._conn.execute(
            """
            SELECT s.composite_figi, tk.symbol_value, s.mic
              FROM securities s
              LEFT JOIN LATERAL (
                  SELECT symbol_value FROM security_symbology y
                   WHERE y.composite_figi = s.composite_figi AND y.symbol_type = 'ticker'
                   ORDER BY (y.valid_to IS NULL) DESC, y.valid_from DESC LIMIT 1
              ) tk ON TRUE
             WHERE s.composite_figi = ANY(%s)
            """,
            (list(figis),),
        ).fetchall()
        meta = {figi: (ticker, mic) for figi, ticker, mic in rows}

        out: list[dict] = []
        attempted = net_errors = 0
        for figi in figis:
            ticker, mic = meta.get(figi, (None, None))
            ysym = quotes_mod.yahoo_symbol_for(ticker, mic)
            row = {
                "figi": figi, "ticker": ticker, "yahoo_symbol": ysym,
                "price": None, "prev_close": None, "live_return": None,
                "currency": None, "quote_time": None,
                "freshness": "unavailable", "age_seconds": None,
            }
            if ysym is not None:
                attempted += 1
                try:
                    q = quotes_mod.fetch_raw_quote(ysym)
                except QuoteSourceUnreachable:
                    net_errors += 1
                    q = None
                if q is not None:
                    fresh, age = quotes_mod.classify_freshness(q.quote_epoch, now)
                    row.update(
                        price=q.price, prev_close=q.prev_close,
                        live_return=quotes_mod.live_return(q.price, q.prev_close),
                        currency=q.currency,
                        quote_time=(
                            datetime.fromtimestamp(q.quote_epoch, tz=timezone.utc).isoformat()
                            if q.quote_epoch is not None else None
                        ),
                        freshness=fresh, age_seconds=age,
                    )
            out.append(row)
        if attempted and net_errors == attempted:
            raise QuoteSourceUnreachable(
                f"quote provider unreachable ({net_errors}/{attempted} symbols)"
            )
        return out

    def security_detail(self, figi: str) -> dict | None:
        """One security: master + latest price + fundamentals + returns across windows."""
        c = self._conn
        master = c.execute(
            "SELECT composite_figi, mic, currency_code, status, delist_date "
            "FROM securities WHERE composite_figi = %s",
            (figi,),
        ).fetchone()
        if not master:
            return None
        ticker = _scalar(
            c,
            "SELECT symbol_value FROM security_symbology WHERE composite_figi = %s "
            "AND symbol_type = 'ticker' ORDER BY (valid_to IS NULL) DESC, valid_from DESC LIMIT 1",
            (figi,),
        )
        name = _scalar(
            c,
            "SELECT name FROM security_names WHERE composite_figi = %s "
            "ORDER BY (valid_to IS NULL) DESC, valid_from DESC LIMIT 1",
            (figi,),
        )
        gics = c.execute(
            "SELECT sector_name, industry_name, sub_industry_name, source FROM gics_scd "
            "WHERE composite_figi = %s ORDER BY (valid_to IS NULL) DESC, valid_from DESC LIMIT 1",
            (figi,),
        ).fetchone()
        # Per-source breakdown — every source's OWN current opinion from the multi-source
        # opinion matrix (gics_source_opinion), one effective row per source. `effective`
        # flags the source that won precedence into the resolved gics_scd (gics[3]). Falls
        # back to the single resolved gics_scd row when the matrix hasn't been populated yet
        # (`sym classify-opinions` not run), so the detail still shows the resolved class.
        resolved_source = gics[3] if gics else None
        opinions = c.execute(
            """
            SELECT source, sector_name, industry_name, sub_industry_name
              FROM gics_source_opinion
             WHERE composite_figi = %s AND valid_to IS NULL
             ORDER BY source
            """,
            (figi,),
        ).fetchall()
        if opinions:
            by_source = [(src, sec, ind, sub, src == resolved_source) for src, sec, ind, sub in opinions]
        elif gics:
            by_source = [(gics[3], gics[0], gics[1], gics[2], True)]  # resolved-row fallback
        else:
            by_source = []
        country = c.execute(
            "SELECT country, country_iso FROM exchange WHERE mic = %s",
            (master[1],),
        ).fetchone()
        px = c.execute(
            "SELECT close, volume, session_date FROM prices_raw WHERE composite_figi = %s "
            "ORDER BY session_date DESC LIMIT 1",
            (figi,),
        ).fetchone()
        fund = c.execute(
            "SELECT market_cap_lcy, market_cap_usd, shares_outstanding, currency_code, as_of_date "
            "FROM fundamentals WHERE composite_figi = %s ORDER BY as_of_date DESC LIMIT 1",
            (figi,),
        ).fetchone()
        rets = c.execute(
            """
            SELECT DISTINCT ON (fr.window_id) fr.window_id, w.code, w.label, fr.pr, fr.tr, fr.as_of_date
              FROM fact_returns fr JOIN return_window w USING (window_id)
             WHERE fr.composite_figi = %s
             ORDER BY fr.window_id, fr.as_of_date DESC
            """,
            (figi,),
        ).fetchall()
        return {
            "figi": master[0],
            "ticker": ticker or master[0],
            "name": name,
            "mic": master[1],
            "currency": master[2],
            "status": master[3],
            "delist_date": master[4].isoformat() if master[4] else None,
            "country": country[0] if country else None,
            "country_iso": country[1] if country else None,
            "sector": gics[0] if gics else None,
            "industry": gics[1] if gics else None,
            "sub_industry": gics[2] if gics else None,
            "source": gics[3] if gics else None,
            "classifications": [
                {
                    "source": src,
                    "sector": sec,
                    "industry": ind,
                    "sub_industry": sub,
                    "effective": bool(eff),
                }
                for src, sec, ind, sub, eff in by_source
            ],
            "price": {
                "close": float(px[0]) if px and px[0] is not None else None,
                "volume": int(px[1]) if px and px[1] is not None else None,
                "session_date": px[2].isoformat() if px and px[2] else None,
            },
            "fundamentals": {
                "market_cap_lcy": float(fund[0]) if fund and fund[0] is not None else None,
                "market_cap_usd": float(fund[1]) if fund and fund[1] is not None else None,
                "shares_outstanding": float(fund[2]) if fund and fund[2] is not None else None,
                "currency": fund[3] if fund else None,
                "as_of_date": fund[4].isoformat() if fund and fund[4] else None,
            }
            if fund
            else None,
            "returns": [
                {
                    "code": code,
                    "label": label,
                    "pr": float(pr) if pr is not None else None,
                    "tr": float(tr) if tr is not None else None,
                    "as_of_date": as_of_date.isoformat() if as_of_date else None,
                }
                for _wid, code, label, pr, tr, as_of_date in sorted(rets, key=lambda r: r[0])
            ],
        }

    def attention(self) -> dict:
        """Open attention items sym flagged: review queue, price gaps, membership proposals.
        Read-only (acting on items is deferred — FR-11). Each surfaces sym's evidence."""
        c = self._conn
        review = c.execute(
            "SELECT review_id, source_key, source_input, status, created_at "
            "FROM securities_review_queue ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
        gaps_total = c.execute("SELECT count(*) FROM price_gaps").fetchone()[0]
        gaps_recent = c.execute(
            """
            SELECT pg.composite_figi, tk.symbol_value, pg.session_date, pg.source, pg.detected_at
              FROM price_gaps pg
              LEFT JOIN LATERAL (
                  SELECT symbol_value FROM security_symbology y
                   WHERE y.composite_figi = pg.composite_figi AND y.symbol_type = 'ticker'
                   ORDER BY (y.valid_to IS NULL) DESC, y.valid_from DESC LIMIT 1
              ) tk ON TRUE
             ORDER BY pg.detected_at DESC LIMIT 30
            """
        ).fetchall()
        props = c.execute(
            "SELECT proposal_id, universe_id, raw_identifier, change, status, created_at "
            "FROM membership_proposal ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
        return {
            "review_queue": [
                {
                    "review_id": str(rid),
                    "source_key": _as_text(sk),
                    "source_input": _as_text(si),
                    "status": st,
                    "created_at": ca.isoformat() if ca else None,
                }
                for rid, sk, si, st, ca in review
            ],
            "price_gaps": {
                "total": gaps_total,
                "recent": [
                    {
                        "figi": figi,
                        "ticker": tk,
                        "session_date": sd.isoformat() if sd else None,
                        "source": src,
                        "detected_at": da.isoformat() if da else None,
                    }
                    for figi, tk, sd, src, da in gaps_recent
                ],
            },
            "membership_proposals": [
                {
                    "proposal_id": str(pid),
                    "universe_id": uid,
                    "raw_identifier": ri,
                    "change": ch,
                    "status": st,
                    "created_at": ca.isoformat() if ca else None,
                }
                for pid, uid, ri, ch, st, ca in props
            ],
        }

    def validation(self) -> list[dict]:
        """Recent validation runs (validation_run_log), newest first."""
        rows = self._conn.execute(
            "SELECT run_id, run_at, universe_id, checks, passed, warned, failed, status "
            "FROM validation_run_log ORDER BY run_at DESC LIMIT 50"
        ).fetchall()
        return [
            {
                "run_id": str(rid),
                "run_at": ra.isoformat() if ra else None,
                "universe_id": uid,
                "checks": checks,
                "passed": passed,
                "warned": warned,
                "failed": failed,
                "status": status,
            }
            for rid, ra, uid, checks, passed, warned, failed, status in rows
        ]
