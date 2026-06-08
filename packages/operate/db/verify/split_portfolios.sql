-- Verify qrp_core:split_portfolios on pg

BEGIN;

-- qrp.portfolio must be ABSENT (relocated); qrp.job must remain.
DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'qrp' AND c.relname = 'portfolio'
    ) THEN
        RAISE EXCEPTION 'qrp.portfolio still present (expected: relocated to the portfolios DB)';
    END IF;
END $$;
SELECT job_id FROM qrp.job WHERE FALSE;  -- the job ledger remains

ROLLBACK;
