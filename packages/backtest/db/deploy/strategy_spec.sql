-- Deploy backtest:strategy_spec to pg
-- requires: backtest

BEGIN;

-- FR-18 "defined strategy" (Story Q6.3): the FULL strategy specification a run was
-- produced from — factor (any signals-package factor incl. cross-module ones),
-- selection (top_pct XOR top_n), weighting (equal|cap), rebalance cadence, date range.
-- Reproducibility lives here; the legacy scalar columns stay for the existing list UI.
ALTER TABLE backtest.run
    ADD COLUMN spec JSONB;

COMMENT ON COLUMN backtest.run.spec IS
    'The reproducible strategy definition (Story Q6.3). NULL on pre-spec runs.';

COMMIT;
