-- Deploy backtest:backtest to pg

BEGIN;

-- The `backtest` package's own database: walk-forward factor-strategy simulations. The engine
-- recomputes the factor FROM sym's fact_returns at each rebalance (no look-ahead), reading sym
-- read-only over a separate connection; runs + equity curves persist here. No FK to sym.
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

COMMIT;
