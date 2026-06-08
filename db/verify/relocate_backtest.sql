-- Verify qrp:relocate_backtest on pg

BEGIN;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'backtest') THEN
        RAISE EXCEPTION 'backtest schema still present in this database (expected: relocated)';
    END IF;
END $$;

ROLLBACK;
