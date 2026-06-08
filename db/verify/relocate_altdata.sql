-- Verify qrp:relocate_altdata on pg

BEGIN;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'altdata') THEN
        RAISE EXCEPTION 'altdata schema still present in this database (expected: relocated)';
    END IF;
END $$;

ROLLBACK;
