# Universe maintenance plans

Every index universe MUST have a maintenance plan before it is populated:
**source · monitor cadence · gating · point-in-time (PIT) boundary**. This file
records them. (US/European index plans follow the same template; the B3 plan
below is the first written down explicitly. The S&P 500/400/600 and the eight
European index universes are POPULATED WITHOUT WRITTEN PLANS — a known violation
of this rule, backlogged in the deferred-work ledger, chunk-3 review D4.)

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

## ibx — IBrX 100 (B3) — planned, not yet populated

Same provider/cadence/PIT semantics as `ibov`; B3 code `IBXX`, MIC `BVMF`. Add with
`--index ibx --source-pref b3` when needed. (IBrX-50 would be code `IBXL`.)
