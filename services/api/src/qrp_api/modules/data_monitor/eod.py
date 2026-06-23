"""EOD data-freshness gateway — per-bucket expected-vs-actual business date + latest run.

Reads each bucket's representative dataset (from the shared ``lineage.buckets`` taxonomy) on the
owning package's database, READ-ONLY, and classifies recency against the platform's latest equity
trading session (QRP's honest "current business day" proxy — sym owns the calendar; this is the
same proxy the former sym Overview used). Resilient by construction: a dataset that can't be read
(missing DB/table) degrades that one row to ``unknown`` and never 500s the endpoint. The wide
cross-sectional tables (prices, returns) use the broadly-complete *coverage session* so one fresh
sub-universe can't mask a stale rest (the documented max-masks-laggards trap); the rates bucket is
broken down per country with the worst-lagging country surfaced.
"""

from __future__ import annotations

from datetime import date, datetime

import psycopg
from lineage.buckets import BUCKETS, SYM, Bucket, Dataset

from qrp_api.config import package_dsn
from qrp_api.modules.data_monitor.dagster_runs import latest_runs_by_job
from qrp_api.modules.sym.freshness import classify

COVERAGE_FRACTION = 0.9  # "broadly complete" = >= 90% of the fullest day in the trailing window
COVERAGE_WINDOW_DAYS = 90


def _as_date(v: object) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else None


class EodMonitorGateway:
    def __init__(self, sym_conn: psycopg.Connection) -> None:
        self._sym = sym_conn  # sym DB (full read surface, read-only by convention)

    # -- low-level reads -------------------------------------------------------------------

    def _scalar(self, conn: psycopg.Connection, sql: str, params: tuple = ()) -> object:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else None

    def _max_date(self, conn: psycopg.Connection, ds: Dataset) -> date | None:
        # Table/column come from our own constant taxonomy, never user input — safe to interpolate.
        return _as_date(self._scalar(conn, f"SELECT max({ds.date_column}) FROM {ds.table}"))

    def _expected_business_date(self) -> date | None:
        """The PREVIOUS business date — the last completed equity trading session STRICTLY before
        today. This is the EOD bar: after the close you expect data through the prior session, not
        today's in-progress one. Using the trading-session calendar (prices_raw) skips weekends and
        holidays for free."""
        return _as_date(self._scalar(
            self._sym,
            "SELECT max(session_date) FROM prices_raw WHERE session_date < CURRENT_DATE",
        ))

    def _coverage_session(
        self, conn: psycopg.Connection, ds: Dataset
    ) -> tuple[date | None, str | None]:
        """Latest date at which the wide table is broadly complete (>= COVERAGE_FRACTION of the
        fullest day in the trailing window), plus a "n_at_latest/n_at_coverage" note. Avoids the
        max-is-fresh-masks-the-laggards trap for prices/returns."""
        latest = self._max_date(conn, ds)
        if latest is None:
            return None, None
        cov = _as_date(
            self._scalar(
                conn,
                f"""
                WITH per_day AS (
                    SELECT {ds.date_column} AS d, count(DISTINCT {ds.id_column}) AS n
                      FROM {ds.table}
                     WHERE {ds.date_column} >= (SELECT max({ds.date_column}) FROM {ds.table})
                                                - {COVERAGE_WINDOW_DAYS}
                     GROUP BY {ds.date_column}
                )
                SELECT max(d) FROM per_day
                 WHERE n >= {COVERAGE_FRACTION} * (SELECT max(n) FROM per_day)
                """,
            )
        )
        n_latest = self._scalar(
            conn,
            f"SELECT count(DISTINCT {ds.id_column}) FROM {ds.table} WHERE {ds.date_column} = %s",
            (latest,),
        )
        note = f"{n_latest} entities at {latest.isoformat()}"
        if cov and cov != latest:
            note += f"; broadly complete through {cov.isoformat()}"
        return (cov or latest), note

    def _grouped(
        self, conn: psycopg.Connection, ds: Dataset, latest_session: date | None
    ) -> tuple[date | None, str | None, list[dict]]:
        """Per-group (e.g. per-country) latest date; the bucket's actual = the WORST-lagging group
        so the status flags when ANY group is behind. Returns (worst_date, note, subgroups)."""
        rows = conn.execute(
            f"SELECT {ds.group_column}, max({ds.date_column}) "
            f"FROM {ds.table} GROUP BY {ds.group_column} ORDER BY {ds.group_column}"
        ).fetchall()
        if not rows:
            return None, None, []
        groups = [(g, _as_date(d)) for g, d in rows if _as_date(d) is not None]
        if not groups:
            return None, None, []
        newest = max(d for _, d in groups)
        worst = min(d for _, d in groups)
        n_current = sum(1 for _, d in groups if d == newest)
        laggard = min(groups, key=lambda gd: gd[1])
        note = f"{n_current}/{len(groups)} current"
        if worst != newest:
            note += f"; {laggard[0]} {(newest - worst).days}d behind"
        subgroups = [
            {
                "group": g,
                "as_of_date": d.isoformat(),
                # clamp at 0: a rates curve can be NEWER than the latest equity session (independent
                # series), which would otherwise render a negative "days behind".
                "days_behind": max(0, (latest_session - d).days) if latest_session else None,
            }
            for g, d in sorted(groups, key=lambda gd: gd[1])
        ]
        return worst, note, subgroups

    # -- per-bucket row --------------------------------------------------------------------

    def _row(self, b: Bucket, latest_session: date | None, runs: dict[str, dict]) -> dict:
        ds = b.datasets[0]  # one representative dataset per bucket (v1)
        actual: date | None = None
        coverage: str | None = None
        subgroups: list[dict] = []
        error: str | None = None
        try:
            owns_conn = ds.package != SYM
            conn = (
                psycopg.connect(package_dsn(ds.package), connect_timeout=5)
                if owns_conn
                else self._sym
            )
            try:
                if ds.group_column:
                    actual, coverage, subgroups = self._grouped(conn, ds, latest_session)
                elif ds.wide:
                    actual, coverage = self._coverage_session(conn, ds)
                else:
                    actual = self._max_date(conn, ds)
            finally:
                if owns_conn:
                    conn.close()
        except Exception as exc:  # noqa: BLE001 — one unreadable dataset must not 500 the page
            error = type(exc).__name__

        fresh = classify(
            b.key, actual, latest_session, coverage=coverage, stale_after_days=b.stale_after_days
        )
        status = "unknown" if error else fresh.status
        return {
            "key": b.key,
            "label": b.label,
            "subcategory": b.subcategory,
            "datasets": [d.label for d in b.datasets],
            "cadence": b.cadence,
            "note": b.note,
            "actual_date": actual.isoformat() if actual else None,
            "expected_date": latest_session.isoformat() if latest_session else None,
            "days_behind": fresh.days_behind,
            "status": status,
            "coverage": coverage,
            "error": error,
            "subgroups": subgroups,
            "last_run": runs.get(b.key),
        }

    # -- summary header (migrated from the former sym Overview) ----------------------------

    def _summary(self, latest_session: date | None) -> dict:
        c = self._sym
        securities = self._scalar(c, "SELECT count(*) FROM securities")
        universes = self._scalar(c, "SELECT count(*) FROM universe")
        priced = self._scalar(
            c,
            "SELECT count(*) FROM securities s WHERE EXISTS "
            "(SELECT 1 FROM prices_raw p WHERE p.composite_figi = s.composite_figi)",
        )
        row = c.execute(
            "SELECT run_id, mode, status, started_at, finished_at, rows_written "
            "FROM pipeline_run_log ORDER BY started_at DESC NULLS LAST LIMIT 1"
        ).fetchone()
        last_run = (
            {
                "run_id": str(row[0]),
                "mode": row[1],
                "status": row[2],
                "started_at": row[3].isoformat() if row[3] else None,
                "finished_at": row[4].isoformat() if row[4] else None,
                "rows_written": row[5],
            }
            if row
            else None
        )
        return {
            "securities": securities,
            "universes": universes,
            "priced_securities": priced,
            "latest_session": latest_session.isoformat() if latest_session else None,
            "last_pipeline_run": last_run,
        }

    # -- entrypoint ------------------------------------------------------------------------

    def eod(self) -> dict:
        # "Never 500s the page": even the platform-level reads degrade to None rather than raising,
        # so a sym hiccup still returns a renderable board (each bucket row has its own try/except).
        # Freshness is judged against the EXPECTED (previous) business date; the summary still shows
        # the TRUE latest session in the warehouse (today's partial session, if any) for context.
        try:
            expected = self._expected_business_date()
        except Exception:  # noqa: BLE001 — resilience contract: degrade, don't 500
            expected = None
        try:
            true_latest = self._max_date(
                self._sym, Dataset(SYM, "prices_raw", "session_date", "sym.prices_raw")
            )
        except Exception:  # noqa: BLE001
            true_latest = None
        runs = latest_runs_by_job()
        try:
            summary = self._summary(true_latest)
        except Exception:  # noqa: BLE001
            summary = {
                "securities": None, "universes": None, "priced_securities": None,
                "latest_session": true_latest.isoformat() if true_latest else None,
                "last_pipeline_run": None,
            }
        return {
            "expected_date": expected.isoformat() if expected else None,
            "expected_basis": "previous business date (last completed equity trading session)",
            "dagster_runs_available": bool(runs),
            "summary": summary,
            "buckets": [self._row(b, expected, runs) for b in BUCKETS],
        }
