-- Revert sym:session_return_windows from pg

BEGIN;

-- Drop materialized rows for these windows first (FK), then the seed + the kind widening.
DELETE FROM fact_returns       WHERE window_id IN (19, 20);
DELETE FROM fact_index_returns WHERE window_id IN (19, 20);
DELETE FROM return_window      WHERE window_id IN (19, 20);

ALTER TABLE return_window DROP CONSTRAINT return_window_kind_chk;
ALTER TABLE return_window ADD CONSTRAINT return_window_kind_chk
    CHECK (kind IN ('calendar', 'rolling', 'multiyear', 'ipo'));

COMMIT;
