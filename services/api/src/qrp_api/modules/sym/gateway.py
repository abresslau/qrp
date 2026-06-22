"""DB-backed reads for the sym module (Overview Q2.1 + Universe heat map Q2.6/FR-23).

Reads sym's tables/views directly (read/trigger posture; no writes). Every figure is a live
read of sym — nothing mocked.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import psycopg

from qrp_api.modules.sym import news as news_mod
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


_TRAILING_KEYS = ("mtd", "qtd", "ytd", "1y", "2y", "3y", "5y", "10y")

# Default currency set for the FX cross-rate matrix — the majors basket (G10 + Scandies + HKD/SGD/MXN
# + CNY/BRL), all populated in fx_rate. USD last (the star base sits at the bottom row / right column
# so the non-USD crosses read first).
DEFAULT_FX_MATRIX = [
    # by FX trading volume, matching Bloomberg FXC's column order (USD prepended on the page):
    # USD, EUR, JPY, GBP, CHF, CAD, AUD, NZD, then the Scandies + HKD/SGD/MXN + CNY/BRL.
    "EUR", "JPY", "GBP", "CHF", "CAD", "AUD", "NZD",
    "SEK", "NOK", "DKK", "HKD", "SGD", "MXN",
    "CNY", "BRL", "USD",
]


def _period_return(series: list[dict], days: int) -> float | None:
    """Trailing return over a day window: latest level vs the last observation on-or-before
    latest − ``days``. None when the series doesn't reach that far back. Pure helper (no DB)."""
    if len(series) < 2:
        return None
    last = series[-1]
    start_iso = (date.fromisoformat(last["date"]) - timedelta(days=days)).isoformat()
    base = None
    for p in series:
        if p["date"] <= start_iso:
            base = p
        else:
            break
    return last["level"] / base["level"] - 1.0 if base and base["level"] and base["date"] < last["date"] else None


def _trailing_returns(series: list[dict]) -> dict:
    """Trailing returns (MTD/QTD/YTD/1Y/2Y/3Y/5Y/10Y) from a date-ascending level series — latest
    level vs the last observation on-or-before each window's start date. MTD/QTD/YTD anchor on the
    prior month/quarter/year end; the year windows on latest − N×365d. None when the series doesn't
    reach back far enough. Pure helper (no DB)."""
    if len(series) < 2:
        return dict.fromkeys(_TRAILING_KEYS)
    last = series[-1]
    last_date = date.fromisoformat(last["date"])

    def ret(start_iso: str) -> float | None:
        base = None
        for p in series:
            if p["date"] <= start_iso:
                base = p
            else:
                break
        # require a real lookback (a base strictly before the latest point) + a positive divisor
        return last["level"] / base["level"] - 1.0 if base and base["level"] and base["date"] < last["date"] else None

    y, m = last_date.year, last_date.month
    q_start_month = ((m - 1) // 3) * 3 + 1  # 1/4/7/10 — first month of the current quarter
    return {
        "mtd": ret(f"{y:04d}-{m:02d}-01"),
        "qtd": ret(f"{y:04d}-{q_start_month:02d}-01"),
        "ytd": ret(f"{y:04d}-01-01"),
        "1y": ret((last_date - timedelta(days=365)).isoformat()),
        "2y": ret((last_date - timedelta(days=2 * 365)).isoformat()),
        "3y": ret((last_date - timedelta(days=3 * 365)).isoformat()),
        "5y": ret((last_date - timedelta(days=5 * 365)).isoformat()),
        "10y": ret((last_date - timedelta(days=10 * 365)).isoformat()),
    }


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
            SELECT m.universe_id, u.name,
                   count(*) AS members,
                   count(*) FILTER (WHERE s.status = 'active') AS active,
                   count(*) FILTER (WHERE s.status = 'active' AND px.d >= %(latest)s - 7) AS px_cov,
                   max(px.d) FILTER (WHERE s.status = 'active') AS px_latest,
                   count(*) FILTER (WHERE s.status = 'active' AND rt.d >= %(latest)s - 7) AS rt_cov,
                   max(rt.d) FILTER (WHERE s.status = 'active') AS rt_latest,
                   count(*) FILTER (WHERE s.status = 'active' AND fn.d IS NOT NULL) AS fn_cov,
                   max(fn.d) FILTER (WHERE s.status = 'active') AS fn_latest
              FROM members m
              JOIN universe u ON u.universe_id = m.universe_id
              JOIN securities s ON s.composite_figi = m.composite_figi
              LEFT JOIN px ON px.composite_figi = m.composite_figi
              LEFT JOIN rt ON rt.composite_figi = m.composite_figi
              LEFT JOIN fn ON fn.composite_figi = m.composite_figi
             GROUP BY m.universe_id, u.name
             ORDER BY members DESC, m.universe_id
            """,
            {"latest": latest, "w": one_win},
        ).fetchall()

        def _layer(cov: int, total: int, latest_d) -> dict:
            # `total` is the ACTIVE member count — delisted names are not expected to have
            # current data, so they neither count against coverage nor as covered.
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
                "members_resolved": members,
                "active_members": active,
                "prices": _layer(pxc, active, pxl),
                "returns": _layer(rtc, active, rtl),
                "fundamentals": _layer(fnc, active, fnl),
            }
            for uid, name, members, active, pxc, pxl, rtc, rtl, fnc, fnl in rows
        ]

    def return_windows(self) -> list[tuple[str, str]]:
        """Curated (code, label) windows for the heat-map selector, in HEATMAP_WINDOWS order."""
        rows = self._conn.execute(
            "SELECT code, label FROM return_window WHERE code = ANY(%s)", (HEATMAP_WINDOWS,)
        ).fetchall()
        by_code = {code: label for code, label in rows}
        return [(c, by_code[c]) for c in HEATMAP_WINDOWS if c in by_code]

    def security_news(self, figi: str, *, limit: int = 12) -> list[dict]:
        """Recent news headlines for a security (Google News RSS, fetched at serve time, not
        persisted). Resolves the figi to its company name (best news coverage), falling back to
        ticker. Best-effort: a feed failure returns []."""
        c = self._conn
        name = _scalar(
            c,
            "SELECT name FROM security_names WHERE composite_figi = %s "
            "ORDER BY (valid_to IS NULL) DESC, valid_from DESC LIMIT 1",
            (figi,),
        )
        ticker = _scalar(
            c,
            "SELECT symbol_value FROM security_symbology WHERE composite_figi = %s "
            "AND symbol_type = 'ticker' ORDER BY (valid_to IS NULL) DESC, valid_from DESC LIMIT 1",
            (figi,),
        )
        query = name or ticker or figi
        items = news_mod.fetch_news(f"{query} stock", limit=limit)
        return [
            {"title": i.title, "link": i.link, "source": i.source, "published": i.published}
            for i in items
        ]

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
        self,
        q: str | None,
        limit: int,
        offset: int,
        universe: str | None = None,
        gap: str | None = None,
    ) -> dict:
        """Paged list of securities — optionally searched (ticker/name/FIGI), filtered to one
        universe's resolved members, and/or restricted to that universe's GAP names in a layer
        (``gap`` in prices/returns/fundamentals = the members the Universes-coverage "partial"
        pill counts as not-covered). All filters apply to the count + rows alike."""
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
        # Gap drill-down (only within a universe): members NOT covered in a layer — the inverse
        # of the coverage "covered" test, using the SAME cutoffs so it matches the pill count.
        if gap and universe:
            latest = _scalar(c, "SELECT max(session_date) FROM prices_raw")
            if gap == "prices":
                conds.append(
                    "NOT EXISTS (SELECT 1 FROM prices_raw p WHERE p.composite_figi = s.composite_figi "
                    "AND p.session_date >= %s - 7)"
                )
                params.append(latest)
            elif gap == "returns":
                one_win = _scalar(c, "SELECT min(window_id) FROM return_window")
                conds.append(
                    "NOT EXISTS (SELECT 1 FROM fact_returns fr WHERE fr.composite_figi = s.composite_figi "
                    "AND fr.window_id = %s AND fr.as_of_date >= %s - 7)"
                )
                params += [one_win, latest]
            elif gap == "fundamentals":
                conds.append(
                    "NOT EXISTS (SELECT 1 FROM fundamentals f WHERE f.composite_figi = s.composite_figi "
                    "AND f.as_of_date >= %s - 180)"
                )
                params.append(latest)
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

    def security_prices(self, figi: str, *, days: int = 365) -> list[dict]:
        """Daily OHLC + volume history for a security (for the detail-page chart: line/area/
        candle), most-recent `days` calendar days, oldest-first. Index-bounded by
        session_date + composite_figi (rides the prices_raw PK) — bounded scan, not a
        full-table read."""
        rows = self._conn.execute(
            """
            SELECT session_date, open, high, low, close, volume FROM prices_raw
             WHERE composite_figi = %s
               AND session_date >= (SELECT max(session_date) FROM prices_raw
                                     WHERE composite_figi = %s) - %s
             ORDER BY session_date
            """,
            (figi, figi, days),
        ).fetchall()
        return [
            {
                "session_date": d.isoformat(),
                "open": float(o) if o is not None else None,
                "high": float(h) if h is not None else None,
                "low": float(low) if low is not None else None,
                "close": float(close) if close is not None else None,
                "volume": int(volume) if volume is not None else None,
            }
            for d, o, h, low, close, volume in rows
        ]

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

    def indices(self) -> list[dict]:
        """Benchmark index instruments that have level data — name, MSCI code+variant (parsed from
        the `msci` xref `<code>:<VARIANT>`), currency, asset class, level count, first/last/latest
        level. Lists ALL index instruments incl. non-equity (VIX) — the equity-only filter is the
        WEI board's job, not this list."""
        from sym.benchmarks.levels import category_for

        rows = self._conn.execute(
            """
            SELECT i.sym_id, i.name, i.currency_code,
                   (SELECT value FROM instrument_xref x
                     WHERE x.sym_id = i.sym_id AND x.source = 'msci' LIMIT 1) AS msci_xref,
                   count(l.session_date)                                       AS n_levels,
                   min(l.session_date)                                         AS first_date,
                   max(l.session_date)                                         AS last_date,
                   (SELECT level FROM index_levels ll
                     WHERE ll.sym_id = i.sym_id ORDER BY ll.session_date DESC LIMIT 1) AS last_level
              FROM instrument i
              JOIN index_levels l ON l.sym_id = i.sym_id
             WHERE i.kind = 'index'
             GROUP BY i.sym_id, i.name, i.currency_code
             ORDER BY i.name NULLS LAST, i.sym_id
            """
        ).fetchall()
        out: list[dict] = []
        for sym_id, name, ccy, xref, n, first_d, last_d, last_level in rows:
            code, _, variant = (xref or "").partition(":")
            out.append(
                {
                    "sym_id": sym_id,
                    "name": name,
                    "currency": ccy,
                    "msci_code": code or None,
                    "variant": variant or None,  # NETR/STRD/GRTR (None for non-MSCI indices)
                    "category": category_for(name),
                    "n_levels": n,
                    "first_date": first_d.isoformat() if first_d else None,
                    "last_date": last_d.isoformat() if last_d else None,
                    "last_level": float(last_level) if last_level is not None else None,
                }
            )
        return out

    def index_levels(
        self, sym_id: int, *, start: str | None = None, end: str | None = None
    ) -> dict:
        """The level series for one index instrument (ascending by date), with light metadata +
        a since-start return. 404-able by the router when the sym_id has no levels."""
        conds = ["sym_id = %s"]
        params: list = [sym_id]
        if start:
            conds.append("session_date >= %s")
            params.append(start)
        if end:
            conds.append("session_date <= %s")
            params.append(end)
        rows = self._conn.execute(
            f"SELECT session_date, level FROM index_levels WHERE {' AND '.join(conds)} "
            "ORDER BY session_date",
            params,
        ).fetchall()
        meta = self._conn.execute(
            """
            SELECT i.name, i.currency_code,
                   (SELECT value FROM instrument_xref x
                     WHERE x.sym_id = i.sym_id AND x.source = 'msci' LIMIT 1) AS msci_xref
              FROM instrument i WHERE i.sym_id = %s
            """,
            (sym_id,),
        ).fetchone()
        series = [{"date": d.isoformat(), "level": float(lv)} for d, lv in rows]
        since_start = None
        if len(series) >= 2 and series[0]["level"]:
            since_start = series[-1]["level"] / series[0]["level"] - 1.0
        name, ccy, xref = meta if meta else (None, None, None)
        code, _, variant = (xref or "").partition(":")
        return {
            "sym_id": sym_id,
            "name": name,
            "currency": ccy,
            "msci_code": code or None,
            "variant": variant or None,
            "n_levels": len(series),
            "since_start_return": since_start,
            "trailing": _trailing_returns(series),
            "series": series,
        }

    def index_board(self, as_of_date: date | None = None) -> list[dict]:
        """World-Equity-Indices board: every index instrument with levels — latest + prior session
        (1D net/% change), YTD, region, currency, and a recent sparkline — in two queries (no N+1).
        MSCI aggregates are limited to the Net (NETR) variant so the board shows one row per index.

        ``as_of_date`` rewinds the board to a past close: each index anchors on its latest session
        with ``session_date <= as_of_date`` (per-market as-of resolution — last value with date ≤ D),
        and every window re-bases to that anchor (the trailing helpers anchor on the clipped series'
        last point, so no formula changes). Omitted ⇒ the latest session (unchanged behaviour); an
        index with no session on-or-before the date drops out (inner join), never a fabricated row."""
        from sym.benchmarks.levels import category_for, country_for, region_for

        c = self._conn
        # The anchor is the latest session per index ≤ as_of_date (or the global latest when omitted).
        # Both queries stay relative to that anchor so the omitted path is byte-for-byte as before.
        params: dict = {}
        if as_of_date is not None:
            params["as_of_date"] = as_of_date
            ranked_filter = "WHERE session_date <= %(as_of_date)s"
            recent_sql = """
                SELECT sym_id, session_date, level FROM index_levels
                 WHERE session_date <= %(as_of_date)s AND session_date >= %(as_of_date)s - 1900
                 ORDER BY sym_id, session_date
                """
        else:
            ranked_filter = ""
            recent_sql = """
                SELECT sym_id, session_date, level FROM index_levels
                 WHERE session_date >= (SELECT max(session_date) FROM index_levels) - 1900
                 ORDER BY sym_id, session_date
                """
        rows = c.execute(
            f"""
            WITH ranked AS (
                SELECT sym_id, session_date, level,
                       row_number() OVER (PARTITION BY sym_id ORDER BY session_date DESC) AS rn
                  FROM index_levels
                 {ranked_filter}
            )
            SELECT i.sym_id, i.name, i.currency_code,
                   (SELECT value FROM instrument_xref x
                     WHERE x.sym_id = i.sym_id AND x.source = 'msci' LIMIT 1)        AS msci_xref,
                   max(r.level) FILTER (WHERE r.rn = 1)                              AS last,
                   max(r.session_date) FILTER (WHERE r.rn = 1)                       AS last_date,
                   max(r.level) FILTER (WHERE r.rn = 2)                              AS prev
              FROM instrument i
              JOIN ranked r ON r.sym_id = i.sym_id AND r.rn <= 2
             WHERE i.kind = 'index'
             GROUP BY i.sym_id, i.name, i.currency_code
            """,
            params,
        ).fetchall()
        # recent levels (one query) for trailing-return bases + sparkline; ~1900d reaches back past the
        # 5Y window (and the prior year-end for MTD/YTD), so every window resolves from one pull.
        recent = c.execute(recent_sql, params).fetchall()
        series: dict[int, list[tuple[date, float]]] = {}
        for sid, d, lv in recent:
            series.setdefault(sid, []).append((d, float(lv)))

        out: list[dict] = []
        for sym_id, name, ccy, xref, last, last_date, prev in rows:
            if category_for(name) != "equity":
                continue  # non-equity (e.g. the VIX volatility index) — kept off the equity board
                # (its up/down colour semantics invert); it still shows on the Indices page.
            _code, _sep, variant = (xref or "").partition(":")
            if xref and variant and variant != "NETR":
                continue  # MSCI PR/GR triplets — board shows the Net variant only
            last_f = float(last) if last is not None else None
            prev_f = float(prev) if prev is not None else None
            chg = last_f - prev_f if last_f is not None and prev_f is not None else None
            # `prev_f` truthiness still guards divide-by-zero; `last_f is not None` lets a legitimate
            # zero level through (consistent with chg's None-check).
            chg_pct = last_f / prev_f - 1.0 if last_f is not None and prev_f else None
            s = series.get(sym_id, [])
            asc = [{"date": d.isoformat(), "level": lv} for d, lv in s]
            tr = _trailing_returns(asc)
            # day-window returns: latest vs last obs on-or-before latest − Nd (same convention as the
            # year windows). 5D ≈ 7 calendar days (5 trading sessions); 1M/3M/6M = 30/91/182 days.
            d5 = _period_return(asc, 7)
            m1 = _period_return(asc, 30)
            m3 = _period_return(asc, 91)
            m6 = _period_return(asc, 182)
            # 52-week range: low/high of the trailing 365d of levels (incl. the latest observation)
            lo52 = hi52 = None
            if last_date:
                yr_ago = (last_date - timedelta(days=365)).isoformat()
                w52 = [lv for d, lv in s if d.isoformat() >= yr_ago]
                if w52:
                    lo52, hi52 = min(w52), max(w52)
            out.append(
                {
                    "sym_id": sym_id,
                    "name": name,
                    "region": region_for(name, ccy),
                    "country": country_for(name, ccy),
                    "currency": ccy,
                    "last": last_f,
                    "last_date": last_date.isoformat() if last_date else None,
                    "prev": prev_f,
                    "chg": chg,
                    "chg_pct": chg_pct,  # 1D
                    "d5": d5,
                    "mtd": tr["mtd"],
                    "m1": m1,
                    "m3": m3,
                    "m6": m6,
                    "ytd": tr["ytd"],
                    "1y": tr["1y"],
                    "2y": tr["2y"],
                    "3y": tr["3y"],
                    "5y": tr["5y"],
                    "lo_52w": lo52,
                    "hi_52w": hi52,
                    "spark": [lv for _, lv in s[-30:]],
                }
            )
        return out

    def index_board_live(self, now: float | None = None) -> dict:
        """LIVE World-Equity-Indices board (Story wei-live-board): the EOD ``index_board`` with each
        row's ``last``/1D and trailing windows re-marked to a LIVE intraday quote (the QH.2 source,
        fanned out per QH.9). Quotes are best-effort and **never persisted**.

        Re-base is exact and series-free: a window's base (N periods ago) is unchanged; only the
        endpoint moves from the EOD close to the live price, so ``r_live = (1 + r_eod) * f - 1`` with
        ``f = live / eod_last``. Live 1D = live vs the latest stored EOD close ("today's move"). An
        index with no usable quote keeps its EOD row and is marked ``unavailable`` (never a fabricated
        live mark). Per-row ``freshness`` + a board rollup (``as_of`` = most-recent priced quote, worst
        ``freshness``, ``priced``/``total``). Raises ``QuoteSourceUnreachable`` (→503) only when the
        provider is wholly unreachable; a per-index miss is an ``unavailable`` row, not a failure."""
        eod = self.index_board()  # equity-only latest-EOD board — the shared row build
        c = self._conn
        sym_ids = [r["sym_id"] for r in eod]
        # each equity index's Yahoo symbol (^GSPC, ^FTSE, …) from its `yahoo` xref — an index symbol
        # IS the Yahoo symbol (not the equity ticker+MIC path); the chart endpoint serves it (the same
        # one YahooIndexLevelSource.official_quote uses).
        xref: dict[int, str] = {}
        if sym_ids:
            for sid, val in c.execute(
                "SELECT sym_id, value FROM instrument_xref WHERE source = 'yahoo' AND sym_id = ANY(%s)",
                (sym_ids,),
            ).fetchall():
                xref[sid] = val
        now = quotes_mod.now_epoch() if now is None else now
        symbols = [xref[sid] for sid in sym_ids if xref.get(sid)]
        batch = quotes_mod.fetch_quotes_batch(symbols) if symbols else {}

        _windows = ("d5", "mtd", "m1", "m3", "m6", "ytd", "1y", "2y", "3y", "5y")
        priced = 0
        any_delayed = False
        newest_epoch: int | None = None
        rows: list[dict] = []
        for r in eod:
            ysym = xref.get(r["sym_id"])
            q = batch.get(ysym) if ysym else None
            eod_last = r["last"]
            live = dict(r)
            live["freshness"] = "unavailable"
            live["quote_time"] = None
            # need a positive live price AND a positive EOD close to re-base (else keep EOD, unavailable)
            if q is not None and q.price is not None and q.price > 0 and eod_last is not None and eod_last > 0:
                f = q.price / eod_last
                live["last"] = q.price
                live["prev"] = eod_last  # today's move is vs the latest stored close
                live["chg"] = q.price - eod_last
                live["chg_pct"] = f - 1.0
                for w in _windows:
                    base = r.get(w)
                    live[w] = (1.0 + base) * f - 1.0 if base is not None else None
                lo, hi = r["lo_52w"], r["hi_52w"]
                live["lo_52w"] = min(lo, q.price) if lo is not None else None
                live["hi_52w"] = max(hi, q.price) if hi is not None else None
                live["spark"] = [*(r["spark"] or []), q.price]
                fresh, _age = quotes_mod.classify_freshness(q.quote_epoch, now)
                live["freshness"] = fresh
                if q.quote_epoch is not None:
                    live["quote_time"] = datetime.fromtimestamp(
                        q.quote_epoch, tz=timezone.utc
                    ).isoformat()
                    newest_epoch = (
                        q.quote_epoch if newest_epoch is None else max(newest_epoch, q.quote_epoch)
                    )
                priced += 1
                any_delayed = any_delayed or fresh == "delayed"
            rows.append(live)
        return {
            "as_of": (
                datetime.fromtimestamp(newest_epoch, tz=timezone.utc).isoformat()
                if newest_epoch is not None else None
            ),
            # worst-of: nothing priced → unavailable; any delayed OR partial coverage (some indices
            # unavailable) → delayed (amber), so the badge never reads fully-"live" while rows are
            # stale EOD; only a fully-priced, all-fresh board reads "live".
            "freshness": (
                "unavailable" if priced == 0
                else "delayed" if (any_delayed or priced < len(rows))
                else "live"
            ),
            "priced": priced,
            "total": len(rows),
            "rows": rows,
        }

    def fx_matrix(
        self, currencies: list[str] | None = None, as_of_date: date | None = None
    ) -> dict:
        """FX cross-rate matrix: a square grid of major currencies where cell(base, quote) = units of
        quote per 1 base (= quote_rate / base_rate, both per-USD), diagonal = 1.0. Derived from the
        USD-base ``fx_rate`` star — two as-of resolutions per currency (the date + its prior
        observation), then the N×N grid by division (no N²). Each cell carries ``chg`` = the day's move
        in the cross (for the green/red heat map). ``as_of_date`` backdates the whole matrix (omitted ⇒
        the latest FX date). A cell whose base or quote leg isn't ``ok`` (stale/no_data) gets a null
        rate (never a fabricated cross)."""
        from sym.fx.convention import conventional_pair, quote_rank
        from sym.fx.resolve import fx_rate

        c = self._conn
        # Dedupe preserving order — a repeated code (e.g. ?currencies=USD,EUR,EUR) must not produce
        # duplicate grid rows/cols (which would collide on the page's per-currency React keys).
        ccys = list(dict.fromkeys(x.strip().upper() for x in (currencies or DEFAULT_FX_MATRIX) if x and x.strip()))
        if as_of_date is None:
            row = c.execute("SELECT max(as_of_date) FROM fx_rate").fetchone()
            as_of_date = row[0] if row and row[0] else date.today()
        res = {ccy: fx_rate(c, ccy, as_of_date) for ccy in ccys}
        # the prior observation per currency (the day before its resolved date) — for the cell's
        # daily change. USD is the constant star base; a leg with no observation has no prior.
        prev = {
            ccy: fx_rate(c, ccy, res[ccy].observed_date - timedelta(days=1))
            if res[ccy].observed_date is not None
            else None
            for ccy in ccys
        }
        meta = [
            {
                "currency": ccy,
                "status": r.status,
                "observed_date": r.observed_date.isoformat() if r.observed_date else None,
                "days_stale": r.days_stale,
                "quote_rank": quote_rank(ccy),  # quoting precedence (lower = conventional base)
            }
            for ccy in ccys
            for r in (res[ccy],)
        ]

        def cross_chg(base: str, quote: str) -> float | None:
            """Day's move in the cross (now vs the prior session), or None when unavailable."""
            pb, pq = prev.get(base), prev.get(quote)
            nb, nq = res[base].rate, res[quote].rate
            if not (pb and pq and nb is not None and nq is not None and pb.rate and pq.rate):
                return None
            now, before = nq / nb, pq.rate / pb.rate
            return float(now / before) - 1.0 if before else None

        rows: list[dict] = []
        for base in ccys:
            b = res[base]
            cells = []
            for quote in ccys:
                q = res[quote]
                cb, cq = conventional_pair(base, quote)
                pair = f"{cb}/{cq}"  # the market-standard direction for this pair
                if base == quote:
                    cells.append({"rate": 1.0, "chg": 0.0, "stale": False, "pair": pair})
                elif b.rate is not None and q.rate is not None:
                    # both legs resolved (ok, possibly carried-forward) — derive the cross + its move
                    cells.append(
                        {
                            "rate": float(q.rate / b.rate),
                            "chg": cross_chg(base, quote),
                            "stale": b.is_filled or q.is_filled,
                            "pair": pair,
                        }
                    )
                else:
                    cells.append({"rate": None, "chg": None, "stale": True, "pair": pair})
            rows.append({"base": base, "cells": cells})
        return {
            "as_of_date": as_of_date.isoformat(),
            "currencies": ccys,
            "meta": meta,
            "rows": rows,
        }

    def index_reconcile(self) -> dict:
        """Live index-close fidelity check: stored latest level vs the source's official close, per
        benchmark index. Read-only (SELECTs index_levels/xref + outbound vendor quotes; no writes) —
        the same check `sym index-reconcile` runs. Returns the tri-state result for the console."""
        from sym.benchmarks.levels import YahooIndexLevelSource
        from sym.validate.index_levels import check_index_level_fidelity

        r = check_index_level_fidelity(self._conn, YahooIndexLevelSource())
        return {
            "status": r.status,
            "checked": r.checked,
            "warnings": r.warnings,
            "failures": r.failures,
            "samples": r.samples,
            "detail": r.detail,
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
