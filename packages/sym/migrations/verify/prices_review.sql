-- Verify sym:prices_review on pg

BEGIN;

SELECT composite_figi, session_date, flag_type, detail, pct_move, source,
       reviewed, resolution, reviewed_at, created_at, updated_at
  FROM prices_review WHERE FALSE;

ROLLBACK;
