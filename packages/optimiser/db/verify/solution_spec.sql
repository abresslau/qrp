-- Verify optimiser:solution_spec on pg

BEGIN;

SELECT spec FROM optimiser.solution WHERE FALSE;

ROLLBACK;
