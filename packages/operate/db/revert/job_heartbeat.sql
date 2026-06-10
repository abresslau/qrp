-- Revert qrp_core:job_heartbeat from pg

BEGIN;

ALTER TABLE qrp.job DROP COLUMN IF EXISTS heartbeat_at;

COMMIT;
