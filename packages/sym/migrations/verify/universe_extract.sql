-- Verify sym:universe_extract on pg
-- The 7 universe tables must be GONE from the sym database (they live in the universe database now);
-- universe_member_completeness must REMAIN. (universe_benchmark also stayed here at the time, but it
-- moved on to the `indices` package in a later change, sym:index_extract — so it is no longer asserted
-- present here.)

BEGIN;

DO $$
BEGIN
    IF to_regclass('public.universe') IS NOT NULL
       OR to_regclass('public.membership_event') IS NOT NULL
       OR to_regclass('public.universe_member_resolution') IS NOT NULL
       OR to_regclass('public.universe_membership') IS NOT NULL
       OR to_regclass('public.membership_proposal') IS NOT NULL
       OR to_regclass('public.universe_monitor_log') IS NOT NULL
       OR to_regclass('public.universe_accuracy_check') IS NOT NULL THEN
        RAISE EXCEPTION 'a universe membership table still present in the sym database';
    END IF;
    IF to_regclass('public.universe_member_completeness') IS NULL THEN
        RAISE EXCEPTION 'universe_member_completeness must remain in sym';
    END IF;
END $$;

ROLLBACK;
