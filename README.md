# QRP — Quant Research Platform

A console + API composing QRP's standalone packages (sym, macro, signals, …). Owner-operated.
**sym** is a peer package (security master · prices · returns · FX) — a common read-only *upstream*,
not a hub; packages that need it read via stable views over a read-only connection, never mutating
another package's schema.
The platform name is config-driven — change `platform.toml` and the API title + console
follow. Planning artifacts live in the sym repo under
`_bmad-output/planning-artifacts/` (`prd-qrp-*`, `epics-qrp.md`, `architecture-qrp.md`).

## Layout

```
qrp/
├─ platform.toml          # brand + enabled-modules (single source of truth)
├─ apps/web/              # Next.js 16 + Tailwind v4 console (:3000)
├─ services/api/          # FastAPI (uv) — per-module routers over sym (:8001)
├─ packages/sym/          # sym package (folded in 2026-06-08) — a peer, not a hub
├─ sqitch.conf            # Sqitch config (project=qrp, engine=pg)
├─ db/                    # QRP's own schemas as Sqitch migrations (deploy/revert/verify)
└─ scripts/dev.mjs        # runs API + console together
```

## Database migrations (Sqitch)

QRP owns six schemas (`qrp`, `macro`, `signal`, `backtest`, `optimiser`, `altdata`) on the
**shared** Postgres alongside sym (AR-Q4: schema-per-module). They are managed as a Sqitch
project named **`qrp`** (`sqitch.conf` + `db/sqitch.plan` + `db/{deploy,revert,verify}/`),
distinct from sym's own `sym` project; the two histories coexist in one registry, keyed by
project name. QRP never mutates sym's schema — these migrations only create QRP-owned objects.

Deploy via the `sqitch/sqitch` Docker image (no local sqitch needed), targeting the sym DB:

```bash
# PowerShell — set the target (no password in the repo; use a pgpass file or inline it locally)
docker run --rm -v "${PWD}:/repo" -w /repo sqitch/sqitch \
  deploy --verify "db:pg://postgres@host.docker.internal:5432/sym"
```

The deploy scripts are idempotent (`CREATE … IF NOT EXISTS`), so this is safe against both a
blank database (full replay from zero) and the already-applied dev DB (no-op DDL + registry
baseline). `sqitch revert` / `sqitch status <target>` work as usual.

## Run it (dev)

Reads the same sym database as the sym CLI (`SYM_DB_*` / `SYM_DATABASE_URL`; see `.env.example`).
The API runs on **:8001**, the console on **:3000** (console proxies `/api/*` → :8001).

```bash
uv sync --all-packages   # the root is a VIRTUAL workspace — plain `uv sync` installs only the
                         # (empty) root + dev group and PRUNES member deps (uvicorn, dagster,
                         # yfinance, …). --all-packages installs every workspace member's deps.
npm install
npm run dev              # starts BOTH: API (:8001) + console (:3000)
```

Or run them separately:

```bash
npm run dev:api      # FastAPI on :8001  (no --reload — restart after API code changes)
npm run dev:web      # Next console on :3000
```

Orchestration (Dagster) is a **separate** service — `npm run dev` does NOT start it:

```bash
DAGSTER_HOME=C:/Projects/qrp/.dagster_home \
  uv run dagster dev -m lineage.definitions -h 127.0.0.1 -p 3333   # → http://127.0.0.1:3333
```

> Note: uvicorn `--reload` is unreliable on this Windows setup — run without it and restart
> the single process after backend edits. To free a wedged API port, kill all `python` uvicorn
> processes (not just the listener).

Open http://localhost:3000 — the sidebar lights up the **enabled** modules from `platform.toml`.

## Status (v1)

- ✅ **Q1 spine** — config-driven shell + API + brand; Light/Dark/System theme
- ✅ **Q2 "See"** — Overview (counts/freshness/last-run) · Explorer (search + security detail,
  returns × 28 windows) · Universes · **Heat map** (Perplexity-style treemap, sector groups,
  share-class merge, hover tooltip) · Attention (review queue, price gaps) · Validation
- ✅ **Q4 portfolios** — weights-first (`qrp` schema) + weighted return/PnL engine + contributions
  (live-PnL foundation: swap a real-time price source for intraday)
- next: Q3 Operate (trigger sym ops; spike-first) · Q5 analytics (Sharpe/alpha vs benchmark) ·
  Brazilian B3 ingest · openapi-typescript types · a live quote source (none in this env)

