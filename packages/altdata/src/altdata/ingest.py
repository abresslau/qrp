"""Altdata ingest: multi-source alt-data series keyed to sym securities.

Sources (v1): Wikimedia daily pageviews (per-company attention proxy) and SEC EDGAR
filing activity (daily Form 4 / 8-K counts — insider-transaction and corporate-event
intensity). Each curated ticker resolves to a sym composite_figi over a read-only sym
connection (AR-R2); series + observations land in the altdata-owned generic tables
(``altdata.series`` / ``altdata.observation``), provenance in ``series.detail`` (wiki
article title / zero-padded CIK). Idempotent. Never fabricates — unresolved tickers or
CIKs are skipped and reported; per-series failures are attributed in the summary.
"""

from __future__ import annotations

from datetime import date

import psycopg

from altdata.db import connect
from altdata.sources import fetch_company_ciks, fetch_pageviews, fetch_sec_filing_counts

# Curated ticker -> (en.wikipedia article, display name). Wikipedia article titles are
# stable; the attention signal is the daily pageview count.
_MAP = {
    "AAPL": ("Apple_Inc.", "Apple"),
    "NVDA": ("Nvidia", "Nvidia"),
    "MSFT": ("Microsoft", "Microsoft"),
    "AMZN": ("Amazon_(company)", "Amazon"),
    "GOOGL": ("Alphabet_Inc.", "Alphabet"),
    "META": ("Meta_Platforms", "Meta Platforms"),
    "TSLA": ("Tesla,_Inc.", "Tesla"),
    "JPM": ("JPMorgan_Chase", "JPMorgan Chase"),
    "KO": ("The_Coca-Cola_Company", "Coca-Cola"),
    "DIS": ("The_Walt_Disney_Company", "Walt Disney"),
}

# SEC EDGAR metrics: metric name -> exact form types counted (amendments excluded by
# design — see fetch_sec_filing_counts).
_SEC_METRICS: dict[str, frozenset[str]] = {
    "filings_form4": frozenset({"4"}),
    "filings_8k": frozenset({"8-K"}),
}


def _resolve_figi(conn: psycopg.Connection, ticker: str) -> str | None:
    r = conn.execute(
        "SELECT composite_figi FROM security_symbology WHERE symbol_type='ticker' "
        "AND upper(symbol_value)=upper(%s) "
        "ORDER BY (valid_to IS NULL) DESC, valid_from DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    return r[0] if r else None


def _upsert_series(
    conn: psycopg.Connection,
    figi: str,
    source: str,
    metric: str,
    ticker: str,
    name: str,
    detail: str,
    unit: str,
) -> None:
    conn.execute(
        "INSERT INTO altdata.series (composite_figi, source, metric, ticker, name, detail, unit) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (composite_figi, source, metric) DO UPDATE SET "
        "ticker=EXCLUDED.ticker, name=EXCLUDED.name, detail=EXCLUDED.detail, unit=EXCLUDED.unit",
        (figi, source, metric, ticker, name, detail, unit),
    )


def _upsert_observations(
    conn: psycopg.Connection,
    figi: str,
    source: str,
    metric: str,
    obs: list[tuple[date, float]],
) -> int:
    n = 0
    for d, v in obs:
        conn.execute(
            "INSERT INTO altdata.observation (composite_figi, source, metric, obs_date, value) "
            "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (composite_figi, source, metric, obs_date) "
            "DO UPDATE SET value=EXCLUDED.value",
            (figi, source, metric, d, v),
        )
        n += 1
    return n


def run_ingest(
    sym_conn: psycopg.Connection,
    ad_conn: psycopg.Connection,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    """Ingest all curated series. One summary row per (ticker, source, metric) attempt.

    ``obs`` counts rows upserted for that series in this run (window-bound, not lifetime).
    """
    ad_conn.autocommit = True
    end_date = end_date or date.today()
    start_date = start_date or date.fromordinal(end_date.toordinal() - 120)  # default ~120 days
    summary: list[dict] = []

    figis = {t: _resolve_figi(sym_conn, t) for t in _MAP}

    # --- wikipedia: daily pageviews -----------------------------------------------------
    for ticker, (article, name) in _MAP.items():
        figi = figis[ticker]
        if not figi:
            summary.append(
                {"ticker": ticker, "source": "wikipedia", "metric": "pageviews",
                 "ok": False, "reason": "unresolved ticker"}
            )
            continue
        try:
            pvs = fetch_pageviews(article, start_date, end_date)
        except Exception as exc:  # noqa: BLE001 — per-series attribution
            summary.append(
                {"ticker": ticker, "source": "wikipedia", "metric": "pageviews",
                 "ok": False, "reason": str(exc)[:120]}
            )
            continue
        _upsert_series(ad_conn, figi, "wikipedia", "pageviews", ticker, name, article, "views")
        n = _upsert_observations(ad_conn, figi, "wikipedia", "pageviews", pvs)
        summary.append(
            {"ticker": ticker, "source": "wikipedia", "metric": "pageviews", "ok": True, "obs": n}
        )

    # --- sec_edgar: filing-activity counts ----------------------------------------------
    try:
        ciks = fetch_company_ciks(set(_MAP))
    except Exception as exc:  # noqa: BLE001 — the map failing fails all EDGAR series, attributed
        ciks = None
        map_reason = f"company_tickers.json: {str(exc)[:100]}"
        for ticker in _MAP:
            # a sym-unresolved ticker keeps its own reason — the map failure is unrelated
            reason = "unresolved ticker" if not figis[ticker] else map_reason
            for metric in _SEC_METRICS:
                summary.append(
                    {"ticker": ticker, "source": "sec_edgar", "metric": metric,
                     "ok": False, "reason": reason}
                )
    if ciks is not None:
        for ticker, (_article, name) in _MAP.items():
            figi = figis[ticker]
            cik = ciks.get(ticker)
            if not figi or not cik:
                reason = "unresolved ticker" if not figi else "no CIK in company_tickers.json"
                for metric in _SEC_METRICS:
                    summary.append(
                        {"ticker": ticker, "source": "sec_edgar", "metric": metric,
                         "ok": False, "reason": reason}
                    )
                continue
            try:
                counts = fetch_sec_filing_counts(cik, _SEC_METRICS, start_date, end_date)
            except Exception as exc:  # noqa: BLE001 — one fetch serves both metrics
                for metric in _SEC_METRICS:
                    summary.append(
                        {"ticker": ticker, "source": "sec_edgar", "metric": metric,
                         "ok": False, "reason": str(exc)[:120]}
                    )
                continue
            for metric in _SEC_METRICS:
                _upsert_series(ad_conn, figi, "sec_edgar", metric, ticker, name, cik, "filings")
                n = _upsert_observations(ad_conn, figi, "sec_edgar", metric, counts[metric])
                summary.append(
                    {"ticker": ticker, "source": "sec_edgar", "metric": metric,
                     "ok": True, "obs": n}
                )

    # End-of-run sweep (macro's rule): a series row with no observations at all is not
    # data and is never served — e.g. an EDGAR metric with zero matching filings in the
    # window and no prior history.
    ad_conn.execute(
        "DELETE FROM altdata.series s WHERE NOT EXISTS ("
        "SELECT 1 FROM altdata.observation o WHERE o.composite_figi=s.composite_figi "
        "AND o.source=s.source AND o.metric=s.metric)"
    )

    return {"series": summary, "total_obs": sum(s.get("obs", 0) for s in summary)}


if __name__ == "__main__":
    sym_conn = connect("sym")
    ad_conn = connect()
    try:
        res = run_ingest(sym_conn, ad_conn)
        for s in res["series"]:
            print(s)
        print("total observations:", res["total_obs"])
    finally:
        sym_conn.close()
        ad_conn.close()
