-- Verify sym:trailing_kind_prior_quarter on pg

BEGIN;

-- No legacy kinds remain, and PQ is the lone 'period' window (errors if either fails).
SELECT 1 / (CASE WHEN (
    SELECT count(*) FROM return_window WHERE kind IN ('rolling', 'multiyear')
) = 0 THEN 1 ELSE 0 END);
SELECT 1 / (CASE WHEN (
    SELECT count(*) FROM return_window WHERE kind = 'period' AND code = 'PQ'
) = 1 THEN 1 ELSE 0 END);

ROLLBACK;
