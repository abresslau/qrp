-- Revert signals:factor_traceability from pg

BEGIN;

ALTER TABLE signals.factor
    DROP COLUMN IF EXISTS inputs,
    DROP COLUMN IF EXISTS method;

COMMIT;
