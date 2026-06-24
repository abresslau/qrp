"""Dagster entrypoint for the QRP lineage code location.

Launch with::

    uv run dagster dev -m lineage.definitions -p 3333

The in-process executor is used deliberately: it sidesteps the Windows spawn/fork
multiprocessing path and the SQLite "database is locked" contention (see the data-manager
research), keeping local self-hosted runs robust on a single Windows box.
"""

from __future__ import annotations

from dagster import Definitions, in_process_executor

from .assets import all_assets
from .bucket_jobs import BUCKET_JOBS
from .schedules import (
    commodities_daily,
    commodities_job,
    eod_daily,
    eod_job,
    rates_curve_daily,
    rates_curve_job,
    rates_world_daily,
    rates_world_job,
    sym_eod_daily,
    sym_eod_job,
)

defs = Definitions(
    assets=all_assets(),
    # `eod` runs the whole nightly refresh in one trigger; the per-asset pipeline jobs (sym_eod /
    # rates / commodities) remain for granular runs, PLUS the nine config-driven bucket jobs (fx,
    # equity_prices, index_levels, rates, fundamental, alt_data, macro, universe, calculations).
    jobs=[eod_job, sym_eod_job, rates_curve_job, rates_world_job, commodities_job, *BUCKET_JOBS],
    schedules=[eod_daily, sym_eod_daily, rates_curve_daily, rates_world_daily, commodities_daily],
    executor=in_process_executor,
)
