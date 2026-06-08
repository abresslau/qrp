-- Verify qrp:relocate_qrp on pg

BEGIN;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'qrp') THEN
        RAISE EXCEPTION 'qrp schema still present in this database (expected: relocated)';
    END IF;
END $$;

ROLLBACK;
