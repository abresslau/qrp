-- Deploy optimiser:optimiser to pg

BEGIN;

-- The `optimiser` package's own database: mean-variance portfolio solutions computed from
-- sym's daily return covariance (engine reads sym read-only over a separate connection).
-- A solution stores its config + expected stats; weights hold the long-only allocation with a
-- denormalized ticker so the read API stays standalone. No FK to sym.
CREATE SCHEMA IF NOT EXISTS optimiser;

CREATE TABLE IF NOT EXISTS optimiser.solution (
    solution_id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    universe_id   TEXT NOT NULL,
    method        TEXT NOT NULL,             -- 'min_variance' | 'max_sharpe'
    n_assets      INTEGER NOT NULL,
    lookback_days INTEGER NOT NULL,
    exp_return    DOUBLE PRECISION,          -- annualised
    exp_vol       DOUBLE PRECISION,          -- annualised
    sharpe        DOUBLE PRECISION,
    ew_vol        DOUBLE PRECISION,          -- equal-weight vol on the same covariance (benchmark)
    summary       JSONB
);

CREATE TABLE IF NOT EXISTS optimiser.weight (
    solution_id    BIGINT NOT NULL REFERENCES optimiser.solution(solution_id) ON DELETE CASCADE,
    composite_figi CHAR(12) NOT NULL,
    ticker         TEXT,
    weight         DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (solution_id, composite_figi)
);

COMMIT;
