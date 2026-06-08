-- Verify qrp:relocate_signal on pg

BEGIN;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'signal') THEN
        RAISE EXCEPTION 'signal schema still present in this database (expected: relocated)';
    END IF;
END $$;

ROLLBACK;
