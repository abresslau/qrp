-- Deploy backtest:sweep to pg
-- requires: strategy_spec

BEGIN;

-- Story 1B: a SWEEP is a set of N backtest runs over a parameter grid, evaluated TOGETHER for
-- overfitting. Capturing N (the number of configs tried) is what makes the Deflated Sharpe / PBO /
-- Minimum Backtest Length honest — a lone run cannot know how many siblings were tried. `summary`
-- holds the computed verdict (DSR of the best config, PBO via CSCV, MinBTL, the selection).
CREATE TABLE IF NOT EXISTS backtest.sweep (
    sweep_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    base_spec   JSONB   NOT NULL,   -- the fixed run kwargs (factor/universe/dates/cost)
    grid        JSONB   NOT NULL,   -- the varied parameters {param: [values...]}
    n_configs   INTEGER NOT NULL,   -- N trials = grid size (the DSR / MinBTL multiple-testing count)
    best_run_id BIGINT REFERENCES backtest.run(run_id) ON DELETE SET NULL,
    summary     JSONB               -- {deflated_sharpe, pbo, min_btl_years, verdict_credible, ...}
);

-- link a run to its parent sweep (NULL for standalone runs); created after `sweep` exists so the
-- two-way reference (sweep.best_run_id ↔ run.sweep_id) deploys without a circular dependency.
ALTER TABLE backtest.run
    ADD COLUMN IF NOT EXISTS sweep_id BIGINT REFERENCES backtest.sweep(sweep_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_run_sweep ON backtest.run (sweep_id);

COMMENT ON TABLE backtest.sweep IS
    'A parameter-grid sweep of N backtest runs evaluated together for overfitting (Story 1B): '
    'Deflated Sharpe, PBO (CSCV), Minimum Backtest Length. n_configs is the multiple-testing N.';

COMMIT;
