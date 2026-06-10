"""Macro ingest: fetch the configured public series and upsert into the `macro` schema.

Idempotent (observations upserted on (series_id, obs_date)). Run via
``python -m macro.ingest`` or the gateway's refresh().
"""

from __future__ import annotations

import psycopg

from macro.db import connect
from macro.sources import fetch_ecb, fetch_worldbank

# World Bank annual indicators × countries (US, Brazil, Euro area, UK, Japan).
_WB = [
    ("FP.CPI.TOTL.ZG", "CPI inflation (YoY)", "% per year", ["US", "BRA", "EMU", "GBR", "JPN"]),
    ("NY.GDP.MKTP.KD.ZG", "Real GDP growth", "% per year", ["US", "BRA", "EMU"]),
    ("FR.INR.RINR", "Real interest rate", "%", ["US", "BRA"]),
    ("SL.UEM.TOTL.ZS", "Unemployment rate", "% of labour force", ["US", "BRA", "EMU"]),
]

# ECB Data Portal series (monthly to keep observations lean).
_ECB = [
    (
        "FM/D.U2.EUR.4F.KR.MRR_FR.LEV",  # daily feed; fetcher compresses to change-points
        "ECB:MRR",
        "ECB main refinancing rate",
        "%",
        "daily",
    ),
]


def _upsert(conn: psycopg.Connection, meta: dict, obs: list) -> int:
    if not obs:
        return 0  # never store an empty series (honest: a no-data series is omitted, not faked)
    conn.execute(
        """
        INSERT INTO macro.series (series_id, source, name, geo, unit, frequency, updated_at)
        VALUES (%(series_id)s, %(source)s, %(name)s, %(geo)s, %(unit)s, %(frequency)s, now())
        ON CONFLICT (series_id) DO UPDATE SET
            name = EXCLUDED.name, geo = EXCLUDED.geo, unit = EXCLUDED.unit,
            frequency = EXCLUDED.frequency, updated_at = now()
        """,
        meta,
    )
    n = 0
    for d, v in obs:
        conn.execute(
            "INSERT INTO macro.observation (series_id, obs_date, value) VALUES (%s, %s, %s) "
            "ON CONFLICT (series_id, obs_date) DO UPDATE SET value = EXCLUDED.value",
            (meta["series_id"], d, v),
        )
        n += 1
    return n


def run_ingest(conn: psycopg.Connection) -> dict:
    """Fetch + upsert all configured series. Returns a per-series summary (never fabricates)."""
    conn.autocommit = True
    summary: list[dict] = []
    for indicator, name, unit, geos in _WB:
        # One fetch per geo so a single failing country doesn't skip the indicator's
        # remaining geos (and the failure is attributed to the right series).
        for geo in geos:
            try:
                for meta, obs in fetch_worldbank(indicator, name, unit, [geo]):
                    n = _upsert(conn, meta, obs)
                    summary.append({"series_id": meta["series_id"], "obs": n, "ok": True})
            except Exception as exc:  # noqa: BLE001
                summary.append({"series_id": f"WB:{indicator}:{geo}", "obs": 0, "ok": False,
                                "error": str(exc)[:160]})
    for key, sid, name, unit, freq in _ECB:
        try:
            meta, obs = fetch_ecb(key, sid, name, unit, freq)
            n = _upsert(conn, meta, obs)
            summary.append({"series_id": sid, "obs": n, "ok": True})
        except Exception as exc:  # noqa: BLE001
            summary.append({"series_id": sid, "obs": 0, "ok": False, "error": str(exc)[:160]})
    # Drop any catalog rows left without observations (e.g. a source with no data for a geo).
    conn.execute(
        "DELETE FROM macro.series s "
        "WHERE NOT EXISTS (SELECT 1 FROM macro.observation o WHERE o.series_id = s.series_id)"
    )
    return {"series": summary, "total_obs": sum(s["obs"] for s in summary)}


if __name__ == "__main__":
    conn = connect()  # macro owns its own database (DSN resolved by macro.config)
    try:
        result = run_ingest(conn)
        for s in result["series"]:
            print(s)
        print("total observations:", result["total_obs"])
    finally:
        conn.close()
