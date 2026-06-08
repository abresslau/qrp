-- Revert qrp:jobs from pg

BEGIN;

DROP TABLE IF EXISTS qrp.job;

COMMIT;
