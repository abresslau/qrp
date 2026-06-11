-- Revert optimiser:solution_spec from pg

BEGIN;

ALTER TABLE optimiser.solution DROP COLUMN IF EXISTS spec;

COMMIT;
