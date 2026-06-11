"""Macro ingest: fetch the configured public series and upsert into the `macro` schema.

Idempotent (observations upserted on (series_id, obs_date)). Sources: World Bank, ECB,
US Treasury FiscalData, OECD, Eurostat — each series source-attributed; a no-data series
is omitted, never faked. Run via ``python -m macro.ingest`` or the gateway's refresh().
"""

from __future__ import annotations

import psycopg

from macro.db import connect
from macro.sources import (
    fetch_ecb,
    fetch_eurostat,
    fetch_fiscaldata_avg_rates,
    fetch_fiscaldata_debt,
    fetch_oecd_cpi,
    fetch_worldbank,
)

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

# OECD CPI YoY (monthly) per REF_AREA. An area the flow doesn't serve yields an empty
# series and is omitted by the no-data rule.
_OECD_CPI_GEOS = ["USA", "GBR", "JPN", "BRA"]

# Eurostat datasets, every non-time dimension pinned (the fetcher asserts the shape).
# une_rt_m serves no euro-area aggregate (EA/EA19/EA20 all empty, probed 2026-06-11) —
# EU27_2020 is the configured aggregate instead.
_EUROSTAT = [
    (
        "prc_hicp_manr",
        {"geo": "EA", "coicop": "CP00", "unit": "RCH_A"},
        "EU:HICP:EA",
        "HICP inflation (YoY, monthly)",
        "% per year",
    ),
    (
        "une_rt_m",
        {"geo": "EU27_2020", "s_adj": "SA", "age": "TOTAL", "sex": "T", "unit": "PC_ACT"},
        "EU:UNEMP:EU27",
        "Unemployment rate (monthly)",
        "% of labour force",
    ),
]


def _upsert(conn: psycopg.Connection, meta: dict, obs: list) -> tuple[int, int]:
    """Upsert one series + observations; returns ``(n_obs, n_restated)``.

    ``n_obs`` counts the observations processed (present after the call); ``n_restated``
    counts ONLY existing rows whose value actually changed — those get a fresh
    ``last_changed_at``; equal-value re-ingests leave the row untouched.

    Same-date duplicates within one fetch are collapsed FIRST (last wins, post-sort) —
    otherwise the second row would hit ON CONFLICT against its own sibling and count as
    a vendor restatement that never happened.
    """
    if not obs:
        return 0, 0  # never store an empty series (honest: a no-data series is omitted, not faked)
    obs = list(dict(obs).items())  # collapse same-date duplicates (dict keyed by date)
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
    n = restated = 0
    for d, v in obs:
        cur = conn.execute(
            """
            INSERT INTO macro.observation AS o (series_id, obs_date, value)
            VALUES (%s, %s, %s)
            ON CONFLICT (series_id, obs_date) DO UPDATE
                SET value = EXCLUDED.value, last_changed_at = now()
                WHERE o.value IS DISTINCT FROM EXCLUDED.value
            RETURNING (xmax <> 0) AS was_update
            """,
            (meta["series_id"], d, v),
        )
        row = cur.fetchone()
        # row is None when the conflict row was identical (DO UPDATE's WHERE filtered it
        # out — nothing written); (True,) when an existing value was changed (restatement).
        if row is not None and row[0]:
            restated += 1
        n += 1
    return n, restated


def run_ingest(conn: psycopg.Connection) -> dict:
    """Fetch + upsert all configured series. Returns a per-series summary (never fabricates)."""
    conn.autocommit = True
    summary: list[dict] = []

    def _record(series_id: str, fetched: tuple[dict, list]) -> None:
        meta, obs = fetched
        n, restated = _upsert(conn, meta, obs)
        summary.append({"series_id": series_id, "obs": n, "restated": restated, "ok": True})

    def _failed(series_id: str, exc: Exception) -> None:
        summary.append(
            {"series_id": series_id, "obs": 0, "restated": 0, "ok": False,
             "error": str(exc)[:160]}
        )

    for indicator, name, unit, geos in _WB:
        # One fetch per geo so a single failing country doesn't skip the indicator's
        # remaining geos (and the failure is attributed to the right series).
        for geo in geos:
            try:
                for meta, obs in fetch_worldbank(indicator, name, unit, [geo]):
                    _record(meta["series_id"], (meta, obs))
            except Exception as exc:  # noqa: BLE001
                _failed(f"WB:{indicator}:{geo}", exc)
    for key, sid, name, unit, freq in _ECB:
        try:
            _record(sid, fetch_ecb(key, sid, name, unit, freq))
        except Exception as exc:  # noqa: BLE001
            _failed(sid, exc)
    try:
        _record("UST:DEBT", fetch_fiscaldata_debt())
    except Exception as exc:  # noqa: BLE001
        _failed("UST:DEBT", exc)
    try:
        rate_series = fetch_fiscaldata_avg_rates()
    except Exception as exc:  # noqa: BLE001
        # ONE fetch serves all three series — only the shared HTTP call gets the
        # wildcard id; upsert failures are attributed per series below.
        _failed("UST:AVG_RATE:*", exc)
    else:
        for meta, obs in rate_series:
            try:
                _record(meta["series_id"], (meta, obs))
            except Exception as exc:  # noqa: BLE001
                _failed(meta["series_id"], exc)
    for geo in _OECD_CPI_GEOS:
        try:
            _record(f"OECD:CPI:{geo}", fetch_oecd_cpi(geo))
        except Exception as exc:  # noqa: BLE001
            _failed(f"OECD:CPI:{geo}", exc)
    for code, filters, sid, name, unit in _EUROSTAT:
        try:
            _record(sid, fetch_eurostat(code, filters, sid, name, unit))
        except Exception as exc:  # noqa: BLE001
            _failed(sid, exc)

    # Drop any catalog rows left without observations (e.g. a source with no data for a geo).
    conn.execute(
        "DELETE FROM macro.series s "
        "WHERE NOT EXISTS (SELECT 1 FROM macro.observation o WHERE o.series_id = s.series_id)"
    )
    return {
        "series": summary,
        "total_obs": sum(s["obs"] for s in summary),
        "total_restated": sum(s["restated"] for s in summary),
    }


if __name__ == "__main__":
    conn = connect()  # macro owns its own database (DSN resolved by macro.config)
    try:
        result = run_ingest(conn)
        for s in result["series"]:
            print(s)
        print("total observations:", result["total_obs"], "| restated:", result["total_restated"])
    finally:
        conn.close()
