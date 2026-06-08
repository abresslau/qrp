-- Revert sym:cumulative_multiyear_windows from pg

BEGIN;

DELETE FROM fact_returns       WHERE window_id BETWEEN 21 AND 27;
DELETE FROM fact_index_returns WHERE window_id BETWEEN 21 AND 27;
DELETE FROM return_window      WHERE window_id BETWEEN 21 AND 27;

COMMIT;
