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
    eod_daily,
    eod_job,
)

defs = Definitions(
    assets=all_assets(),
    # `eod` runs the whole nightly refresh in one trigger, PLUS the config-driven bucket jobs for
    # granular ad-hoc runs (fx_load, equity_load, index_load, rates_load [UK + world, unified],
    # commodity_load, fundamental_load, alt_data_load, macro_load, universe_load, calculations).
    # Commodity has NO separate job/schedule — it's an `eod` node + a generated `commodity_load`
    # bucket job like every other bucket. (The sym-only `sym_eod` job was retired similarly.)
    jobs=[eod_job, *BUCKET_JOBS],
    schedules=[eod_daily],
    executor=in_process_executor,
)
