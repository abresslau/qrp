"""Example Prefect flow for the sym EOD pipeline (copy into your Prefect project).

Each task shells out to `sym eod --steps <step>`. sym has no Prefect dependency.
"""
from __future__ import annotations

# import subprocess
# from prefect import flow, task
#
# SYM = ["uv", "run", "--project", "/opt/sym", "sym"]
#
# @task(retries=2)
# def step(name: str) -> None:
#     subprocess.run([*SYM, "eod", "--steps", name], check=True)
#
# @flow(name="sym-eod")
# def sym_eod() -> None:
#     m = step.submit("monitor")
#     d = step.submit("fill", wait_for=[m])
#     mp = step.submit("map", wait_for=[d])
#     b = step.submit("indices", wait_for=[mp])
#     x = step.submit("fx", wait_for=[b])
#     r = step.submit("recompute", wait_for=[x])
#     step.submit("validate", wait_for=[r])
#
# if __name__ == "__main__":
#     sym_eod()
