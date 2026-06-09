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

defs = Definitions(assets=all_assets(), executor=in_process_executor)
