# sym operator runbook

How to define, populate, maintain, and validate the warehouse. Commands are
`uv run sym <cmd>`. See `docs/data-conventions.md` for date/time + SCD semantics
and `_bmad-output/planning-artifacts/` for the epics.

## 0. Reconstruct everything from inception

The repository is the **canonical, complete record** — the live database is
disposable and is rebuilt by replaying versioned artifacts. Nothing is ever
hand-edited into the schema or data out of band:

- **Structure** = `migrations/` (Sqitch). Every table, column, index, view, and
  constraint since inception is a `deploy`/`revert`/`verify` triplet, linearly
  ordered in `migrations/sqitch.plan`. Invariant: every plan entry has all three
  scripts and every deploy script is in the plan (currently 33/33).
- **Logic** = git. One logical commit per story, each with its spec under
  `_bmad-output/implementation-artifacts/` and the plans/ADRs under
  `_bmad-output/planning-artifacts/`.
- **Data** = reproducible from immutable sources. Raw inputs (`prices_raw`,
  `corporate_actions`, the `membership_event` log) are immutable and
  source-tagged; everything derived (`v_prices_adjusted`, `universe_membership`,
  `fact_returns`, `fundamentals`) is recomputed deterministically
  (`input_hash`, `calendar_version`, event-log-as-truth).

**Full rebuild against an empty database:**

```
# 1. Structure — replay the entire schema from zero (idempotent, ordered).
sqitch deploy --verify <target>          # via Docker: sqitch/sqitch + host.docker.internal

# 2. Reference + identity
sym snapshot-calendar                    # exchange calendars (versioned)
sym resolve                              # seed -> CompositeFIGI (OpenFIGI)
sym review list                          # FIGI-assignment issues awaiting stewarding
sym review resolve <id> [--figi BBG...]  # assign the steward's pick, or dismiss
#  ^ open review rows GATE `sym resolve`: queued inputs are skipped (no OpenFIGI
#    re-query, no auto-assignment) until resolved; dismissal re-admits the input.
#    Permanently-dead names (delisted, never coming back): dismiss the row AND
#    remove the entry from the seed file - the queue tracks pending decisions,
#    not tombstones.

# 3. Universe membership (per universe)
sym universe add <id> --kind index --index <key> --source-pref wikipedia
sym universe refresh <id>                # events -> resolve -> project (resumable)

# 4. Prices, fundamentals, returns
sym load --scope universe:<id> --start_date 1990-01-01   # backfill, gap-aware, resumable
sym classify ; sym recompute ; sym fundamentals --all

# 5. Prove the rebuild
sym validate                             # cross-layer integrity gate
```

Steps 2–5 are re-runnable and converge to the same state (immutable writes +
deterministic recompute), so a rebuild reproduces the structure exactly and the
data up to vendor availability. **Any structural change must land as a migration
(never an in-place edit) so this replay stays complete.**

> Operational note: migrations are deployed to the live dev database as they are
> authored (so a couple of changes were applied + committed during development),
> but the **committed migration set is always canonical** — replaying it against a
> blank database yields the identical structure. The live DB is never the source
> of truth; the repo is.

## 1. Define a universe

```
sym universe add <id> --kind index  --index <key> --source-pref wikipedia   # an index
sym universe add <id> --kind custom_list --from path/to/list.toml           # a custom list
sym universe add <id> --kind criteria --rule top_n_market_cap --n 1000      # a screen
sym universe list
```

Index keys ship for the S&P family (`sp500/sp400/sp600`) and European flagships
(`dax cac40 ftse100 ibex35 ftsemib aex smi estoxx50`). `--source-pref` is the
ordered archetype fallback (`fmp,etf_holdings,wikipedia`); FMP needs `FMP_API_KEY`,
so Wikipedia is the live default.

## 2. Populate membership

```
sym universe refresh <id>          # provider -> append events -> resolve -> project
sym universe members <id> --as_of_date 2010-06-01
sym universe coverage <id>
```

Refresh is resumable (OpenFIGI is throttled + chunked; re-run resolves only the
still-pending members). Index `pit_valid_from` is derived from the earliest dated
leave (the survivorship floor); a query before it is refused.

## 3. Maintain (daily)

```
sym universe monitor <id>          # discover + append changes; idempotent
sym universe review                # gated changes, stale monitors, aging-unresolved,
                                   # accuracy alarms, incomplete members
sym universe confirm <proposal_id> [--reject]
```

## 4. Price + returns (ingestion)

```
sym load --scope universe:<id> --start_date 1990-01-01   # full history for members (gap-aware)
sym load --scope universe:<id> --start_date 2000-01-01   # price history from a build-forward floor
sym load --scope universe:<id>               # daily incremental (only the new tail since each cursor)
sym recompute                                # materialize fact_returns (PR + TR)
```

Backfill is **gap-aware + resumable**: the `pipeline_backfill_progress.floor_reached_date`
watermark + per-figi cursor mean a completed name is *skipped before any network
call* on a re-run — so a second backfill only touches incomplete/errored names.
Prices are immutable (`ON CONFLICT DO NOTHING`). A plain `sym load` (forward fill) is
the daily-ops mode (pulls only sessions after the cursor).

### 4a. Return windows (`fact_returns` / `fact_index_returns`)

`recompute` materializes **PR + TR** for every security (and `indices` does the
same for index levels as a single `ret`) across **28 windows**, keyed by the integer
`return_window.window_id`. The spec lives in `src/sym/returns/windows.py`; the seed is
in `return_window` (replayed by migrations). Query/label by `code`, never by `kind`.

| code(s) | window | kind | cumulative / annualized |
|---|---|---|---|
| `1D` | prior session | calendar | cumulative |
| `WTD` `MTD` `QTD` `YTD` | week/month/quarter/year **to date** (resets at the boundary) | calendar | cumulative |
| `5D` `10D` | 5 / 10 **trading sessions** back | session | cumulative |
| `1W` `1M` `3M` `6M` `9M` `1Y` | trailing N weeks/months | trailing | cumulative |
| `2Y` `3Y` `5Y` `10Y` `20Y` `30Y` | trailing N years, **total return** | trailing | cumulative |
| `2Y_ANN` … `30Y_ANN` | trailing N years, **CAGR** | trailing | annualized |
| `SI` / `SI_ANN` | since inception (first listed session) | inception | cumulative / annualized |
| `PQ` | **last completed calendar quarter** (both endpoints in the past) | period | cumulative |

- **`kind` is internal plumbing** (which base-date math to run), *not* a financial
  category. The only financial split is `calendar` (period-to-date, resets) vs
  everything else (trailing/discrete). Cumulative-vs-CAGR is the `annualized` flag.
- **Same endpoints, two expressions**: `5Y` (total, e.g. +61%) and `5Y_ANN`
  (CAGR, e.g. +10%/yr) share a base date; `5Y_ANN = (1+5Y)^(1/years) − 1`.
- **`QTD` vs `PQ`**: `QTD` is the *current* (incomplete) quarter ending at as-of; `PQ`
  is the *just-finished* quarter (e.g. mid-Q4 → the full-Q3 return).
- Insufficient history → the window is **NULL** (e.g. `30Y` for a name listed in 2015).
- Windows are **append-only** (`window_id` is a stable PK): a new window is added via a
  migration with the next id and a `windows.py` entry — never renumbered.

## 5. Finisher sequence (after a large backfill)

Run in this order so each layer is consistent:

```
sym classify                 # GICS for active securities (financedatabase; local)
sym recompute                # fact_returns for newly-priced names
sym fundamentals --all       # historical shares/market cap for all members (yfinance; long)
sym validate                 # the gate (below)
```

`recompute`/`classify` are DB-only; `fundamentals` is the yfinance long pole — run
it after a price backfill, not during (avoid rate-limit contention). Do **not**
re-snapshot calendars while `recompute` runs (it reads the current calendar).

## 6. Validate (the integrity gate)

```
sym validate [--universe <id>]     # exit 0 = pass/warn, exit 2 = hard fail
```

Runs the Epic-V suite across all layers. Read the result by severity:

- **fail** = something is wrong and actionable: orphaned keys, missing metadata,
  a priceable-but-unpriced member, a price after delisting, projection drift, a
  universe below the returns-readiness threshold.
- **warn** = a known/expected gap, *not* breakage:
  - off-calendar bars — pre-1990 US sessions (our calendar floored at ~1990 while
    Yahoo serves from 1962) and vendor holiday-phantom bars; both inert to returns;
  - a MIC with no current calendar (e.g. XNSE/Reliance) — can't compute returns;
  - delisted/suspended members missing prices/fundamentals (no vendor data).
- Incomplete members are persisted to `universe_member_completeness` (which
  dimensions are missing) and summarized in `sym universe review`.

## 7. Known levers / limitations

- **EODHD** (deferred Story 2.7) — the licensed source for delisted-leaver price
  history that yfinance can't serve; the `unpriced_securities`/completeness warns
  name exactly that gap.
- **Calendar floor** — to make pre-1990 US prices usable for returns, re-snapshot
  calendars with an earlier start (`exchange_calendars` XNYS goes back decades);
  otherwise pre-floor prices sit inert (returns start where the calendar does).
- **GICS coverage** — `financedatabase` covers ~92% of the populated set (US-strong);
  uncovered names stay flagged as incomplete until classified another way.

## 8. Daily EOD (scheduled)

sym is **scheduler-agnostic** — it carries no Airflow/Prefect dependency. Run the
daily pipeline either coarse or fine-grained:

```
sym eod                       # coarse: monitor -> fill -> map -> indices -> fx -> recompute -> validate
sym eod --dry-run             # print the step plan
sym eod --steps fill,recompute    # run a subset (one task per step under an orchestrator)
sym eod --skip indices
```

Each step is idempotent + error-isolated; `fill`/`recompute` are critical (a
failure exits non-zero), `monitor`/`indices`/`validate` are non-critical
(surfaced, don't fail the night). Periodic steps run on their own cadence:
`sym fundamentals --all` (weekly), `sym snapshot-calendar` (occasional).

Wire it to a scheduler with the thin example wrappers in `docs/orchestration/`
(Airflow DAG / Prefect flow — each task is just `sym eod --steps <step>`). See
`docs/architecture-modules.md` for how future modules (live pricing, backtests,
analytics) build on sym via `sym_id` + the schema contract.
