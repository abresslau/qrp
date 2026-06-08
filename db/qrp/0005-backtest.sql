-- QRP-managed `backtest` schema (NOT sym): walk-forward factor-strategy simulations over
-- sym history. A run persists its config + summary; points hold the equity curves. The
-- factor is recomputed from fact_returns at each rebalance date (no look-ahead). Idempotent
-- per run_id; sym is read-only.

CREATE SCHEMA IF NOT EXISTS backtest;

CREATE TABLE IF NOT EXISTS backtest.run (
    run_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    factor        TEXT NOT NULL,
    universe_id   TEXT NOT NULL,
    top_pct       DOUBLE PRECISION NOT NULL,
    rebalance     TEXT NOT NULL,
    start_date    DATE,
    end_date      DATE,
    n_days        INTEGER,
    n_rebalances  INTEGER,
    summary       JSONB
);

CREATE TABLE IF NOT EXISTS backtest.point (
    run_id     BIGINT NOT NULL REFERENCES backtest.run(run_id) ON DELETE CASCADE,
    obs_date   DATE NOT NULL,
    strat_cum  DOUBLE PRECISION NOT NULL,
    base_cum   DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (run_id, obs_date)
);
