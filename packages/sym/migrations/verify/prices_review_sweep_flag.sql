-- Verify sym:prices_review_sweep_flag on pg

BEGIN;

-- The flag_type CHECK admits 'sweep_divergence' (errors if the constraint rejects it).
SELECT 1 / (CASE WHEN pg_get_constraintdef(
    (SELECT oid FROM pg_constraint WHERE conname = 'prices_review_flag_type_chk')
) LIKE '%sweep_divergence%' THEN 1 ELSE 0 END);

ROLLBACK;
