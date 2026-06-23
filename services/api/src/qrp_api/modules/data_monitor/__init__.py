"""Data Monitor — the data/ETL observability area (freshness + runs per pipeline bucket).

Frontend-plus-thin-backend area: a single aggregating endpoint (``GET /api/data-monitor/eod``)
reports each pipeline bucket's expected-vs-actual business date and, best-effort, its latest
Dagster run. Read-only across the package databases; never writes.
"""
