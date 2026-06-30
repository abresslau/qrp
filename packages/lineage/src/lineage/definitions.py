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
    commodity_daily,
    commodity_job,
    eod_daily,
    eod_job,
    sym_eod_daily,
    sym_eod_job,
)

defs = Definitions(
    assets=all_assets(),
    # `eod` runs the whole nightly refresh in one trigger; sym_eod / commodity remain as standalone
    # pipelines, PLUS the nine config-driven bucket jobs (fx_load, equity_load, index_load, rates_load
    # [UK + world, unified], fundamental_load, alt_data_load, macro_load, universe_load, calculations).
    jobs=[eod_job, sym_eod_job, commodity_job, *BUCKET_JOBS],
    schedules=[eod_daily, sym_eod_daily, commodity_daily],
    executor=in_process_executor,
)
