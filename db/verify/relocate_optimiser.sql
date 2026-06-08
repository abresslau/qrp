-- Verify qrp:relocate_optimiser on pg

BEGIN;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'optimiser') THEN
        RAISE EXCEPTION 'optimiser schema still present in this database (expected: relocated)';
    END IF;
END $$;

ROLLBACK;
