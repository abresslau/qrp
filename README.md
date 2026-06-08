# QRP — Quant Research Platform

A console + API over the existing **sym** warehouse. Owner-operated; a *consumer* of sym
(reads via views, triggers sym's idempotent ops out-of-process; never mutates sym's schema).
The platform name is config-driven — change `platform.toml` and the API title + console
follow. Planning artifacts live in the sym repo under
`_bmad-output/planning-artifacts/` (`prd-qrp-*`, `epics-qrp.md`, `architecture-qrp.md`).

## Layout

```
qrp/
├─ platform.toml          # brand + enabled-modules (single source of truth)
├─ apps/web/              # Next.js 16 + Tailwind v4 console (:3000)
├─ services/api/          # FastAPI (uv) — per-module routers over sym (:8001)
├─ packages/sym/          # reserved fold-in slot (sym joins here later)
├─ db/qrp/                # QRP's own `qrp` Postgres schema (portfolios) — 0001-portfolios.sql
└─ scripts/dev.mjs        # runs API + console together
```

## Run it (dev)

Reads the same sym database as the sym CLI (`SYM_DB_*` / `SYM_DATABASE_URL`; see `.env.example`).
The API runs on **:8001**, the console on **:3000** (console proxies `/api/*` → :8001).

```bash
uv sync
npm install
npm run dev          # starts BOTH: API (:8001) + console (:3000)
```

Or run them separately:

```bash
npm run dev:api      # FastAPI on :8001  (no --reload — restart after API code changes)
npm run dev:web      # Next console on :3000
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

