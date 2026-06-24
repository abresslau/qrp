-- Verify sym:fx_extract on pg
-- The fx objects must be GONE from the sym database (they live in the fx database now).

BEGIN;

DO $$
BEGIN
    IF to_regclass('public.fx_rate') IS NOT NULL THEN
        RAISE EXCEPTION 'fx_rate still present in the sym database';
    END IF;
    IF to_regclass('public.fx_rate_review') IS NOT NULL THEN
        RAISE EXCEPTION 'fx_rate_review still present in the sym database';
    END IF;
    IF to_regclass('public.v_fx') IS NOT NULL THEN
        RAISE EXCEPTION 'v_fx still present in the sym database';
    END IF;
    IF to_regclass('public.v_fx_daily') IS NOT NULL THEN
        RAISE EXCEPTION 'v_fx_daily still present in the sym database';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'fx_source_rank') THEN
        RAISE EXCEPTION 'fx_source_rank() still present in the sym database';
    END IF;
END $$;

ROLLBACK;
