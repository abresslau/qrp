-- Verify sym:session_return_windows on pg

BEGIN;

-- The two session windows are seeded with kind='session' (errors if not exactly 2).
SELECT 1 / (CASE WHEN (
    SELECT count(*) FROM return_window WHERE code IN ('5D', '10D') AND kind = 'session'
) = 2 THEN 1 ELSE 0 END);

ROLLBACK;
