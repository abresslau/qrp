# Orchestration (scheduler-agnostic)

sym carries **no** Airflow/Prefect dependency. It exposes the daily work as
idempotent steps (`sym eod --steps <step>`, or the individual `sym <cmd>`s) and a
coarse runner (`sym eod`). An external scheduler composes them. These files are
**examples** — copy into your Airflow/Prefect project; they only shell out to the
`sym` CLI, so switching orchestrators is a wrapper swap.

Daily core (order): `monitor -> fill -> map -> indices -> fx -> recompute -> validate`.
Periodic (own schedules): `sym fundamentals --all` (weekly), `sym snapshot-calendar` (occasional).

- Coarse cron: `uv run sym eod`
- Fine-grained (per-task retries/observability): one task per step, `uv run sym eod --steps <step>`
