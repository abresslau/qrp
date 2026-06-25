"""equity — raw equity prices, corporate-action factors, and the reproducible returns engine.

A standalone peer package with its own `equity` Postgres database (DB-per-package topology). It
imports nothing from `sym`; identity/calendar reads are done through an injected read-only sym
connection. `sym` depends on `equity` (its cli/eod/indices orchestrate the engine), never the reverse.
"""
