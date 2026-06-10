# Universe maintenance plans

Every index universe MUST have a maintenance plan before it is populated:
**source · monitor cadence · gating · point-in-time (PIT) boundary**. This file
records them — one `## <universe_id>` section per populated universe, enforced
by the `maintenance_plan_coverage` check in `sym validate` (a populated index
universe with no section here FAILS the gate).

The monitor's safety machinery (Story U3.5, wired 2026-06-10): a snapshot source
declares its full current member set (`last_snapshot_tokens`); `run_monitor` derives
leaves by diffing it against currently-open members, stages every discovery as a
`membership_proposal` (churn above 10% gates the whole run for review), and promotes
proposals to the append-only log only after 2-day persistence or second-source
corroboration. `sym universe accuracy <id>` cross-checks membership against the
configured `config.accuracy_reference` source (exit 2 on alarm); `sym universe
reverse` appends a corrective event for a wrongly-recorded change.

## ibov — Ibovespa (B3)

- **Kind / provider:** `index`, archetype `b3` (`source_pref=['b3']`). The
  provider is the **authoritative** source — B3's official theoretical portfolio
  via the listed-systems `GetPortfolioDay` endpoint (`indexProxy/indexCall`). This
  *is* the index, so no cross-source corroboration is needed (unlike the
  scraped/Wikipedia archetypes).
- **Constituents:** ~78 names as of 2026-06-08 (e.g. PETR4, VALE3, ITUB4, ABEV3).
  All list on **BVMF**; Yahoo suffix `.SA` (resolver maps BVMF→.SA).
- **Source nature:** **snapshot** — the endpoint returns only the *current*
  portfolio. Membership is the constituent **ticker set** at the poll date; weight
  changes are NOT membership changes. An empty/garbled response is a loud
  `IndexSourceError` (never applied as "every member left").
- **PIT boundary:** **build-forward.** B3's daily endpoint carries no history, so
  `pit_valid_from` is pinned at inception (2026-06-08). Membership before that date
  is unknown and is not back-projected (no survivorship bias). Leavers are tracked
  *forward*: each monitor run diffs B3's declared snapshot against the open
  membership, so a name that drops out of the portfolio is staged as a leave.
- **Rebalance cadence:** B3 rebalances three times a year (**Jan / May / Sep**)
  plus ad-hoc corporate events.
- **Monitor cadence:** daily `sym universe monitor ibov` — the daily diff catches
  both scheduled rebalances and ad-hoc events. Events are `poll_bounded` (the
  effective date is bounded by the polling interval, not exact).
  `config.calendar_mic=BVMF` snaps event dates to B3 sessions.
- **Gating:** LIVE: every monitor discovery is staged as a `membership_proposal`
  and surfaces in `sym universe review`; a run whose churn exceeds 10% of current
  membership is gated (`status=gated`, nothing auto-applied) pending
  `sym universe confirm <id>` (or `--reject`); ordinary changes auto-promote after
  2-day persistence or second-source corroboration.
- **Prices / FX / returns:** prices via yfinance (`.SA`); **USD/BRL FX already
  present** in `fx_rate` (to 2026-06-05) — no FX ingest needed; returns via
  `sym recompute`; market cap via `sym fundamentals --universe ibov`.
- **Build sequence:**
  ```
  sym universe add ibov --kind index --index ibov --name "Ibovespa" \
      --source-pref b3 --pit-from 2026-06-08
  sym universe refresh ibov            # B3 -> events -> OpenFIGI resolve -> project
  sym load --scope universe:ibov --start_date 1990-01-01   # prices backfill (gap-aware, resumable)
  sym recompute                        # fact_returns (PR+TR)
  sym fundamentals --universe ibov     # shares / market cap (BRL->USD via fx_rate)
  sym validate --universe ibov         # integrity gate
  ```

## ibx — IBrX 100 (B3)

- **Source:** `index`, archetype `b3` (`source_pref=['b3']`) — B3 code `IBXX`,
  same authoritative `GetPortfolioDay` snapshot endpoint as `ibov`. 99 members
  as of 2026-06-08, all on **BVMF**.
- **PIT boundary:** **build-forward**, `pit_valid_from=2026-06-08` (no vendor
  history; membership before inception is unknown, not back-projected).
- **Rebalance cadence:** B3 three times a year (**Jan / May / Sep**) + ad-hoc.
- **Monitor cadence:** daily `sym universe monitor ibx`;
  `config.calendar_mic=BVMF` snaps event dates to B3 sessions.
- **Gating:** standard two-stage (see the header paragraph): snapshot leaver
  diff, 10% churn gate, 2-day persistence promotion. Authoritative source — no
  cross-source corroboration needed (same posture as `ibov`).

## Wikipedia-sourced universes — shared mechanics

The eleven universes below are all `index` universes with
`source_pref=['wikipedia']`: membership scraped from the index's Wikipedia
page. Shared posture (stated once, referenced per-universe):

- **Source nature:** the constituents table is a **declared full snapshot**
  (`last_snapshot_tokens`) — the monitor derives leavers from absence; where a
  "Date added"/changes table exists, EXACT-dated events flow as history. An
  empty/garbled page is a loud `IndexSourceError`, never "every member left".
- **Monitor cadence:** daily `sym universe monitor <id>`; `config.calendar_mic`
  (per-universe below) snaps event dates to the home-exchange calendar.
- **Gating:** standard two-stage (header paragraph). **Corroboration posture —
  honest:** these are SINGLE-SOURCE scraped universes. No independent
  `accuracy_reference` is configurable today (FMP unreachable in this
  environment; no ETF-holdings URLs configured), so the churn gate +
  persistence window + review digest are the active safeguards against a
  vandalised or mis-parsed page. Wiring a reachable second source per universe
  is an operational follow-up (deferred-work ledger).
- **Prices / returns:** yfinance via the resolver's MIC→Yahoo-suffix mapping;
  returns via `sym recompute`; integrity via `sym validate --universe <id>`.

## sp500 — S&P 500

- **Source:** Wikipedia "List of S&P 500 companies", tokens `ticker:*@XNYS`;
  constituents snapshot + "Selected changes" dated history. 503 members.
- **PIT boundary:** `pit_valid_from=1994-09-30` — the depth of the Wikipedia
  changes-table backfill; membership before that is unknown.
- **Rebalance cadence:** quarterly (Mar/Jun/Sep/Dec) + ad-hoc corporate events.
- **Monitor / gating:** shared mechanics above; `calendar_mic=XNYS`.

## sp400 — S&P MidCap 400

- **Source:** Wikipedia "List of S&P 400 companies", `ticker:*@XNYS`;
  snapshot + dated history. 411 members.
- **PIT boundary:** `pit_valid_from=2012-01-13` (changes-table depth).
- **Rebalance cadence:** quarterly (Mar/Jun/Sep/Dec) + ad-hoc.
- **Monitor / gating:** shared mechanics above; `calendar_mic=XNYS`.

## sp600 — S&P SmallCap 600

- **Source:** Wikipedia "List of S&P 600 companies", `ticker:*@XNYS`;
  snapshot + dated history. 600 members.
- **PIT boundary:** `pit_valid_from=2019-12-17` (changes-table depth).
- **Rebalance cadence:** quarterly (Mar/Jun/Sep/Dec) + ad-hoc.
- **Monitor / gating:** shared mechanics above; `calendar_mic=XNYS`.

## dax — DAX 40

- **Source:** Wikipedia "DAX", `ticker:*@XETR` (Yahoo-suffix tokens);
  constituents snapshot only (build-forward). 40 members.
- **PIT boundary:** **build-forward**, `pit_valid_from=2026-06-07`.
- **Rebalance cadence:** quarterly review (Mar/Jun/Sep/Dec) + fast entry/exit.
- **Monitor / gating:** shared mechanics above; `calendar_mic=XETR`.

## cac40 — CAC 40

- **Source:** Wikipedia "CAC 40", `ticker:*@XPAR`. 40 members.
- **PIT boundary:** **build-forward**, `pit_valid_from=2026-06-07`.
- **Rebalance cadence:** quarterly review (Mar/Jun/Sep/Dec).
- **Monitor / gating:** shared mechanics above; `calendar_mic=XPAR`.

## ftse100 — FTSE 100

- **Source:** Wikipedia "FTSE 100", `ticker:*@XLON`. 92 members (the page's
  current count; the index targets 100 — watch the completeness check).
- **PIT boundary:** **build-forward**, `pit_valid_from=2026-06-07`.
- **Rebalance cadence:** quarterly review (Mar/Jun/Sep/Dec).
- **Monitor / gating:** shared mechanics above; `calendar_mic=XLON`.

## ibex35 — IBEX 35

- **Source:** Wikipedia "IBEX 35", `ticker:*@XMAD`. 35 members.
- **PIT boundary:** **build-forward**, `pit_valid_from=2026-06-07`.
- **Rebalance cadence:** semi-annual review (Jun/Dec) + technical follow-ups.
- **Monitor / gating:** shared mechanics above; `calendar_mic=XMAD`.

## ftsemib — FTSE MIB

- **Source:** Wikipedia "FTSE MIB", `ticker:*@XMIL`. 40 members.
- **PIT boundary:** **build-forward**, `pit_valid_from=2026-06-07`.
- **Rebalance cadence:** quarterly review (Mar/Jun/Sep/Dec).
- **Monitor / gating:** shared mechanics above; `calendar_mic=XMIL`.

## aex — AEX

- **Source:** Wikipedia "AEX index", `ticker:*@XAMS`. 25 members.
- **PIT boundary:** **build-forward**, `pit_valid_from=2026-06-07`.
- **Rebalance cadence:** annual March review + quarterly partial reviews.
- **Monitor / gating:** shared mechanics above; `calendar_mic=XAMS`.

## smi — Swiss Market Index

- **Source:** Wikipedia "Swiss Market Index", `ticker:*@XSWX`. 19 members
  (index targets 20 — watch the completeness check).
- **PIT boundary:** **build-forward**, `pit_valid_from=2026-06-07`.
- **Rebalance cadence:** annual September review.
- **Monitor / gating:** shared mechanics above; `calendar_mic=XSWX`.

## estoxx50 — EURO STOXX 50

- **Source:** Wikipedia "EURO STOXX 50", `ticker:*@XETR`. 49 members (index
  targets 50 — watch the completeness check).
- **PIT boundary:** **build-forward**, `pit_valid_from=2026-06-07`.
- **Rebalance cadence:** annual September review + fast entry/exit rule.
- **Monitor / gating:** shared mechanics above; `calendar_mic=XETR`.
  **Alignment caveat:** membership is pan-European (multiple home venues);
  XETR is the token/alignment calendar because the Wikipedia spec mints
  XETR-MIC tokens — per-member home-exchange alignment is not attempted.
