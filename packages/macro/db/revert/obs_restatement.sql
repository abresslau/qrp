-- Revert macro:obs_restatement from pg

BEGIN;

ALTER TABLE macro.observation DROP COLUMN IF EXISTS last_changed_at;

COMMIT;
