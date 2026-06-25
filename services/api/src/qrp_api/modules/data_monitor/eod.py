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

from datetime import date, datetime, timedelta

import psycopg
from lineage.buckets import BUCKETS, SYM, Bucket, Dataset, job_name

from qrp_api.config import dagster_job_url, dagster_ui_base, package_dsn
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
        today, from the AUTHORITATIVE ``trading_calendar`` (sym), NOT the price data.

        Deriving "expected" from ``max(prices_raw.session_date)`` is circular: if the latest session
        simply wasn't LOADED, the proxy slides back to the last loaded day and the board can no
        longer flag the missing load — defeating the monitor's whole purpose. The calendar knows the
        session happened regardless of whether data landed, so a not-yet-loaded latest session shows
        up honestly as a behind-by-one (or more) bucket. The current calendar version already encodes
        weekends + holidays; max() over all current-calendar MICs is the last weekday markets traded."""
        return _as_date(self._scalar(
            self._sym,
            "SELECT max(tc.session_date) FROM trading_calendar tc "
            "JOIN trading_calendar_version v USING (calendar_version) "
            "WHERE v.is_current AND tc.session_date < CURRENT_DATE",
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

    def _calc_coverage(
        self, conn: psycopg.Connection, ds: Dataset
    ) -> tuple[date | None, str | None]:
        """fact_returns recency, PARTIAL-AWARE but without the coverage-session scan. A full
        broadly-complete scan over fact_returns (28 windows × figis × dates) is the documented
        count(DISTINCT) perf trap, so we use a cheap two-day check instead: if the latest as_of_date
        carries far fewer names than the prior day, it's a partial recompute (e.g. the European
        indexes priced/returned ahead of the US close) — fall back to the prior broadly-complete day
        so the bucket reports honestly stale instead of flashing green on a slice. Three single-day,
        date-indexed reads (max, count@latest, count@prev) — never a full-table aggregate."""
        latest = self._max_date(conn, ds)
        if latest is None:
            return None, None
        n_latest = self._scalar(
            conn,
            f"SELECT count(DISTINCT composite_figi) FROM {ds.table} WHERE {ds.date_column} = %s",
            (latest,),
        )
        prev = _as_date(self._scalar(
            conn,
            f"SELECT max({ds.date_column}) FROM {ds.table} WHERE {ds.date_column} < %s",
            (latest,),
        ))
        note = f"{n_latest} names at {latest.isoformat()}"
        if prev is not None and n_latest:
            n_prev = self._scalar(
                conn,
                f"SELECT count(DISTINCT composite_figi) FROM {ds.table} WHERE {ds.date_column} = %s",
                (prev,),
            )
            if n_prev and n_latest < COVERAGE_FRACTION * n_prev:
                # latest is a partial slice — the broadly-complete day is `prev`
                return prev, note + f"; partial vs {n_prev} on {prev.isoformat()} — using {prev.isoformat()}"
        return latest, note

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
                "detail": None,
            }
            for g, d in sorted(groups, key=lambda gd: gd[1])
        ]
        return worst, note, subgroups

    # -- per-bucket breakdowns (informational sub-rows; don't change the bucket status) -----

    def _subgroup(self, group: str, d: date | None, expected: date | None, detail: str | None) -> dict:
        return {
            "group": group,
            "as_of_date": d.isoformat() if d else None,
            "days_behind": max(0, (expected - d).days) if (expected and d) else None,
            "detail": detail,
        }

    def _equity_universe_breakdown(self, conn, expected: date | None) -> list[dict]:
        """Per-universe price freshness: the latest session each universe is broadly priced
        (>= COVERAGE_FRACTION of its CURRENT members), so a single lagging universe is visible.

        Cross-DB roster-fetch: the current-member roster comes from the universe DB; the per-session
        priced counts come from sym's prices_raw filtered by the roster (no cross-DB join)."""
        from collections import defaultdict

        from universe.db import connect as u_connect

        with u_connect() as u:
            roster = u.execute(
                "SELECT universe_id, composite_figi FROM universe_membership WHERE valid_to IS NULL"
            ).fetchall()
        total_by_u: dict[str, int] = defaultdict(int)
        figi_universes: dict[str, list[str]] = defaultdict(list)
        for uid, figi in roster:
            total_by_u[uid] += 1
            figi_universes[figi].append(uid)
        figis = list(figi_universes)
        latest = self._scalar(conn, "SELECT max(session_date) FROM prices_raw")
        cov: dict[str, dict[date, set]] = defaultdict(lambda: defaultdict(set))
        if figis and latest is not None:
            for figi, sd in conn.execute(
                "SELECT composite_figi, session_date FROM prices_raw "
                "WHERE composite_figi = ANY(%s) AND session_date >= %s - %s",
                (figis, latest, COVERAGE_WINDOW_DAYS),
            ).fetchall():
                for uid in figi_universes[figi]:
                    cov[uid][sd].add(figi)
        out: list[dict] = []
        for uid in sorted(total_by_u):
            total = total_by_u[uid]
            covered = None
            for sd, figset in cov.get(uid, {}).items():
                if len(figset) >= COVERAGE_FRACTION * total and (covered is None or sd > covered):
                    covered = sd
            out.append(self._subgroup(uid, covered, expected, f"{total} names"))
        return out

    def _index_breakdown(self, conn, expected: date | None) -> list[dict]:
        """Per-index latest level date (one row per index instrument by name).

        Cross-DB: the level dates live in the indices DB (``conn`` — the bucket's package conn); the
        index names live in sym (``self._sym``). Roster-fetch the latest date per sym_id, resolve
        names from sym, merge in Python (no cross-DB join)."""
        latest = dict(
            conn.execute("SELECT sym_id, max(session_date) FROM index_levels GROUP BY sym_id").fetchall()
        )
        if not latest:
            return []
        names = dict(
            self._sym.execute(
                "SELECT sym_id, name FROM instrument WHERE sym_id = ANY(%s)", (list(latest),)
            ).fetchall()
        )
        rows = sorted(
            ((names.get(sid) or "(unnamed)", d) for sid, d in latest.items()), key=lambda t: t[0]
        )
        return [self._subgroup(name, _as_date(d), expected, None) for name, d in rows]

    def _universe_breakdown(self, conn) -> list[dict]:
        """Per-universe membership: current member count + last membership-event date. Informational
        (event-log; ``days_behind`` is left null — a universe with no recent change is not 'stale').

        Membership lives in the universe DB now — read it there (``conn`` is ignored)."""
        from universe.db import connect as u_connect

        with u_connect() as u:
            rows = u.execute(
                """
                SELECT u.universe_id,
                       (SELECT count(*) FROM universe_membership m
                         WHERE m.universe_id = u.universe_id AND m.valid_to IS NULL) AS members,
                       (SELECT max(recorded_at) FROM membership_event e
                         WHERE e.universe_id = u.universe_id) AS last_event
                  FROM universe u ORDER BY u.universe_id
                """
            ).fetchall()
        out = []
        for uid, members, last_event in rows:
            d = _as_date(last_event)
            out.append({
                "group": uid,
                "as_of_date": d.isoformat() if d else None,
                "days_behind": None,  # event-log: no-change ≠ stale
                "detail": f"{members} members",
            })
        return out

    # -- instrument count (distinct entities at the latest day) ----------------------------

    def _instrument_count(self, conn: psycopg.Connection, b: Bucket, ds: Dataset) -> int | None:
        """Distinct entities active in the TRAILING WINDOW — not a single day: lagged/slow series
        (per-country rates curves, monthly macro series) don't all print on the very latest date, so a
        single-day count understates the universe (rates would read "1 curve"). The window is bounded
        and date-indexed — cheaper than the coverage-session GROUP BY, and NEVER a full-table
        count(DISTINCT) (the `calculations` bucket carries no id_column for exactly that reason —
        fact_returns is 28 windows × figis × dates). Rates has no single id_column (a "curve" is a
        composite key), so it is counted specially. None when the dataset has no count basis."""
        latest = self._max_date(conn, ds)
        if latest is None:
            return None
        if ds.id_column:
            sql = (f"SELECT count(DISTINCT {ds.id_column}) FROM {ds.table} "
                   f"WHERE {ds.date_column} >= %s")
        elif b.key == "rates":
            sql = (f"SELECT count(DISTINCT (country, curve_set, basis, rate_type)) FROM {ds.table} "
                   f"WHERE {ds.date_column} >= %s")
        else:
            return None
        n = self._scalar(conn, sql, (latest - timedelta(days=COVERAGE_WINDOW_DAYS),))
        return int(n) if n is not None else None

    # -- per-bucket row --------------------------------------------------------------------

    def _row(self, b: Bucket, latest_session: date | None, runs: dict[str, dict]) -> dict:
        ds = b.datasets[0]  # one representative dataset per bucket (v1)
        actual: date | None = None
        coverage: str | None = None
        subgroups: list[dict] = []
        instrument_count: int | None = None
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
                elif b.key == "calculations":
                    actual, coverage = self._calc_coverage(conn, ds)
                else:
                    actual = self._max_date(conn, ds)
                # Per-subcategory breakdowns (informational sub-rows; the bucket's headline status
                # is unchanged). rates already produced its per-country subgroups via _grouped.
                if b.key == "equity_prices":
                    subgroups = self._equity_universe_breakdown(conn, latest_session)
                elif b.key == "index_levels":
                    subgroups = self._index_breakdown(conn, latest_session)
                elif b.key == "universe":
                    subgroups = self._universe_breakdown(conn)
                instrument_count = self._instrument_count(conn, b, ds)
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
            "instrument_count": instrument_count,
            "instrument_label": ds.count_label,
            "error": error,
            "subgroups": subgroups,
            # Dagster keys runs + the job URL by the JOB name (mnemonic), not the bucket key.
            "last_run": runs.get(job_name(b.key)),
            "dagster_url": dagster_job_url(job_name(b.key)),
            "run_subcategories": list(b.run_options),
        }

    # -- summary header (migrated from the former sym Overview) ----------------------------

    def _summary(self, latest_session: date | None) -> dict:
        c = self._sym
        securities = self._scalar(c, "SELECT count(*) FROM securities")
        from universe.db import connect as u_connect

        with u_connect() as u:  # the universe registry lives in the universe DB now
            universes = self._scalar(u, "SELECT count(*) FROM universe")
        # prices_raw + pipeline_run_log live in the equity DB now (priced = securities with any
        # price = distinct figis in prices_raw, since composite_figi -> securities). Open equity
        # read-only for both.
        with psycopg.connect(package_dsn("equity"), connect_timeout=5) as eq:
            priced = self._scalar(eq, "SELECT count(DISTINCT composite_figi) FROM prices_raw")
            row = eq.execute(
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
            # prices_raw lives in the equity DB now — read the true latest session there (NOT on the
            # shared sym conn: a failing query would poison it for the summary + every sym bucket).
            with psycopg.connect(package_dsn("equity"), connect_timeout=5) as eq:
                true_latest = self._max_date(
                    eq, Dataset("equity", "prices_raw", "session_date", "equity.prices_raw")
                )
        except Exception:  # noqa: BLE001
            true_latest = None
        dagster_reachable, runs = latest_runs_by_job()
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
            "dagster_runs_available": dagster_reachable,
            "dagster": {
                "reachable": dagster_reachable,
                "ui_url": dagster_ui_base(),
                # how many bucket jobs Dagster reported a run for (health signal beyond "daemon up").
                "jobs_with_runs": sum(1 for r in runs.values() if r),
            },
            "summary": summary,
            "buckets": [self._row(b, expected, runs) for b in BUCKETS],
        }
