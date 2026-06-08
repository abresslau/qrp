# sym

Global Equity Security Master + Market Data + Returns warehouse. Module 1 of a
personal quant research warehouse.

`sym` stores a FIGI-keyed security master, raw daily OHLCV plus explicit
corporate-action factors, and a derived 18-window price/total-return matrix
(FactSet EXDATE_C methodology). The query surface is DBeaver; there is no UI.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (manages Python 3.13)
- PostgreSQL 18.4 (native Windows install)
- [Sqitch](https://sqitch.org/) for migrations (`pg` engine)

## Setup

```powershell
uv sync                      # create the venv and install dependencies
copy .env.example .env       # then edit .env with your DB connection
uv run sym --help
uv run sym check-db          # verify the connection resolved from config
```

## Layout

```
src/sym/          package (identity, sources, ingest, calendar, returns, classification)
migrations/       Sqitch plain-SQL migrations (top_dir; sqitch.conf at repo root)
benchmark/        the ~50-name adversarial seed universe (fixtures = SM-6 set = MVP)
tests/            pytest suite
_bmad-output/planning-artifacts/  PRD, architecture, epics & stories (BMad outputs)
```

## Database migrations

```powershell
$env:SQITCH_TARGET = "db:pg://postgres@localhost:5432/sym"
sqitch deploy
sqitch verify
sqitch revert
```
