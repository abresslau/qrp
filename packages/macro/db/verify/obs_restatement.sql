-- Verify macro:obs_restatement on pg

BEGIN;

SELECT last_changed_at FROM macro.observation WHERE FALSE;

ROLLBACK;
