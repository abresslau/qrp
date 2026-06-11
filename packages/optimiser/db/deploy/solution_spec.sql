-- Deploy optimiser:solution_spec to pg
-- requires: optimiser

BEGIN;

-- FR-22 reproducibility (Story Q7.3): the FULL solve specification — universe, method,
-- n, lookback, max_weight constraint, signal tilt (factor + strength), holdout split,
-- save_portfolio — plus the resolved data window. NULL on pre-spec solutions.
ALTER TABLE optimiser.solution
    ADD COLUMN spec JSONB;

COMMENT ON COLUMN optimiser.solution.spec IS
    'The reproducible solve definition (Story Q7.3). NULL on pre-spec solutions.';

COMMIT;
