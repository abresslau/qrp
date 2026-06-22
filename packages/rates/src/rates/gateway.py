"""DB gateway for the rates module (reads the QRP-managed `rates` schema)."""

from __future__ import annotations

from datetime import date

import psycopg


class DbRatesGateway:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def curve_sets(self) -> list[dict]:
        """Available (curve_set, basis, rate_type) series with their day/node coverage."""
        rows = self._conn.execute(
            """
            SELECT curve_set, basis, rate_type, count(DISTINCT as_of_date) AS days,
                   min(as_of_date) AS first, max(as_of_date) AS last
              FROM rates.curve_point
             GROUP BY curve_set, basis, rate_type
             ORDER BY curve_set, basis, rate_type
            """
        ).fetchall()
        return [
            {
                "curve_set": r[0], "basis": r[1], "rate_type": r[2], "days": r[3],
                "start_date": r[4].isoformat() if r[4] else None,
                "end_date": r[5].isoformat() if r[5] else None,
            }
            for r in rows
        ]

    def curve(
        self,
        curve_set: str = "glc",
        basis: str = "nominal",
        rate_type: str = "spot",
        as_of_date: date | None = None,
        *,
        vintage: str = "latest",
    ) -> dict:
        """The curve grid for one (curve_set, basis, rate_type) as-of a date (<= as_of_date; latest
        if None). ``vintage='first'`` returns the immutable first-published values (PIT)."""
        anchor = self._conn.execute(
            """
            SELECT max(as_of_date) FROM rates.curve_point
             WHERE curve_set=%s AND basis=%s AND rate_type=%s
               AND (%s::date IS NULL OR as_of_date <= %s::date)
            """,
            (curve_set, basis, rate_type, as_of_date, as_of_date),
        ).fetchone()
        anchored = anchor[0] if anchor else None
        if anchored is None:
            return {
                "curve_set": curve_set, "basis": basis, "rate_type": rate_type,
                "vintage": vintage, "as_of_date": None, "points": [],
            }
        value_col = "first_value" if vintage == "first" else "value"
        rows = self._conn.execute(
            f"""
            SELECT tenor, {value_col}, first_published_at, last_changed_at
              FROM rates.curve_point
             WHERE curve_set=%s AND basis=%s AND rate_type=%s AND as_of_date=%s
             ORDER BY tenor
            """,
            (curve_set, basis, rate_type, anchored),
        ).fetchall()
        return {
            "curve_set": curve_set, "basis": basis, "rate_type": rate_type, "vintage": vintage,
            "as_of_date": anchored.isoformat(),
            "points": [{"tenor": float(t), "value": float(v)} for t, v, _, _ in rows],
        }
