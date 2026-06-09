"""Example Airflow DAG for the sym EOD pipeline (copy into your Airflow project).

Each task shells out to `sym eod --steps <step>` so retries/observability are
per-step. sym itself has no Airflow dependency — this wrapper is the only coupling.
"""
from __future__ import annotations

# from airflow import DAG
# from airflow.operators.bash import BashOperator
# import pendulum
#
# SYM = "uv run --project /opt/sym sym"  # or the installed `sym` entrypoint
#
# with DAG(
#     dag_id="sym_eod",
#     schedule="30 22 * * 1-5",          # weekday evening, after closes
#     start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
#     catchup=False,
#     default_args={"retries": 2},
# ) as dag:
#     monitor    = BashOperator(task_id="monitor",    bash_command=f"{SYM} eod --steps monitor")
#     fill       = BashOperator(task_id="fill",       bash_command=f"{SYM} eod --steps fill")
#     benchmarks = BashOperator(task_id="benchmarks", bash_command=f"{SYM} eod --steps benchmarks")
#     recompute  = BashOperator(task_id="recompute",  bash_command=f"{SYM} eod --steps recompute")
#     validate   = BashOperator(task_id="validate",   bash_command=f"{SYM} eod --steps validate")
#     monitor >> fill >> benchmarks >> recompute >> validate
