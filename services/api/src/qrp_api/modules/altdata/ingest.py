"""Altdata ingest: Wikimedia daily pageviews as a per-company attention proxy.

Maps a curated set of large caps to en.wikipedia articles, resolves each to a sym
composite_figi (read-only) by current ticker, and upserts daily pageviews into the
QRP-managed `altdata` schema. Idempotent. Never fabricates — unresolved tickers are
skipped and reported; a name with no pageviews simply has no rows.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import date

import psycopg

from qrp_api.db import connect

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

_PV_URL = (
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
    "en.wikipedia/all-access/all-agents/{article}/daily/{start}/{end}"
)
_UA = {"User-Agent": "qrp-altdata/1.0 (personal research)"}


def _resolve_figi(conn, ticker: str) -> str | None:
    r = conn.execute(
        "SELECT composite_figi FROM security_symbology WHERE symbol_type='ticker' "
        "AND upper(symbol_value)=upper(%s) ORDER BY (valid_to IS NULL) DESC, valid_from DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    return r[0] if r else None


def _fetch_pageviews(article: str, start: date, end: date) -> list[tuple[date, int]]:
    url = _PV_URL.format(article=article, start=start.strftime("%Y%m%d00"),
                         end=end.strftime("%Y%m%d00"))
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310
        payload = json.loads(r.read().decode("utf-8", "replace"))
    out: list[tuple[date, int]] = []
    for item in payload.get("items", []):
        ts = item.get("timestamp")  # 'YYYYMMDD00'
        views = item.get("views")
        if ts and views is not None:
            out.append((date(int(ts[0:4]), int(ts[4:6]), int(ts[6:8])), int(views)))
    return out


def run_ingest(conn: psycopg.Connection, start: date | None = None,
               end: date | None = None) -> dict:
    conn.autocommit = True
    end = end or date(2026, 6, 5)
    start = start or date(end.year, end.month, 1).replace(day=1)
    # default to ~120 days
    start = date.fromordinal(end.toordinal() - 120)
    summary = []
    for ticker, (article, name) in _MAP.items():
        figi = _resolve_figi(conn, ticker)
        if not figi:
            summary.append({"ticker": ticker, "ok": False, "reason": "unresolved ticker"})
            continue
        conn.execute(
            "INSERT INTO altdata.wiki_map (composite_figi, ticker, name, article) "
            "VALUES (%s,%s,%s,%s) ON CONFLICT (composite_figi) DO UPDATE SET "
            "ticker=EXCLUDED.ticker, name=EXCLUDED.name, article=EXCLUDED.article",
            (figi, ticker, name, article),
        )
        try:
            pvs = _fetch_pageviews(article, start, end)
        except Exception as exc:  # noqa: BLE001
            summary.append({"ticker": ticker, "ok": False, "reason": str(exc)[:120]})
            continue
        n = 0
        for d, v in pvs:
            conn.execute(
                "INSERT INTO altdata.pageview (composite_figi, obs_date, views) VALUES (%s,%s,%s) "
                "ON CONFLICT (composite_figi, obs_date) DO UPDATE SET views=EXCLUDED.views",
                (figi, d, v),
            )
            n += 1
        summary.append({"ticker": ticker, "ok": True, "obs": n})
    return {"series": summary, "total_obs": sum(s.get("obs", 0) for s in summary)}


if __name__ == "__main__":
    conn = connect()
    try:
        res = run_ingest(conn)
        for s in res["series"]:
            print(s)
        print("total observations:", res["total_obs"])
    finally:
        conn.close()
